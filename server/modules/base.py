# -*- coding: utf-8 -*-
"""
游戏模块统一抽象契约（GameModule + ResourceKey）：
把所有「单形态 vs 多形态（normal/after_training/fes/card/support）」的：
  - URL 形态归一
  - 缩略图 / 原图 / 超分图磁盘路径
  - 历史遗留文件名兼容读取（修复旧版 _trained_2k/_trained_4k 错位 404！）
  - 下载落盘规范命名
  - 缓存统计与分模块清理
全部收敛到一个单一真源基类，从结构上终结 T12 / T20 / T22。
"""
import os
from dataclasses import dataclass

from server.config import JSON_CACHE, sanitize_name


@dataclass(frozen=True)
class ResourceKey:
    mod: str
    card_id: int
    kind: str


class GameModule:
    # 子类覆盖以下元数据
    id = ""              # 规范后端 ID：pjsk | bandori | shinycolors | onotes
    route_id = ""        # 前端 hash 路由 ID：pjsk | bandori | sc | onotes
    aliases = ()         # 可接受的别名，如 ("sc",)
    name = ""
    icon = ""
    theme = ""
    schedule_text = ""
    source_name = ""
    probe_target = ""
    brand = ""
    composite_key = False  # True 时按 (card_id, kind) 复合键查卡（Our Notes）

    def __init__(self, data_dir):
        self.data_dir = data_dir
        self.db_dir = self._resolve_db_dir(data_dir)
        self.thumb_dir = self._resolve_thumb_dir(data_dir)
        self.original_dir = self._resolve_original_dir(data_dir)
        self.state_path = self._resolve_state_path(data_dir)
        self.retry_path = os.path.join(self.db_dir, "retry.json")

    def _resolve_db_dir(self, data_dir):
        raise NotImplementedError

    def _resolve_thumb_dir(self, data_dir):
        raise NotImplementedError

    def _resolve_original_dir(self, data_dir):
        raise NotImplementedError

    def _resolve_state_path(self, data_dir):
        return os.path.join(self.db_dir, "state.json")

    # ---- 形态契约 ----
    def normalize_kind(self, kind=None):
        raise NotImplementedError

    def allowed_kinds(self):
        raise NotImplementedError

    def kind_label(self, kind):
        raise NotImplementedError

    def thumb_filename(self, card_id, kind):
        raise NotImplementedError

    def original_filename_disk(self, card_id, kind, tier=None):
        """规范磁盘缓存文件名（唯一真源）。"""
        raise NotImplementedError

    def legacy_original_filenames_disk(self, card_id, kind, tier=None):
        """兼容历史版本落盘命名（只读回退，避免升级后旧缓存失效）。"""
        return ()

    def original_v2_url(self, card_id, kind, tier=None):
        k = self.normalize_kind(kind)
        base = f"/api/v2/modules/{self.id}/originals/{card_id}/{k}"
        return f"{base}?tier={tier}" if tier else base

    def original_legacy_url(self, card_id, kind, tier=None):
        return self.original_v2_url(card_id, kind, tier=tier)

    def thumb_v2_url(self, card_id, kind):
        k = self.normalize_kind(kind)
        return f"/api/v2/modules/{self.id}/thumbs/{card_id}/{k}"

    def download_filename(self, card, kind, tier=None):
        """系统「下载」文件夹与 ZIP 导出使用的规范文件名。"""
        k = self.normalize_kind(kind)
        prefix = sanitize_name((card or {}).get("prefix"))
        char_name = sanitize_name(
            (card or {}).get("characterFullName") or (card or {}).get("characterName")
        )
        label = self.kind_label(k)
        tier_suffix = "_4K超分" if tier == "4k" else "_2K超分" if tier == "2k" else ""
        cid = (card or {}).get("id", "0")
        return f"{self.brand}_{cid}_{prefix}_{char_name}_{label}{tier_suffix}.png"

    # ---- 索引与查卡 ----
    @property
    def index_path(self):
        return os.path.join(self.db_dir, "index.json")

    def load_index(self):
        return JSON_CACHE.read(self.index_path)

    def load_index_optional(self):
        return JSON_CACHE.read_optional(self.index_path, {"updatedAt": 0, "cards": []})

    def find_card(self, card_id, kind=None):
        cards = self.load_index_optional().get("cards", [])
        cid = int(card_id)
        if self.composite_key and kind is not None:
            want = self.normalize_kind(kind)
            return next(
                (c for c in cards if c.get("id") == cid and self.normalize_kind(c.get("cardKind")) == want),
                None,
            )
        return next((c for c in cards if c.get("id") == cid), None)

    # ---- 文件路径解析 ----
    def thumb_path(self, card_id, kind):
        fname = self.thumb_filename(int(card_id), kind)
        p = os.path.join(self.thumb_dir, fname)
        return p if os.path.isfile(p) and os.path.getsize(p) > 0 else None

    def original_path(self, card_id, kind, tier=None):
        fname = self.original_filename_disk(int(card_id), kind, tier=tier)
        return os.path.join(self.original_dir, fname)

    def find_existing_original(self, card_id, kind, tier=None):
        """优先查规范路径，未命中时查历史遗留文件名（自动兼容旧缓存）。"""
        cid = int(card_id)
        k = self.normalize_kind(kind)
        p = self.original_path(cid, k, tier=tier)
        if os.path.isfile(p) and os.path.getsize(p) > 0:
            return p
        for alt in self.legacy_original_filenames_disk(cid, k, tier=tier):
            ap = os.path.join(self.original_dir, alt)
            if os.path.isfile(ap) and os.path.getsize(ap) > 0:
                return ap
        return None

    def media_status(self, card_id, kinds):
        """返回各形态的原图与 2K/4K 超分就绪状态，供详情页在线查看与对比滑块使用。"""
        cid = int(card_id)
        out = {}
        for k in kinds:
            nk = self.normalize_kind(k)
            orig = self.find_existing_original(cid, nk)
            sr2k = self.find_existing_original(cid, nk, tier="2k")
            sr4k = self.find_existing_original(cid, nk, tier="4k")
            out[nk] = {
                "hasOriginal": bool(orig),
                "originalUrl": self.original_v2_url(cid, nk) if orig else "",
                "has2k": bool(sr2k),
                "url2k": self.original_v2_url(cid, nk, tier="2k") if sr2k else "",
                "has4k": bool(sr4k),
                "url4k": self.original_v2_url(cid, nk, tier="4k") if sr4k else "",
            }
        return out

    # ---- 子类实现的核心数据能力 ----
    def resolve_original(self, card_id, kind, progress_cb=None):
        raise NotImplementedError

    def card_detail(self, card_id, kind=None):
        raise NotImplementedError

    # ---- 状态与缓存管理 ----
    def cache_stats(self):
        total = 0
        count = 0
        if os.path.isdir(self.original_dir):
            for fname in os.listdir(self.original_dir):
                if fname.endswith((".png", ".jpg", ".webp")):
                    fp = os.path.join(self.original_dir, fname)
                    if os.path.isfile(fp):
                        count += 1
                        total += os.path.getsize(fp)
        return {
            "mod": self.id,
            "name": self.name,
            "count": count,
            "bytes": total,
            "mb": round(total / 1048576, 2),
        }

    def clear_cache(self):
        removed = 0
        freed = 0
        if os.path.isdir(self.original_dir):
            for fname in os.listdir(self.original_dir):
                if fname.endswith((".png", ".jpg", ".webp", ".low")):
                    fp = os.path.join(self.original_dir, fname)
                    try:
                        if os.path.isfile(fp):
                            freed += os.path.getsize(fp)
                            os.remove(fp)
                            removed += 1
                    except OSError:
                        pass
        return {
            "mod": self.id,
            "removed": removed,
            "bytes": freed,
            "freedMB": round(freed / 1048576, 2),
        }

    def status_summary(self):
        idx = self.load_index_optional()
        cards = idx.get("cards", [])
        state = JSON_CACHE.read_optional(self.state_path, {}) or {}
        retry_q = JSON_CACHE.read_optional(self.retry_path, {}) or {}
        cache = self.cache_stats()
        return {
            "id": self.id,
            "routeId": self.route_id,
            "name": self.name,
            "icon": self.icon,
            "theme": self.theme,
            "sourceName": self.source_name,
            "schedule": self.schedule_text,
            "cardCount": len(cards),
            "spoilerCount": sum(1 for c in cards if c.get("spoiler")),
            "updatedAt": idx.get("updatedAt"),
            "dataVersion": idx.get("dataVersion", ""),
            "lastRun": state.get("last_run"),
            "lastResult": state.get("last_result"),
            "lastCounts": state.get("counts"),
            "retryPending": len(retry_q.get("items", {})) if isinstance(retry_q, dict) else 0,
            "originalsCount": cache["count"],
            "cacheMB": cache["mb"],
        }
