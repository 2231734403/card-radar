# -*- coding: utf-8 -*-
"""
闪耀色彩（シャニマス/Shiny Colors）卡面爬虫 —— 数据源 shinycolors.moe 公开 API
  - 偶像名单：https://api.shinycolors.moe/info/idolList（28 位）
  - 偶像详情：/info/idolInfo?idolId={n}（内含 cardLists[] 该偶像全部卡面）
  - 卡面图：https://cf-static.shinycolors.moe/images/content/
      {idols|support_idols}/card/{enzaId}.jpg        （突破前）
      {idols|support_idols}/fes_card/{enzaId}.jpg    （突破后，仅 P 卡）
  - 卡详情：/info/pCardInfo?uuid={uuid} / /info/sCardInfo?cardId={uuid}
网络层：三通路自动回退（直连 → 127.0.0.1:7890 → 7897）——API 子域常需代理、
图床（cf-static）直连通常可达，自动探测无需感知 VPN 状态。
行为对齐 pjsk/bandori 模块：index + 增量缩略图 + 详情预爬分批 + missing 记忆。
输出全部写入 data/shinycolors（index.json / thumbs_shinycolors / state.json）。
无属性体系（本篇卡无属性色），故 index 不含 attr 字段、前端不渲染属性角标。
用法：py -X utf8 scraper/shinycolors_scrape.py [limit]  （limit：仅前 N 张待下载缩略）
"""
import json
import logging
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta

# ---------------------------------------------------------------- 常量配置
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
DB_DIR = os.path.join(DATA_DIR, "shinycolors")
THUMB_DIR = os.path.join(DATA_DIR, "thumbs_shinycolors")
LOG_DIR = os.path.join(DATA_DIR, "logs")
STATE_PATH = os.path.join(DB_DIR, "state.json")

API_BASE = "https://api.shinycolors.moe"
API_IDOL_LIST = "/info/idolList"
API_IDOL_INFO = "/info/idolInfo?idolId={n}"
ART_BASE = ("https://cf-static.shinycolors.moe/images/content/"
            "{dir}/card/{enza}.jpg")
FES_BASE = ("https://cf-static.shinycolors.moe/images/content/"
            "{dir}/fes_card/{enza}.jpg")
DIR_P = "idols"            # P 卡图目录
DIR_S = "support_idols"    # S 卡图目录

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
WORKERS = 4
THUMB_MAX_H = 240
DETAIL_BATCH = 400          # 详情预爬每次运行限量（API 限流，分批补齐）
MISSING_RETRY_MS = 14 * 86400 * 1000

# 三通路：直连优先（cf-static 实测直连 200），API 子域直连常断 → 自动回退代理
PROXIES = [None, "http://127.0.0.1:7890", "http://127.0.0.1:7897"]
CTX = ssl.create_default_context()

# 萌娘百科对照（人物 → 团体）：爬取后自检 unitName 一一对应，错位即告警
# 来源：zh.moegirl.org.cn/偶像大师_闪耀色彩
EXPECTED_UNIT = {
    "櫻木真乃": "illumination STARS", "風野灯織": "illumination STARS",
    "八宮めぐる": "illumination STARS",
    "月岡恋鐘": "L'Antica", "田中摩美々": "L'Antica", "白瀬咲耶": "L'Antica",
    "三峰結華": "L'Antica", "幽谷霧子": "L'Antica",
    "小宮果穂": "放課後クライマックスガールズ", "園田智代子": "放課後クライマックスガールズ",
    "西城樹里": "放課後クライマックスガールズ", "杜野凛世": "放課後クライマックスガールズ",
    "有栖川夏葉": "放課後クライマックスガールズ",
    "大崎甘奈": "ALSTROEMERIA", "大崎甜花": "ALSTROEMERIA", "桑山千雪": "ALSTROEMERIA",
    "芹沢あさひ": "Straylight", "黛冬優子": "Straylight", "和泉愛依": "Straylight",
    "浅倉透": "noctchill", "樋口円香": "noctchill", "福丸小糸": "noctchill",
    "市川雛菜": "noctchill",
    "七草にちか": "SHHis", "緋田美琴": "SHHis",
    "斑鳩ルカ": "CoMETIK", "鈴木羽那": "CoMETIK", "郁田はるき": "CoMETIK",
}


class NotFoundError(Exception):
    """资源不存在（HTTP 404）。"""


# ---------------------------------------------------------------- 日志
os.makedirs(DB_DIR, exist_ok=True)
os.makedirs(THUMB_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

logger = logging.getLogger("shinycolors_scrape")
logger.setLevel(logging.INFO)
_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
_fh = logging.FileHandler(os.path.join(LOG_DIR, "shinycolors_scrape.log"), encoding="utf-8")
_fh.setFormatter(_fmt)
logger.addHandler(_fh)
_sh = logging.StreamHandler(sys.stdout)
_sh.setFormatter(_fmt)
logger.addHandler(_sh)


# ---------------------------------------------------------------- 网络层（三通路回退）
def _make_opener(tag):
    """按通路构造 opener：直连无代理；代理通路显式挂 SSL 上下文
    （opener.open() 不接受 context 参数，必须由 HTTPSHandler 携带）。"""
    handlers = [urllib.request.HTTPSHandler(context=CTX)]
    if tag.startswith("代理"):
        p = tag.replace("代理", "")
        handlers.append(urllib.request.ProxyHandler({"http": p, "https": p}))
    return urllib.request.build_opener(*handlers)


def fetch_bytes(url, timeout=60):
    """GET 原始字节：直连 → 代理 7890 → 7897 自动回退。404 抛 NotFoundError，
    HTML 响应视为 SPA 壳（404 同义）。全部失败抛 ConnectionError。"""
    last = None
    for tag in ["直连", "代理7890", "代理7897"]:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with _make_opener(tag).open(req, timeout=timeout) as r:
                data = r.read()
                ct = (r.headers.get("Content-Type") or "")
            if ct.startswith("text/html"):
                raise NotFoundError(url)
            return data
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise NotFoundError(url) from e
            last = e
        except NotFoundError:
            raise
        except Exception as e:  # noqa: BLE001
            last = f"{tag}: {e}"
        time.sleep(1)
    raise ConnectionError(f"{url} -> {last}")


def fetch_json(url, timeout=90):
    return json.loads(fetch_bytes(url, timeout=timeout).decode("utf-8", "replace"))


# ---------------------------------------------------------------- index 构建
def build_index(idols):
    """idolInfo 响应（每偶像含 cardLists）→ pjsk 兼容 index。
    无属性体系 → 不含 attr 字段（前端不渲染属性角标）。"""
    index = []
    unit_warn = []
    now_ms = int(time.time() * 1000)
    for idol in idols:
        idol_id = idol.get("idolId")
        idol_name = idol.get("idolName") or ""
        unit = idol.get("unit") or {}
        unit_name = unit.get("unitName") or ""
        # 萌娘百科对照自检：人物与团体一一对应
        expect = EXPECTED_UNIT.get(idol_name)
        if expect and unit_name != expect:
            unit_warn.append(f"{idol_name}: API={unit_name} 萌百={expect}")
        for c in idol.get("cardLists") or []:
            cid = c.get("cardIndex")
            enza = c.get("enzaId")
            if cid is None or not enza:
                continue
            card_type = c.get("cardType") or ""      # P_SSR / S_SR / ...
            kind = "P" if card_type.startswith("P") else "S"
            rarity = card_type.split("_")[-1] if "_" in card_type else card_type
            rel = c.get("releaseDate")
            release_ms = 0
            if rel:
                try:
                    from datetime import datetime as _dt  # noqa: PLC0415
                    release_ms = int(_dt.strptime(rel, "%Y-%m-%d")
                                     .replace(tzinfo=timezone(timedelta(hours=8)))
                                     .timestamp() * 1000)
                except Exception:  # noqa: BLE001
                    release_ms = 0
            # P 卡 fes_card = 突破后立绘；S 卡无突破后
            trainable = kind == "P"
            index.append({
                "id": cid,
                "cardUuid": c.get("cardUuid"),
                "enzaId": enza,
                "prefix": (c.get("cardName") or "").strip(),
                "characterId": idol_id,
                "characterName": idol_name,
                "unitName": unit_name,
                "cardKind": kind,
                "rarity": rarity,
                "cardType": card_type,
                "trainable": trainable,
                "releaseDate": rel or "",
                "releaseAt": release_ms,
                "spoiler": release_ms > now_ms,
                "getMethod": c.get("getMethod") or "",
                "thumbNormal": os.path.join("thumbs_shinycolors",
                                            f"{cid}_normal.webp").replace("\\", "/"),
                "thumbTrained": (os.path.join("thumbs_shinycolors",
                                              f"{cid}_trained.webp").replace("\\", "/")
                                 if trainable else None),
            })
    index.sort(key=lambda c: c["id"], reverse=True)
    return index, unit_warn


def load_state():
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:  # noqa: BLE001
            logger.warning("state.json 损坏，重建")
    return {"trained_missing": [], "runs": 0, "last_run": None}


def save_state(state):
    tmp = STATE_PATH + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE_PATH)


# ---------------------------------------------------------------- 详情预爬
def fetch_details(index, limit=400):
    """预爬单卡详情到 data/shinycolors/card_{id}.json（增量分批补齐）。
    P 卡走 pCardInfo、S 卡走 sCardInfo（均按 cardUuid）。"""
    todo = []
    for c in index:
        p = os.path.join(DB_DIR, f"card_{c['id']}.json")
        if not os.path.exists(p):
            todo.append(c)
    if limit:
        todo = todo[: int(limit)]
    logger.info("需要预爬详情 %d 张（已有缓存 %d 张）",
                len(todo), len(index) - len(todo))
    ok = fail = 0
    for i, c in enumerate(todo, 1):
        uuid = c.get("cardUuid")
        ep = "/info/pCardInfo?cardId=" if c["cardKind"] == "P" else "/info/sCardInfo?cardId="
        try:
            raw = fetch_json(API_BASE + ep + uuid)
            tmp = os.path.join(DB_DIR, f"card_{c['id']}.json.part")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(raw, f, ensure_ascii=False)
            os.replace(tmp, os.path.join(DB_DIR, f"card_{c['id']}.json"))
            ok += 1
        except NotFoundError:
            logger.warning("详情 404：card %s（保留缓存占位跳过）", c["id"])
            with open(os.path.join(DB_DIR, f"card_{c['id']}.json"), "w",
                      encoding="utf-8") as f:
                json.dump({"cardIndex": c["id"], "notFound": True}, f,
                          ensure_ascii=False)
            ok += 1
        except Exception as e:  # noqa: BLE001
            fail += 1
            logger.warning("详情预爬失败 card %s：%s（下次运行自动重试）", c["id"], e)
        if i % 100 == 0:
            logger.info("详情预爬进度 %d/%d（成功 %d）", i, len(todo), ok)
        time.sleep(0.3)
    logger.info("详情预爬完成：成功 %d 失败 %d", ok, fail)
    return ok, fail


# ---------------------------------------------------------------- 缩略图
def shrink_webp(src_bytes, dst_path):
    from PIL import Image  # noqa: PLC0415
    import io  # noqa: PLC0415
    img = Image.open(io.BytesIO(src_bytes))
    if img.mode != "RGB":
        img = img.convert("RGB")
    w, h = img.size
    if h > THUMB_MAX_H:
        k = THUMB_MAX_H / h
        img = img.resize((max(1, int(round(w * k))), THUMB_MAX_H), Image.LANCZOS)
    img.save(dst_path, "WEBP", quality=80)


def scrape_thumbs(index, state, limit=None):
    """增量下载缩略图：normal = card/*.jpg；trained = fes_card/*.jpg（仅 P 卡）。
    missing 记忆机制与 pjsk/bandori 一致。"""
    trained_missing = set(state.get("trained_missing", []))
    normal_missing = state.get("normal_missing", {})
    now_ms = int(time.time() * 1000)

    def pending(cid):
        ts = normal_missing.get(str(cid))
        return ts is not None and now_ms - ts < MISSING_RETRY_MS

    jobs = []
    for card in index:
        cid = card["id"]
        enza = card["enzaId"]
        if not enza:
            continue
        d = DIR_P if card["cardKind"] == "P" else DIR_S
        normal_path = os.path.join(THUMB_DIR, f"{cid}_normal.webp")
        if (not (os.path.exists(normal_path) and os.path.getsize(normal_path) > 0)
                and not pending(cid)):
            jobs.append((cid, "normal", normal_path,
                         ART_BASE.format(dir=d, enza=enza)))
        if card["trainable"] and cid not in trained_missing:
            trained_path = os.path.join(THUMB_DIR, f"{cid}_trained.webp")
            if not (os.path.exists(trained_path) and os.path.getsize(trained_path) > 0):
                jobs.append((cid, "trained", trained_path,
                             FES_BASE.format(dir=d, enza=enza)))

    if limit:
        jobs = jobs[: int(limit)]

    total_slots = len(index) + sum(1 for c in index if c["trainable"])
    skipped = total_slots - len(jobs)
    logger.info("需要下载缩略图 %d 张（已存在跳过 %d 张）", len(jobs), skipped)
    if not jobs:
        return 0, skipped, 0, 0

    def work(job):
        cid, kind, path, url = job
        try:
            data = fetch_bytes(url, timeout=60)
        except NotFoundError:
            return (cid, kind, "missing", 0)
        except Exception as e:  # noqa: BLE001
            return (cid, kind, f"fail:{e}", 0)
        try:
            tmp = path + ".part"
            shrink_webp(data, tmp)
            os.replace(tmp, path)
            return (cid, kind, "ok", os.path.getsize(path))
        except Exception as e:  # noqa: BLE001
            return (cid, kind, f"fail:{e}", 0)

    ok = failed = missing = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(work, j): j for j in jobs}
        done = 0
        for fut in as_completed(futures):
            done += 1
            cid, kind, status, size = fut.result()
            if status == "ok":
                ok += 1
                normal_missing.pop(str(cid), None)
            elif status == "missing":
                missing += 1
                if kind == "trained":
                    trained_missing.add(cid)
                else:
                    normal_missing[str(cid)] = now_ms
                    logger.info("卡面缩略图暂无资源（14 天后重试）：card %s", cid)
            else:
                failed += 1
                logger.error("缩略图下载失败：card %s %s -> %s", cid, kind, status)
            if done % 100 == 0:
                logger.info("进度 %d/%d", done, len(jobs))

    state["trained_missing"] = sorted(trained_missing)
    state["normal_missing"] = normal_missing
    return ok, skipped, failed, missing


# ---------------------------------------------------------------- 主流程
def main():
    limit = None
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        limit = int(sys.argv[1])

    started = time.time()
    state = load_state()
    logger.info("=== 闪耀色彩卡面抓取开始（第 %d 次运行，shinycolors.moe）===",
                state.get("runs", 0) + 1)

    # 1. 偶像名单
    try:
        idols = fetch_json(API_BASE + API_IDOL_LIST)
    except Exception as e:  # noqa: BLE001
        logger.error("偶像名单拉取失败：%s", e)
        logger.error("本次抓取中止（致命）。")
        return 1
    logger.info("偶像名单 OK：%d 位", len(idols))

    # 2. 逐偶像详情（内含 cardLists 全量卡面）
    idols_detail = []
    for entry in idols:
        n = entry.get("idolId")
        try:
            idols_detail.append(fetch_json(API_BASE + API_IDOL_INFO.format(n=n)))
            logger.info("idolInfo %s（%s）OK", n, entry.get("idolName"))
        except Exception as e:  # noqa: BLE001
            logger.error("idolInfo %s 拉取失败：%s", n, e)
    if not idols_detail:
        logger.error("全部 idolInfo 拉取失败，本次中止（致命）。")
        return 1

    # 3. index 重建 + 萌百对照自检
    index, unit_warn = build_index(idols_detail)
    for w in unit_warn:
        logger.warning("人物-团体对照异常：%s", w)
    idx_path = os.path.join(DB_DIR, "index.json")
    tmp = idx_path + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"updatedAt": int(time.time() * 1000), "cards": index}, f,
                  ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, idx_path)
    logger.info("索引已写入 data/shinycolors（共 %d 张卡）", len(index))

    # 4. 详情预爬（分批）
    fetch_details(index, limit=DETAIL_BATCH)

    # 5. 增量缩略图
    ok, skipped, failed, missing = scrape_thumbs(index, state, limit=limit)

    # 6. 状态落盘
    state["runs"] = state.get("runs", 0) + 1
    state["last_run"] = datetime.now(timezone(timedelta(hours=8))).isoformat()
    state["last_result"] = "ok" if failed == 0 else "partial"
    state["counts"] = {"downloaded": ok, "skipped": skipped, "failed": failed,
                       "trained_missing": missing}
    save_state(state)

    elapsed = time.time() - started
    logger.info("=== 闪耀色彩抓取结束：新下载 %d，跳过 %d，失败 %d，突破缺图 %d，耗时 %.1fs ===",
                ok, skipped, failed, missing, elapsed)
    if failed > 0:
        return 2
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
