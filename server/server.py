# -*- coding: utf-8 -*-
"""
Pjsk 卡牌雷达 —— 本地网站服务器（仅标准库）
职责：
  1. 托管 web/ 静态前端
  2. 提供数据 API（索引 / 详情 / 状态）
  3. 按需下载原图：只有用户在网站上点击「下载原图」时，
     才从源站抓取高清卡面存入 data/originals（平时只存低清缩略图，节省空间）
所有文件读写都限制在本项目文件夹内；只监听 127.0.0.1。
"""
import json
import logging
import ssl
import mimetypes
import os
import random
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.join(PROJECT_ROOT, "web")
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
DB_DIR = os.path.join(DATA_DIR, "db")
THUMB_DIR = os.path.join(DATA_DIR, "thumbs")
COSTUME_THUMB_DIR = os.path.join(DATA_DIR, "thumbs_costume")
ORIGINAL_DIR = os.path.join(DATA_DIR, "originals")
STATE_PATH = os.path.join(DATA_DIR, "state.json")
# 邦多利模块（bestdori.com 公开数据）
BANDORI_DB_DIR = os.path.join(DATA_DIR, "bandori")
BANDORI_THUMB_DIR = os.path.join(DATA_DIR, "thumbs_bandori")
BANDORI_ORIGINAL_DIR = os.path.join(DATA_DIR, "originals_bandori")
BESTDORI_CARD_API = "https://bestdori.com/api/cards/{cid}.json"
BESTDORI_ART = ("https://bestdori.com/assets/{region}/characters/"
                "resourceset/{res}_rip/{file}")
HOST = "127.0.0.1"
PORT = 8819

STORAGE_MAIN = "https://storage.pjsk.moe/sekai-jp-assets"
STORAGE_BACKUP = "https://storage.exmeaning.com/sekai-jp-assets"
SERVER_VERSION = "1.15.0"  # bump on every behavior change, so e2e tests can
# prove the running process is the new code (tieba-radar lesson E07/E18)
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("server")

_ID_RE = re.compile(r"^\d{1,6}$")
_ASSET_RE = re.compile(r"^[a-z0-9_]+$", re.IGNORECASE)


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_db():
    """读取索引与主数据（每次请求都读，保证周更后自动生效）。"""
    index = read_json(os.path.join(DB_DIR, "index.json"))
    skills = read_json(os.path.join(DB_DIR, "skills.json"))
    characters = read_json(os.path.join(DB_DIR, "gameCharacters.json"))
    costumes = read_json(os.path.join(DB_DIR, "moe_costume.json"))
    episodes = read_json(os.path.join(DB_DIR, "cardEpisodes.json"))
    return index, skills, characters, costumes, episodes


class _RacerAbort(Exception):
    """竞速败者的正常退出路径。"""


class NotFoundError(Exception):
    """资源不存在（HTTP 404）。"""


def race_fetch(urls, progress_cb=None, budget=25, timeout=30):
    """多源并发竞速 GET：先完成的源胜出，其余连接立即中止。
    progress_cb(downloaded, total, url) 由领先线程回调（用于进度条）。
    「一切以速度为标准」——VPN 开启时主源快则主源胜，VPN 关闭时主源
    被限速则备源自动胜出，无需感知 VPN 状态。
    全部失败抛 ConnectionError（含首个错误）。"""
    result = {"data": None, "url": None, "err": None}
    cancel = threading.Event()
    lock = threading.Lock()

    def work(url):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                total = int(r.headers.get("Content-Length") or 0)
                chunks = []
                t0 = time.time()
                while True:
                    if cancel.is_set():
                        raise _RacerAbort()
                    chunk = r.read(131072)
                    if not chunk:
                        break
                    chunks.append(chunk)
                    with lock:
                        if result["data"] is None and progress_cb:
                            progress_cb(sum(len(c) for c in chunks), total, url)
                    if time.time() - t0 > budget:
                        raise TimeoutError(f"{budget}s 预算耗尽")
                data = b"".join(chunks)
            with lock:
                if result["data"] is None:
                    result["data"] = data
                    result["url"] = url
                    cancel.set()  # 通知对手中止
        except _RacerAbort:
            pass
        except Exception as e:  # noqa: BLE001
            with lock:
                if result["data"] is None and result["err"] is None:
                    result["err"] = f"{url} -> {e}"

    threads = [threading.Thread(target=work, args=(u,)) for u in urls]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    if result["data"] is None:
        raise ConnectionError(result["err"] or "全部源失败")
    return result["data"], result["url"]


def resolve_original(card_id, kind, progress_cb=None):
    """竞速抓取 PNG 原图并缓存。kind: normal | trained。
    progress_cb(done_bytes, total_bytes, tag)。返回 (文件路径, 错误信息)。"""
    index, *_ = load_db()
    card = next((c for c in index["cards"] if c["id"] == card_id), None)
    if not card:
        return None, "找不到该卡牌"
    abn = card["assetbundleName"]
    if not abn:
        return None, "该卡牌没有卡面资源"
    if kind == "trained":
        if not card.get("trainable"):
            return None, "该卡牌不支持突破（3★/4★ 专属）"
        fname = f"{card_id}_after_training.png"
        remote = f"/character/member/{abn}/card_after_training.png"
    else:
        kind = "normal"
        fname = f"{card_id}_normal.png"
        remote = f"/character/member/{abn}/card_normal.png"

    os.makedirs(ORIGINAL_DIR, exist_ok=True)
    path = os.path.join(ORIGINAL_DIR, fname)
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path, None  # 已缓存：直接复用，不重复抓取

    def cb(done, total, url):
        if progress_cb:
            tag = "主源" if "pjsk.moe" in url else "备源"
            progress_cb(done, total, tag)

    urls = [b + remote for b in (STORAGE_MAIN, STORAGE_BACKUP)]
    try:
        data, winner = race_fetch(urls, progress_cb=cb)
    except Exception as e:  # noqa: BLE001
        return None, f"下载失败：{e}"
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)
    log.info("原图已下载：card %s %s（%.1f KB，源 %s）", card_id, kind,
             len(data) / 1024, "主源" if "pjsk.moe" in winner else "备源")
    return path, None


def costume_thumb(abn):
    """按需下载服装缩略图（低清），缓存后返回路径。"""
    if not _ASSET_RE.match(abn or ""):
        return None
    os.makedirs(COSTUME_THUMB_DIR, exist_ok=True)
    path = os.path.join(COSTUME_THUMB_DIR, f"{abn}.webp")
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path
    for base in (STORAGE_MAIN, STORAGE_BACKUP):
        try:
            req = urllib.request.Request(f"{base}/thumbnail/costume/{abn}.webp",
                                         headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=20) as r:
                data = r.read()
            tmp = path + ".part"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, path)
            return path
        except Exception:  # noqa: BLE001
            continue
    return None


def _sanitize_name(name, maxlen=60):
    """文件名净化：去掉 Windows 非法字符与首尾空白/点。"""
    name = re.sub(r'[\\/:*?"<>|\r\n\t]', '', name or '')
    name = re.sub(r'\s+', ' ', name).strip().rstrip('.')
    return name[:maxlen] or '未命名'


def build_original_filename(card, kind, brand="Pjsk卡牌"):
    """可识别的下载文件名：{brand}_编号_卡名_角色_突破前后.png"""
    label = '突破后' if kind == 'trained' else '突破前'
    return (f"{brand}_{card['id']}_{_sanitize_name(card.get('prefix'))}"
            f"_{_sanitize_name(card.get('characterFullName') or card.get('characterName'))}"
            f"_{label}.png")


def downloads_dir():
    """系统「下载」文件夹：优先读注册表（兼容 OneDrive 重定向），回退 ~/Downloads。"""
    try:
        import winreg
        with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer"
                r"\User Shell Folders") as k:
            val, _ = winreg.QueryValueEx(k, "{374DE290-123F-4565-9164-39C4925E467B}")
            path = os.path.expandvars(val)
            if path and os.path.isdir(path):
                return path
    except Exception:  # noqa: BLE001 — 非 Windows 或注册表缺失时走回退
        pass
    return os.path.join(os.path.expanduser("~"), "Downloads")


def save_original_to_downloads(card, internal_kind, cached_path, brand="Pjsk卡牌"):
    """把已缓存的原图以规范文件名复制进系统「下载」文件夹。
    返回 (目标路径, 是否为新增)。同名文件已存在则跳过（同一卡面内容不变）。"""
    name = build_original_filename(card, internal_kind, brand)
    ddir = downloads_dir()
    os.makedirs(ddir, exist_ok=True)
    dst = os.path.join(ddir, name)
    if os.path.exists(dst) and os.path.getsize(dst) > 0:
        return dst, False
    shutil.copyfile(cached_path, dst)
    return dst, True


# ------------------------------------------------ 邦多利模块（bestdori）
def load_bandori_index():
    """读取邦多利索引（每次请求都读，周更后自动生效）。"""
    return read_json(os.path.join(BANDORI_DB_DIR, "index.json"))


def resolve_bandori_original(card_id, kind, progress_cb=None):
    """bestdori 抓取卡面原图并缓存。kind: normal | trained。
    JP 区域优先、EN 兜底；返回 (文件路径, 错误信息)。"""
    index = load_bandori_index()
    card = next((c for c in index["cards"] if c["id"] == card_id), None)
    if not card:
        return None, "找不到该卡牌"
    res = card.get("assetbundleName")
    if not res:
        return None, "该卡牌没有卡面资源"
    if kind == "trained":
        if not card.get("trainable"):
            return None, "该卡牌不支持突破（3★ 以上专属）"
        fname = f"{card_id}_after_training.png"
        remote_file = "card_after_training.png"
    else:
        kind = "normal"
        fname = f"{card_id}_normal.png"
        remote_file = "card_normal.png"

    os.makedirs(BANDORI_ORIGINAL_DIR, exist_ok=True)
    path = os.path.join(BANDORI_ORIGINAL_DIR, fname)
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path, None  # 已缓存：直接复用

    last_err = None
    for region in ("jp", "en"):
        url = BESTDORI_ART.format(region=region, res=res, file=remote_file)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                total = int(r.headers.get("Content-Length") or 0)
                tmp = path + ".part"
                done = 0
                with open(tmp, "wb") as f:
                    while True:
                        chunk = r.read(131072)
                        if not chunk:
                            break
                        f.write(chunk)
                        done += len(chunk)
                        if progress_cb:
                            progress_cb(done, total, region)
            os.replace(tmp, path)
            log.info("邦多利原图已下载：card %s %s（%.1f KB，%s 区域）",
                     card_id, kind, done / 1024, region)
            return path, None
        except urllib.error.HTTPError as e:
            if e.code == 404:
                last_err = f"资源不存在（{region} 区域）"
                continue
            last_err = f"{region}: HTTP {e.code}"
        except Exception as e:  # noqa: BLE001
            last_err = f"{region}: {e}"
    return None, last_err or "全部区域失败"


def _bandori_skill_lines(skill_id):
    """按 skillId 从技能全量缓存取描述，{0} 用最高等级 duration 插值。
    返回 [(语言标签, 文本)]（日文主行在前，其余语言作次行）；无数据返回 []。"""
    p = os.path.join(BANDORI_DB_DIR, "skills_all.json")
    try:
        sk = read_json(p).get(str(skill_id))
        if not sk:
            return []
    except Exception:  # noqa: BLE001
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
        out.append((tags[i], txt))
    return out


def bandori_card_detail(card_id):
    """bestdori 单卡详情（本地缓存按需拉取）。返回 None=卡不存在。"""
    cache = os.path.join(BANDORI_DB_DIR, f"card_{card_id}.json")
    try:
        raw = read_json(cache)
    except Exception:  # noqa: BLE001
        try:
            req = urllib.request.Request(BESTDORI_CARD_API.format(cid=card_id),
                                         headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise
        tmp = cache + ".part"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False)
        os.replace(tmp, cache)

    index = load_bandori_index()
    card = next((c for c in index["cards"] if c["id"] == card_id), None)
    if not card:
        return None

    def zh(arr, fallback=""):
        """bestdori 多语言数组取简体（[日, 英, 繁, 简, 韩]），回退首项。"""
        if isinstance(arr, list) and len(arr) >= 4:
            return arr[3] or arr[0] or fallback
        if isinstance(arr, list) and arr:
            return arr[0] or fallback
        return fallback

    episodes = []
    for ep in ((raw.get("episodes") or {}).get("entries") or []):
        episodes.append({
            "title": zh(ep.get("title")),
            "type": ep.get("episodeType"),
            "append": [ep.get("appendPerformance"), ep.get("appendTechnique"),
                       ep.get("appendVisual")],
            "releaseLevel": ep.get("releaseLevel"),
        })
    # 已缓存原图标记（详情页「在线查看原图」按钮的显隐）
    originals = {}
    for k2, f2 in (("normal", "normal"), ("trained", "after_training")):
        p = os.path.join(BANDORI_ORIGINAL_DIR, f"{card_id}_{f2}.png")
        if os.path.exists(p) and os.path.getsize(p) > 0:
            originals[k2] = f"/api/bandori/originals/{card_id}_{f2}.png"
    return {
        "card": card,
        "prefix": zh(raw.get("prefix"), card.get("prefix")),
        "skillName": zh(raw.get("skillName"), card.get("skillName") or ""),
        "skillLines": _bandori_skill_lines(raw.get("skillId") or card.get("skillId")),
        "gachaText": zh(raw.get("gachaText")),
        "cardType": raw.get("type") or card.get("cardType"),
        "levelLimit": raw.get("levelLimit"),
        "episodes": episodes,
        "originals": originals,
    }


def _bandori_download_job(job_id, card_id, external_kind):
    """后台下载任务（邦多利）：bestdori 抓取 PNG → 缓存 → 写入系统「下载」文件夹。"""
    job = _JOBS[job_id]
    internal = "trained" if external_kind == "after_training" else "normal"
    try:
        def cb(done, total, tag):
            job["downloaded"] = done
            job["total"] = total
            job["source"] = tag

        path, err = resolve_bandori_original(card_id, internal, progress_cb=cb)
        if not path:
            job["state"] = "error"
            job["error"] = err
            return
        index = load_bandori_index()
        card = next((c for c in index["cards"] if c["id"] == card_id), None)
        try:
            dst, created = save_original_to_downloads(card, internal, path,
                                                      brand="Bandori卡牌")
        except Exception as e:  # noqa: BLE001
            job["state"] = "error"
            job["error"] = f"写入下载文件夹失败：{e}"
            return
        if created:
            log.info("邦多利原图已保存到下载文件夹：%s", os.path.basename(dst))
        job["state"] = "done"
        job["filename"] = os.path.basename(dst)
        job["already"] = not created
        job["url"] = f"/api/bandori/originals/{card_id}_{external_kind}.png"
    except Exception as e:  # noqa: BLE001
        job["state"] = "error"
        job["error"] = str(e)


def _bandori_superres_job(job_id, card_id, external_kind, tier, engine):
    """后台超分任务（邦多利）：原图缺失自动级联 → 超分 → 写入下载文件夹。
    与 pjsk 同一 AI/经典管线；原图副本保留（不删除）。"""
    job = _JOBS[job_id]
    internal = "trained" if external_kind == "after_training" else "normal"
    try:
        src = os.path.join(BANDORI_ORIGINAL_DIR, f"{card_id}_{internal}.png")
        if not (os.path.exists(src) and os.path.getsize(src) > 0):
            job["phase"] = "download"
            job["source"] = ""

            def dcb(done, total, tag):
                job["downloaded"] = done
                job["total"] = total
                job["source"] = tag

            path, err = resolve_bandori_original(card_id, internal, progress_cb=dcb)
            if not path:
                job["state"] = "error"
                job["error"] = f"原图下载失败：{err}"
                return
            src = path
        job["phase"] = "superres"
        job["downloaded"] = 0
        job["total"] = 0
        dst = os.path.join(BANDORI_ORIGINAL_DIR, f"{card_id}_{internal}_{tier}.png")
        if not (os.path.exists(dst) and os.path.getsize(dst) > 0):
            used = "pillow"
            if engine == "ai":
                if os.path.isfile(AI_EXE):
                    try:
                        job["phase"] = "ai"
                        job["source"] = "AI"
                        size = _ai_upscale(src, dst, tier, job)
                        used = "ai"
                        log.info("AI 超分完成（邦多利）：card %s %s [%s] → %dx%d",
                                 card_id, external_kind, tier, *size)
                    except Exception as e:  # noqa: BLE001 — 失败回退
                        log.warning("AI 超分失败（邦多利），回退 Pillow：card %s -> %s",
                                    card_id, e)
                        job["engineFallback"] = True
                else:
                    log.warning("AI 引擎缺失，回退 Pillow 管线（邦多利）")
                    job["engineFallback"] = True
            job["engine"] = used
            if used == "pillow":
                job["source"] = "Pillow"
                job["srProgress"] = None
                job["phase"] = "superres"
                size = superres_image(src, dst, tier)
                log.info("超分完成（邦多利）：card %s %s [%s] → %dx%d",
                         card_id, external_kind, tier, *size)
            else:
                job["srProgress"] = 100
        # 写入下载文件夹（Bandori 命名；原图副本保留——v1.8.5 起的行为）
        index = load_bandori_index()
        card = next((c for c in index["cards"] if c["id"] == card_id), None)
        dl_name = build_original_filename(card, internal, brand="Bandori卡牌")
        dl_name = dl_name[:-4] + ("_4K超分.png" if tier == "4k" else "_2K超分.png")
        ddir = downloads_dir()
        os.makedirs(ddir, exist_ok=True)
        dst_dl = os.path.join(ddir, dl_name)
        created = False
        if not (os.path.exists(dst_dl) and os.path.getsize(dst_dl) > 0):
            shutil.copyfile(dst, dst_dl)
            created = True
            log.info("邦多利超分图已保存到下载文件夹：%s", dl_name)
        job["state"] = "done"
        job["filename"] = dl_name
        job["already"] = not created
        job["url"] = f"/api/bandori/originals/{card_id}_{external_kind}_{tier}.png"
    except ImportError:
        job["state"] = "error"
        job["error"] = "服务器缺少 Pillow，无法超分（pip install --user pillow）"
    except Exception as e:  # noqa: BLE001
        job["state"] = "error"
        job["error"] = str(e)


# ------------------------------------------------ 闪耀色彩模块（shinycolors.moe）
# 数据源：api.shinycolors.moe（idolInfo 内含 cardLists 全量卡面）+ cf-static 图床
# ⚠️ 本机直连 api 子域常断连，需走本机代理（FlClash 7890）；cf-static 图床直连 200
SHINY_DB_DIR = os.path.join(DATA_DIR, "shinycolors")
SHINY_THUMB_DIR = os.path.join(DATA_DIR, "thumbs_shinycolors")
SHINY_ORIGINAL_DIR = os.path.join(DATA_DIR, "originals_shinycolors")
SHINY_CARD_API = ("https://api.shinycolors.moe/info/{ep}?cardId={uuid}")
SHINY_ART = ("https://cf-static.shinycolors.moe/images/content/"
             "{dir}/card/{enza}.jpg")
# 特训后（Fes）立绘：仅 P 卡 trainable 才有，官方图床单独目录 fes_card
SHINY_FES = ("https://cf-static.shinycolors.moe/images/content/"
             "{dir}/fes_card/{enza}.jpg")
# 高清档图库（社区，2272×1280 = 官方 1136×640 的 2×）：
#   文件名 = 【卡名】角色[2].{jpg|webp}；2 = 特训后；
#   2024-10-08 之后实装的卡改用 webp，之前为 jpg
SHINY_GAMEO = "https://gameo.jp/img/imassc/card/{name}.{ext}"
SHINY_GAMEO_WEBP_AFTER = "2024-10-08"
SHINY_ART_DIRS = {"P": "idols", "S": "support_idols"}


def load_shiny_index():
    return read_json(os.path.join(SHINY_DB_DIR, "index.json"))


def _shiny_fetch(url, timeout=60):
    """shinycolors API 抓取：直连 → 代理 7890 → 7897 自动回退
    （api 子域直连常断连，代理通路实测 200）。"""
    last = None
    for proxy in [None, "http://127.0.0.1:7890", "http://127.0.0.1:7897"]:
        handlers = [urllib.request.HTTPSHandler(context=ssl.create_default_context())]
        if proxy:
            handlers.append(urllib.request.ProxyHandler(
                {"http": proxy, "https": proxy}))
        opener = urllib.request.build_opener(*handlers)
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with opener.open(req, timeout=timeout) as r:
                ct = (r.headers.get("Content-Type") or "")
                data = r.read()
            if ct.startswith("text/html"):
                raise ConnectionError(f"{url} -> SPA 壳（疑似限流）")
            return data
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise NotFoundError(url) from e
            last = f"HTTP {e.code}"
        except NotFoundError:
            raise
        except Exception as e:  # noqa: BLE001
            last = str(e)
        time.sleep(1)
    raise ConnectionError(f"{url} -> {last}")


def _shiny_kind_norm(kind):
    """闪彩卡面类型归一：normal（突破前）/ fes（特训后）。"""
    k = (kind or "normal").lower()
    if k in ("fes", "trained", "after_training", "特训后"):
        return "fes"
    return "normal"


def _shiny_kind_label(kind):
    return "特训后" if _shiny_kind_norm(kind) == "fes" else "突破前"


def _shiny_cache_paths(card_id, kind):
    stem = f"{card_id}" if kind == "normal" else f"{card_id}_fes"
    return (os.path.join(SHINY_ORIGINAL_DIR, stem + ".png"),
            os.path.join(SHINY_ORIGINAL_DIR, stem + ".jpg"))


def _low_marker_fresh(marker, days=7):
    """升级失败标记 7 天内有效（图库后补高清档时会自动重试）。"""
    try:
        return (time.time() - os.path.getmtime(marker)) < days * 86400
    except OSError:
        return False


def _shiny_source_urls(card, kind):
    """原图候选 URL，按画质排序：
    1) gameo.jp 高清档 2272×1280（社区图库，文件名 = 【卡名】角色[2].jpg|webp）
    2) cf-static 官方档 1136×640（官方 CDN，兜底）
    文件名规则抄 gameo 前端：标题去掉 / : #，’→'，…→...；特训后加 2。"""
    urls = []
    name = (card.get("prefix") or "").strip()
    if name and not name.startswith("【"):
        name = f"【{name}】{card.get('characterName') or ''}"
    safe = (name.replace("/", "").replace(":", "").replace("#", "")
                .replace("’", "'").replace("…", "..."))
    stem = safe + ("2" if kind == "fes" else "")
    exts = (["webp", "jpg"]
            if (card.get("releaseDate") or "") > SHINY_GAMEO_WEBP_AFTER
            else ["jpg", "webp"])
    for ext in exts:
        urls.append(SHINY_GAMEO.format(name=urllib.parse.quote(stem), ext=ext))
    d = SHINY_ART_DIRS.get(card.get("cardKind") or "S", "support_idols")
    tmpl = SHINY_FES if kind == "fes" else SHINY_ART
    if card.get("enzaId"):
        urls.append(tmpl.format(dir=d, enza=card["enzaId"]))
    return urls


def _shiny_to_png(src, png):
    """任意图档 → PNG 缓存（无损容器）。返回 (png, 错误)。"""
    try:
        from PIL import Image  # noqa: PLC0415 — 延迟导入，缺 Pillow 时给出明确报错
    except ImportError:
        return None, "服务器缺少 Pillow，无法转出 PNG（pip install --user pillow）"
    try:
        tmp = png + ".part"
        im = Image.open(src)
        im.convert("RGB").save(tmp, "PNG", compress_level=6)
        os.replace(tmp, png)
        return png, None
    except Exception as e:  # noqa: BLE001
        return None, f"PNG 转换失败：{e}"


def resolve_shiny_original(card_id, kind="normal", progress_cb=None):
    """抓取闪耀色彩卡面原图并缓存为 PNG（高清优先 2272×1280，官方 1136×640 兜底）。
    kind=normal 突破前；kind=fes 特训后（仅 trainable 的 P 卡）。
    返回 (png 文件路径, 错误信息)。"""
    kind = _shiny_kind_norm(kind)
    index = load_shiny_index()
    card = next((c for c in index["cards"] if c["id"] == card_id), None)
    if not card:
        return None, "找不到该卡面"
    if kind == "fes" and not card.get("trainable"):
        return None, "该卡面没有特训后立绘"
    os.makedirs(SHINY_ORIGINAL_DIR, exist_ok=True)
    png, legacy = _shiny_cache_paths(card_id, kind)
    # .low 标记：低清档且升级失败过，后续请求直接复用，避免反复重试拖慢下载
    low_marker = png + ".low"
    have_legacy = os.path.exists(legacy) and os.path.getsize(legacy) > 0
    if os.path.exists(png) and os.path.getsize(png) > 0:
        try:
            from PIL import Image  # noqa: PLC0415
            png_w = Image.open(png).width
        except Exception:  # noqa: BLE001
            png_w = 0
        if png_w >= 2000 or _low_marker_fresh(low_marker):
            return png, None  # 已缓存（高清档，或确认过无法升级）
    elif have_legacy:
        try:
            from PIL import Image  # noqa: PLC0415
            legacy_w = Image.open(legacy).width
        except Exception:  # noqa: BLE001
            legacy_w = 0
        if legacy_w >= 2000:  # 已是高清档（旧缓存）→ 直接转 PNG
            return _shiny_to_png(legacy, png)

    last = None
    for url in _shiny_source_urls(card, kind):
        for proxy in [None, "http://127.0.0.1:7890", "http://127.0.0.1:7897"]:
            handlers = [urllib.request.HTTPSHandler(context=ssl.create_default_context())]
            if proxy:
                handlers.append(urllib.request.ProxyHandler(
                    {"http": proxy, "https": proxy}))
            opener = urllib.request.build_opener(*handlers)
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            tmp = png + ".dl"  # 下载临时档（与 _shiny_to_png 的 .part 区分，避免同路径读写）
            try:
                with opener.open(req, timeout=60) as r:
                    total = int(r.headers.get("Content-Length") or 0)
                    done = 0
                    with open(tmp, "wb") as f:
                        while True:
                            chunk = r.read(131072)
                            if not chunk:
                                break
                            f.write(chunk)
                            done += len(chunk)
                            if progress_cb:
                                progress_cb(done, total, "直连" if not proxy else "代理")
                out, err = _shiny_to_png(tmp, png)
                if out:
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
                    try:
                        os.remove(low_marker)  # 升级成功，清掉失败标记
                    except OSError:
                        pass
                    log.info("闪耀卡面原图已缓存（PNG）：card %s(%s) ← %s（%.1f KB）",
                             card_id, kind, url.split("/")[2], done / 1024)
                    return out, None
                last = err
                break  # 图片解码失败：换下一个源
            except urllib.error.HTTPError as e:
                last = f"HTTP {e.code}"
                if e.code == 404:
                    break  # 同 URL 换代理无意义
            except Exception as e:  # noqa: BLE001
                last = str(e)
            finally:
                if os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
    if os.path.exists(png) and os.path.getsize(png) > 0:  # 已有低清档：标记后直接用
        try:
            open(low_marker, "wb").close()
        except OSError:
            pass
        log.warning("闪耀卡面高清档不可用，沿用已有档：card %s(%s)", card_id, kind)
        return png, None
    if have_legacy:  # 升级失败：退回已有低清档，不让下载直接失败
        out, err = _shiny_to_png(legacy, png)
        if out:
            try:
                open(low_marker, "wb").close()
            except OSError:
                pass
            log.warning("闪耀卡面高清档不可用，回退已有 1136 档：card %s(%s)", card_id, kind)
            return out, None
    if kind == "fes" and last == "HTTP 404":
        return None, "该卡面暂无特训后立绘（图库未提供）"
    return None, last or "全部通路失败"


def ensure_shiny_png(card_id, kind="normal"):
    """兼容包装：返回 PNG 缓存路径（不存在则抓取/转换）。"""
    return resolve_shiny_original(card_id, _shiny_kind_norm(kind))


def build_shiny_filename(card, kind="normal"):
    """规范命名：ShinyColors卡牌_编号_卡名[_特训后].png
    （shinycolors 的卡名 prefix 自带角色名，如「【flieeeeeers】浅倉透」）"""
    suffix = "_特训后" if _shiny_kind_norm(kind) == "fes" else ""
    return (f"ShinyColors卡牌_{card['id']}_{_sanitize_name(card.get('prefix'))}"
            f"{suffix}.png")


def shinycolors_card_detail(card_id):
    """单卡详情（读本地缓存 card_{id}.json = pCardInfo/sCardInfo 原始响应）。
    返回 None=无缓存且现场拉取失败。"""
    cache = os.path.join(SHINY_DB_DIR, f"card_{card_id}.json")
    raw = None
    try:
        raw = read_json(cache)
    except Exception:  # noqa: BLE001
        index = load_shiny_index()
        card = next((c for c in index["cards"] if c["id"] == card_id), None)
        if card and card.get("cardUuid"):
            ep = "pCardInfo" if card.get("cardKind") == "P" else "sCardInfo"
            try:
                raw = json.loads(_shiny_fetch(
                    SHINY_CARD_API.format(ep=ep, uuid=card["cardUuid"]),
                    timeout=30).decode("utf-8", "replace"))
                tmp = cache + ".part"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(raw, f, ensure_ascii=False)
                os.replace(tmp, cache)
            except Exception as e:  # noqa: BLE001
                log.warning("shinycolors 详情现场拉取失败 card %s：%s", card_id, e)
    if raw is None:
        return None
    index = load_shiny_index()
    card = next((c for c in index["cards"] if c["id"] == card_id), None)
    has_original = os.path.exists(os.path.join(SHINY_ORIGINAL_DIR, f"{card_id}.jpg")) \
        or os.path.exists(os.path.join(SHINY_ORIGINAL_DIR, f"{card_id}.png"))
    has_fes_original = os.path.exists(os.path.join(SHINY_ORIGINAL_DIR, f"{card_id}_fes.jpg")) \
        or os.path.exists(os.path.join(SHINY_ORIGINAL_DIR, f"{card_id}_fes.png"))
    has_trained = os.path.exists(os.path.join(SHINY_THUMB_DIR, f"{card_id}_trained.webp"))
    return {
        "card": card,
        "idol": raw.get("idol") or {},
        "status": raw.get("cardStatus") or {},
        "panels": raw.get("cardPanels") or [],
        "supportSkills": raw.get("cardSupportSkills") or [],
        "fightSkill": raw.get("supportFightSkills") or {},
        "events": raw.get("cardSupportEvents") or [],
        "hasOriginal": has_original,
        "hasFesOriginal": has_fes_original,
        "hasTrained": has_trained,
    }


def _shinycolors_download_job(job_id, card_id, kind="normal"):
    """后台下载任务（闪耀色彩）：cf-static 抓 jpg 原档 → 无损转 PNG → 写入「下载」文件夹。
    kind=normal 突破前 / fes 特训后。"""
    job = _JOBS[job_id]
    kind = _shiny_kind_norm(kind)
    try:
        def cb(done, total, tag):
            job["downloaded"] = done
            job["total"] = total
            job["source"] = tag

        path, err = ensure_shiny_png(card_id, kind)
        if not path:
            job["state"] = "error"
            job["error"] = err
            return
        index = load_shiny_index()
        card = next((c for c in index["cards"] if c["id"] == card_id), None)
        try:
            name = build_shiny_filename(card, kind)
            ddir = downloads_dir()
            os.makedirs(ddir, exist_ok=True)
            dst = os.path.join(ddir, name)
            created = not (os.path.exists(dst) and os.path.getsize(dst) > 0)
            if created:
                shutil.copyfile(path, dst)
                log.info("闪耀卡面已保存到下载文件夹：%s", name)
        except Exception as e:  # noqa: BLE001
            job["state"] = "error"
            job["error"] = f"写入下载文件夹失败：{e}"
            return
        job["state"] = "done"
        job["kind"] = kind
        job["filename"] = name
        job["already"] = not created
        job["url"] = (f"/api/shinycolors/originals/{card_id}"
                      f"{'_fes' if kind == 'fes' else ''}.png")
    except Exception as e:  # noqa: BLE001
        job["state"] = "error"
        job["error"] = str(e)


def _shinycolors_superres_job(job_id, card_id, tier, engine, kind="normal"):
    """后台超分任务（闪耀色彩）：原图缺失自动级联 → AI/Pillow 超分 → PNG 输出
    → 写入下载文件夹。kind=normal 突破前 / fes 特训后。"""
    job = _JOBS[job_id]
    kind = _shiny_kind_norm(kind)
    try:
        # 高清 PNG 源档（缺失时 resolve 内部自动抓取/升级，已缓存则秒回）
        job["phase"] = "download"
        job["source"] = ""

        def dcb(done, total, tag):
            job["downloaded"] = done
            job["total"] = total
            job["source"] = tag

        src, err = resolve_shiny_original(card_id, kind, progress_cb=dcb)
        if not src:
            job["state"] = "error"
            job["error"] = f"原图下载失败：{err}"
            return
        job["phase"] = "superres"
        job["downloaded"] = 0
        job["total"] = 0
        sr_stem = f"{card_id}_{tier}" if kind == "normal" else f"{card_id}_fes_{tier}"
        dst = os.path.join(SHINY_ORIGINAL_DIR, f"{sr_stem}.png")
        if not (os.path.exists(dst) and os.path.getsize(dst) > 0):
            used = "pillow"
            if engine == "ai":
                if os.path.isfile(AI_EXE):
                    try:
                        job["phase"] = "ai"
                        job["source"] = "AI"
                        size = _ai_upscale(src, dst, tier, job)
                        used = "ai"
                        log.info("AI 超分完成（闪耀）：card %s(%s) [%s] → %dx%d",
                                 card_id, kind, tier, *size)
                    except Exception as e:  # noqa: BLE001
                        log.warning("AI 超分失败（闪耀），回退 Pillow：card %s(%s) -> %s",
                                    card_id, kind, e)
                        job["engineFallback"] = True
                else:
                    log.warning("AI 引擎缺失，回退 Pillow 管线（闪耀）")
                    job["engineFallback"] = True
            job["engine"] = used
            if used == "pillow":
                job["source"] = "Pillow"
                job["srProgress"] = None
                job["phase"] = "superres"
                size = superres_image(src, dst, tier)
                log.info("超分完成（闪耀）：card %s(%s) [%s] → %dx%d",
                         card_id, kind, tier, *size)
            else:
                job["srProgress"] = 100
        index = load_shiny_index()
        card = next((c for c in index["cards"] if c["id"] == card_id), None)
        base = build_shiny_filename(card, kind)
        dl_name = base[:-4] + ("_4K超分.png" if tier == "4k" else "_2K超分.png")
        ddir = downloads_dir()
        os.makedirs(ddir, exist_ok=True)
        dst_dl = os.path.join(ddir, dl_name)
        created = False
        if not (os.path.exists(dst_dl) and os.path.getsize(dst_dl) > 0):
            shutil.copyfile(dst, dst_dl)
            created = True
            log.info("闪耀超分图已保存到下载文件夹：%s", dl_name)
        job["state"] = "done"
        job["kind"] = kind
        job["filename"] = dl_name
        job["already"] = not created
        job["url"] = f"/api/shinycolors/originals/{sr_stem}.png"
    except ImportError:
        job["state"] = "error"
        job["error"] = "服务器缺少 Pillow，无法超分（pip install --user pillow）"
    except Exception as e:  # noqa: BLE001
        job["state"] = "error"
        job["error"] = str(e)


# ------------------------------------------------ Our Notes 模块（bdon.moe）
# 数据源 Moenotes（StarMoe 团队）：静态 Markdown 站 + 专用图床 CDN，专为程序化
# 访问设计（robots 全开放 + llms.txt：任意页面 URL 加 .md 即数据）。默认 zh-CN
# 免翻译层。角色卡（card，稀有度 R/SR/SSR/BD）与支援卡（support，稀有度 3/4/10）
# 是两套 ID 序列与两套图路径，全链路以 kind 区分。
ONOTES_DB_DIR = os.path.join(DATA_DIR, "onotes")
ONOTES_THUMB_DIR = os.path.join(DATA_DIR, "thumbs_onotes")
ONOTES_ORIGINAL_DIR = os.path.join(DATA_DIR, "originals_onotes")
ONOTES_ASSET = "https://assets.bdon.moe/zh-Hans"
ONOTES_ART = {
    "card": ONOTES_ASSET + "/MemberCard/{id}/member_full/member_full.webp",
    "support": ONOTES_ASSET + "/SupportCard/{id}/snap_full/snap_full.webp",
}
ONOTES_MD = {
    "card": "https://bdon.moe/cards/{id}.md",
    "support": "https://bdon.moe/support-cards/{id}.md",
}


def load_onotes_index():
    return read_json(os.path.join(ONOTES_DB_DIR, "index.json"))


def _onotes_kind_norm(kind):
    """Our Notes 卡面类型归一：card（角色卡）/ support（支援卡）。"""
    k = (kind or "card").lower()
    if k in ("support", "s", "支援卡", "snap"):
        return "support"
    return "card"


def to_int(s, default=0):
    try:
        return int(str(s).replace(",", ""))
    except (TypeError, ValueError):
        return default


def _onotes_kind_label(kind):
    return "支援卡" if _onotes_kind_norm(kind) == "support" else "角色卡"


def build_onotes_filename(card, kind="card"):
    """规范命名：OurNotes卡牌_编号_卡名.png / OurNotes支援卡_编号_卡名.png"""
    brand = "OurNotes支援卡" if _onotes_kind_norm(kind) == "support" else "OurNotes卡牌"
    return f"{brand}_{card['id']}_{_sanitize_name(card.get('prefix'))}.png"


def resolve_onotes_original(card_id, kind="card", progress_cb=None):
    """抓取 Our Notes 卡面原图并缓存为 PNG（webp → PNG 无损容器）。
    kind=card 角色卡（member_full 1440×1920）/ support 支援卡（snap_full）。
    返回 (png 文件路径, 错误信息)。"""
    kind = _onotes_kind_norm(kind)
    index = load_onotes_index()
    card = next((c for c in index["cards"] if c["id"] == card_id), None)
    if not card:
        return None, "找不到该卡面"
    os.makedirs(ONOTES_ORIGINAL_DIR, exist_ok=True)
    webp = os.path.join(ONOTES_ORIGINAL_DIR, f"{card_id}_{kind}.webp")
    png = os.path.join(ONOTES_ORIGINAL_DIR, f"{card_id}_{kind}.png")
    if os.path.exists(png) and os.path.getsize(png) > 0:
        return png, None  # 已缓存
    if not (os.path.exists(webp) and os.path.getsize(webp) > 0):
        url = ONOTES_ART[kind].format(id=card_id)
        last = None
        for proxy in [None, "http://127.0.0.1:7890", "http://127.0.0.1:7897"]:
            handlers = [urllib.request.HTTPSHandler(context=ssl.create_default_context())]
            if proxy:
                handlers.append(urllib.request.ProxyHandler(
                    {"http": proxy, "https": proxy}))
            opener = urllib.request.build_opener(*handlers)
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            tmp = webp + ".part"
            try:
                with opener.open(req, timeout=120) as r:
                    total = int(r.headers.get("Content-Length") or 0)
                    done = 0
                    with open(tmp, "wb") as f:
                        while True:
                            chunk = r.read(131072)
                            if not chunk:
                                break
                            f.write(chunk)
                            done += len(chunk)
                            if progress_cb:
                                progress_cb(done, total, "直连" if not proxy else "代理")
                os.replace(tmp, webp)
                break
            except urllib.error.HTTPError as e:
                last = f"HTTP {e.code}"
                if e.code == 404:
                    break
            except Exception as e:  # noqa: BLE001
                last = str(e)
            finally:
                if os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
        else:
            last = "全部通路失败"
        if not (os.path.exists(webp) and os.path.getsize(webp) > 0):
            return None, last or "原图下载失败"
    out, err = _shiny_to_png(webp, png)  # 复用 webp→PNG 无损转换
    if out:
        log.info("Our Notes 卡面原图已缓存（PNG）：card %s(%s)", card_id, kind)
    return out, err


def _onotes_parse_detail_md(text):
    """详情 Markdown -> 结构化 dict（字段表 + 技能 Lv 表 + 台词）。
    与 scraper/onotes_scrape.py 的 parse_detail_md 同一格式约定。"""
    body = text
    m = re.match(r"\s*---\s*\n(.*?)\n---\s*\n", text, re.S)
    if m:
        body = text[m.end():]
    fields = {}
    flavors = []
    skills = []
    cur = None
    in_level = False
    for line in body.splitlines():
        s = line.strip()
        if s.startswith(">") and s[1:].strip():
            flavors.append(s[1:].strip())
            continue
        if s.startswith("### ") and s != "### ":
            name = s[4:].strip()
            tag = ""
            mm = re.search(r"\((leader|live|gekisou|support)\)\s*$", name)
            if mm:
                tag = mm.group(1)
                name = name[:mm.start()].strip()
            cur = {"name": name, "kind": tag, "levels": []}
            skills.append(cur)
            in_level = False
            continue
        if s.startswith("|") and s.endswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if all(set(c) <= set("-: ") for c in cells):
                continue
            if cells and cells[0] == "Field":
                in_level = False
                continue
            if cells and cells[0] == "Level":
                in_level = True
                continue
            if in_level and cur is not None:
                cur["levels"].append([cells[0], cells[1] if len(cells) > 1 else ""])
                continue
            if len(cells) >= 2:
                key, val = cells[0], cells[1]
                mm = re.match(r"\[([^\]]+)\]\(/characters/(\d+)\.md\)", val)
                if key == "":
                    fields.setdefault("_charLinks", []).append(
                        {"name": mm.group(1) if mm else val,
                         "id": int(mm.group(2)) if mm else None})
                else:
                    mm = re.match(r"\[([^\]]+)\]\([^\)]+\)", val)
                    fields[key] = {"text": mm.group(1) if mm else val}
    return {"fields": fields, "flavor": " ".join(flavors), "skills": skills}


def onotes_card_detail(card_id, kind=None):
    """单卡详情（读爬虫缓存 {kind}_{id}.json = 详情 md 解析结果）。
    ⚠️ 角色卡与支援卡 ID 序列重叠（1~81 双方都有）：kind 缺省时按索引取第一个
    命中（角色卡在前），前端路由永远显式带 kind。缓存文件名必须含 kind。
    返回 None=找不到。"""
    index = load_onotes_index()
    kind = _onotes_kind_norm(kind)
    card = next((c for c in index["cards"]
                 if c["id"] == card_id
                 and _onotes_kind_norm(c.get("cardKind")) == kind), None)
    if not card:
        return None
    cache = os.path.join(ONOTES_DB_DIR, f"{kind}_{card_id}.json")
    raw = None
    try:
        raw = read_json(cache)
    except Exception:  # noqa: BLE001
        try:
            raw = _onotes_parse_detail_md(
                _shiny_fetch(ONOTES_MD[kind].format(id=card_id),
                             timeout=60).decode("utf-8", "replace"))
            tmp = cache + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(raw, f, ensure_ascii=False)
            os.replace(tmp, cache)
        except Exception as e:  # noqa: BLE001
            log.warning("onotes 详情现场拉取失败 card %s(%s)：%s", card_id, kind, e)
            return None
    f = raw.get("fields") or {}
    num = lambda k: to_int((f.get(k) or {}).get("text"))  # noqa: E731
    rel = (f.get("Release") or {}).get("text", "")
    has_original = os.path.exists(os.path.join(ONOTES_ORIGINAL_DIR, f"{card_id}_{kind}.png"))
    return {
        "card": card,
        "kind": kind,
        "band": (f.get("乐队") or {}).get("text") or card.get("unitName"),
        "rarity": (f.get("稀有度") or {}).get("text") or card.get("rarity"),
        "attr": (f.get("属性") or {}).get("text") or card.get("attr") or "",
        "characterLinks": f.get("_charLinks") or [],
        "pf": num("Performance"), "tc": num("Technic"), "vi": num("Visual"),
        "total": num("Total Power") or card.get("power"),
        "release": rel,
        "servers": (f.get("Servers") or {}).get("text", ""),
        "flavor": raw.get("flavor") or "",
        "skills": raw.get("skills") or [],
        "hasOriginal": has_original,
        "hasTrained": False,  # 每卡单立绘（分层设计），无特训后独立图
    }


def _onotes_index_card(card_id, kind):
    """按 (id, kind) 在索引中找卡——两类 ID 序列重叠，必须复合键。"""
    kind = _onotes_kind_norm(kind)
    try:
        index = load_onotes_index()
        return next((c for c in index["cards"]
                     if c["id"] == card_id
                     and _onotes_kind_norm(c.get("cardKind")) == kind), None)
    except Exception:  # noqa: BLE001
        return None


def _onotes_download_job(job_id, card_id, kind="card"):
    """后台下载任务（Our Notes）：图床抓 webp → 无损转 PNG → 写入「下载」文件夹。"""
    job = _JOBS[job_id]
    kind = _onotes_kind_norm(kind)
    try:
        def cb(done, total, tag):
            job["downloaded"] = done
            job["total"] = total
            job["source"] = tag

        path, err = resolve_onotes_original(card_id, kind, progress_cb=cb)
        if not path:
            job["state"] = "error"
            job["error"] = err
            return
        card = _onotes_index_card(card_id, kind)
        try:
            name = build_onotes_filename(card, kind)
            ddir = downloads_dir()
            os.makedirs(ddir, exist_ok=True)
            dst = os.path.join(ddir, name)
            created = not (os.path.exists(dst) and os.path.getsize(dst) > 0)
            if created:
                shutil.copyfile(path, dst)
                log.info("Our Notes 卡面已保存到下载文件夹：%s", name)
        except Exception as e:  # noqa: BLE001
            job["state"] = "error"
            job["error"] = f"写入下载文件夹失败：{e}"
            return
        job["state"] = "done"
        job["kind"] = kind
        job["filename"] = name
        job["already"] = not created
        job["url"] = f"/api/onotes/originals/{card_id}_{kind}.png"
    except Exception as e:  # noqa: BLE001
        job["state"] = "error"
        job["error"] = str(e)


def _onotes_superres_job(job_id, card_id, tier, engine, kind="card"):
    """后台超分任务（Our Notes）：原图缺失自动级联 → AI/Pillow 超分 → PNG 输出
    → 写入下载文件夹。kind=card 角色卡 / support 支援卡。"""
    job = _JOBS[job_id]
    kind = _onotes_kind_norm(kind)
    try:
        job["phase"] = "download"
        job["source"] = ""

        def dcb(done, total, tag):
            job["downloaded"] = done
            job["total"] = total
            job["source"] = tag

        src, err = resolve_onotes_original(card_id, kind, progress_cb=dcb)
        if not src:
            job["state"] = "error"
            job["error"] = f"原图下载失败：{err}"
            return
        job["phase"] = "superres"
        job["downloaded"] = 0
        job["total"] = 0
        dst = os.path.join(ONOTES_ORIGINAL_DIR, f"{card_id}_{kind}_{tier}.png")
        if not (os.path.exists(dst) and os.path.getsize(dst) > 0):
            used = "pillow"
            if engine == "ai":
                if os.path.isfile(AI_EXE):
                    try:
                        job["phase"] = "ai"
                        job["source"] = "AI"
                        size = _ai_upscale(src, dst, tier, job)
                        used = "ai"
                        log.info("AI 超分完成（Our Notes）：card %s(%s) [%s] → %dx%d",
                                 card_id, kind, tier, *size)
                    except Exception as e:  # noqa: BLE001
                        log.warning("AI 超分失败（Our Notes），回退 Pillow：card %s(%s) -> %s",
                                    card_id, kind, e)
                        job["engineFallback"] = True
                else:
                    log.warning("AI 引擎缺失，回退 Pillow 管线（Our Notes）")
                    job["engineFallback"] = True
            job["engine"] = used
            if used == "pillow":
                job["source"] = "Pillow"
                job["srProgress"] = None
                job["phase"] = "superres"
                size = superres_image(src, dst, tier)
                log.info("超分完成（Our Notes）：card %s(%s) [%s] → %dx%d",
                         card_id, kind, tier, *size)
            else:
                job["srProgress"] = 100
        card = _onotes_index_card(card_id, kind)
        base = build_onotes_filename(card, kind)
        dl_name = base[:-4] + ("_4K超分.png" if tier == "4k" else "_2K超分.png")
        ddir = downloads_dir()
        os.makedirs(ddir, exist_ok=True)
        dst_dl = os.path.join(ddir, dl_name)
        created = False
        if not (os.path.exists(dst_dl) and os.path.getsize(dst_dl) > 0):
            shutil.copyfile(dst, dst_dl)
            created = True
            log.info("Our Notes 超分图已保存到下载文件夹：%s", dl_name)
        job["state"] = "done"
        job["kind"] = kind
        job["filename"] = dl_name
        job["already"] = not created
        job["url"] = f"/api/onotes/originals/{card_id}_{kind}_{tier}.png"
    except ImportError:
        job["state"] = "error"
        job["error"] = "服务器缺少 Pillow，无法超分（pip install --user pillow）"
    except Exception as e:  # noqa: BLE001
        job["state"] = "error"
        job["error"] = str(e)


# ------------------------------------------------ 下载任务（进度条）


# ------------------------------------------------ 下载任务（进度条）
# RLock：_download_job 回调链与 POST 处理线程会嵌套加锁（_prune_jobs 在持锁时调用），
# 普通 Lock 不可重入，曾导致整个 API 死锁假死。
_JOBS = {}
_JOBS_LOCK = threading.RLock()
_JOB_HISTORY_MAX = 40


def _prune_jobs():
    """任务数超限时清理最早的已结束任务（运行中的永不清理）。需持有 _JOBS_LOCK。"""
    with _JOBS_LOCK:
        if len(_JOBS) <= _JOB_HISTORY_MAX:
            return
        finished = [(k, v) for k, v in _JOBS.items() if v.get("state") != "running"]
        finished.sort(key=lambda kv: kv[0])  # jobId 前缀为时间戳，最早在前
        for k, _ in finished[: len(_JOBS) - _JOB_HISTORY_MAX]:
            _JOBS.pop(k, None)


def _job_snapshot(job_id):
    with _JOBS_LOCK:
        j = _JOBS.get(job_id)
        return dict(j) if j else None


def _download_job(job_id, card_id, external_kind):
    """后台下载任务：竞速抓取 PNG → 缓存 → 写入系统「下载」文件夹。"""
    job = _JOBS[job_id]
    internal = "trained" if external_kind == "after_training" else "normal"
    try:
        def cb(done, total, tag):
            job["downloaded"] = done
            job["total"] = total
            job["source"] = tag

        path, err = resolve_original(card_id, internal, progress_cb=cb)
        if not path:
            job["state"] = "error"
            job["error"] = err
            return
        index, *_ = load_db()
        card = next((c for c in index["cards"] if c["id"] == card_id), None)
        try:
            dst, created = save_original_to_downloads(card, internal, path)
        except Exception as e:  # noqa: BLE001
            job["state"] = "error"
            job["error"] = f"写入下载文件夹失败：{e}"
            return
        if created:
            log.info("原图已保存到下载文件夹：%s", os.path.basename(dst))
        job["state"] = "done"
        job["filename"] = os.path.basename(dst)
        job["already"] = not created
        job["url"] = f"/api/originals/{card_id}_{external_kind}.png"
    except Exception as e:  # noqa: BLE001
        job["state"] = "error"
        job["error"] = str(e)


SR_TIERS = {"2k": 2560, "4k": 3840}  # 超分档位 → 输出长边

# AI 超分实验引擎（Real-ESRGAN ncnn-vulkan 独立 exe）：借独立显卡的 Vulkan 算力
# （驱动自带运行时，无需 CUDA/Python 依赖，subprocess 调用守住零依赖原则）。
# 引擎缺失或推理失败一律自动回退 Pillow 经典管线，实验功能永不炸主功能。
AI_DIR = os.path.join(PROJECT_ROOT, "ai_engine")
AI_EXE = os.path.join(AI_DIR, "realesrgan-ncnn-vulkan.exe")
# 模型策略（srank 工程流程 + 本工程三模型对比实验）：主用 animevideov3-x4——
# 二次元柔滑风格，发丝线条平滑无锯齿感，速度比 x4plus-anime 快 ~1.7 倍；
# 校验失败自动换备模型 x4plus-anime（精修锐利）重试一次。
# ⚠️ animevideov3 系对 RGBA 大图会输出全黑帧，必须先经 _ai_prepare 通道预处理
# （真透明合成白底 / 全不透明转 RGB）。
AI_MODELS = ["realesr-animevideov3-x4", "realesrgan-x4plus-anime"]
AI_SCALE = "4"    # 固定 4x 推理，输出按档位长边 BOX 缩回
AI_TILE = "128"   # 分块推理（与 srank 一致，防显存溢出）
AI_GPU = "0"      # GPU 序号：0=RTX 4060 独显（780M 核显为 1），显式锁独显
AI_TIMEOUT = 600  # 单次推理超时（秒），超时视为该模型失败


def _progressive_upscale(img, target_long):
    """渐进抗锯齿放大（无模型）：
    1. 拆成多步、每步 ≤1.3×（大倍率单步 LANCZOS 是锯齿与振铃的主要来源）；
    2. 中间步后做轻量平滑压掉像素阶梯；
    3. 末步后轻微高斯收噪，再用温和 USM（低强度）恢复线条清晰度——
       强度刻意压低，避免把小颗粒重新锐成锯齿。"""
    from PIL import Image, ImageFilter  # noqa: PLC0415

    w, h = img.size
    long_side = max(w, h)
    if long_side >= target_long:
        # 源已达到目标：只做轻锐化，不放大也不缩小
        out = img.filter(ImageFilter.UnsharpMask(radius=2.2, percent=85, threshold=4))
        return out

    # 计算步进序列（每步 ≤1.3×）
    sizes = []
    cur = float(long_side)
    while cur < target_long:
        cur = min(target_long, cur * 1.3)
        sizes.append(cur)

    cur_img = img
    n = len(sizes)
    for i, s in enumerate(sizes):
        k = s / long_side  # 该步的累计倍率（相对源）
        nw, nh = max(1, int(round(w * k))), max(1, int(round(h * k)))
        cur_img = cur_img.resize((nw, nh), Image.LANCZOS)
        if i < n - 1:
            # 中间步：轻平滑去阶梯（不是最后一步，宁可略糊后续还能修）
            cur_img = cur_img.filter(ImageFilter.GaussianBlur(0.5))
    # 末步收尾：轻高斯压颗粒 → 温和 USM 收线
    cur_img = cur_img.filter(ImageFilter.GaussianBlur(0.6))
    cur_img = cur_img.filter(ImageFilter.UnsharpMask(radius=2.2, percent=85, threshold=4))
    return cur_img


def superres_image(src, dst, tier="4k"):
    """无模型超分（抗锯齿管线）：渐进步进放大 + 平滑去阶梯 + 温和收锐。
    tier: 2k → 长边 2560；4k → 长边 3840（2520×1440 源 → 3840×2194 壁纸级）。
    源已大于目标时只做锐化、不缩小。返回输出尺寸。"""
    from PIL import Image  # noqa: PLC0415 — 延迟导入，未装 Pillow 时给出明确报错
    final = _progressive_upscale(Image.open(src), SR_TIERS.get(tier, 3840))
    final.save(dst, "PNG", compress_level=6)
    return final.size


def _ai_prepare(src, work_png):
    """srank 式防黑帧通道预处理：animevideov3 系模型对 RGBA 大图会输出全黑帧——
    真透明像素（alpha 最低值 < 250）合成白底，全不透明直接转 RGB。
    预处理结果落盘 work_png，返回期望输出尺寸 (宽, 高)。"""
    from PIL import Image  # noqa: PLC0415
    work = Image.open(src)
    work.load()
    exp_w, exp_h = work.width * int(AI_SCALE), work.height * int(AI_SCALE)
    if work.mode == "RGBA":
        lo, _ = work.getchannel("A").getextrema()
        if lo < 250:
            bg = Image.new("RGB", work.size, (255, 255, 255))
            bg.paste(work, mask=work.getchannel("A"))
            work = bg
        else:
            work = work.convert("RGB")
    elif work.mode != "RGB":
        work = work.convert("RGB")
    work.save(work_png)
    work.close()
    return exp_w, exp_h


def _ai_validate(out_png, exp_w, exp_h, in_png):
    """srank 式三重校验（纯 Pillow 实现，零新依赖）：尺寸 / 空图 / 内容比对。
    内容比对：输出缩回输入尺寸逐像素平均差（MAD），正常 2~5、乱码 60~120。
    返回 None=通过，否则失败原因字符串。"""
    from PIL import Image, ImageChops, ImageStat  # noqa: PLC0415
    with Image.open(out_png) as im:
        im.load()
        if im.size != (exp_w, exp_h) or im.mode not in ("RGB", "RGBA"):
            return f"输出尺寸异常 {im.size}"
        lo, hi = im.convert("L").getextrema()
        if hi - lo < 8:
            return "输出为空图（GPU 瞬时异常）"
        with Image.open(in_png) as ref:
            ref_rgb = ref.convert("RGB")
            out_small = im.convert("RGB").resize(ref.size, Image.LANCZOS)
        diff = ImageChops.difference(out_small, ref_rgb)
        mad = sum(ImageStat.Stat(diff).mean) / 3.0
        if mad > 40:
            return f"输出内容异常（与原图平均差 {mad:.0f}）"
    return None


def _ai_infer_once(in_png, out_png, model, job):
    """单次推理：Popen + stderr 逐字符解析百分比（ncnn 的 % 行以 \\r 结尾，
    按字符分段比按行更实时）。返回退出码；超时 kill 并抛 RuntimeError。"""
    cmd = [AI_EXE, "-i", in_png, "-o", out_png, "-n", model, "-s", AI_SCALE,
           "-m", os.path.join(AI_DIR, "models"), "-f", "png",
           "-t", AI_TILE, "-g", AI_GPU]
    log.info("AI 推理：%s（tile %s，GPU %s）", model, AI_TILE, AI_GPU)
    proc = subprocess.Popen(cmd, cwd=AI_DIR, stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE, text=True,
                            encoding="utf-8", errors="replace")

    def _pump():
        buf = ""
        while True:
            ch = proc.stderr.read(1)
            if not ch:
                break
            buf += ch
            if ch in ("\r", "\n"):
                m = re.findall(r"(\d+(?:\.\d+)?)%", buf)
                if m:
                    try:
                        job["srProgress"] = max(0, min(100, int(float(m[-1]))))
                    except ValueError:
                        pass
                buf = ""

    pump = threading.Thread(target=_pump, daemon=True)
    pump.start()
    try:
        return proc.wait(timeout=AI_TIMEOUT)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        raise RuntimeError(f"AI 引擎推理超过 {AI_TIMEOUT}s，已中止") from None


def _ai_upscale(src, dst, tier, job):
    """AI 超分（v1.9.1 按srank 工程流程强化）：防黑帧通道预处理 → 双模型推理
    （失败自动换模型重试一次）→ 三重输出校验 → BOX 缩回档位长边 → 极轻 USM 收线。
    两次推理均失败抛异常，由 _superres_job 回退 Pillow 经典管线。"""
    from PIL import Image, ImageFilter  # noqa: PLC0415
    tmp_out = dst + ".ai.png"
    work_png = dst + ".ai.in.png"
    exp_w, exp_h = _ai_prepare(src, work_png)
    last_err = None
    try:
        for model in AI_MODELS:
            try:
                if os.path.exists(tmp_out):
                    os.remove(tmp_out)
                code = _ai_infer_once(work_png, tmp_out, model, job)
                if code != 0:
                    raise RuntimeError(f"推理进程退出码 {code}（显卡/驱动问题）")
                err = _ai_validate(tmp_out, exp_w, exp_h, work_png)
                if err:
                    raise RuntimeError(err)
                last_err = None
                break  # 校验通过
            except RuntimeError as e:
                last_err = f"{model}: {e}"
                log.warning("AI 推理失败，自动换模型重试：%s", e)
        if last_err:
            raise RuntimeError(f"两次 AI 推理均失败：{last_err}")
        img = Image.open(tmp_out)
        if img.mode != "RGB":
            img = img.convert("RGB")
        w, h = img.size
        long_side = max(w, h)
        target_long = SR_TIERS.get(tier, 3840)
        if long_side > target_long:
            # BOX（面积平均）下采样：高倍非整数缩小天然抗锯齿
            # （LANCZOS 有 aliasing 残留，主人反馈发丝锯齿后改 BOX）
            k = target_long / long_side
            img = img.resize((max(1, int(round(w * k))), max(1, int(round(h * k)))),
                             Image.BOX)
        # AI 重建线稿本身锐利，USM 只做极轻收线（85% 会锐出过冲/锯齿，T11 同源）
        img = img.filter(ImageFilter.UnsharpMask(radius=1.0, percent=30, threshold=3))
        img.save(dst, "PNG", compress_level=6)
        return img.size
    finally:
        for p in (tmp_out, work_png):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except OSError:
                pass


def _superres_job(job_id, card_id, external_kind, tier, engine="pillow"):
    """后台超分任务：原图缓存缺失时自动先竞速下载 → 超分 → 写入下载文件夹。
    engine="ai" 走 Real-ESRGAN 实验引擎，缺失/失败自动回退 Pillow 经典管线。
    超分前的原图副本保留在下载文件夹（2026-11-14 主人指示：不再自动删除）。"""
    job = _JOBS[job_id]
    internal = "trained" if external_kind == "after_training" else "normal"
    try:
        # 1. 确保原图缓存存在；缺失则自动级联下载（竞速，进度实时回填）
        src = os.path.join(ORIGINAL_DIR, f"{card_id}_{internal}.png")
        if not (os.path.exists(src) and os.path.getsize(src) > 0):
            job["phase"] = "download"
            job["source"] = ""

            def dcb(done, total, tag):
                job["downloaded"] = done
                job["total"] = total
                job["source"] = tag

            path, err = resolve_original(card_id, internal, progress_cb=dcb)
            if not path:
                job["state"] = "error"
                job["error"] = f"原图下载失败：{err}"
                return
            src = path
        # 2. 超分：engine=ai 走 AI 引擎（实验功能），任何失败自动回退经典管线
        job["phase"] = "superres"
        job["downloaded"] = 0
        job["total"] = 0
        dst = os.path.join(ORIGINAL_DIR, f"{card_id}_{internal}_{tier}.png")
        if not (os.path.exists(dst) and os.path.getsize(dst) > 0):
            used = "pillow"
            if engine == "ai":
                if os.path.isfile(AI_EXE):
                    try:
                        job["phase"] = "ai"
                        job["source"] = "AI"
                        size = _ai_upscale(src, dst, tier, job)
                        used = "ai"
                        log.info("AI 超分完成：card %s %s [%s] → %dx%d",
                                 card_id, external_kind, tier, *size)
                    except Exception as e:  # noqa: BLE001 — 实验功能，失败回退
                        log.warning("AI 超分失败，回退 Pillow 管线：card %s %s -> %s",
                                    card_id, external_kind, e)
                        job["engineFallback"] = True
                else:
                    log.warning("AI 引擎缺失（%s），回退 Pillow 管线", AI_EXE)
                    job["engineFallback"] = True
            job["engine"] = used
            if used == "pillow":
                job["source"] = "Pillow"
                job["srProgress"] = None
                job["phase"] = "superres"
                size = superres_image(src, dst, tier)
                log.info("超分完成：card %s %s [%s] → %dx%d",
                         card_id, external_kind, tier, *size)
            else:
                job["srProgress"] = 100
        # 3. 写入下载文件夹
        index, *_ = load_db()
        card = next((c for c in index["cards"] if c["id"] == card_id), None)
        name = build_original_filename(card, internal)
        dl_name = name[:-4] + ("_4K超分.png" if tier == "4k" else "_2K超分.png")
        ddir = downloads_dir()
        os.makedirs(ddir, exist_ok=True)
        dst_dl = os.path.join(ddir, dl_name)
        created = False
        if not (os.path.exists(dst_dl) and os.path.getsize(dst_dl) > 0):
            shutil.copyfile(dst, dst_dl)
            created = True
            log.info("超分图已保存到下载文件夹：%s", dl_name)
        # 4. 超分前的原图副本保留在下载文件夹（2026-11-14 主人指示改回：
        #    不再自动删除；缓存原图同样保留，供其他档位复用与在线查看）
        job["state"] = "done"
        job["filename"] = dl_name
        job["already"] = not created
        job["url"] = f"/api/originals/{card_id}_{external_kind}_{tier}.png"
    except ImportError:
        job["state"] = "error"
        job["error"] = "服务器缺少 Pillow，无法超分（pip install --user pillow）"
    except Exception as e:  # noqa: BLE001
        job["state"] = "error"
        job["error"] = str(e)


def fmt_skill_description(desc, effects, character_name=""):
    """把技能描述模板替换成实际数值（逻辑对齐官网 formatSkillDescription）。
    模板：{{id;type}}，type ∈ d 时长 / v 数值 / e 追加值 / m 上限 / c 角色名；
    双参 {{id1,id2;type}} 取两效果之和。数值取最高等级。"""
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
        """整数值的浮点去掉小数尾巴（5.0 -> 5）。"""
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


def card_detail(card_id):
    index, skills, characters, costumes, episodes = load_db()
    card = next((c for c in index["cards"] if c["id"] == card_id), None)
    if not card:
        return None
    skill = next((s for s in skills if s.get("id") == card.get("skillId") and card.get("skillId")), None)
    char = next((c for c in characters if c.get("id") == card.get("characterId")), None)
    # 卡牌剧情标题：JP 数据为日文，直接用方向标签
    eps = [{"id": e.get("id"),
            "title": "卡牌剧情（下篇）" if e.get("cardEpisodePartType") == "second_part"
            else "卡牌剧情（上篇）",
            "partType": e.get("cardEpisodePartType")}
           for e in episodes if str(e.get("cardId")) == str(card_id)]
    # 原图（PNG）与各档超分版本是否已缓存
    originals = {}
    for kind, fname in (("normal", f"{card_id}_normal.png"),
                        ("trained", f"{card_id}_after_training.png")):
        originals[kind] = os.path.exists(os.path.join(ORIGINAL_DIR, fname))
    for tier in ("2k", "4k"):
        for kind in ("normal", "trained"):
            fname = f"{card_id}_{kind}_{tier}.png"
            originals[f"sr{tier}_{kind}"] = os.path.exists(os.path.join(ORIGINAL_DIR, fname))
    skill_desc = fmt_skill_description(
        (skill or {}).get("description", ""),
        (skill or {}).get("skillEffects") or [],
        character_name=card.get("characterName") or "")
    return {
        "card": card,
        "skill": {"name": card.get("skillName"),
                  "description": skill_desc,
                  "spriteName": (skill or {}).get("descriptionSpriteName")} if skill else None,
        "character": {"name": card.get("characterFullName"),
                      "givenName": card.get("characterName"),
                      "unit": card.get("unitName"),
                      "height": (char or {}).get("height"),
                      "birthday": (char or {}).get("birthday")} if char else None,
        "episodes": eps,
        "originals": originals,
    }


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    # ------------------------------------------------ 基础工具
    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path, ctype=None):
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError:
            self._send(404, {"error": "文件不存在"})
            return
        if ctype is None:
            ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        # 本地站：代码类文件禁缓存（防止改版后浏览器仍用旧 JS）；
        # 图片允许短缓存。
        ext = os.path.splitext(path)[1].lower()
        if ext in (".html", ".js", ".css", ".mjs", ".vbs"):
            self.send_header("Cache-Control", "no-cache")
        else:
            self.send_header("Cache-Control", "max-age=300")
        self.end_headers()
        self.wfile.write(data)

    def _send_attachment(self, path, filename, ascii_name):
        """以「附件下载」方式发送文件，浏览器会存入其默认下载文件夹
        （通常即系统「下载」），并使用我们提供的可识别文件名。"""
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError:
            self._send(404, {"error": "文件不存在"})
            return
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header(
            "Content-Disposition",
            f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}")
        self.end_headers()
        self.wfile.write(data)

    def _safe_join(self, base, sub):
        """防目录穿越：拼接后必须仍在 base 内。"""
        full = os.path.abspath(os.path.join(base, sub.lstrip("/")))
        if not full.startswith(os.path.abspath(base) + os.sep):
            return None
        return full

    def log_message(self, fmt, *args):  # 静默默认访问日志
        pass

    # ------------------------------------------------ GET
    def do_GET(self):
        path = self.path.split("?")[0]
        try:
            if path == "/api/status":
                state = {}
                try:
                    state = read_json(STATE_PATH)
                except Exception:  # noqa: BLE001
                    pass
                index = read_json(os.path.join(DB_DIR, "index.json"))
                cards = index.get("cards", [])
                originals = len([f for f in os.listdir(ORIGINAL_DIR)
                                 if f.endswith(".png")]) if os.path.isdir(ORIGINAL_DIR) else 0
                shiny_count = 0
                try:
                    shiny_count = len(read_json(os.path.join(SHINY_DB_DIR, "index.json")).get("cards", []))
                except Exception:  # noqa: BLE001
                    pass
                onotes_count = 0
                try:
                    onotes_count = len(read_json(os.path.join(ONOTES_DB_DIR, "index.json")).get("cards", []))
                except Exception:  # noqa: BLE001
                    pass
                self._send(200, {
                    "version": SERVER_VERSION,
                    "updatedAt": index.get("updatedAt"),
                    "lastRun": state.get("last_run"),
                    "lastResult": state.get("last_result"),
                    "lastCounts": state.get("counts"),
                    "cardCount": len(cards),
                    "spoilerCount": sum(1 for c in cards if c.get("spoiler")),
                    "originalsCount": originals,
                    "aiEngine": os.path.isfile(AI_EXE),
                    "shinyCardCount": shiny_count,
                    "onotesCardCount": onotes_count,
                    "nextRun": "每两周 · 周一 09:00",
                })
                return

            m = re.match(r"^/api/cards/(\d+)$", path)
            if m:
                detail = card_detail(int(m.group(1)))
                if detail is None:
                    self._send(404, {"error": "卡牌不存在"})
                else:
                    self._send(200, detail)
                return

            m = re.match(r"^/api/index$", path)
            if m:
                self._send_file(os.path.join(DB_DIR, "index.json"))
                return

            m = re.match(r"^/api/originals/(\d+)_(normal|after_training)(_2k|_4k)?\.png$", path)
            if m:
                card_id, kind, sr = int(m.group(1)), m.group(2), m.group(3) or ""
                p = os.path.join(ORIGINAL_DIR, f"{card_id}_{kind}{sr}.png")
                if os.path.exists(p):
                    self._send_file(p, "image/png")
                else:
                    self._send(404, {"error": "原图尚未下载，请先点击「下载原图」"})
                return

            # 下载进度查询（前端轮询）
            m = re.match(r"^/api/download-progress/([A-Za-z0-9_]+)$", path)
            if m:
                snap = _job_snapshot(m.group(1))
                if snap is None:
                    self._send(404, {"error": "任务不存在"})
                else:
                    self._send(200, snap)
                return

            # 全部下载任务列表（统一下载面板）
            if path == "/api/download-jobs":
                with _JOBS_LOCK:
                    items = [dict(v, jobId=k) for k, v in _JOBS.items()]
                items.sort(key=lambda j: j["jobId"], reverse=True)
                self._send(200, {"jobs": items[:_JOB_HISTORY_MAX]})
                return

            # 缓存统计（原图 + 超分图内部缓存）
            if path == "/api/cache-stats":
                total = n = 0
                if os.path.isdir(ORIGINAL_DIR):
                    for f in os.listdir(ORIGINAL_DIR):
                        if f.endswith(".png"):
                            n += 1
                            total += os.path.getsize(os.path.join(ORIGINAL_DIR, f))
                self._send(200, {"count": n, "bytes": total,
                                 "mb": round(total / 1048576, 1)})
                return

            # ---------------- 闪耀色彩模块 ----------------
            if path == "/api/shinycolors/index":
                self._send_file(os.path.join(SHINY_DB_DIR, "index.json"))
                return
            if path == "/api/shinycolors/status":
                st = {}
                try:
                    st = read_json(os.path.join(SHINY_DB_DIR, "state.json"))
                except Exception:  # noqa: BLE001
                    pass
                n = 0
                try:
                    n = len(read_json(os.path.join(SHINY_DB_DIR, "index.json")).get("cards", []))
                except Exception:  # noqa: BLE001
                    pass
                self._send(200, {"cardCount": n, "lastRun": st.get("last_run"),
                                 "lastResult": st.get("last_result"),
                                 "lastCounts": st.get("counts")})
                return
            m = re.match(r"^/api/shinycolors/cards/(\d+)$", path)
            if m:
                detail = shinycolors_card_detail(int(m.group(1)))
                if detail is None:
                    self._send(404, {"error": "卡面不存在或详情未就绪"})
                else:
                    self._send(200, detail)
                return
            m = re.match(r"^/api/shinycolors/thumbs/(\d+)_(normal|trained)\.webp$", path)
            if m:
                p = self._safe_join(SHINY_THUMB_DIR,
                                    f"{m.group(1)}_{m.group(2)}.webp")
                if p and os.path.exists(p):
                    self._send_file(p, "image/webp")
                else:
                    self._send(404, {"error": "缩略图不存在"})
                return
            m = re.match(r"^/api/shinycolors/originals/(\d+)(?:_(fes))?(?:_(2k|4k))?\.(jpg|png)$",
                         path)
            if m:
                cid = int(m.group(1))
                kind = "fes" if m.group(2) else "normal"
                tier, ext = m.group(3), m.group(4)
                stem = f"{cid}" if kind == "normal" else f"{cid}_fes"
                if tier:
                    p = os.path.join(SHINY_ORIGINAL_DIR, f"{stem}_{tier}.png")
                elif ext == "png":
                    # 原档一律以 PNG 提供：已有 PNG 直接发；仅有旧 jpg 缓存则本地转码（不触网）
                    p = os.path.join(SHINY_ORIGINAL_DIR, f"{stem}.png")
                    if not (os.path.exists(p) and os.path.getsize(p) > 0):
                        jpg = os.path.join(SHINY_ORIGINAL_DIR, f"{stem}.jpg")
                        if os.path.exists(jpg):
                            p, _ = _shiny_to_png(jpg, p)
                        else:
                            p = None
                else:
                    p = os.path.join(SHINY_ORIGINAL_DIR, f"{stem}.jpg")
                if p and os.path.exists(p):
                    self._send_file(p, "image/png" if p.endswith(".png") else "image/jpeg")
                else:
                    self._send(404, {"error": "原图尚未下载，请先点击「下载原图」"})
                return

            # ---------------- Our Notes 模块 ----------------
            if path == "/api/onotes/index":
                self._send_file(os.path.join(ONOTES_DB_DIR, "index.json"))
                return
            if path == "/api/onotes/status":
                st = {}
                try:
                    st = read_json(os.path.join(ONOTES_DB_DIR, "state.json"))
                except Exception:  # noqa: BLE001
                    pass
                n = 0
                try:
                    n = len(read_json(os.path.join(ONOTES_DB_DIR, "index.json")).get("cards", []))
                except Exception:  # noqa: BLE001
                    pass
                self._send(200, {"cardCount": n, "lastRun": st.get("last_run"),
                                 "lastResult": st.get("last_result"),
                                 "lastCounts": st.get("counts")})
                return
            m = re.match(r"^/api/onotes/cards/(\d+)(?:/(card|support))?$", path)
            if m:
                detail = onotes_card_detail(int(m.group(1)), m.group(2))
                if detail is None:
                    self._send(404, {"error": "卡面不存在或详情未就绪"})
                else:
                    self._send(200, detail)
                return
            m = re.match(r"^/api/onotes/thumbs/(\d+)_(card|support)\.webp$", path)
            if m:
                p = self._safe_join(ONOTES_THUMB_DIR,
                                    f"{m.group(1)}_{m.group(2)}.webp")
                if p and os.path.exists(p):
                    self._send_file(p, "image/webp")
                else:
                    self._send(404, {"error": "缩略图不存在"})
                return
            m = re.match(r"^/api/onotes/originals/(\d+)_(card|support)(?:_(2k|4k))?\.png$",
                         path)
            if m:
                cid, kind, tier = int(m.group(1)), m.group(2), m.group(3)
                stem = f"{cid}_{kind}"
                fname = f"{stem}_{tier}.png" if tier else f"{stem}.png"
                p = os.path.join(ONOTES_ORIGINAL_DIR, fname)
                if p and os.path.exists(p):
                    self._send_file(p, "image/png")
                else:
                    self._send(404, {"error": "原图尚未下载，请先点击「下载原图」"})
                return

            # ---------------- 邦多利模块 ----------------
            if path == "/api/bandori/index":
                self._send_file(os.path.join(BANDORI_DB_DIR, "index.json"))
                return
            if path == "/api/bandori/status":
                st = {}
                try:
                    st = read_json(os.path.join(BANDORI_DB_DIR, "state.json"))
                except Exception:  # noqa: BLE001
                    pass
                n = 0
                try:
                    n = len(read_json(os.path.join(BANDORI_DB_DIR, "index.json")).get("cards", []))
                except Exception:  # noqa: BLE001
                    pass
                self._send(200, {"cardCount": n, "lastRun": st.get("last_run"),
                                 "lastResult": st.get("last_result"),
                                 "lastCounts": st.get("counts")})
                return
            m = re.match(r"^/api/bandori/cards/(\d+)$", path)
            if m:
                detail = bandori_card_detail(int(m.group(1)))
                if detail is None:
                    self._send(404, {"error": "卡牌不存在"})
                else:
                    self._send(200, detail)
                return
            m = re.match(r"^/api/bandori/thumbs/(\d+)_(normal|trained|after_training)\.webp$", path)
            if m:
                cid, kind = int(m.group(1)), m.group(2)
                fname = f"{cid}_{'trained' if kind in ('trained', 'after_training') else 'normal'}.webp"
                p = self._safe_join(BANDORI_THUMB_DIR, fname)
                if p and os.path.exists(p):
                    self._send_file(p, "image/webp")
                else:
                    self._send(404, {"error": "缩略图不存在"})
                return
            m = re.match(r"^/api/bandori/originals/(\d+)_(normal|after_training)(_2k|_4k)?\.png$",
                         path)
            if m:
                cid, kind, sr = int(m.group(1)), m.group(2), m.group(3) or ""
                # 文件名用 URL kind 原文（normal/after_training）——与
                # resolve_bandori_original 的落盘命名严格一致（曾因
                # 「URL after_training → 内部 trained」映射错位导致 404）
                p = os.path.join(BANDORI_ORIGINAL_DIR, f"{cid}_{kind}{sr}.png")
                if os.path.exists(p):
                    self._send_file(p, "image/png")
                else:
                    self._send(404, {"error": "原图尚未下载，请先点击「下载原图」"})
                return

            m = re.match(r"^/api/thumbs/(\d+)_([a-z_]+)\.webp$", path)
            if m:
                p = self._safe_join(THUMB_DIR, f"{m.group(1)}_{m.group(2)}.webp")
                if p and os.path.exists(p):
                    self._send_file(p, "image/webp")
                else:
                    self._send(404, {"error": "缩略图不存在"})
                return

            m = re.match(r"^/api/costume-thumb/([a-z0-9_]+)\.webp$", path)
            if m:
                p = costume_thumb(m.group(1))
                if p:
                    self._send_file(p, "image/webp")
                else:
                    self._send(404, {"error": "服装缩略图不可用"})
                return

            # 静态文件（web/）
            sub = path if path != "/" else "/index.html"
            p = self._safe_join(WEB_DIR, sub)
            if p and os.path.isfile(p):
                self._send_file(p)
                return
            self._send(404, {"error": "Not Found"})
        except Exception as e:  # noqa: BLE001
            log.exception("GET %s 出错", path)
            self._send(500, {"error": str(e)})

    # ------------------------------------------------ POST
    def do_POST(self):
        path = self.path.split("?")[0]
        try:
            m = re.match(r"^/api/download/(\d+)/([a-z_]+)$", path)
            if m:
                card_id, kind = int(m.group(1)), m.group(2)
                if kind == "trained":  # 别名兼容：前后端词表不一致也不再报错
                    kind = "after_training"
                if kind not in ("normal", "after_training"):
                    self._send(400, {"error": "kind 必须是 normal 或 after_training"})
                    return
                # 同卡同方向已有运行中任务 → 复用，避免重复抓取（mod 隔离防跨模块误配）
                with _JOBS_LOCK:
                    for jid, j in _JOBS.items():
                        if (j.get("card") == card_id and j.get("kind") == kind
                                and j.get("mod", "pjsk") == "pjsk"
                                and j.get("state") == "running"):
                            self._send(200, {"ok": True, "jobId": jid, "reused": True})
                            return
                try:
                    index, *_ = load_db()
                    card = next((c for c in index["cards"] if c["id"] == card_id), None)
                except Exception:  # noqa: BLE001 — 索引读取失败不阻塞任务创建
                    card = None
                label = (f"{card.get('prefix', '未知卡面')} · "
                         f"{'突破后' if kind == 'after_training' else '突破前'}") if card \
                    else f"卡面 #{card_id} · {'突破后' if kind == 'after_training' else '突破前'}"
                job_id = f"dl{int(time.time() * 1000) % 100000000}_{random.randint(100, 999)}"
                with _JOBS_LOCK:
                    _JOBS[job_id] = {"type": "download", "mod": "pjsk", "card": card_id,
                                     "kind": kind, "state": "running",
                                     "downloaded": 0, "total": 0, "source": "",
                                     "filename": "", "error": "", "already": False,
                                     "url": "", "label": label}
                    _prune_jobs()
                threading.Thread(target=_download_job, args=(job_id, card_id, kind),
                                 daemon=True).start()
                self._send(200, {"ok": True, "jobId": job_id})
                return
            # 超分：把已缓存的 PNG 原图强化到目标档位（任务化，进度在下载面板统一展示）
            m = re.match(r"^/api/superres/(\d+)/([a-z_]+)$", path)
            if m:
                card_id, kind = int(m.group(1)), m.group(2)
                if kind == "trained":
                    kind = "after_training"
                if kind not in ("normal", "after_training"):
                    self._send(400, {"error": "kind 必须是 normal 或 after_training"})
                    return
                # 原图缓存缺失时不再拦截——超分任务内部会自动级联竞速下载原图
                # 超分档位（设置页可切换）：2k → 长边 2560；4k → 长边 3840
                qs = urllib.parse.parse_qs(self.path.split("?")[1] or "")
                tier = (qs.get("target") or ["4k"])[0].lower()
                if tier not in SR_TIERS:
                    tier = "4k"
                # AI 超分实验开关（设置页 srEngine）：ai | pillow，默认经典管线
                engine = (qs.get("engine") or ["pillow"])[0].lower()
                if engine not in ("ai", "pillow"):
                    engine = "pillow"
                try:
                    index, *_ = load_db()
                    card = next((c for c in index["cards"] if c["id"] == card_id), None)
                except Exception:  # noqa: BLE001
                    card = None
                tier_label = "2K" if tier == "2k" else "4K"
                base_prefix = card.get("prefix", "未知卡面") if card else f"卡面 #{card_id}"
                label = f"{base_prefix} · {'AI超分' if engine == 'ai' else '超分'}{tier_label}"
                job_id = f"sr{int(time.time() * 1000) % 100000000}_{random.randint(100, 999)}"
                with _JOBS_LOCK:
                    _JOBS[job_id] = {"type": "superres", "mod": "pjsk", "card": card_id,
                                     "kind": kind, "tier": tier, "engine": engine,
                                     "engineFallback": False, "state": "running",
                                     "downloaded": 0, "total": 0,
                                     "source": "AI" if engine == "ai" else "Pillow",
                                     "srProgress": None,
                                     "filename": "", "error": "", "already": False,
                                     "url": "", "label": label}
                    _prune_jobs()
                threading.Thread(target=_superres_job,
                                 args=(job_id, card_id, kind, tier, engine),
                                 daemon=True).start()
                self._send(200, {"ok": True, "jobId": job_id})
                return
            # 删除指定任务记录（下载面板条目的「单独删除」）：
            # 进行中任务不可删——后台线程仍持有 job dict 引用在写状态，删了会名存实亡
            m = re.match(r"^/api/job-remove/([A-Za-z0-9_]+)$", path)
            if m:
                with _JOBS_LOCK:
                    j = _JOBS.get(m.group(1))
                    if j is None:
                        self._send(404, {"error": "任务不存在"})
                        return
                    if j.get("state") == "running":
                        self._send(400, {"error": "任务进行中，结束后再删除"})
                        return
                    _JOBS.pop(m.group(1), None)
                self._send(200, {"ok": True})
                return
            # ---------------- 闪耀色彩模块 ----------------
            m = re.match(r"^/api/shinycolors/download/(\d+)(?:/([a-z_]+))?$", path)
            if m:
                card_id = int(m.group(1))
                kind = _shiny_kind_norm(m.group(2))
                with _JOBS_LOCK:
                    for jid, j in _JOBS.items():
                        if (j.get("card") == card_id and j.get("mod") == "shinycolors"
                                and j.get("kind") == kind
                                and j.get("type") == "download"
                                and j.get("state") == "running"):
                            self._send(200, {"ok": True, "jobId": jid, "reused": True})
                            return
                try:
                    index = load_shiny_index()
                    card = next((c for c in index["cards"] if c["id"] == card_id), None)
                except Exception:  # noqa: BLE001
                    card = None
                label = (f"{(card.get('prefix') or '未知卡面')[:40]} · "
                         f"{_shiny_kind_label(kind)}") if card else f"卡面 #{card_id}"
                job_id = f"dl{int(time.time() * 1000) % 100000000}_{random.randint(100, 999)}"
                with _JOBS_LOCK:
                    _JOBS[job_id] = {"type": "download", "mod": "shinycolors",
                                     "card": card_id, "kind": kind,
                                     "state": "running",
                                     "downloaded": 0, "total": 0, "source": "",
                                     "filename": "", "error": "", "already": False,
                                     "url": "", "label": label}
                    _prune_jobs()
                threading.Thread(target=_shinycolors_download_job,
                                 args=(job_id, card_id, kind), daemon=True).start()
                self._send(200, {"ok": True, "jobId": job_id})
                return
            m = re.match(r"^/api/shinycolors/superres/(\d+)(?:/([a-z_]+))?$", path)
            if m:
                card_id = int(m.group(1))
                qs = urllib.parse.parse_qs(self.path.split("?")[1] or "")
                kind = _shiny_kind_norm(m.group(2) or (qs.get("kind") or ["normal"])[0])
                tier = (qs.get("target") or ["4k"])[0].lower()
                if tier not in SR_TIERS:
                    tier = "4k"
                engine = (qs.get("engine") or ["ai"])[0].lower()
                if engine not in ("ai", "pillow"):
                    engine = "ai"
                try:
                    index = load_shiny_index()
                    card = next((c for c in index["cards"] if c["id"] == card_id), None)
                except Exception:  # noqa: BLE001
                    card = None
                base_prefix = (card.get("prefix") or "未知卡面")[:30] if card else f"卡面 #{card_id}"
                tier_label = "2K" if tier == "2k" else "4K"
                label = (f"{base_prefix} · {_shiny_kind_label(kind)} · "
                         f"{'AI超分' if engine == 'ai' else '超分'}{tier_label}")
                job_id = f"sr{int(time.time() * 1000) % 100000000}_{random.randint(100, 999)}"
                with _JOBS_LOCK:
                    _JOBS[job_id] = {"type": "superres", "mod": "shinycolors",
                                     "card": card_id, "kind": kind, "tier": tier,
                                     "engine": engine, "engineFallback": False,
                                     "state": "running",
                                     "downloaded": 0, "total": 0,
                                     "source": "AI" if engine == "ai" else "Pillow",
                                     "srProgress": None,
                                     "filename": "", "error": "", "already": False,
                                     "url": "", "label": label}
                    _prune_jobs()
                threading.Thread(target=_shinycolors_superres_job,
                                 args=(job_id, card_id, tier, engine, kind),
                                 daemon=True).start()
                self._send(200, {"ok": True, "jobId": job_id})
                return

            # ---------------- Our Notes 模块 ----------------
            m = re.match(r"^/api/onotes/download/(\d+)/(card|support)$", path)
            if m:
                card_id, kind = int(m.group(1)), m.group(2)
                with _JOBS_LOCK:
                    for jid, j in _JOBS.items():
                        if (j.get("card") == card_id and j.get("kind") == kind
                                and j.get("mod") == "onotes"
                                and j.get("type") == "download"
                                and j.get("state") == "running"):
                            self._send(200, {"ok": True, "jobId": jid, "reused": True})
                            return
                card = _onotes_index_card(card_id, kind)
                label = (f"{(card.get('prefix') or '未知卡面')} · "
                         f"{_onotes_kind_label(kind)}") if card else f"卡面 #{card_id}"
                job_id = f"dl{int(time.time() * 1000) % 100000000}_{random.randint(100, 999)}"
                with _JOBS_LOCK:
                    _JOBS[job_id] = {"type": "download", "mod": "onotes", "card": card_id,
                                     "kind": kind, "state": "running",
                                     "downloaded": 0, "total": 0, "source": "",
                                     "filename": "", "error": "", "already": False,
                                     "url": "", "label": label}
                    _prune_jobs()
                threading.Thread(target=_onotes_download_job,
                                 args=(job_id, card_id, kind), daemon=True).start()
                self._send(200, {"ok": True, "jobId": job_id})
                return
            m = re.match(r"^/api/onotes/superres/(\d+)/(card|support)$", path)
            if m:
                card_id, kind = int(m.group(1)), m.group(2)
                # 原图缓存缺失不拦截——超分任务内部自动级联下载
                qs = urllib.parse.parse_qs(self.path.split("?")[1] or "")
                tier = (qs.get("target") or ["4k"])[0].lower()
                if tier not in SR_TIERS:
                    tier = "4k"
                engine = (qs.get("engine") or ["ai"])[0].lower()
                if engine not in ("ai", "pillow"):
                    engine = "ai"
                card = _onotes_index_card(card_id, kind)
                tier_label = "2K" if tier == "2k" else "4K"
                base_prefix = (card.get("prefix") or "未知卡面")[:30] if card else f"卡面 #{card_id}"
                label = (f"{base_prefix} · {_onotes_kind_label(kind)} · "
                         f"{'AI超分' if engine == 'ai' else '超分'}{tier_label}")
                job_id = f"sr{int(time.time() * 1000) % 100000000}_{random.randint(100, 999)}"
                with _JOBS_LOCK:
                    _JOBS[job_id] = {"type": "superres", "mod": "onotes", "card": card_id,
                                     "kind": kind, "tier": tier, "engine": engine,
                                     "engineFallback": False, "state": "running",
                                     "downloaded": 0, "total": 0,
                                     "source": "AI" if engine == "ai" else "Pillow",
                                     "srProgress": None,
                                     "filename": "", "error": "", "already": False,
                                     "url": "", "label": label}
                    _prune_jobs()
                threading.Thread(target=_onotes_superres_job,
                                 args=(job_id, card_id, tier, engine, kind),
                                 daemon=True).start()
                self._send(200, {"ok": True, "jobId": job_id})
                return

            # ---------------- 邦多利模块 ----------------
            m = re.match(r"^/api/bandori/download/(\d+)/([a-z_]+)$", path)
            if m:
                card_id, kind = int(m.group(1)), m.group(2)
                if kind == "trained":  # 别名兼容
                    kind = "after_training"
                if kind not in ("normal", "after_training"):
                    self._send(400, {"error": "kind 必须是 normal 或 after_training"})
                    return
                with _JOBS_LOCK:
                    for jid, j in _JOBS.items():
                        if (j.get("card") == card_id and j.get("kind") == kind
                                and j.get("mod") == "bandori"
                                and j.get("state") == "running"):
                            self._send(200, {"ok": True, "jobId": jid, "reused": True})
                            return
                try:
                    index = load_bandori_index()
                    card = next((c for c in index["cards"] if c["id"] == card_id), None)
                except Exception:  # noqa: BLE001
                    card = None
                label = (f"{(card.get('prefix') or '未知卡面')} · "
                         f"{'突破后' if kind == 'after_training' else '突破前'}") if card \
                    else f"卡面 #{card_id}"
                job_id = f"dl{int(time.time() * 1000) % 100000000}_{random.randint(100, 999)}"
                with _JOBS_LOCK:
                    _JOBS[job_id] = {"type": "download", "mod": "bandori", "card": card_id,
                                     "kind": kind, "state": "running",
                                     "downloaded": 0, "total": 0, "source": "",
                                     "filename": "", "error": "", "already": False,
                                     "url": "", "label": label}
                    _prune_jobs()
                threading.Thread(target=_bandori_download_job,
                                 args=(job_id, card_id, kind), daemon=True).start()
                self._send(200, {"ok": True, "jobId": job_id})
                return
            m = re.match(r"^/api/bandori/superres/(\d+)/([a-z_]+)$", path)
            if m:
                card_id, kind = int(m.group(1)), m.group(2)
                if kind == "trained":
                    kind = "after_training"
                if kind not in ("normal", "after_training"):
                    self._send(400, {"error": "kind 必须是 normal 或 after_training"})
                    return
                # 原图缓存缺失不拦截——超分任务内部自动级联下载
                qs = urllib.parse.parse_qs(self.path.split("?")[1] or "")
                tier = (qs.get("target") or ["4k"])[0].lower()
                if tier not in SR_TIERS:
                    tier = "4k"
                engine = (qs.get("engine") or ["ai"])[0].lower()
                if engine not in ("ai", "pillow"):
                    engine = "ai"
                try:
                    index = load_bandori_index()
                    card = next((c for c in index["cards"] if c["id"] == card_id), None)
                except Exception:  # noqa: BLE001
                    card = None
                tier_label = "2K" if tier == "2k" else "4K"
                base_prefix = (card.get("prefix") or "未知卡面") if card else f"卡面 #{card_id}"
                label = f"{base_prefix} · {'AI超分' if engine == 'ai' else '超分'}{tier_label}"
                job_id = f"sr{int(time.time() * 1000) % 100000000}_{random.randint(100, 999)}"
                with _JOBS_LOCK:
                    _JOBS[job_id] = {"type": "superres", "mod": "bandori", "card": card_id,
                                     "kind": kind, "tier": tier, "engine": engine,
                                     "engineFallback": False, "state": "running",
                                     "downloaded": 0, "total": 0,
                                     "source": "AI" if engine == "ai" else "Pillow",
                                     "srProgress": None,
                                     "filename": "", "error": "", "already": False,
                                     "url": "", "label": label}
                    _prune_jobs()
                threading.Thread(target=_bandori_superres_job,
                                 args=(job_id, card_id, kind, tier, engine),
                                 daemon=True).start()
                self._send(200, {"ok": True, "jobId": job_id})
                return
            # 清除图片缓存（data/originals 全部 PNG；下载文件夹里的成品不受影响）
            if path == "/api/cache-clear":
                removed = freed = 0
                if os.path.isdir(ORIGINAL_DIR):
                    for f in os.listdir(ORIGINAL_DIR):
                        if f.endswith(".png"):
                            p = os.path.join(ORIGINAL_DIR, f)
                            try:
                                freed += os.path.getsize(p)
                                os.remove(p)
                                removed += 1
                            except OSError as e:
                                log.warning("缓存清除失败 %s：%s", f, e)
                log.info("图片缓存已清除：%d 个文件，释放 %.1f MB", removed, freed / 1048576)
                self._send(200, {"ok": True, "removed": removed,
                                 "freedMB": round(freed / 1048576, 1)})
                return
            self._send(404, {"error": "Not Found"})
        except Exception as e:  # noqa: BLE001
            log.exception("POST %s 出错", path)
            self._send(500, {"error": str(e)})


def main():
    # 旧版缓存清理：webp（v1.4.0 前）与旧 _2k 命名（v1.7.0 起档位为 _2k/_4k 且尺寸不同）
    if os.path.isdir(ORIGINAL_DIR):
        stale = [f for f in os.listdir(ORIGINAL_DIR)
                 if f.endswith(".webp") or "_2k.png" in f]
        for f in stale:
            try:
                os.remove(os.path.join(ORIGINAL_DIR, f))
            except OSError as e:
                log.warning("清理旧缓存失败 %s：%s", f, e)
        if stale:
            log.info("已清理 %d 个旧缓存文件（webp / 旧 _2k 命名）", len(stale))
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    log.info("Pjsk 卡牌雷达网站 v%s 已启动：http://%s:%d", SERVER_VERSION, HOST, PORT)
    server.serve_forever()


if __name__ == "__main__":
    if sys.stdout:  # may be None under pythonw/hidden consoles
        sys.stdout.reconfigure(encoding="utf-8")
    main()
