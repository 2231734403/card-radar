# -*- coding: utf-8 -*-
"""
统一任务调度与持久化引擎：
  - RLock 保证回调链嵌套加锁绝不死锁（严守 T1）
  - 原子落盘 data/jobs.json：重启后自动恢复历史记录，中断任务标为 interrupted 支持一键重试
  - 下载并发线程池（max_workers=3）与 AI 超分 GPU 串行锁分离，批量超分稳如磐石
  - 标准库 zipfile 导出收藏/勾选卡面压缩包（按乐队/稀有度/平铺分目录，零第三方依赖）
"""
import io
import json
import logging
import os
import random
import shutil
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor

from server.config import (
    SR_TIERS,
    atomic_write_json,
    downloads_dir,
    sanitize_name,
)
from server.upscaler import run_upscale

log = logging.getLogger("server.jobs")


class JobManager:
    def __init__(self, registry, persist_path=None, max_history=80, max_workers=3):
        self.registry = registry
        self.persist_path = persist_path
        self.max_history = max_history
        self._lock = threading.RLock()
        self._jobs = {}
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="cr-job")
        self._load_persisted()

    def _load_persisted(self):
        if not self.persist_path or not os.path.isfile(self.persist_path):
            return
        try:
            with open(self.persist_path, encoding="utf-8") as f:
                raw = json.load(f)
            items = raw.get("jobs") if isinstance(raw, dict) else []
            if not isinstance(items, list):
                return
            changed = False
            with self._lock:
                for item in items[: self.max_history]:
                    jid = item.get("jobId")
                    if not jid:
                        continue
                    rec = dict(item)
                    if rec.get("state") == "running":
                        rec["state"] = "error"
                        rec["interrupted"] = True
                        rec["error"] = "服务重启导致任务中断，可点击重试"
                        changed = True
                    self._jobs[jid] = rec
            if changed:
                self._persist_locked()
        except Exception as exc:  # noqa: BLE001
            log.warning("恢复历史任务失败（已忽略）：%s", exc)

    def _persist_locked(self):
        if not self.persist_path:
            return
        try:
            ordered = sorted(self._jobs.values(), key=lambda x: x.get("jobId", ""), reverse=True)
            atomic_write_json(self.persist_path, {"jobs": ordered[: self.max_history]})
        except Exception as exc:  # noqa: BLE001
            log.warning("任务持久化写入失败：%s", exc)

    def _prune_locked(self):
        if len(self._jobs) <= self.max_history:
            return
        finished = [(k, v) for k, v in self._jobs.items() if v.get("state") != "running"]
        finished.sort(key=lambda kv: kv[0])
        for k, _ in finished[: max(0, len(self._jobs) - self.max_history)]:
            self._jobs.pop(k, None)

    def _new_job_id(self, prefix):
        return f"{prefix}{int(time.time() * 1000)}_{random.randint(100, 999)}"

    def _set_job_fields(self, job_id, persist=False, **fields):
        with self._lock:
            j = self._jobs.get(job_id)
            if not j:
                return
            j.update(fields)
            if persist:
                self._persist_locked()

    def get(self, job_id):
        with self._lock:
            j = self._jobs.get(job_id)
            return dict(j) if j else None

    def list_jobs(self, mod=None, state=None):
        with self._lock:
            items = [dict(v) for v in self._jobs.values()]
        if mod:
            resolved = self.registry.get(mod)
            target_mod = resolved.id if resolved else mod
            items = [j for j in items if j.get("mod") == target_mod]
        if state:
            items = [j for j in items if j.get("state") == state]
        items.sort(key=lambda j: j.get("jobId", ""), reverse=True)
        return items[: self.max_history]

    def remove(self, job_id):
        with self._lock:
            j = self._jobs.get(job_id)
            if j is None:
                return False, "任务不存在", 404
            if j.get("state") == "running":
                return False, "任务进行中，结束后再删除", 400
            self._jobs.pop(job_id, None)
            self._persist_locked()
            return True, "", 200

    def clear_finished(self):
        with self._lock:
            to_del = [k for k, v in self._jobs.items() if v.get("state") != "running"]
            for k in to_del:
                self._jobs.pop(k, None)
            self._persist_locked()
            return len(to_del)

    def enqueue_download(self, mod_key, card_id, kind=None):
        mod = self.registry.require(mod_key)
        cid = int(card_id)
        norm_kind = mod.normalize_kind(kind)

        with self._lock:
            for jid, j in self._jobs.items():
                if (
                    j.get("type") == "download"
                    and j.get("mod") == mod.id
                    and j.get("card") == cid
                    and j.get("kind") == norm_kind
                    and j.get("state") == "running"
                ):
                    return {"ok": True, "jobId": jid, "reused": True}

            card = mod.find_card(cid, kind=norm_kind)
            prefix = (card.get("prefix") or f"卡面 #{cid}") if card else f"卡面 #{cid}"
            kind_lbl = mod.kind_label(norm_kind)
            label = f"{prefix[:40]} · {kind_lbl}"
            job_id = self._new_job_id("dl")
            self._jobs[job_id] = {
                "jobId": job_id,
                "type": "download",
                "mod": mod.id,
                "modName": mod.name,
                "card": cid,
                "kind": norm_kind,
                "kindLabel": kind_lbl,
                "state": "running",
                "phase": "download",
                "downloaded": 0,
                "total": 0,
                "source": "",
                "filename": "",
                "error": "",
                "already": False,
                "interrupted": False,
                "url": "",
                "label": label,
                "createdAt": int(time.time() * 1000),
            }
            self._prune_locked()
            self._persist_locked()

        self._pool.submit(self._run_download, job_id, mod, cid, norm_kind)
        return {"ok": True, "jobId": job_id, "reused": False}

    def enqueue_superres(self, mod_key, card_id, kind=None, tier="4k", engine="ai"):
        mod = self.registry.require(mod_key)
        cid = int(card_id)
        norm_kind = mod.normalize_kind(kind)
        tier = (tier or "4k").lower()
        if tier not in SR_TIERS:
            tier = "4k"
        engine = (engine or "ai").lower()
        if engine not in ("ai", "pillow"):
            engine = "ai"

        with self._lock:
            for jid, j in self._jobs.items():
                if (
                    j.get("type") == "superres"
                    and j.get("mod") == mod.id
                    and j.get("card") == cid
                    and j.get("kind") == norm_kind
                    and j.get("tier") == tier
                    and j.get("state") == "running"
                ):
                    return {"ok": True, "jobId": jid, "reused": True}

            card = mod.find_card(cid, kind=norm_kind)
            prefix = (card.get("prefix") or f"卡面 #{cid}") if card else f"卡面 #{cid}"
            kind_lbl = mod.kind_label(norm_kind)
            tier_label = "2K" if tier == "2k" else "4K"
            label = f"{prefix[:32]} · {kind_lbl} · {'AI超分' if engine == 'ai' else '超分'}{tier_label}"
            job_id = self._new_job_id("sr")
            self._jobs[job_id] = {
                "jobId": job_id,
                "type": "superres",
                "mod": mod.id,
                "modName": mod.name,
                "card": cid,
                "kind": norm_kind,
                "kindLabel": kind_lbl,
                "tier": tier,
                "engine": engine,
                "engineFallback": False,
                "state": "running",
                "phase": "download",
                "downloaded": 0,
                "total": 0,
                "source": "AI" if engine == "ai" else "Pillow",
                "srProgress": None,
                "filename": "",
                "error": "",
                "already": False,
                "interrupted": False,
                "url": "",
                "label": label,
                "createdAt": int(time.time() * 1000),
            }
            self._prune_locked()
            self._persist_locked()

        self._pool.submit(self._run_superres, job_id, mod, cid, norm_kind, tier, engine)
        return {"ok": True, "jobId": job_id, "reused": False}

    def enqueue_batch(self, action, items, tier="4k", engine="ai"):
        if action not in ("download", "superres"):
            raise ValueError("action 必须是 download 或 superres")
        if not isinstance(items, list) or not items:
            raise ValueError("items 必须是非空数组")
        if len(items) > 100:
            raise ValueError("单次批量任务最多 100 项")

        created = []
        errors = []
        for idx, item in enumerate(items):
            try:
                mod_key = item.get("mod") or "pjsk"
                cid = int(item.get("cardId") if "cardId" in item else item.get("id"))
                kind = item.get("kind")
                if action == "download":
                    res = self.enqueue_download(mod_key, cid, kind)
                else:
                    res = self.enqueue_superres(mod_key, cid, kind, tier=tier, engine=engine)
                created.append({"index": idx, "jobId": res["jobId"], "reused": res.get("reused", False)})
            except Exception as exc:  # noqa: BLE001
                errors.append({"index": idx, "error": str(exc)})
        return {"ok": True, "created": created, "errors": errors, "count": len(created)}

    def retry_job(self, job_id):
        snap = self.get(job_id)
        if not snap:
            return None, "任务不存在", 404
        if snap.get("state") == "running":
            return None, "任务正在运行中", 400
        if snap.get("type") == "superres":
            res = self.enqueue_superres(
                snap["mod"],
                snap["card"],
                snap.get("kind"),
                tier=snap.get("tier", "4k"),
                engine=snap.get("engine", "ai"),
            )
        else:
            res = self.enqueue_download(snap["mod"], snap["card"], snap.get("kind"))
        return res, "", 200

    # ---- 后台任务执行器 ----
    def _save_to_downloads(self, src_path, filename):
        ddir = downloads_dir()
        os.makedirs(ddir, exist_ok=True)
        dst = os.path.join(ddir, filename)
        if os.path.isfile(dst) and os.path.getsize(dst) > 0:
            return dst, False
        tmp = f"{dst}.{os.getpid()}.{threading.get_ident()}.dl"
        try:
            shutil.copyfile(src_path, tmp)
            os.replace(tmp, dst)
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
        return dst, True

    def _run_download(self, job_id, mod, card_id, kind):
        try:
            def cb(done, total, tag):
                self._set_job_fields(job_id, downloaded=done, total=total, source=tag)

            path, err = mod.resolve_original(card_id, kind, progress_cb=cb)
            if not path:
                self._set_job_fields(job_id, persist=True, state="error", error=err or "下载失败")
                return

            card = mod.find_card(card_id, kind=kind) or {"id": card_id, "prefix": f"卡面{card_id}"}
            filename = mod.download_filename(card, kind)
            try:
                _dst, created = self._save_to_downloads(path, filename)
            except Exception as exc:  # noqa: BLE001
                self._set_job_fields(
                    job_id,
                    persist=True,
                    state="error",
                    error=f"写入下载文件夹失败：{exc}",
                )
                return

            if created:
                log.info("原图已保存到下载文件夹：%s", filename)
            self._set_job_fields(
                job_id,
                persist=True,
                state="done",
                filename=filename,
                already=not created,
                url=mod.original_v2_url(card_id, kind),
            )
        except Exception as exc:  # noqa: BLE001
            self._set_job_fields(job_id, persist=True, state="error", error=str(exc))

    def _run_superres(self, job_id, mod, card_id, kind, tier, engine):
        try:
            # 1. 确保原图已缓存，缺失则自动级联下载
            src = mod.find_existing_original(card_id, kind)
            if not src:
                self._set_job_fields(job_id, phase="download", source="")

                def dcb(done, total, tag):
                    self._set_job_fields(job_id, downloaded=done, total=total, source=tag)

                src, err = mod.resolve_original(card_id, kind, progress_cb=dcb)
                if not src:
                    self._set_job_fields(
                        job_id,
                        persist=True,
                        state="error",
                        error=f"原图下载失败：{err}",
                    )
                    return

            # 2. 查规范/历史超分缓存，未命中则执行 GPU 串行 AI 或 Pillow 超分
            self._set_job_fields(job_id, phase="superres", downloaded=0, total=0)
            dst = mod.find_existing_original(card_id, kind, tier=tier)
            if not dst:
                dst = mod.original_path(card_id, kind, tier=tier)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                res = run_upscale(
                    src,
                    dst,
                    tier=tier,
                    engine=engine,
                    on_phase=lambda ph, src_tag: self._set_job_fields(job_id, phase=ph, source=src_tag),
                    on_progress=lambda pct: self._set_job_fields(job_id, srProgress=pct),
                )
                self._set_job_fields(
                    job_id,
                    engine=res["engine"],
                    engineFallback=res["fallback"],
                )
                log.info(
                    "超分完成（%s）：card %s(%s) [%s/%s] → %dx%d",
                    mod.id,
                    card_id,
                    kind,
                    tier,
                    res["engine"],
                    *res["size"],
                )

            # 3. 写入下载文件夹（保留原图副本）
            card = mod.find_card(card_id, kind=kind) or {"id": card_id, "prefix": f"卡面{card_id}"}
            dl_name = mod.download_filename(card, kind, tier=tier)
            _dst_dl, created = self._save_to_downloads(dst, dl_name)
            if created:
                log.info("超分图已保存到下载文件夹：%s", dl_name)
            self._set_job_fields(
                job_id,
                persist=True,
                state="done",
                filename=dl_name,
                already=not created,
                url=mod.original_v2_url(card_id, kind, tier=tier),
            )
        except ImportError:
            self._set_job_fields(
                job_id,
                persist=True,
                state="error",
                error="服务器缺少 Pillow，无法超分（pip install --user pillow）",
            )
        except Exception as exc:  # noqa: BLE001
            self._set_job_fields(job_id, persist=True, state="error", error=str(exc))

    # ---- ZIP 收藏包打包导出（纯标准库 zipfile） ----
    def build_zip_archive(self, items, group_by="unit", fetch_missing=True):
        """把选中的卡面（支持原图或指定超分档位）打包为内存 ZIP 字节流。
        group_by: 'unit'（按模块/乐队分目录）| 'rarity'（按模块/稀有度）| 'flat'（平铺）。"""
        if not isinstance(items, list) or not items:
            raise ValueError("导出列表不能为空")
        if len(items) > 60:
            raise ValueError("单次 ZIP 导出最多 60 张卡面")

        buf = io.BytesIO()
        added = 0
        skipped = []
        used_names = set()

        with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_STORED) as zf:
            for item in items:
                try:
                    mod = self.registry.require(item.get("mod") or "pjsk")
                    cid = int(item.get("cardId") if "cardId" in item else item.get("id"))
                    kind = mod.normalize_kind(item.get("kind"))
                    tier = (item.get("tier") or "").lower()
                    if tier not in ("", "2k", "4k"):
                        tier = ""

                    card = mod.find_card(cid, kind=kind)
                    if not card:
                        skipped.append({"mod": mod.id, "id": cid, "reason": "找不到卡面"})
                        continue

                    path = mod.find_existing_original(cid, kind, tier=tier or None)
                    if not path and not tier and fetch_missing:
                        path, err = mod.resolve_original(cid, kind)
                        if not path:
                            skipped.append({"mod": mod.id, "id": cid, "reason": err or "抓取失败"})
                            continue
                    if not path:
                        skipped.append({"mod": mod.id, "id": cid, "reason": "未缓存"})
                        continue

                    fname = mod.download_filename(card, kind, tier=tier or None)
                    if group_by == "unit":
                        folder = f"{sanitize_name(mod.name, 24)}/{sanitize_name(card.get('unitName') or '未分组', 32)}"
                        arcname = f"{folder}/{fname}"
                    elif group_by == "rarity":
                        r_label = str(card.get("rarity") or "未知")
                        folder = f"{sanitize_name(mod.name, 24)}/{sanitize_name(r_label, 16)}"
                        arcname = f"{folder}/{fname}"
                    else:
                        arcname = fname

                    if arcname in used_names:
                        base, ext = os.path.splitext(arcname)
                        arcname = f"{base}_{cid}{ext}"
                    used_names.add(arcname)
                    zf.write(path, arcname=arcname)
                    added += 1
                except Exception as exc:  # noqa: BLE001
                    skipped.append({"item": item, "reason": str(exc)})

            if skipped:
                manifest = {"exported": added, "skipped": skipped}
                zf.writestr("export_report.json", json.dumps(manifest, ensure_ascii=False, indent=2))

        if added == 0:
            raise RuntimeError("没有可导出的卡面图片（请确认网络连接或先下载原图）")
        return buf.getvalue(), added, len(skipped)

    def shutdown(self, wait=False):
        self._pool.shutdown(wait=wait)
