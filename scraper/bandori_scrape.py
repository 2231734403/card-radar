# -*- coding: utf-8 -*-
"""
邦多利（BanG Dream!）卡面爬虫 v3 —— 数据源 bestdori.com 公开 API
修复与强化：
  - 修复原版 status == "missing" 不匹配 "missing:..." 导致全部 404 被误算为失败且永不入缺图表的问题！
  - 接入公共底座：三通路代理回退 + Magic Bytes 防 SPA 壳 + 熔断器 + 离线降级 + 指数退避 RetryQueue
  - 保留 jp → cn（bilibili 特有卡）→ en 三区域回退与日服/国服双服上线时间
退出码：0=成功  1=致命失败  2=部分失败
"""
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from scraper.common.image import shrink_to_webp  # noqa: E402
from scraper.common.logging_setup import setup_logger  # noqa: E402
from scraper.common.net import NotFoundError, fetch_bytes, fetch_json  # noqa: E402
from scraper.common.paths import DATA_DIR, atomic_write_json, now_bj, now_ms  # noqa: E402
from scraper.common.resilience import (  # noqa: E402
    CircuitBreaker,
    RetryQueue,
    load_state,
    save_state,
    try_offline_fallback,
)

DB_DIR = os.path.join(DATA_DIR, "bandori")
THUMB_DIR = os.path.join(DATA_DIR, "thumbs_bandori")
STATE_PATH = os.path.join(DB_DIR, "state.json")
RETRY_PATH = os.path.join(DB_DIR, "retry.json")

API_CARDS = "https://bestdori.com/api/cards/all.5.json"
API_CHARS = "https://bestdori.com/api/characters/main.2.json"
API_BANDS = "https://bestdori.com/api/bands/main.1.json"
API_SKILLS = "https://bestdori.com/api/skills/all.10.json"
ART_BASE = "https://bestdori.com/assets/{region}/characters/resourceset/{res}_rip/{file}"
REGIONS = ("jp", "cn", "en")

WORKERS = 4
THUMB_MAX_H = 240
TRAINABLE_MIN_RARITY = 4

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

logger = setup_logger("bandori_scrape", "bandori_scrape.log")


def build_index(cards, chars, bands=None):
    band_names = {}
    for bid, b in (bands or {}).items():
        nm = (b.get("bandName") or [None])[0:4]
        zh = (nm[3] or nm[0]) if len(nm) >= 4 else (nm[0] if nm else None)
        if zh:
            try:
                band_names[int(bid)] = zh
            except ValueError:
                pass

    index = []
    for cid_s, v in cards.items():
        cid = int(cid_s)
        prefixes = v.get("prefix") or []
        prefix = (prefixes[3] or prefixes[0] or "") if len(prefixes) >= 4 else (prefixes[0] if prefixes else "")
        rel = v.get("releasedAt") or []
        release_jp = int(rel[0]) if len(rel) > 0 and rel[0] else 0
        release_cn = int(rel[3]) if len(rel) > 3 and rel[3] else 0
        release_at = release_cn or release_jp
        char = chars.get(str(v.get("characterId"))) or {}
        char_names = char.get("characterName") or []
        char_name = (char_names[3] or char_names[0] or "") if len(char_names) >= 4 else (char_names[0] if char_names else "")
        band_id = char.get("bandId")
        unit = (
            band_names.get(band_id)
            or BAND_NAMES.get(band_id)
            or (SPECIAL_UNIT if char.get("characterType") != "band" else f"乐队 {band_id}")
        )
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
            "thumbNormal": f"thumbs_bandori/{cid}_normal.webp",
            "thumbTrained": f"thumbs_bandori/{cid}_trained.webp" if trainable else None,
        })
    index.sort(key=lambda c: c["id"], reverse=True)
    return index


def fetch_details(index, limit=400):
    todo = [c["id"] for c in index if not os.path.isfile(os.path.join(DB_DIR, f"card_{c['id']}.json"))]
    if limit:
        todo = todo[: int(limit)]
    logger.info("需要预爬详情 %d 张（已覆盖 %d/%d）", len(todo), len(index) - len(todo), len(index))
    if not todo:
        return 0, 0

    ok = skip404 = fail = 0
    breaker = CircuitBreaker(threshold=6)
    for i, cid in enumerate(todo, 1):
        if breaker.is_open:
            logger.warning("详情预爬连续异常触发熔断，跳过剩余 %d 张（不阻塞缩略图抓取）", len(todo) - i + 1)
            break
        try:
            raw = fetch_json(f"https://bestdori.com/api/cards/{cid}.json", timeout=45)
            atomic_write_json(os.path.join(DB_DIR, f"card_{cid}.json"), raw)
            ok += 1
            breaker.record_success()
        except NotFoundError:
            skip404 += 1
            breaker.record_success()
        except Exception as exc:  # noqa: BLE001
            fail += 1
            breaker.record_failure()
            logger.warning("详情预爬失败 card %s：%s", cid, exc)
        if i % 200 == 0:
            logger.info("详情预爬进度 %d/%d（成功 %d）", i, len(todo), ok)
        time.sleep(0.4)
    logger.info("详情预爬完成：成功 %d，无详情 404 %d，失败 %d", ok, skip404, fail)
    return ok, skip404


def scrape_thumbs(index, state, retry_q, limit=None):
    os.makedirs(THUMB_DIR, exist_ok=True)
    trained_missing = set(state.get("trained_missing", []))
    current_ms = now_ms()
    breaker = CircuitBreaker(threshold=10)

    jobs = []
    for card in index:
        cid = card["id"]
        res = card.get("assetbundleName")
        if not res:
            continue
        normal_path = os.path.join(THUMB_DIR, f"{cid}_normal.webp")
        if not (os.path.isfile(normal_path) and os.path.getsize(normal_path) > 0):
            if retry_q.is_due(f"{cid}:normal", current_ms):
                jobs.append((cid, "normal", normal_path, res))
        if card["trainable"] and cid not in trained_missing:
            trained_path = os.path.join(THUMB_DIR, f"{cid}_trained.webp")
            if not (os.path.isfile(trained_path) and os.path.getsize(trained_path) > 0):
                if retry_q.is_due(f"{cid}:trained", current_ms):
                    jobs.append((cid, "trained", trained_path, res))

    if limit:
        jobs = jobs[: int(limit)]

    total_slots = len(index) + sum(1 for c in index if c["trainable"])
    skipped = max(0, total_slots - len(jobs))
    logger.info("需要下载缩略图 %d 张（已存在或冷却跳过 %d 张）", len(jobs), skipped)
    if not jobs:
        return 0, skipped, 0, 0

    def work(job):
        cid, kind, path, res = job
        if breaker.is_open:
            return cid, kind, "circuit_open", ""
        fname = "card_after_training.png" if kind == "trained" else "card_normal.png"
        data = None
        all_not_found = True
        last_err = ""
        for region in REGIONS:
            url = ART_BASE.format(region=region, res=res, file=fname)
            try:
                data = fetch_bytes(url, timeout=60, expect_image=True)
                breaker.record_success()
                break
            except NotFoundError:
                last_err = f"{region} 无资源"
                continue
            except Exception as exc:  # noqa: BLE001
                all_not_found = False
                last_err = f"{region}: {exc}"
                continue

        if data is None:
            if all_not_found:
                breaker.record_success()
                return cid, kind, "missing", last_err
            breaker.record_failure()
            return cid, kind, "fail", last_err
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
                    retry_q.record_failure(key, detail or "404", kind="missing", current_ms=current_ms)
                    logger.info("卡面缩略图暂无资源（指数退避重试）：card %s", cid)
            elif status == "circuit_open":
                circuit_skipped += 1
            else:
                failed += 1
                retry_q.record_failure(key, detail, kind="network", current_ms=current_ms)
                logger.error("缩略图下载失败：card %s %s -> %s", cid, kind, detail)
            if done % 100 == 0:
                logger.info("进度 %d/%d", done, len(jobs))

    if circuit_skipped:
        logger.warning("bestdori 限流/断连触发熔断，跳过剩余 %d 张", circuit_skipped)
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
    logger.info("=== 邦多利卡面抓取开始（第 %d 次运行，bestdori）===", state.get("runs", 0) + 1)

    try:
        cards = fetch_json(API_CARDS, timeout=90)
        chars = fetch_json(API_CHARS, timeout=90)
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
    logger.info("bestdori 数据 OK：cards=%d characters=%d", len(cards), len(chars))

    bands = None
    try:
        bands = fetch_json(API_BANDS, timeout=60)
        atomic_write_json(os.path.join(DB_DIR, "bands.json"), bands)
        logger.info("乐队数据 OK：%d 支乐队", len(bands))
    except Exception as exc:  # noqa: BLE001
        logger.warning("乐队数据拉取失败（使用内置乐队表）：%s", exc)

    index = build_index(cards, chars, bands)
    atomic_write_json(
        os.path.join(DB_DIR, "index.json"),
        {"updatedAt": now_ms(), "cards": index},
        separators=(",", ":"),
    )
    logger.info("索引已写入 data/bandori（共 %d 张卡）", len(index))

    try:
        sk = fetch_json(API_SKILLS, timeout=60)
        atomic_write_json(os.path.join(DB_DIR, "skills_all.json"), sk)
        logger.info("技能数据 OK：%d 个技能", len(sk))
    except Exception as exc:  # noqa: BLE001
        logger.warning("技能数据拉取失败（保留旧文件）：%s", exc)

    fetch_details(index, limit=400)
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
        "=== 邦多利抓取结束：新下载 %d，跳过 %d，失败 %d，缺图 %d，耗时 %.1fs ===",
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
