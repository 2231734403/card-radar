# -*- coding: utf-8 -*-
"""
邦多利（BanG Dream!）卡面爬虫 —— 数据源 bestdori.com 公开 API
  - 列表：https://bestdori.com/api/cards/all.5.json（2500+ 张，prefix 自带简体中文）
  - 角色：https://bestdori.com/api/characters/main.2.json（多语言名 + bandId）
  - 卡面图：https://bestdori.com/assets/jp/characters/resourceset/{res}_rip/card_{normal|after_training}.png
行为（对齐 pjsk 模块的增量机制）：
  1. 每次运行重建 index（单请求全量，成本低）；index 结构与 pjsk 兼容（前端复用）
  2. 缩略图增量：磁盘已有跳过；下载 card_*.png 后本地缩为 webp（原图不驻留）
  3. 3 星以上探测「突破后」图，404 记入 trained_missing 永久跳过
  4. 未上架/暂无资源的 404 记 normal_missing，14 天后自动重试
  5. 原图（PNG）不在本脚本职责内 —— 由网站服务器按用户点击时抓取
输出全部写入 <项目根>/data（data/bandori、data/thumbs_bandori、data/logs）
退出码：0=成功  1=致命失败  2=部分失败
用法：py -X utf8 scraper/bandori_scrape.py [limit]   （limit：仅处理前 N 张待下载缩略，调试用）
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
DB_DIR = os.path.join(DATA_DIR, "bandori")
THUMB_DIR = os.path.join(DATA_DIR, "thumbs_bandori")
LOG_DIR = os.path.join(DATA_DIR, "logs")
STATE_PATH = os.path.join(DB_DIR, "state.json")

API_CARDS = "https://bestdori.com/api/cards/all.5.json"
API_CHARS = "https://bestdori.com/api/characters/main.2.json"
API_BANDS = "https://bestdori.com/api/bands/main.1.json"
API_SKILLS = "https://bestdori.com/api/skills/all.10.json"
ART_BASE = "https://bestdori.com/assets/{region}/characters/resourceset/{res}_rip/{file}"
REGION_MAIN = "jp"     # JP 服资产最全（与 pjsk 模块的 JP 策略一致）
REGION_FALLBACKS = ["cn", "en"]  # cn：bilibili 服特有卡在 cn 区域

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
WORKERS = 4
THUMB_MAX_H = 240  # 缩略图高度（低清预览，与 pjsk 缩略体量一致）
# 邦多利机制：3★ 训练后只加数值不换立绘，仅 4★/5★ 有突破后卡面图
TRAINABLE_MIN_RARITY = 4
MISSING_RETRY_MS = 14 * 86400 * 1000

# 邦多利乐队表：bandId → 乐队名。⚠️ bestdori 的 bandId 是游戏内乐队编号，
# 与直觉顺序完全不同（3=HHW、4=Pastel*Palettes、18=RAS、21=Morfonica、45=MyGO），
# 曾因想当然按 1-9 顺序填表导致乐队全部错位（大和麻弥被标成 Roselia）。
# 校准依据：main.2.json 全部 40 角色的 bandId 分组 + 官方阵容对照。
BAND_NAMES = {
    1: "Poppin'Party",
    2: "Afterglow",
    3: "Hello, Happy World!",
    4: "Pastel*Palettes",
    5: "Roselia",
    18: "RAISE A SUILEN",
    21: "Morfonica",
    45: "MyGO!!!!!",
}
SPECIAL_UNIT = "其他"

CTX = ssl.create_default_context()


class NotFoundError(Exception):
    """资源不存在（HTTP 404）。"""


# ---------------------------------------------------------------- 日志
os.makedirs(DB_DIR, exist_ok=True)
os.makedirs(THUMB_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

logger = logging.getLogger("bandori_scrape")
logger.setLevel(logging.INFO)
_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
_fh = logging.FileHandler(os.path.join(LOG_DIR, "bandori_scrape.log"), encoding="utf-8")
_fh.setFormatter(_fmt)
logger.addHandler(_fh)
_sh = logging.StreamHandler(sys.stdout)
_sh.setFormatter(_fmt)
logger.addHandler(_sh)


# ---------------------------------------------------------------- 网络工具
def fetch_bytes(url, timeout=60):
    """GET 原始字节；404 抛 NotFoundError；非 200/HTML 伪装响应视为失败。"""
    last = None
    for attempt in range(2):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
                data = r.read()
            ct = (r.headers.get("Content-Type") or "")
            if ct.startswith("text/html"):
                # bestdori 对未知路径回 SPA 壳 —— 视为 404
                raise NotFoundError(url)
            return data
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise NotFoundError(url) from e
            last = e
        except NotFoundError:
            raise
        except Exception as e:  # noqa: BLE001
            last = e
        if attempt == 0:
            time.sleep(2)
    raise ConnectionError(f"{url} -> {last}")


def fetch_json(url):
    return json.loads(fetch_bytes(url, timeout=90))


# ---------------------------------------------------------------- index 构建
def build_index(cards, chars, bands=None):
    """bestdori 数据 → pjsk 兼容 index（前端图鉴/详情/下载链路直接复用字段名）。
    bands：官方乐队名数据（bandId → bandName 多语言），优先于内置表。"""
    band_names = {}
    for bid, b in (bands or {}).items():
        nm = (b.get("bandName") or [None])[0:4]
        zh = (nm[3] or nm[0]) if len(nm) >= 4 else None
        if zh:
            try:
                band_names[int(bid)] = zh
            except ValueError:
                pass
    index = []
    for cid_s, v in cards.items():
        cid = int(cid_s)
        prefixes = v.get("prefix") or []
        # prefix 数组序：[日, 英, 繁, 简, 韩] —— 简体优先，回退日文
        prefix = (prefixes[3] or prefixes[0] or "") if len(prefixes) >= 4 else (prefixes[0] if prefixes else "")
        rel = v.get("releasedAt") or []
        # 数组序 [日服, 英服, 台服, 国服(简中), 韩服]——JP/CN 双服上线时间都要记录
        release_jp = int(rel[0]) if len(rel) > 0 and rel[0] else 0
        release_cn = int(rel[3]) if len(rel) > 3 and rel[3] else 0
        release_at = release_cn or release_jp  # 展示口径沿用：国服优先，回退日服
        char = chars.get(str(v.get("characterId"))) or {}
        char_names = char.get("characterName") or []
        char_name = (char_names[3] or char_names[0] or "") if len(char_names) >= 4 else ""
        band_id = char.get("bandId")
        unit = (band_names.get(band_id) or BAND_NAMES.get(band_id)
                or (SPECIAL_UNIT if char.get("characterType") != "band" else f"乐队 {band_id}"))
        rarity = int(v.get("rarity") or 1)
        trainable = rarity >= TRAINABLE_MIN_RARITY
        index.append({
            "id": cid,
            "seq": cid,
            "prefix": prefix,
            "characterId": v.get("characterId"),
            "characterName": char_name,
            "characterFullName": char_name,
            "unit": unit,
            "unitName": unit,
            "attr": v.get("attribute") or "",
            "rarity": rarity,
            "rarityType": f"rarity_{rarity}",
            "trainable": trainable,
            "skillId": v.get("skillId"),
            "skillName": "",
            "cardType": v.get("type") or "",
            "releaseAt": release_at,
            "releaseJp": release_jp,
            "releaseCn": release_cn,
            "assetbundleName": v.get("resourceSetName"),
            "thumbNormal": os.path.join("thumbs_bandori", f"{cid}_normal.webp").replace("\\", "/"),
            "thumbTrained": (os.path.join("thumbs_bandori", f"{cid}_trained.webp").replace("\\", "/")
                             if trainable else None),
        })
    index.sort(key=lambda c: c["id"], reverse=True)
    return index


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
def fetch_details(index, limit=None):
    """预爬单卡详情（skillName/episodes/stat 等）到 data/bandori/card_{id}.json：
    server 的详情接口命中缓存后秒回，前端详情页无需等待网络。
    增量：已有缓存的卡跳过（周更只拉新卡）。404 跳过（该卡无详情）。"""
    todo = [c["id"] for c in index
            if not os.path.exists(os.path.join(DB_DIR, f"card_{c['id']}.json"))]
    if limit:
        todo = todo[: int(limit)]
    logger.info("需要预爬详情 %d 张（本次限额内；详情缓存已覆盖 %d/%d）",
                len(todo), len(index) - len(todo), len(index))
    if not todo:
        return 0, 0

    ok = skip404 = fail = 0
    # 保守限速：bestdori 对连续请求限流（4 并发曾大量超时），单线程 + 0.4s 间隔
    for i, cid in enumerate(todo, 1):
        try:
            raw = fetch_json(f"https://bestdori.com/api/cards/{cid}.json")
            tmp = os.path.join(DB_DIR, f"card_{cid}.json.part")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(raw, f, ensure_ascii=False)
            os.replace(tmp, os.path.join(DB_DIR, f"card_{cid}.json"))
            ok += 1
        except NotFoundError:
            skip404 += 1
        except Exception as e:  # noqa: BLE001
            fail += 1
            logger.warning("详情预爬失败 card %s：%s（下次运行自动重试）", cid, e)
        if i % 200 == 0:
            logger.info("详情预爬进度 %d/%d（成功 %d）", i, len(todo), ok)
        time.sleep(0.4)
    logger.info("详情预爬完成：成功 %d，无详情 404 %d，失败 %d", ok, skip404, fail)
    return ok, skip404


# ---------------------------------------------------------------- 缩略图
def shrink_webp(src_bytes, dst_path):
    """下载到的 PNG → 低清 webp 缩略（原图字节不落盘，直进内存）。"""
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
    """增量下载缩略图（normal + trained 突破后）。返回 (成功, 跳过, 失败, 新缺失)。"""
    trained_missing = set(state.get("trained_missing", []))
    normal_missing = state.get("normal_missing", {})
    now_ms = int(time.time() * 1000)

    def pending_retry(cid):
        ts = normal_missing.get(str(cid))
        return ts is not None and now_ms - ts < MISSING_RETRY_MS

    jobs = []
    for card in index:
        cid = card["id"]
        res = card["assetbundleName"]
        if not res:
            continue
        normal_path = os.path.join(THUMB_DIR, f"{cid}_normal.webp")
        if (not (os.path.exists(normal_path) and os.path.getsize(normal_path) > 0)
                and not pending_retry(cid)):
            jobs.append((cid, "normal", normal_path, res))
        if card["trainable"] and cid not in trained_missing:
            trained_path = os.path.join(THUMB_DIR, f"{cid}_trained.webp")
            if not (os.path.exists(trained_path) and os.path.getsize(trained_path) > 0):
                jobs.append((cid, "trained", trained_path, res))

    if limit:
        jobs = jobs[: int(limit)]

    total_slots = len(index) + sum(1 for c in index if c["trainable"])
    skipped = total_slots - len(jobs)
    logger.info("需要下载缩略图 %d 张（已存在跳过 %d 张）", len(jobs), skipped)
    if not jobs:
        return 0, skipped, 0, 0

    def work(job):
        cid, kind, path, res = job
        # ⚠️ bestdori 的突破后文件名是 card_after_training.png（非 pjsk 式
        #    card_trained——曾因文件名错误全量 404）
        fname = "card_after_training.png" if kind == "trained" else "card_normal.png"
        # 区域回退链：JP（主）→ CN（bilibili 服特有卡在 cn 区域！）→ EN
        data = None
        last_err = None
        for region in [REGION_MAIN] + REGION_FALLBACKS:
            try:
                data = fetch_bytes(
                    ART_BASE.format(region=region, res=res, file=fname), timeout=60)
                break
            except NotFoundError:
                last_err = f"{region} 区域无此资源"
                continue
            except Exception as e:  # noqa: BLE001
                last_err = f"{region}: {e}"
                continue
        if data is None:
            return (cid, kind, f"missing:{last_err}", 0)
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
    logger.info("=== 邦多利卡面抓取开始（第 %d 次运行，bestdori JP 资产）===",
                state.get("runs", 0) + 1)

    # 1. 列表 + 角色 + 乐队（三次全量请求，成本低）
    try:
        cards = fetch_json(API_CARDS)
        chars = fetch_json(API_CHARS)
    except Exception as e:  # noqa: BLE001
        logger.error("bestdori 数据拉取失败：%s", e)
        logger.error("本次抓取中止（致命）。")
        return 1
    logger.info("bestdori 数据 OK：cards=%d characters=%d", len(cards), len(chars))

    # 1.5 乐队官方名（bandId → 简体乐队名，build_index 用它替代内置表；
    #     拉取失败时保留旧文件、回退 BAND_NAMES）
    bands = None
    try:
        bands = fetch_json(API_BANDS)
        tmp = os.path.join(DB_DIR, "bands.json.part")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(bands, f, ensure_ascii=False)
        os.replace(tmp, os.path.join(DB_DIR, "bands.json"))
        logger.info("乐队数据 OK：%d 支乐队", len(bands))
    except Exception as e:  # noqa: BLE001
        logger.warning("乐队数据拉取失败（使用内置乐队表）：%s", e)

    # 2. 重建 index（与 pjsk 字段兼容）
    index = build_index(cards, chars, bands)
    idx_path = os.path.join(DB_DIR, "index.json")
    tmp = idx_path + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"updatedAt": int(time.time() * 1000), "cards": index}, f,
                  ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, idx_path)
    logger.info("索引已写入 data/bandori（共 %d 张卡）", len(index))

    # 2.4 技能全量（含完整描述多语言 + duration；详情接口用它渲染技能块。
    #     拉取失败时保留旧文件、详情技能降级为技能名）
    try:
        sk = fetch_json(API_SKILLS)
        tmp = os.path.join(DB_DIR, "skills_all.json.part")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(sk, f, ensure_ascii=False)
        os.replace(tmp, os.path.join(DB_DIR, "skills_all.json"))
        logger.info("技能数据 OK：%d 个技能", len(sk))
    except Exception as e:  # noqa: BLE001
        logger.warning("技能数据拉取失败（技能描述降级为技能名）：%s", e)

    # 2.5 详情预爬（每次限 400 张分批补齐：bestdori API 限流严重，全量一次
    #     拉不完；未覆盖卡由 server 按需拉取缓存 + 前端两段渲染兜底，不阻塞体验）
    fetch_details(index, limit=400)

    # 3. 增量下载缩略图
    ok, skipped, failed, missing = scrape_thumbs(index, state, limit=limit)

    # 4. 状态落盘
    state["runs"] = state.get("runs", 0) + 1
    state["last_run"] = datetime.now(timezone(timedelta(hours=8))).isoformat()
    state["last_result"] = "ok" if failed == 0 else "partial"
    state["counts"] = {"downloaded": ok, "skipped": skipped, "failed": failed,
                       "trained_missing": missing}
    save_state(state)

    elapsed = time.time() - started
    logger.info("=== 邦多利抓取结束：新下载 %d，跳过 %d，失败 %d，特训缺图 %d，耗时 %.1fs ===",
                ok, skipped, failed, missing, elapsed)
    if failed > 0:
        return 2
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
