# -*- coding: utf-8 -*-
"""
BanG Dream! Our Notes 卡面爬虫 v3 —— 数据源 bdon.moe（Moenotes）
修复与强化：
  - 修复原版 enrich_support_meta 调用 fetch_bytes 被 text/html 拦截导致 100% 熔断的 Bug（改传 allow_html=True）！
  - 修复详情重拉失败时未从本地已有 {kind}_{id}.json 回填 releaseDate/releaseAt 导致上线时间被清零的问题
  - 共用 scraper.common.onotes_md 解析器（与服务端单一真源）
  - 保留判定分层（支援卡元数据补全失败不触发 partial）、熔断器、离线降级、标准退出码 0/1/2
"""
import json
import os
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from scraper.common.logging_setup import setup_logger  # noqa: E402
from scraper.common.net import NotFoundError, download_image_to, fetch_bytes  # noqa: E402
from scraper.common.onotes_md import (  # noqa: E402
    SUPPORT_RARITY_MAP,
    detail_to_card_fields,
    parse_detail_md,
    parse_index_tables,
    parse_support_meta_html,
    strip_front_matter,
)
from scraper.common.paths import (  # noqa: E402
    DATA_DIR,
    atomic_write_json,
    now_bj,
    now_ms,
    read_json_optional,
)
from scraper.common.resilience import (  # noqa: E402
    CircuitBreaker,
    RetryQueue,
    load_state,
    save_state,
    try_offline_fallback,
)

DB_DIR = os.path.join(DATA_DIR, "onotes")
THUMB_DIR = os.path.join(DATA_DIR, "thumbs_onotes")
STATE_PATH = os.path.join(DB_DIR, "state.json")
RETRY_PATH = os.path.join(DB_DIR, "retry.json")

SITE = "https://bdon.moe"
MD_CARDS = SITE + "/cards.md"
MD_SUPPORT = SITE + "/support-cards.md"
MD_CHARS = SITE + "/characters.md"
MD_CARD_DETAIL = SITE + "/cards/{id}.md"
MD_SUPPORT_DETAIL = SITE + "/support-cards/{id}.md"
SUPPORT_PAGE = SITE + "/en/support-cards/{id}"

ASSET_BASE = "https://assets.bdon.moe/zh-Hans"
ASSET_MEMBER_THUMB = ASSET_BASE + "/MemberCard/{id}/member_thumbnail/member_thumbnail.webp"
ASSET_SUPPORT_THUMB = ASSET_BASE + "/SupportCard/{id}/snap_thumbnail/snap_thumbnail.webp"

POLITE_DELAY = 0.25
DETAIL_DELAY = 0.3

log = setup_logger("onotes_scrape", "onotes_scrape.log")


def build_index():
    log.info("拉取三张索引表 …")
    cards_body = fetch_bytes(MD_CARDS, timeout=60).decode("utf-8", "replace")
    time.sleep(POLITE_DELAY)
    support_body = fetch_bytes(MD_SUPPORT, timeout=60).decode("utf-8", "replace")
    time.sleep(POLITE_DELAY)
    chars_body = fetch_bytes(MD_CHARS, timeout=60).decode("utf-8", "replace")
    fm, _ = strip_front_matter(cards_body)
    fm2, _ = strip_front_matter(support_body)
    cards, chars, dv = parse_index_tables(fm, cards_body, support_body, chars_body)
    return cards, chars, dv or fm2.get("data_version", "")


def scrape_thumbs(cards, retry_q, limit=0):
    os.makedirs(THUMB_DIR, exist_ok=True)
    counts = {"downloaded": 0, "skipped": 0, "failed": 0}
    current_ms = now_ms()
    breaker = CircuitBreaker(threshold=6)

    todo = []
    for c in cards:
        fname = f"{c['id']}_{c['cardKind']}.webp"
        path = os.path.join(THUMB_DIR, fname)
        if os.path.isfile(path) and os.path.getsize(path) > 0:
            counts["skipped"] += 1
            continue
        if not retry_q.is_due(f"{c['cardKind']}:{c['id']}:thumb", current_ms):
            counts["skipped"] += 1
            continue
        todo.append((c, path))

    if limit:
        todo = todo[:limit]

    for c, path in todo:
        key = f"{c['cardKind']}:{c['id']}:thumb"
        if breaker.is_open:
            counts["failed"] += 1
            continue
        tmpl = ASSET_MEMBER_THUMB if c["cardKind"] == "card" else ASSET_SUPPORT_THUMB
        try:
            size = download_image_to(path, tmpl.format(id=c["id"]), timeout=60)
            counts["downloaded"] += 1
            retry_q.record_success(key)
            breaker.record_success()
            log.info("缩略图 %s/%s ✓（%.1f KB）", c["id"], c["cardKind"], size / 1024)
        except NotFoundError:
            counts["failed"] += 1
            retry_q.record_failure(key, "404", kind="missing", current_ms=current_ms)
            breaker.record_success()
            log.warning("缩略图 404：%s/%s", c["id"], c["cardKind"])
        except Exception as exc:  # noqa: BLE001
            counts["failed"] += 1
            retry_q.record_failure(key, str(exc), kind="network", current_ms=current_ms)
            breaker.record_failure()
            log.warning("缩略图失败：%s/%s -> %s", c["id"], c["cardKind"], exc)
        time.sleep(POLITE_DELAY)
    return counts


def fetch_details(cards, retry_q, limit=0):
    """每轮全量校准详情（上线时间/技能变更），仅内容变更时写盘；
    若某张详情网络失败但本地已有旧缓存，回填旧缓存的 releaseDate/releaseAt 不清零。"""
    os.makedirs(DB_DIR, exist_ok=True)
    counts = {"cached": 0, "skipped": 0, "failed": 0}
    breaker = CircuitBreaker(threshold=6)
    todo = list(cards)
    if limit:
        todo = todo[:limit]

    for c in todo:
        kind = c["cardKind"]
        cache = os.path.join(DB_DIR, f"{kind}_{c['id']}.json")
        old_obj = read_json_optional(cache)
        if breaker.is_open:
            if old_obj:
                cf = detail_to_card_fields(old_obj)
                c["releaseDate"], c["releaseAt"] = cf["releaseDate"], cf["releaseAt"]
                c["releaseJp"] = cf["releaseAt"]
                counts["skipped"] += 1
            else:
                counts["failed"] += 1
            continue

        url = (MD_CARD_DETAIL if kind == "card" else MD_SUPPORT_DETAIL).format(id=c["id"])
        try:
            d = parse_detail_md(fetch_bytes(url, timeout=60).decode("utf-8", "replace"), kind=kind)
            cf = detail_to_card_fields(d)
            c["releaseDate"], c["releaseAt"] = cf["releaseDate"], cf["releaseAt"]
            c["releaseJp"] = cf["releaseAt"]
            payload = json.dumps(d, ensure_ascii=False, sort_keys=True)
            old_payload = json.dumps(old_obj, ensure_ascii=False, sort_keys=True) if old_obj else None
            if payload != old_payload:
                atomic_write_json(cache, d)
                counts["cached"] += 1
                log.info("详情 %s/%s 已校准（技能 %d 条）", c["id"], kind, len(d["skills"]))
            else:
                counts["skipped"] += 1
            retry_q.record_success(f"{kind}:{c['id']}:detail")
            breaker.record_success()
        except Exception as exc:  # noqa: BLE001
            counts["failed"] += 1
            breaker.record_failure()
            retry_q.record_failure(f"{kind}:{c['id']}:detail", str(exc), kind="network")
            if old_obj:
                cf = detail_to_card_fields(old_obj)
                c["releaseDate"], c["releaseAt"] = cf["releaseDate"], cf["releaseAt"]
                c["releaseJp"] = cf["releaseAt"]
            log.warning("详情失败：%s/%s -> %s", c["id"], kind, exc)
        time.sleep(DETAIL_DELAY)
    return counts


def enrich_support_meta(cards):
    """支援卡稀有度/属性补全（可自愈增量增强，不参与 partial 判定）。
    修复：显式传 allow_html=True，避免 HTML 详情页被误判为 SPA 假壳导致 100% 熔断！"""
    counts = {"ok": 0, "cached": 0, "failed": 0, "skipped": 0}
    breaker = CircuitBreaker(threshold=3)
    for c in cards:
        if c["cardKind"] != "support":
            continue
        cache = os.path.join(DB_DIR, f"support_meta_{c['id']}.json")
        meta = read_json_optional(cache)
        if meta is not None:
            counts["cached"] += 1
        elif breaker.is_open:
            counts["skipped"] += 1
            raw_r = c.get("rawRarity") or c.get("rarity")
            meta = {"rarity": SUPPORT_RARITY_MAP.get(str(raw_r), c["rarity"]), "attr": None}
        else:
            try:
                html = fetch_bytes(SUPPORT_PAGE.format(id=c["id"]), timeout=45, allow_html=True).decode(
                    "utf-8", "replace"
                )
                meta = parse_support_meta_html(html, fallback_rarity=c.get("rawRarity") or c.get("rarity"))
                atomic_write_json(cache, meta)
                counts["ok"] += 1
                breaker.record_success()
                log.info("支援卡元数据 %s：%s / %s", c["id"], meta["rarity"], meta["attr"])
            except Exception as exc:  # noqa: BLE001
                counts["failed"] += 1
                breaker.record_failure()
                if not breaker.is_open:
                    log.warning("支援卡元数据失败：%s -> %s", c["id"], exc)
                raw_r = c.get("rawRarity") or c.get("rarity")
                meta = {"rarity": SUPPORT_RARITY_MAP.get(str(raw_r), c["rarity"]), "attr": None}
            time.sleep(DETAIL_DELAY)

        if meta:
            c["rarity"] = meta.get("rarity") or c["rarity"]
            c["attr"] = meta.get("attr") or ""
    if counts["skipped"]:
        log.warning("支援卡元数据熔断跳过 %d 张（下次运行自愈）", counts["skipped"])
    return counts


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 0
    os.makedirs(DB_DIR, exist_ok=True)
    os.makedirs(THUMB_DIR, exist_ok=True)

    started = now_bj()
    started_iso = started.isoformat()
    state = load_state(STATE_PATH)
    retry_q = RetryQueue(RETRY_PATH)
    log.info("=== Our Notes 卡面抓取开始（limit=%s）===", limit or "全量")

    try:
        cards, chars, data_version = build_index()
    except Exception as exc:  # noqa: BLE001
        if try_offline_fallback(
            os.path.join(DB_DIR, "index.json"),
            STATE_PATH,
            log,
            started_iso,
            exc,
            prev_state=state,
        ):
            return 0
        return 1

    log.info("索引：角色卡+支援卡 %d 张，角色 %d 人（data_version=%s）", len(cards), len(chars), data_version[:40])

    meta_counts = enrich_support_meta(cards)
    thumb_counts = scrape_thumbs(cards, retry_q, limit=limit)
    detail_counts = fetch_details(cards, retry_q, limit=0)
    retry_q.save()

    index = {
        "updatedAt": int(started.timestamp() * 1000),
        "dataVersion": data_version,
        "site": SITE,
        "characters": chars,
        "cards": cards,
    }
    atomic_write_json(os.path.join(DB_DIR, "index.json"), index)

    counts = {
        "downloaded": thumb_counts["downloaded"],
        "skipped": thumb_counts["skipped"],
        "failed": thumb_counts["failed"],
        "details_cached": detail_counts["cached"],
        "details_failed": detail_counts["failed"],
        "support_meta": meta_counts["ok"],
        "support_meta_cached": meta_counts["cached"],
        "support_meta_skipped": meta_counts["skipped"],
        "retry_pending": retry_q.count(),
    }
    # 判定分层：仅缩略图与详情核心失败计入 partial
    ok = counts["failed"] == 0 and counts["details_failed"] == 0
    state["runs"] = int(state.get("runs") or 0) + 1
    state["last_run"] = started_iso
    state["last_result"] = "ok" if ok else "partial"
    state["counts"] = counts
    save_state(state)
    log.info("=== 抓取结束：%s ===", counts)
    return 0 if ok else 2


if __name__ == "__main__":
    if sys.stdout:
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
