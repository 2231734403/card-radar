# -*- coding: utf-8 -*-
"""闪耀色彩（Shiny Colors / shinycolors.moe + gameo.jp 2× 高清）模块适配器。"""
import io
import json
import logging
import os
import time
from urllib.parse import quote

from server.config import JSON_CACHE, atomic_write_bytes, atomic_write_json, sanitize_name
from server.modules.base import GameModule
from server.net import NotFoundError, fetch_bytes

log = logging.getLogger("server.modules.shinycolors")

SHINY_CARD_API = "https://api.shinycolors.moe/info/{ep}?cardId={uuid}"
SHINY_ART = "https://cf-static.shinycolors.moe/images/content/{dir}/card/{enza}.jpg"
SHINY_FES = "https://cf-static.shinycolors.moe/images/content/{dir}/fes_card/{enza}.jpg"
SHINY_GAMEO = "https://gameo.jp/img/imassc/card/{name}.{ext}"
SHINY_GAMEO_WEBP_AFTER = "2024-10-08"
SHINY_ART_DIRS = {"P": "idols", "S": "support_idols"}


def build_shiny_source_urls(card, kind="normal"):
    """原图候选 URL（画质从高到低）：
    1) gameo.jp 2272×1280 社区高清档（标题净化去 / : #，’→'，…→...，特训后加 2）
    2) cf-static 1136×640 官方兜底档。"""
    urls = []
    name = (card.get("prefix") or "").strip()
    if name and not name.startswith("【"):
        name = f"【{name}】{card.get('characterName') or ''}"
    safe = (
        name.replace("/", "")
        .replace(":", "")
        .replace("#", "")
        .replace("’", "'")
        .replace("…", "...")
    )
    stem = safe + ("2" if kind == "fes" else "")
    exts = (
        ["webp", "jpg"]
        if (card.get("releaseDate") or "") > SHINY_GAMEO_WEBP_AFTER
        else ["jpg", "webp"]
    )
    for ext in exts:
        urls.append(SHINY_GAMEO.format(name=quote(stem), ext=ext))
    d = SHINY_ART_DIRS.get(card.get("cardKind") or "S", "support_idols")
    tmpl = SHINY_FES if kind == "fes" else SHINY_ART
    if card.get("enzaId"):
        urls.append(tmpl.format(dir=d, enza=card["enzaId"]))
    return urls


def convert_bytes_to_png_file(src_bytes_or_path, dst_png):
    """任意图档字节或路径 → 无损 PNG 原子落盘（严格关闭句柄防 Windows 锁冲突）。"""
    try:
        from PIL import Image  # noqa: PLC0415
    except ImportError:
        return None, "服务器缺少 Pillow，无法转出 PNG（pip install --user pillow）"
    try:
        src = io.BytesIO(src_bytes_or_path) if isinstance(src_bytes_or_path, (bytes, bytearray)) else src_bytes_or_path
        buf = io.BytesIO()
        with Image.open(src) as im:
            rgb = im.convert("RGB")
            rgb.save(buf, "PNG", compress_level=6)
        atomic_write_bytes(dst_png, buf.getvalue())
        return dst_png, None
    except Exception as exc:  # noqa: BLE001
        return None, f"PNG 转换失败：{exc}"


def _image_width(path):
    try:
        from PIL import Image  # noqa: PLC0415
        with Image.open(path) as im:
            return im.width
    except Exception:  # noqa: BLE001
        return 0


def _low_marker_fresh(marker, days=7):
    try:
        return (time.time() - os.path.getmtime(marker)) < days * 86400
    except OSError:
        return False


class ShinyColorsModule(GameModule):
    id = "shinycolors"
    route_id = "sc"
    aliases = ("sc",)
    name = "闪彩卡面"
    icon = "✨"
    theme = "sc"
    schedule_text = "每两周 · 周一 09:40"
    source_name = "shinycolors.moe + gameo 2×"
    probe_target = "https://api.shinycolors.moe/info/idolList"
    brand = "ShinyColors卡牌"

    def _resolve_db_dir(self, data_dir):
        return os.path.join(data_dir, "shinycolors")

    def _resolve_thumb_dir(self, data_dir):
        return os.path.join(data_dir, "thumbs_shinycolors")

    def _resolve_original_dir(self, data_dir):
        return os.path.join(data_dir, "originals_shinycolors")

    def normalize_kind(self, kind=None):
        k = (kind or "normal").lower()
        if k in ("fes", "trained", "after_training", "特训后"):
            return "fes"
        if k == "normal":
            return "normal"
        raise ValueError("kind 必须是 normal 或 fes")

    def allowed_kinds(self):
        return ("normal", "fes")

    def kind_label(self, kind):
        return "特训后" if self.normalize_kind(kind) == "fes" else "突破前"

    def thumb_filename(self, card_id, kind):
        k = self.normalize_kind(kind)
        return f"{int(card_id)}_{'trained' if k == 'fes' else 'normal'}.webp"

    def original_filename_disk(self, card_id, kind, tier=None):
        k = self.normalize_kind(kind)
        stem = f"{int(card_id)}_fes" if k == "fes" else f"{int(card_id)}"
        return f"{stem}_{tier}.png" if tier else f"{stem}.png"

    def legacy_original_filenames_disk(self, card_id, kind, tier=None):
        if tier:
            return ()
        k = self.normalize_kind(kind)
        stem = f"{int(card_id)}_fes" if k == "fes" else f"{int(card_id)}"
        return (f"{stem}.jpg",)

    def original_legacy_url(self, card_id, kind, tier=None):
        k = self.normalize_kind(kind)
        stem = f"{int(card_id)}_fes" if k == "fes" else f"{int(card_id)}"
        return f"/api/shinycolors/originals/{stem}_{tier}.png" if tier else f"/api/shinycolors/originals/{stem}.png"

    def download_filename(self, card, kind="normal", tier=None):
        k = self.normalize_kind(kind)
        suffix = "_特训后" if k == "fes" else ""
        tier_suffix = "_4K超分" if tier == "4k" else "_2K超分" if tier == "2k" else ""
        cid = (card or {}).get("id", "0")
        return f"{self.brand}_{cid}_{sanitize_name((card or {}).get('prefix'))}{suffix}{tier_suffix}.png"

    def resolve_original(self, card_id, kind="normal", progress_cb=None):
        k = self.normalize_kind(kind)
        card = self.find_card(card_id)
        if not card:
            return None, "找不到该卡面"
        if k == "fes" and not card.get("trainable"):
            return None, "该卡面没有特训后立绘"

        os.makedirs(self.original_dir, exist_ok=True)
        png = self.original_path(card_id, k)
        legacy = os.path.join(self.original_dir, f"{int(card_id)}{'_fes' if k == 'fes' else ''}.jpg")
        low_marker = png + ".low"

        have_png = os.path.isfile(png) and os.path.getsize(png) > 0
        have_legacy = os.path.isfile(legacy) and os.path.getsize(legacy) > 0
        if have_png:
            if _image_width(png) >= 2000 or _low_marker_fresh(low_marker):
                return png, None
        elif have_legacy and _image_width(legacy) >= 2000:
            return convert_bytes_to_png_file(legacy, png)

        last_err = None
        for url in build_shiny_source_urls(card, k):
            try:
                data, tag = fetch_bytes(url, timeout=60, expect_image=True, progress_cb=progress_cb)
            except NotFoundError:
                last_err = "HTTP 404"
                continue
            except Exception as exc:  # noqa: BLE001
                last_err = str(exc)
                continue

            out, err = convert_bytes_to_png_file(data, png)
            if out:
                if os.path.exists(low_marker):
                    try:
                        os.remove(low_marker)
                    except OSError:
                        pass
                log.info(
                    "闪彩原图已缓存（PNG）：card %s(%s) ← %s（%.1f KB，%s）",
                    card_id,
                    k,
                    url.split("/")[2],
                    len(data) / 1024,
                    tag,
                )
                return out, None
            last_err = err

        if have_png:
            try:
                open(low_marker, "wb").close()
            except OSError:
                pass
            return png, None
        if have_legacy:
            out, err = convert_bytes_to_png_file(legacy, png)
            if out:
                try:
                    open(low_marker, "wb").close()
                except OSError:
                    pass
                return out, None
            last_err = err
        if k == "fes" and last_err == "HTTP 404":
            return None, "该卡面暂无特训后立绘（图库未提供）"
        return None, last_err or "全部通路失败"

    def card_detail(self, card_id, kind=None):
        cid = int(card_id)
        card = self.find_card(cid)
        if not card:
            return None
        cache = os.path.join(self.db_dir, f"card_{cid}.json")
        raw = JSON_CACHE.read_optional(cache)
        if raw is None and card.get("cardUuid"):
            ep = "pCardInfo" if card.get("cardKind") == "P" else "sCardInfo"
            try:
                data, _ = fetch_bytes(
                    SHINY_CARD_API.format(ep=ep, uuid=card["cardUuid"]),
                    timeout=30,
                )
                raw = json.loads(data.decode("utf-8", "replace"))
                atomic_write_json(cache, raw)
                JSON_CACHE.invalidate(cache)
            except Exception as exc:  # noqa: BLE001
                log.warning("闪彩详情现场拉取失败 card %s：%s", cid, exc)
                raw = {}
        if raw is None:
            raw = {}

        media = self.media_status(cid, ("normal", "fes"))
        has_trained = bool(self.thumb_path(cid, "fes"))
        return {
            "card": card,
            "idol": raw.get("idol") or {},
            "status": raw.get("cardStatus") or {},
            "panels": raw.get("cardPanels") or [],
            "supportSkills": raw.get("cardSupportSkills") or [],
            "fightSkill": raw.get("supportFightSkills") or {},
            "events": raw.get("cardSupportEvents") or [],
            "hasOriginal": media["normal"]["hasOriginal"],
            "hasFesOriginal": media["fes"]["hasOriginal"],
            "hasTrained": has_trained,
            "media": media,
        }
