# -*- coding: utf-8 -*-
"""
闪耀色彩（Shiny Colors）卡面爬虫 v3 —— 数据源 shinycolors.moe 公开 API
修复与强化：
  - 修复原版 _make_opener 代理地址缺失 "http://127.0.0.1:" 导致代理回退彻底失效的 Bug
  - 接入公共底座：三通路粘性探测、熔断器、离线降级、Magic Bytes 验真、指数退避 RetryQueue
  - 保留萌娘百科人物-团体对照自检与双服统一时间字段
退出码：0=成功  1=致命失败  2=部分失败
"""
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from scraper.common.image import shrink_to_webp  # noqa: E402
from scraper.common.logging_setup import setup_logger  # noqa: E402
from scraper.common.net import NotFoundError, fetch_bytes, fetch_json  # noqa: E402
from scraper.common.paths import DATA_DIR, TZ_CN, atomic_write_json, now_bj, now_ms  # noqa: E402
from scraper.common.resilience import (  # noqa: E402
    CircuitBreaker,
    RetryQueue,
    load_state,
    save_state,
    try_offline_fallback,
)

DB_DIR = os.path.join(DATA_DIR, "shinycolors")
THUMB_DIR = os.path.join(DATA_DIR, "thumbs_shinycolors")
STATE_PATH = os.path.join(DB_DIR, "state.json")
RETRY_PATH = os.path.join(DB_DIR, "retry.json")

API_BASE = "https://api.shinycolors.moe"
API_IDOL_LIST = "/info/idolList"
API_IDOL_INFO = "/info/idolInfo?idolId={n}"
ART_BASE = "https://cf-static.shinycolors.moe/images/content/{dir}/card/{enza}.jpg"
FES_BASE = "https://cf-static.shinycolors.moe/images/content/{dir}/fes_card/{enza}.jpg"
DIR_P = "idols"
DIR_S = "support_idols"

WORKERS = 4
THUMB_MAX_H = 240
DETAIL_BATCH = 400

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

logger = setup_logger("shinycolors_scrape", "shinycolors_scrape.log")


def build_index(idols):
    index = []
    unit_warn = []
    current_ms = now_ms()
    for idol in idols:
        idol_id = idol.get("idolId")
        idol_name = idol.get("idolName") or ""
        unit = idol.get("unit") or {}
        unit_name = unit.get("unitName") or ""
        expect = EXPECTED_UNIT.get(idol_name)
        if expect and unit_name != expect:
            unit_warn.append(f"{idol_name}: API={unit_name} 萌百={expect}")
        for c in idol.get("cardLists") or []:
            cid = c.get("cardIndex")
            enza = c.get("enzaId")
            if cid is None or not enza:
                continue
            card_type = c.get("cardType") or ""
            kind = "P" if card_type.startswith("P") else "S"
            rarity = card_type.split("_")[-1] if "_" in card_type else card_type
            rel = c.get("releaseDate")
            release_ms = 0
            if rel:
                try:
                    release_ms = int(datetime.strptime(rel, "%Y-%m-%d").replace(tzinfo=TZ_CN).timestamp() * 1000)
                except ValueError:
                    release_ms = 0
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
                "releaseJp": release_ms,
                "releaseCn": 0,
                "spoiler": release_ms > current_ms,
                "getMethod": c.get("getMethod") or "",
                "thumbNormal": f"thumbs_shinycolors/{cid}_normal.webp",
                "thumbTrained": f"thumbs_shinycolors/{cid}_trained.webp" if trainable else None,
            })
    index.sort(key=lambda c: c["id"], reverse=True)
    return index, unit_warn


def fetch_details(index, limit=DETAIL_BATCH):
    todo = [c for c in index if not os.path.isfile(os.path.join(DB_DIR, f"card_{c['id']}.json"))]
    if limit:
        todo = todo[: int(limit)]
    logger.info("需要预爬详情 %d 张（已有缓存 %d 张）", len(todo), len(index) - len(todo))
    ok = fail = 0
    breaker = CircuitBreaker(threshold=6)
    for i, c in enumerate(todo, 1):
        if breaker.is_open:
            logger.warning("详情预爬连续异常触发熔断，跳过剩余 %d 张", len(todo) - i + 1)
            break
        uuid = c.get("cardUuid")
        if not uuid:
            continue
        ep = "/info/pCardInfo?cardId=" if c["cardKind"] == "P" else "/info/sCardInfo?cardId="
        cache = os.path.join(DB_DIR, f"card_{c['id']}.json")
        try:
            raw = fetch_json(API_BASE + ep + uuid, timeout=60)
            atomic_write_json(cache, raw)
            ok += 1
            breaker.record_success()
        except NotFoundError:
            atomic_write_json(cache, {"cardIndex": c["id"], "notFound": True})
            ok += 1
            breaker.record_success()
        except Exception as exc:  # noqa: BLE001
            fail += 1
            breaker.record_failure()
            logger.warning("详情预爬失败 card %s：%s", c["id"], exc)
        if i % 100 == 0:
            logger.info("详情预爬进度 %d/%d（成功 %d）", i, len(todo), ok)
        time.sleep(0.3)
    logger.info("详情预爬完成：成功 %d 失败 %d", ok, fail)
    return ok, fail


def scrape_thumbs(index, state, retry_q, limit=None):
    os.makedirs(THUMB_DIR, exist_ok=True)
    trained_missing = set(state.get("trained_missing", []))
    current_ms = now_ms()
    breaker = CircuitBreaker(threshold=10)

    jobs = []
    for card in index:
        cid = card["id"]
        enza = card.get("enzaId")
        if not enza:
            continue
        d = DIR_P if card["cardKind"] == "P" else DIR_S
        normal_path = os.path.join(THUMB_DIR, f"{cid}_normal.webp")
        if not (os.path.isfile(normal_path) and os.path.getsize(normal_path) > 0):
            if retry_q.is_due(f"{cid}:normal", current_ms):
                jobs.append((cid, "normal", normal_path, ART_BASE.format(dir=d, enza=enza)))
        if card["trainable"] and cid not in trained_missing:
            trained_path = os.path.join(THUMB_DIR, f"{cid}_trained.webp")
            if not (os.path.isfile(trained_path) and os.path.getsize(trained_path) > 0):
                if retry_q.is_due(f"{cid}:trained", current_ms):
                    jobs.append((cid, "trained", trained_path, FES_BASE.format(dir=d, enza=enza)))

    if limit:
        jobs = jobs[: int(limit)]

    total_slots = len(index) + sum(1 for c in index if c["trainable"])
    skipped = max(0, total_slots - len(jobs))
    logger.info("需要下载缩略图 %d 张（已存在或冷却跳过 %d 张）", len(jobs), skipped)
    if not jobs:
        return 0, skipped, 0, 0

    def work(job):
        cid, kind, path, url = job
        if breaker.is_open:
            return cid, kind, "circuit_open", ""
        try:
            data = fetch_bytes(url, timeout=60, expect_image=True)
            breaker.record_success()
        except NotFoundError:
            breaker.record_success()
            return cid, kind, "missing", "404"
        except Exception as exc:  # noqa: BLE001
            breaker.record_failure()
            return cid, kind, "fail", str(exc)
        try:
            shrink_to_webp(data, path, max_h=THUMB_MAX_H, quality=80)
            return cid, kind, "ok", ""
        except Exception as exc:  # noqa: BLE001
            return cid, kind, "fail", str(exc)

    ok = failed = missing = circuit_skipped = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(work, j): j for j in jobs}
        done = 0
        for fut in as_completed(futures):
            done += 1
            cid, kind, status, detail = fut.result()
            key = f"{cid}:{kind}"
            if status == "ok":
                ok += 1
                retry_q.record_success(key)
            elif status == "missing":
                missing += 1
                if kind == "trained":
                    trained_missing.add(cid)
                    retry_q.record_success(key)
                else:
                    retry_q.record_failure(key, "404", kind="missing", current_ms=current_ms)
            elif status == "circuit_open":
                circuit_skipped += 1
            else:
                failed += 1
                retry_q.record_failure(key, detail, kind="network", current_ms=current_ms)
                logger.error("缩略图下载失败：card %s %s -> %s", cid, kind, detail)
            if done % 100 == 0:
                logger.info("进度 %d/%d", done, len(jobs))

    if circuit_skipped:
        logger.warning("图床连续异常触发熔断，跳过剩余 %d 张", circuit_skipped)
        failed += circuit_skipped
    state["trained_missing"] = sorted(trained_missing)
    return ok, skipped, failed, missing


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else None
    os.makedirs(DB_DIR, exist_ok=True)
    os.makedirs(THUMB_DIR, exist_ok=True)

    started = time.time()
    started_iso = now_bj().isoformat()
    state = load_state(STATE_PATH)
    retry_q = RetryQueue(RETRY_PATH)
    logger.info("=== 闪耀色彩卡面抓取开始（第 %d 次运行，shinycolors.moe）===", state.get("runs", 0) + 1)

    try:
        idols = fetch_json(API_BASE + API_IDOL_LIST, timeout=90)
    except Exception as exc:  # noqa: BLE001
        if try_offline_fallback(
            os.path.join(DB_DIR, "index.json"),
            STATE_PATH,
            logger,
            started_iso,
            exc,
            prev_state=state,
        ):
            return 0
        return 1
    logger.info("偶像名单 OK：%d 位", len(idols))

    idols_detail = []
    breaker = CircuitBreaker(threshold=6)
    for entry in idols:
        if breaker.is_open:
            logger.warning("idolInfo 连续失败触发熔断")
            break
        n = entry.get("idolId")
        try:
            idols_detail.append(fetch_json(API_BASE + API_IDOL_INFO.format(n=n), timeout=60))
            breaker.record_success()
            logger.info("idolInfo %s（%s）OK", n, entry.get("idolName"))
        except Exception as exc:  # noqa: BLE001
            breaker.record_failure()
            logger.error("idolInfo %s 拉取失败：%s", n, exc)

    if not idols_detail:
        if try_offline_fallback(
            os.path.join(DB_DIR, "index.json"),
            STATE_PATH,
            logger,
            started_iso,
            "全部 idolInfo 拉取失败",
            prev_state=state,
        ):
            return 0
        return 1

    index, unit_warn = build_index(idols_detail)
    for w in unit_warn:
        logger.warning("人物-团体对照异常：%s", w)
    atomic_write_json(
        os.path.join(DB_DIR, "index.json"),
        {"updatedAt": now_ms(), "cards": index},
        separators=(",", ":"),
    )
    logger.info("索引已写入 data/shinycolors（共 %d 张卡）", len(index))

    fetch_details(index, limit=DETAIL_BATCH)
    ok, skipped, failed, missing = scrape_thumbs(index, state, retry_q, limit=limit)
    retry_q.save()

    state["runs"] = int(state.get("runs") or 0) + 1
    state["last_run"] = started_iso
    state["last_result"] = "ok" if failed == 0 else "partial"
    state["counts"] = {
        "downloaded": ok,
        "skipped": skipped,
        "failed": failed,
        "trained_missing": missing,
        "retry_pending": retry_q.count(),
    }
    save_state(state)

    logger.info(
        "=== 闪耀色彩抓取结束：新下载 %d，跳过 %d，失败 %d，突破缺图 %d，耗时 %.1fs ===",
        ok,
        skipped,
        failed,
        missing,
        time.time() - started,
    )
    return 2 if failed > 0 else 0


if __name__ == "__main__":
    if sys.stdout:
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
