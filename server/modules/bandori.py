# -*- coding: utf-8 -*-
"""邦多利（BanG Dream! GBP / bestdori.com）模块适配器。"""
import json
import logging
import os

from server.config import JSON_CACHE, atomic_write_bytes, atomic_write_json
from server.modules.base import GameModule
from server.net import NotFoundError, fetch_bytes

log = logging.getLogger("server.modules.bandori")

BESTDORI_CARD_API = "https://bestdori.com/api/cards/{cid}.json"
BESTDORI_ART = "https://bestdori.com/assets/{region}/characters/resourceset/{res}_rip/{file}"
# 区域回退链：jp 主源 → cn（bilibili 服特有卡 bili_res*）→ en 兜底
REGIONS = ("jp", "cn", "en")


def _zh_pick(arr, fallback=""):
    """bestdori 多语言数组序 [日, 英, 繁, 简, 韩]，简体优先回退日文。"""
    if isinstance(arr, list) and len(arr) >= 4:
        return arr[3] or arr[0] or fallback
    if isinstance(arr, list) and arr:
        return arr[0] or fallback
    return fallback


class BandoriModule(GameModule):
    id = "bandori"
    route_id = "bandori"
    aliases = ()
    name = "邦多利卡面"
    icon = "🎸"
    theme = "bandori"
    schedule_text = "每两周 · 周一 09:20"
    source_name = "bestdori.com（双服时间 · 简体）"
    probe_target = "https://bestdori.com/api/bands/main.1.json"
    brand = "Bandori卡牌"

    def _resolve_db_dir(self, data_dir):
        return os.path.join(data_dir, "bandori")

    def _resolve_thumb_dir(self, data_dir):
        return os.path.join(data_dir, "thumbs_bandori")

    def _resolve_original_dir(self, data_dir):
        return os.path.join(data_dir, "originals_bandori")

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
        return f"/api/bandori/originals/{int(card_id)}_{k}{suffix}.png"

    def resolve_original(self, card_id, kind="normal", progress_cb=None):
        k = self.normalize_kind(kind)
        card = self.find_card(card_id)
        if not card:
            return None, "找不到该卡牌"
        res = card.get("assetbundleName")
        if not res:
            return None, "该卡牌没有卡面资源"
        if k == "after_training" and not card.get("trainable"):
            return None, "该卡牌不支持突破（4★ 以上专属）"

        existing = self.find_existing_original(card_id, k)
        if existing:
            return existing, None

        remote_file = "card_after_training.png" if k == "after_training" else "card_normal.png"
        last_err = None
        for region in REGIONS:
            url = BESTDORI_ART.format(region=region, res=res, file=remote_file)

            def cb(done, total, tag, _region=region):
                if progress_cb:
                    progress_cb(done, total, f"{_region}/{tag}")

            try:
                data, tag = fetch_bytes(url, timeout=60, expect_image=True, progress_cb=cb)
                dst = self.original_path(card_id, k)
                atomic_write_bytes(dst, data)
                log.info(
                    "邦多利原图已缓存：card %s %s（%.1f KB，%s/%s）",
                    card_id,
                    k,
                    len(data) / 1024,
                    region,
                    tag,
                )
                return dst, None
            except NotFoundError:
                last_err = f"资源不存在（{region} 区域）"
                continue
            except Exception as exc:  # noqa: BLE001
                last_err = f"{region}: {exc}"
        return None, last_err or "全部区域失败"

    def _skill_lines(self, skill_id):
        skills = JSON_CACHE.read_optional(os.path.join(self.db_dir, "skills_all.json"), {}) or {}
        sk = skills.get(str(skill_id))
        if not sk:
            return []
        desc = sk.get("description") or []
        dur = sk.get("duration") or []
        hi = dur[-1] if dur else None
        tags = ["ja", "en", "zh-Hant", "zh-Hans", "ko"]
        out = []
        for i in range(min(len(desc), len(tags))):
            txt = desc[i]
            if not txt:
                continue
            if hi is not None and "{0}" in txt:
                txt = txt.replace("{0}", str(hi))
            out.append([tags[i], txt])
        return out

    def card_detail(self, card_id, kind=None):
        cid = int(card_id)
        card = self.find_card(cid)
        if not card:
            return None

        cache = os.path.join(self.db_dir, f"card_{cid}.json")
        raw = JSON_CACHE.read_optional(cache)
        if raw is None:
            try:
                data, _ = fetch_bytes(BESTDORI_CARD_API.format(cid=cid), timeout=30)
                raw = json.loads(data.decode("utf-8"))
                atomic_write_json(cache, raw)
                JSON_CACHE.invalidate(cache)
            except NotFoundError:
                return None
            except Exception as exc:  # noqa: BLE001
                log.warning("邦多利详情现场拉取失败 card %s：%s", cid, exc)
                raw = {}

        episodes = []
        for ep in ((raw.get("episodes") or {}).get("entries") or []):
            episodes.append({
                "title": _zh_pick(ep.get("title")),
                "type": ep.get("episodeType"),
                "append": [
                    ep.get("appendPerformance"),
                    ep.get("appendTechnique"),
                    ep.get("appendVisual"),
                ],
                "releaseLevel": ep.get("releaseLevel"),
            })

        media = self.media_status(cid, ("normal", "after_training"))
        originals = {}
        if media["normal"]["hasOriginal"]:
            originals["normal"] = self.original_legacy_url(cid, "normal")
        if media["after_training"]["hasOriginal"]:
            originals["trained"] = self.original_legacy_url(cid, "after_training")

        return {
            "card": card,
            "prefix": _zh_pick(raw.get("prefix"), card.get("prefix")),
            "skillName": _zh_pick(raw.get("skillName"), card.get("skillName") or ""),
            "skillLines": self._skill_lines(raw.get("skillId") or card.get("skillId")),
            "gachaText": _zh_pick(raw.get("gachaText")),
            "cardType": raw.get("type") or card.get("cardType"),
            "levelLimit": raw.get("levelLimit"),
            "episodes": episodes,
            "originals": originals,
            "media": media,
        }
