# -*- coding: utf-8 -*-
"""Our Notes（BanG Dream! Our Notes / bdon.moe）模块适配器。
角色卡（card）与支援卡（support）ID 序列重叠，全链路强制 (kind, id) 复合键。"""
import logging
import os

from scraper.common.onotes_md import parse_detail_md, to_int
from server.config import JSON_CACHE, atomic_write_bytes, atomic_write_json, sanitize_name
from server.modules.base import GameModule
from server.modules.shinycolors import convert_bytes_to_png_file
from server.net import fetch_bytes

log = logging.getLogger("server.modules.onotes")

ONOTES_ASSET = "https://assets.bdon.moe/zh-Hans"
ONOTES_ART = {
    "card": ONOTES_ASSET + "/MemberCard/{id}/member_full/member_full.webp",
    "support": ONOTES_ASSET + "/SupportCard/{id}/snap_full/snap_full.webp",
}
ONOTES_MD = {
    "card": "https://bdon.moe/cards/{id}.md",
    "support": "https://bdon.moe/support-cards/{id}.md",
}


class OnotesModule(GameModule):
    id = "onotes"
    route_id = "onotes"
    aliases = ()
    name = "Our Notes 卡面"
    icon = "🎶"
    theme = "onotes"
    schedule_text = "每两周 · 周一 10:00"
    source_name = "bdon.moe（Moenotes · 简体）"
    probe_target = "https://bdon.moe/cards.md"
    brand = "OurNotes卡牌"
    composite_key = True

    def _resolve_db_dir(self, data_dir):
        return os.path.join(data_dir, "onotes")

    def _resolve_thumb_dir(self, data_dir):
        return os.path.join(data_dir, "thumbs_onotes")

    def _resolve_original_dir(self, data_dir):
        return os.path.join(data_dir, "originals_onotes")

    def normalize_kind(self, kind=None):
        k = (kind or "card").lower()
        if k in ("support", "s", "支援卡", "snap"):
            return "support"
        if k in ("card", "member", "角色卡"):
            return "card"
        raise ValueError("kind 必须是 card 或 support")

    def allowed_kinds(self):
        return ("card", "support")

    def kind_label(self, kind):
        return "支援卡" if self.normalize_kind(kind) == "support" else "角色卡"

    def thumb_filename(self, card_id, kind):
        k = self.normalize_kind(kind)
        return f"{int(card_id)}_{k}.webp"

    def original_filename_disk(self, card_id, kind, tier=None):
        k = self.normalize_kind(kind)
        return f"{int(card_id)}_{k}_{tier}.png" if tier else f"{int(card_id)}_{k}.png"

    def original_legacy_url(self, card_id, kind, tier=None):
        k = self.normalize_kind(kind)
        suffix = f"_{tier}" if tier else ""
        return f"/api/onotes/originals/{int(card_id)}_{k}{suffix}.png"

    def download_filename(self, card, kind="card", tier=None):
        k = self.normalize_kind(kind)
        brand = "OurNotes支援卡" if k == "support" else "OurNotes卡牌"
        tier_suffix = "_4K超分" if tier == "4k" else "_2K超分" if tier == "2k" else ""
        cid = (card or {}).get("id", "0")
        return f"{brand}_{cid}_{sanitize_name((card or {}).get('prefix'))}{tier_suffix}.png"

    def resolve_original(self, card_id, kind="card", progress_cb=None):
        k = self.normalize_kind(kind)
        # 修复原版遗漏 kind 过滤的复合键 Bug
        card = self.find_card(card_id, kind=k)
        if not card:
            return None, "找不到该卡面"

        os.makedirs(self.original_dir, exist_ok=True)
        png = self.original_path(card_id, k)
        if os.path.isfile(png) and os.path.getsize(png) > 0:
            return png, None

        webp = os.path.join(self.original_dir, f"{int(card_id)}_{k}.webp")
        if os.path.isfile(webp) and os.path.getsize(webp) > 0:
            return convert_bytes_to_png_file(webp, png)

        url = ONOTES_ART[k].format(id=int(card_id))
        try:
            data, tag = fetch_bytes(url, timeout=120, expect_image=True, progress_cb=progress_cb)
        except Exception as exc:  # noqa: BLE001
            return None, f"原图下载失败：{exc}"

        atomic_write_bytes(webp, data)
        out, err = convert_bytes_to_png_file(data, png)
        if out:
            log.info("Our Notes 原图已缓存（PNG）：card %s(%s)（%s）", card_id, k, tag)
        return out, err

    def card_detail(self, card_id, kind=None):
        cid = int(card_id)
        k = self.normalize_kind(kind)
        card = self.find_card(cid, kind=k)
        if not card:
            return None

        cache = os.path.join(self.db_dir, f"{k}_{cid}.json")
        raw = JSON_CACHE.read_optional(cache)
        if raw is None:
            try:
                data, _ = fetch_bytes(ONOTES_MD[k].format(id=cid), timeout=60)
                raw = parse_detail_md(data.decode("utf-8", "replace"), kind=k)
                atomic_write_json(cache, raw)
                JSON_CACHE.invalidate(cache)
            except Exception as exc:  # noqa: BLE001
                log.warning("Our Notes 详情现场拉取失败 card %s(%s)：%s", cid, k, exc)
                raw = {"fields": {}, "flavor": "", "skills": []}

        f = raw.get("fields") or {}
        num = lambda key: to_int((f.get(key) or {}).get("text"))  # noqa: E731
        media = self.media_status(cid, (k,))
        return {
            "card": card,
            "kind": k,
            "band": (f.get("乐队") or {}).get("text") or card.get("unitName"),
            "rarity": (f.get("稀有度") or {}).get("text") or card.get("rarity"),
            "attr": (f.get("属性") or {}).get("text") or card.get("attr") or "",
            "characterLinks": f.get("_charLinks") or [],
            "pf": num("Performance"),
            "tc": num("Technic"),
            "vi": num("Visual"),
            "total": num("Total Power") or card.get("power"),
            "release": (f.get("Release") or {}).get("text", "") or card.get("releaseDate") or "",
            "servers": (f.get("Servers") or {}).get("text", ""),
            "flavor": raw.get("flavor") or "",
            "skills": raw.get("skills") or [],
            "hasOriginal": media[k]["hasOriginal"],
            "hasTrained": False,
            "media": media,
        }
