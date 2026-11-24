# -*- coding: utf-8 -*-
"""
统一 HTTP API 路由注册（清爽 v2 RESTful API + v1 向后兼容别名 + 静态资源托管）。
"""
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler

from server.config import DATA_DIR, SERVER_VERSION, WEB_DIR
from server.http_utils import (
    query_first,
    read_json_body,
    safe_join,
    send_attachment_bytes,
    send_file,
    send_json,
    split_path_query,
)
from server.jobs import JobManager
from server.modules import ModuleRegistry
from server.net import probe_url
from server.router import Router
from server.upscaler import ai_engine_available
from server.user_data import UserDataStore

log = logging.getLogger("server.api")


class AppContext:
    """服务端运行时依赖容器（支持测试环境注入临时目录）。"""

    def __init__(self, data_dir=None, web_dir=None, version=None):
        self.data_dir = data_dir or DATA_DIR
        self.web_dir = web_dir or WEB_DIR
        self.version = version or SERVER_VERSION
        self.started_at = int(time.time() * 1000)
        self.registry = ModuleRegistry(self.data_dir)
        self.jobs = JobManager(
            self.registry,
            persist_path=os.path.join(self.data_dir, "jobs.json"),
        )
        self.user_data = UserDataStore(
            path=os.path.join(self.data_dir, "user_profile.json"),
        )
        self._probe_cache = {"at": 0, "data": None}

    def probe_sources(self, force=False):
        now = time.time()
        if not force and self._probe_cache["data"] and (now - self._probe_cache["at"] < 60):
            return self._probe_cache["data"]

        mods = self.registry.all()
        results = {}

        def _do(m):
            info = probe_url(m.probe_target, timeout=6)
            return m.id, {
                "mod": m.id,
                "name": m.name,
                "source": m.source_name,
                "url": m.probe_target,
                **info,
            }

        with ThreadPoolExecutor(max_workers=len(mods)) as pool:
            for mod_id, data in pool.map(_do, mods):
                results[mod_id] = data

        payload = {
            "checkedAt": int(now * 1000),
            "sources": results,
            "anyOnline": any(v.get("ok") for v in results.values()),
            "allOnline": all(v.get("ok") for v in results.values()),
        }
        self._probe_cache = {"at": now, "data": payload}
        return payload

    def all_cache_stats(self):
        mods = [m.cache_stats() for m in self.registry.all()]
        total_count = sum(x["count"] for x in mods)
        total_bytes = sum(x["bytes"] for x in mods)
        return {
            "count": total_count,
            "bytes": total_bytes,
            "mb": round(total_bytes / 1048576, 2),
            "modules": {x["mod"]: x for x in mods},
        }

    def clear_cache(self, mod_key=None):
        if mod_key and mod_key != "all":
            mod = self.registry.require(mod_key)
            res = mod.clear_cache()
            return {"ok": True, **res, "modules": {mod.id: res}}
        per = {}
        removed = 0
        freed = 0
        for mod in self.registry.all():
            r = mod.clear_cache()
            per[mod.id] = r
            removed += r["removed"]
            freed += r["bytes"]
        return {
            "ok": True,
            "removed": removed,
            "bytes": freed,
            "freedMB": round(freed / 1048576, 2),
            "modules": per,
        }


def build_router(ctx):
    """构建声明式路由表（v2 统一 REST API + v1 全量向后兼容别名）。"""
    r = Router()

    # ================================================================
    # V2 统一 API
    # ================================================================
    @r.get(r"^/api/v2/health$", name="v2_health")
    def v2_health(h, m, qs):
        mods = [mod.status_summary() for mod in ctx.registry.all()]
        send_json(h, 200, {
            "ok": True,
            "version": ctx.version,
            "pid": os.getpid(),
            "startedAt": ctx.started_at,
            "aiEngine": ai_engine_available(),
            "totalCards": sum(x["cardCount"] for x in mods),
            "modules": mods,
        })

    @r.get(r"^/api/v2/modules$", name="v2_modules")
    def v2_modules(h, m, qs):
        send_json(h, 200, {
            "version": ctx.version,
            "aiEngine": ai_engine_available(),
            "modules": [mod.status_summary() for mod in ctx.registry.all()],
        })

    @r.get(r"^/api/v2/modules/([a-z]+)/index$", name="v2_mod_index")
    def v2_mod_index(h, m, qs):
        mod = ctx.registry.get(m.group(1))
        if not mod:
            send_json(h, 404, {"error": "未知游戏模块"})
            return
        send_file(h, mod.index_path, ctype="application/json; charset=utf-8", cache_control="no-cache")

    @r.get(r"^/api/v2/modules/([a-z]+)/status$", name="v2_mod_status")
    def v2_mod_status(h, m, qs):
        mod = ctx.registry.get(m.group(1))
        if not mod:
            send_json(h, 404, {"error": "未知游戏模块"})
            return
        st = mod.status_summary()
        st["version"] = ctx.version
        st["aiEngine"] = ai_engine_available()
        send_json(h, 200, st)

    @r.get(r"^/api/v2/modules/([a-z]+)/cards/(card|support)/(\d+)$", name="v2_mod_card_detail_kind")
    def v2_mod_card_detail_kind(h, m, qs):
        mod = ctx.registry.get(m.group(1))
        if not mod:
            send_json(h, 404, {"error": "未知游戏模块"})
            return
        detail = mod.card_detail(int(m.group(3)), kind=m.group(2))
        if detail is None:
            send_json(h, 404, {"error": "卡面不存在或详情未就绪"})
            return
        send_json(h, 200, detail)

    @r.get(r"^/api/v2/modules/([a-z]+)/cards/(\d+)$", name="v2_mod_card_detail")
    def v2_mod_card_detail(h, m, qs):
        mod = ctx.registry.get(m.group(1))
        if not mod:
            send_json(h, 404, {"error": "未知游戏模块"})
            return
        kind = query_first(qs, "kind") or None
        detail = mod.card_detail(int(m.group(2)), kind=kind)
        if detail is None:
            send_json(h, 404, {"error": "卡面不存在或详情未就绪"})
            return
        send_json(h, 200, detail)

    @r.get(r"^/api/v2/modules/([a-z]+)/thumbs/(\d+)/([a-z_]+)$", name="v2_mod_thumb")
    def v2_mod_thumb(h, m, qs):
        mod = ctx.registry.get(m.group(1))
        if not mod:
            send_json(h, 404, {"error": "未知游戏模块"})
            return
        try:
            p = mod.thumb_path(int(m.group(2)), m.group(3))
        except ValueError as exc:
            send_json(h, 400, {"error": str(exc)})
            return
        if not p:
            send_json(h, 404, {"error": "缩略图不存在"})
            return
        send_file(h, p, ctype="image/webp")

    @r.get(r"^/api/v2/modules/([a-z]+)/originals/(\d+)/([a-z_]+)$", name="v2_mod_original")
    def v2_mod_original(h, m, qs):
        mod = ctx.registry.get(m.group(1))
        if not mod:
            send_json(h, 404, {"error": "未知游戏模块"})
            return
        tier = query_first(qs, "tier").lower() or None
        if tier and tier not in ("2k", "4k"):
            send_json(h, 400, {"error": "tier 必须是 2k 或 4k"})
            return
        try:
            p = mod.find_existing_original(int(m.group(2)), m.group(3), tier=tier)
        except ValueError as exc:
            send_json(h, 400, {"error": str(exc)})
            return
        if not p:
            send_json(h, 404, {"error": "原图尚未下载，请先点击「下载原图」"})
            return
        ctype = "image/jpeg" if p.endswith(".jpg") else "image/png"
        send_file(h, p, ctype=ctype)

    @r.get(r"^/api/v2/modules/pjsk/costume-thumb/([a-zA-Z0-9_]+)$", name="v2_pjsk_costume_thumb")
    def v2_pjsk_costume_thumb(h, m, qs):
        pjsk = ctx.registry.require("pjsk")
        p = pjsk.costume_thumb(m.group(1))
        if not p:
            send_json(h, 404, {"error": "服装缩略图不可用"})
            return
        send_file(h, p, ctype="image/webp")

    # ---- Jobs v2 ----
    @r.get(r"^/api/v2/jobs$", name="v2_jobs_list")
    def v2_jobs_list(h, m, qs):
        mod = query_first(qs, "mod") or None
        state = query_first(qs, "state") or None
        send_json(h, 200, {"jobs": ctx.jobs.list_jobs(mod=mod, state=state)})

    @r.get(r"^/api/v2/jobs/([A-Za-z0-9_]+)$", name="v2_job_get")
    def v2_job_get(h, m, qs):
        snap = ctx.jobs.get(m.group(1))
        if snap is None:
            send_json(h, 404, {"error": "任务不存在"})
            return
        send_json(h, 200, snap)

    @r.post(r"^/api/v2/jobs/download$", name="v2_job_download")
    def v2_job_download(h, m, qs):
        body = read_json_body(h)
        try:
            res = ctx.jobs.enqueue_download(
                body.get("mod") or "pjsk",
                body.get("cardId") if "cardId" in body else body.get("id"),
                body.get("kind"),
            )
            send_json(h, 200, res)
        except (KeyError, ValueError, TypeError) as exc:
            send_json(h, 400, {"error": str(exc)})

    @r.post(r"^/api/v2/jobs/superres$", name="v2_job_superres")
    def v2_job_superres(h, m, qs):
        body = read_json_body(h)
        try:
            res = ctx.jobs.enqueue_superres(
                body.get("mod") or "pjsk",
                body.get("cardId") if "cardId" in body else body.get("id"),
                body.get("kind"),
                tier=body.get("tier") or body.get("target") or "4k",
                engine=body.get("engine") or "ai",
            )
            send_json(h, 200, res)
        except (KeyError, ValueError, TypeError) as exc:
            send_json(h, 400, {"error": str(exc)})

    @r.post(r"^/api/v2/jobs/batch$", name="v2_job_batch")
    def v2_job_batch(h, m, qs):
        body = read_json_body(h)
        try:
            res = ctx.jobs.enqueue_batch(
                action=body.get("action") or "download",
                items=body.get("items") or [],
                tier=body.get("tier") or "4k",
                engine=body.get("engine") or "ai",
            )
            send_json(h, 200, res)
        except (KeyError, ValueError, TypeError) as exc:
            send_json(h, 400, {"error": str(exc)})

    @r.post(r"^/api/v2/jobs/([A-Za-z0-9_]+)/retry$", name="v2_job_retry")
    def v2_job_retry(h, m, qs):
        res, err, code = ctx.jobs.retry_job(m.group(1))
        if err:
            send_json(h, code, {"error": err})
            return
        send_json(h, 200, res)

    @r.delete(r"^/api/v2/jobs/([A-Za-z0-9_]+)$", name="v2_job_delete")
    def v2_job_delete(h, m, qs):
        ok, err, code = ctx.jobs.remove(m.group(1))
        if not ok:
            send_json(h, code, {"error": err})
            return
        send_json(h, 200, {"ok": True})

    @r.post(r"^/api/v2/jobs/clear$", name="v2_jobs_clear")
    def v2_jobs_clear(h, m, qs):
        removed = ctx.jobs.clear_finished()
        send_json(h, 200, {"ok": True, "removed": removed})

    # ---- ZIP 收藏包导出 ----
    @r.post(r"^/api/v2/export/zip$", name="v2_export_zip")
    def v2_export_zip(h, m, qs):
        body = read_json_body(h)
        try:
            data, added, skipped = ctx.jobs.build_zip_archive(
                items=body.get("items") or [],
                group_by=body.get("groupBy") or "unit",
                fetch_missing=bool(body.get("fetchMissing", True)),
            )
        except ValueError as exc:
            send_json(h, 400, {"error": str(exc)})
            return
        except RuntimeError as exc:
            send_json(h, 422, {"error": str(exc)})
            return
        stamp = time.strftime("%Y%m%d_%H%M%S")
        fname = f"卡牌雷达收藏包_{stamp}_{added}张.zip"
        ascii_name = f"card_radar_pack_{stamp}_{added}.zip"
        send_attachment_bytes(h, data, fname, ascii_name, ctype="application/zip")

    # ---- 缓存管理（覆盖全部四模块！）----
    @r.get(r"^/api/v2/cache$", name="v2_cache_stats")
    def v2_cache_stats(h, m, qs):
        send_json(h, 200, ctx.all_cache_stats())

    @r.delete(r"^/api/v2/cache$", name="v2_cache_clear")
    def v2_cache_clear(h, m, qs):
        mod = query_first(qs, "mod") or "all"
        try:
            send_json(h, 200, ctx.clear_cache(mod))
        except KeyError as exc:
            send_json(h, 404, {"error": str(exc)})

    # ---- 用户档案（收藏/分组/设置持久化）----
    @r.get(r"^/api/v2/user-data$", name="v2_user_data_get")
    def v2_user_data_get(h, m, qs):
        send_json(h, 200, ctx.user_data.get())

    @r.put(r"^/api/v2/user-data$", name="v2_user_data_put")
    def v2_user_data_put(h, m, qs):
        body = read_json_body(h)
        try:
            send_json(h, 200, ctx.user_data.update(body))
        except ValueError as exc:
            send_json(h, 400, {"error": str(exc)})

    # ---- 数据源可用性探活 ----
    @r.get(r"^/api/v2/sources/probe$", name="v2_sources_probe")
    def v2_sources_probe(h, m, qs):
        force = query_first(qs, "force") in ("1", "true")
        send_json(h, 200, ctx.probe_sources(force=force))

    # ================================================================
    # V1 向后兼容路由（确保旧脚本、旧书签、外部检查零破坏）
    # ================================================================
    @r.get(r"^/api/status$", name="v1_pjsk_status")
    def v1_pjsk_status(h, m, qs):
        pjsk = ctx.registry.require("pjsk").status_summary()
        shiny = ctx.registry.require("shinycolors").status_summary()
        onotes = ctx.registry.require("onotes").status_summary()
        bandori = ctx.registry.require("bandori").status_summary()
        send_json(h, 200, {
            "version": ctx.version,
            "updatedAt": pjsk["updatedAt"],
            "lastRun": pjsk["lastRun"],
            "lastResult": pjsk["lastResult"],
            "lastCounts": pjsk["lastCounts"],
            "cardCount": pjsk["cardCount"],
            "spoilerCount": pjsk["spoilerCount"],
            "originalsCount": pjsk["originalsCount"],
            "aiEngine": ai_engine_available(),
            "bandoriCardCount": bandori["cardCount"],
            "shinyCardCount": shiny["cardCount"],
            "onotesCardCount": onotes["cardCount"],
            "nextRun": pjsk["schedule"],
        })

    @r.get(r"^/api/index$", name="v1_pjsk_index")
    def v1_pjsk_index(h, m, qs):
        send_file(h, ctx.registry.require("pjsk").index_path, ctype="application/json; charset=utf-8")

    @r.get(r"^/api/cards/(\d+)$", name="v1_pjsk_detail")
    def v1_pjsk_detail(h, m, qs):
        detail = ctx.registry.require("pjsk").card_detail(int(m.group(1)))
        if detail is None:
            send_json(h, 404, {"error": "卡牌不存在"})
            return
        send_json(h, 200, detail)

    @r.get(r"^/api/thumbs/(\d+)_([a-z_]+)\.webp$", name="v1_pjsk_thumb")
    def v1_pjsk_thumb(h, m, qs):
        mod = ctx.registry.require("pjsk")
        p = safe_join(mod.thumb_dir, f"{m.group(1)}_{m.group(2)}.webp")
        if p and os.path.isfile(p):
            send_file(h, p, ctype="image/webp")
        else:
            send_json(h, 404, {"error": "缩略图不存在"})

    @r.get(r"^/api/originals/(\d+)_(normal|after_training)(?:_(2k|4k))?\.png$", name="v1_pjsk_original")
    def v1_pjsk_original(h, m, qs):
        p = ctx.registry.require("pjsk").find_existing_original(int(m.group(1)), m.group(2), tier=m.group(3))
        if p:
            send_file(h, p, ctype="image/png")
        else:
            send_json(h, 404, {"error": "原图尚未下载，请先点击「下载原图」"})

    @r.get(r"^/api/costume-thumb/([a-zA-Z0-9_]+)\.webp$", name="v1_costume_thumb")
    def v1_costume_thumb(h, m, qs):
        p = ctx.registry.require("pjsk").costume_thumb(m.group(1))
        if p:
            send_file(h, p, ctype="image/webp")
        else:
            send_json(h, 404, {"error": "服装缩略图不可用"})

    @r.get(r"^/api/download-progress/([A-Za-z0-9_]+)$", name="v1_dl_progress")
    def v1_dl_progress(h, m, qs):
        v2_job_get(h, m, qs)

    @r.get(r"^/api/download-jobs$", name="v1_dl_jobs")
    def v1_dl_jobs(h, m, qs):
        v2_jobs_list(h, m, qs)

    @r.get(r"^/api/cache-stats$", name="v1_cache_stats")
    def v1_cache_stats(h, m, qs):
        send_json(h, 200, ctx.all_cache_stats())

    @r.post(r"^/api/cache-clear$", name="v1_cache_clear")
    def v1_cache_clear(h, m, qs):
        mod = query_first(qs, "mod") or "all"
        send_json(h, 200, ctx.clear_cache(mod))

    @r.post(r"^/api/job-remove/([A-Za-z0-9_]+)$", name="v1_job_remove")
    def v1_job_remove(h, m, qs):
        v2_job_delete(h, m, qs)

    @r.post(r"^/api/download/(\d+)/([a-z_]+)$", name="v1_pjsk_download")
    def v1_pjsk_download(h, m, qs):
        try:
            send_json(h, 200, ctx.jobs.enqueue_download("pjsk", int(m.group(1)), m.group(2)))
        except ValueError as exc:
            send_json(h, 400, {"error": str(exc)})

    @r.post(r"^/api/superres/(\d+)/([a-z_]+)$", name="v1_pjsk_superres")
    def v1_pjsk_superres(h, m, qs):
        try:
            send_json(
                h,
                200,
                ctx.jobs.enqueue_superres(
                    "pjsk",
                    int(m.group(1)),
                    m.group(2),
                    tier=query_first(qs, "target", "4k"),
                    engine=query_first(qs, "engine", "ai"),
                ),
            )
        except ValueError as exc:
            send_json(h, 400, {"error": str(exc)})

    # ---- v1 邦多利 / 闪彩 / Our Notes 兼容路由 ----
    for mod_name in ("bandori", "shinycolors", "onotes"):
        _register_v1_module_routes(r, ctx, mod_name)

    return r


def _register_v1_module_routes(r, ctx, mod_id):
    @r.get(rf"^/api/{mod_id}/index$", name=f"v1_{mod_id}_index")
    def _idx(h, m, qs, _mid=mod_id):
        send_file(h, ctx.registry.require(_mid).index_path, ctype="application/json; charset=utf-8")

    @r.get(rf"^/api/{mod_id}/status$", name=f"v1_{mod_id}_status")
    def _st(h, m, qs, _mid=mod_id):
        send_json(h, 200, ctx.registry.require(_mid).status_summary())

    @r.get(rf"^/api/{mod_id}/cards/(\d+)(?:/(card|support))?$", name=f"v1_{mod_id}_detail")
    def _det(h, m, qs, _mid=mod_id):
        detail = ctx.registry.require(_mid).card_detail(int(m.group(1)), kind=m.group(2))
        if detail is None:
            send_json(h, 404, {"error": "卡面不存在或详情未就绪"})
            return
        send_json(h, 200, detail)

    @r.get(rf"^/api/{mod_id}/thumbs/(\d+)_([a-z_]+)\.webp$", name=f"v1_{mod_id}_thumb")
    def _th(h, m, qs, _mid=mod_id):
        try:
            p = ctx.registry.require(_mid).thumb_path(int(m.group(1)), m.group(2))
        except ValueError as exc:
            send_json(h, 400, {"error": str(exc)})
            return
        if p:
            send_file(h, p, ctype="image/webp")
        else:
            send_json(h, 404, {"error": "缩略图不存在"})

    if mod_id == "shinycolors":
        @r.get(r"^/api/shinycolors/originals/(\d+)(?:_(fes))?(?:_(2k|4k))?\.(jpg|png)$", name="v1_shiny_orig")
        def _sh_orig(h, m, qs):
            cid = int(m.group(1))
            kind = "fes" if m.group(2) else "normal"
            tier = m.group(3)
            p = ctx.registry.require("shinycolors").find_existing_original(cid, kind, tier=tier)
            if p:
                send_file(h, p, ctype="image/jpeg" if p.endswith(".jpg") else "image/png")
            else:
                send_json(h, 404, {"error": "原图尚未下载，请先点击「下载原图」"})
    else:
        @r.get(
            rf"^/api/{mod_id}/originals/(\d+)_(normal|after_training|card|support)(?:_(2k|4k))?\.png$",
            name=f"v1_{mod_id}_orig",
        )
        def _orig(h, m, qs, _mid=mod_id):
            try:
                p = ctx.registry.require(_mid).find_existing_original(int(m.group(1)), m.group(2), tier=m.group(3))
            except ValueError as exc:
                send_json(h, 400, {"error": str(exc)})
                return
            if p:
                send_file(h, p, ctype="image/png")
            else:
                send_json(h, 404, {"error": "原图尚未下载，请先点击「下载原图」"})

    @r.post(rf"^/api/{mod_id}/download/(\d+)(?:/([a-z_]+))?$", name=f"v1_{mod_id}_dl")
    def _dl(h, m, qs, _mid=mod_id):
        try:
            send_json(h, 200, ctx.jobs.enqueue_download(_mid, int(m.group(1)), m.group(2)))
        except ValueError as exc:
            send_json(h, 400, {"error": str(exc)})

    @r.post(rf"^/api/{mod_id}/superres/(\d+)(?:/([a-z_]+))?$", name=f"v1_{mod_id}_sr")
    def _sr(h, m, qs, _mid=mod_id):
        kind = m.group(2) or query_first(qs, "kind") or None
        try:
            send_json(
                h,
                200,
                ctx.jobs.enqueue_superres(
                    _mid,
                    int(m.group(1)),
                    kind,
                    tier=query_first(qs, "target", "4k"),
                    engine=query_first(qs, "engine", "ai"),
                ),
            )
        except ValueError as exc:
            send_json(h, 400, {"error": str(exc)})


def make_handler(ctx, router):
    class CardRadarHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):
            pass

        def _dispatch(self, method):
            path, qs = split_path_query(self.path)
            try:
                entry, match = router.resolve(method, path)
                if entry is not None:
                    entry.handler(self, match, qs)
                    return
                if method == "GET":
                    sub = "/index.html" if path == "/" else path
                    fp = safe_join(ctx.web_dir, sub)
                    if fp and os.path.isfile(fp):
                        send_file(self, fp)
                        return
                send_json(self, 404, {"error": "Not Found"})
            except ValueError as exc:
                send_json(self, 400, {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                log.exception("%s %s 处理异常", method, path)
                send_json(self, 500, {"error": str(exc)})

        def do_GET(self):
            self._dispatch("GET")

        def do_POST(self):
            self._dispatch("POST")

        def do_PUT(self):
            self._dispatch("PUT")

        def do_DELETE(self):
            self._dispatch("DELETE")

    return CardRadarHandler
