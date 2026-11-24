# -*- coding: utf-8 -*-
"""PJSK（Project Sekai）模块适配器。"""
import logging
import os
import re

from server.config import JSON_CACHE, atomic_write_bytes
from server.modules.base import GameModule
from server.net import fetch_to_file, race_fetch

log = logging.getLogger("server.modules.pjsk")

STORAGE_MAIN = "https://storage.pjsk.moe/sekai-jp-assets"
STORAGE_BACKUP = "https://storage.exmeaning.com/sekai-jp-assets"
_ASSET_RE = re.compile(r"^[a-z0-9_]+$", re.IGNORECASE)


def fmt_skill_description(desc, effects, character_name=""):
    """把 PJSK 技能描述模板替换成最高等级实际数值。
    模板：{{id;type}}（d 时长 / v 数值 / e 追加值 / m 上限 / c 角色名）；
    双参 {{id1,id2;type}} 取两效果聚合。"""
    if not desc:
        return ""

    def find_effect(eid):
        for eff in effects:
            if eff.get("id") == eid:
                return eff
        return None

    def detail_at(eid):
        eff = find_effect(eid)
        if not eff:
            return None
        details = eff.get("skillEffectDetails") or []
        return max(details, key=lambda d: d.get("level", 0)) if details else None

    def fmt_num(v):
        if isinstance(v, float) and v.is_integer():
            return str(int(v))
        return str(v)

    def single(m):
        eid, typ = int(m.group(1)), m.group(2)
        if typ == "c":
            return character_name or m.group(0)
        eff = find_effect(eid)
        det = detail_at(eid)
        if not eff or not det:
            return m.group(0)
        if typ == "d":
            return fmt_num(det.get("activateEffectDuration", m.group(0)))
        if typ == "v":
            return fmt_num(det.get("activateEffectValue", m.group(0)))
        if typ == "e":
            ev = (eff.get("skillEnhance") or {}).get("activateEffectValue")
            return fmt_num(ev) if ev is not None else m.group(0)
        if typ == "m":
            ev = (eff.get("skillEnhance") or {}).get("activateEffectValue")
            if ev is not None:
                return fmt_num(ev * 5 + (det.get("activateEffectValue") or 0))
            return m.group(0)
        return m.group(0)

    def double(m):
        id1, id2, typ = int(m.group(1)), int(m.group(2)), m.group(3)

        def val(eid, prefer2=False):
            det = detail_at(eid)
            if not det:
                return 0
            if prefer2 and det.get("activateEffectValue2") is not None:
                return det.get("activateEffectValue2")
            return det.get("activateEffectValue") or 0

        v1, v2 = val(id1), val(id2)
        if typ in ("u", "s", "v"):
            return str(v1 + v2)
        if typ == "o":
            return str(val(id1, True) + val(id2, True))
        if typ == "r":
            return str(v2 if v2 > 0 else v1)
        return m.group(0)

    desc = re.sub(r"\{\{(\d+),(\d+);(\w+)\}\}", double, desc)
    return re.sub(r"\{\{(\d+);(\w+)\}\}", single, desc)


class PjskModule(GameModule):
    id = "pjsk"
    route_id = "pjsk"
    aliases = ()
    name = "PJSK 卡面"
    icon = "🐳"
    theme = "pjsk"
    schedule_text = "每两周 · 周一 09:00"
    source_name = "pjsk.moe（JP 服 · 中文化）"
    probe_target = "https://metadata.pjsk.moe/jp/master/gameCharacters.json"
    brand = "Pjsk卡牌"

    def __init__(self, data_dir):
        super().__init__(data_dir)
        self.costume_thumb_dir = os.path.join(data_dir, "thumbs_costume")

    def _resolve_db_dir(self, data_dir):
        return os.path.join(data_dir, "db")

    def _resolve_thumb_dir(self, data_dir):
        return os.path.join(data_dir, "thumbs")

    def _resolve_original_dir(self, data_dir):
        return os.path.join(data_dir, "originals")

    def _resolve_state_path(self, data_dir):
        return os.path.join(data_dir, "state.json")

    def normalize_kind(self, kind=None):
        k = (kind or "normal").lower()
        if k in ("trained", "after_training"):
            return "after_training"
        if k == "normal":
            return "normal"
        raise ValueError("kind 必须是 normal 或 after_training")

    def allowed_kinds(self):
        return ("normal", "after_training")

    def kind_label(self, kind):
        return "突破后" if self.normalize_kind(kind) == "after_training" else "突破前"

    def thumb_filename(self, card_id, kind):
        k = self.normalize_kind(kind)
        return f"{int(card_id)}_{'trained' if k == 'after_training' else 'normal'}.webp"

    def original_filename_disk(self, card_id, kind, tier=None):
        k = self.normalize_kind(kind)
        return f"{int(card_id)}_{k}_{tier}.png" if tier else f"{int(card_id)}_{k}.png"

    def legacy_original_filenames_disk(self, card_id, kind, tier=None):
        k = self.normalize_kind(kind)
        if k == "after_training" and tier:
            return (f"{int(card_id)}_trained_{tier}.png",)
        return ()

    def original_legacy_url(self, card_id, kind, tier=None):
        k = self.normalize_kind(kind)
        suffix = f"_{tier}" if tier else ""
        return f"/api/originals/{int(card_id)}_{k}{suffix}.png"

    def costume_thumb(self, abn):
        if not _ASSET_RE.match(abn or ""):
            return None
        os.makedirs(self.costume_thumb_dir, exist_ok=True)
        path = os.path.join(self.costume_thumb_dir, f"{abn}.webp")
        if os.path.isfile(path) and os.path.getsize(path) > 0:
            return path
        for base in (STORAGE_MAIN, STORAGE_BACKUP):
            try:
                fetch_to_file(f"{base}/thumbnail/costume/{abn}.webp", path, timeout=20, expect_image=True)
                return path
            except Exception:  # noqa: BLE001
                continue
        return None

    def resolve_original(self, card_id, kind="normal", progress_cb=None):
        k = self.normalize_kind(kind)
        card = self.find_card(card_id)
        if not card:
            return None, "找不到该卡牌"
        abn = card.get("assetbundleName")
        if not abn:
            return None, "该卡牌没有卡面资源"
        if k == "after_training" and not card.get("trainable"):
            return None, "该卡牌不支持突破（3★/4★ 专属）"

        existing = self.find_existing_original(card_id, k)
        if existing:
            return existing, None

        remote = (
            f"/character/member/{abn}/card_after_training.png"
            if k == "after_training"
            else f"/character/member/{abn}/card_normal.png"
        )
        urls = [STORAGE_MAIN + remote, STORAGE_BACKUP + remote]

        def cb(done, total, url):
            if progress_cb:
                progress_cb(done, total, "主源" if "pjsk.moe" in url else "备源")

        try:
            data, winner = race_fetch(urls, progress_cb=cb, expect_image=True)
        except Exception as exc:  # noqa: BLE001
            return None, f"下载失败：{exc}"

        dst = self.original_path(card_id, k)
        atomic_write_bytes(dst, data)
        log.info(
            "PJSK 原图已缓存：card %s %s（%.1f KB，%s）",
            card_id,
            k,
            len(data) / 1024,
            "主源" if "pjsk.moe" in winner else "备源",
        )
        return dst, None

    def card_detail(self, card_id, kind=None):
        cid = int(card_id)
        card = self.find_card(cid)
        if not card:
            return None
        skills = JSON_CACHE.read_optional(os.path.join(self.db_dir, "skills.json"), []) or []
        characters = JSON_CACHE.read_optional(os.path.join(self.db_dir, "gameCharacters.json"), []) or []
        episodes = JSON_CACHE.read_optional(os.path.join(self.db_dir, "cardEpisodes.json"), []) or []

        skill = next(
            (s for s in skills if s.get("id") == card.get("skillId") and card.get("skillId")),
            None,
        )
        char = next((c for c in characters if c.get("id") == card.get("characterId")), None)
        eps = [
            {
                "id": e.get("id"),
                "title": "卡牌剧情（下篇）" if e.get("cardEpisodePartType") == "second_part" else "卡牌剧情（上篇）",
                "partType": e.get("cardEpisodePartType"),
            }
            for e in episodes
            if str(e.get("cardId")) == str(cid)
        ]

        media = self.media_status(cid, ("normal", "after_training"))
        originals = {
            "normal": media["normal"]["hasOriginal"],
            "trained": media["after_training"]["hasOriginal"],
            "sr2k_normal": media["normal"]["has2k"],
            "sr2k_trained": media["after_training"]["has2k"],
            "sr4k_normal": media["normal"]["has4k"],
            "sr4k_trained": media["after_training"]["has4k"],
        }

        skill_desc = fmt_skill_description(
            (skill or {}).get("description", ""),
            (skill or {}).get("skillEffects") or [],
            character_name=card.get("characterName") or "",
        )
        return {
            "card": card,
            "skill": {
                "name": card.get("skillName"),
                "description": skill_desc,
                "spriteName": (skill or {}).get("descriptionSpriteName"),
            }
            if skill
            else None,
            "character": {
                "name": card.get("characterFullName"),
                "givenName": card.get("characterName"),
                "unit": card.get("unitName"),
                "height": (char or {}).get("height"),
                "birthday": (char or {}).get("birthday"),
            }
            if char
            else None,
            "episodes": eps,
            "originals": originals,
            "media": media,
        }
