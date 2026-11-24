# -*- coding: utf-8 -*-
"""
Pjsk 卡牌雷达 —— 增量爬虫 v3（JP 服务器 · 接入公共韧性底座）
数据来源：pjsk.moe 公开接口（主备源竞速）+ translation.exmeaning.com 中文覆盖层。
强化项：
  - 接入 scraper.common：三通路回退、Magic Bytes 图片验真、熔断器、离线降级
  - 显式 RetryQueue（data/db/retry.json + 指数退避）
  - 统一双服时间字段（releaseJp / releaseAt）
退出码：0=成功（含离线降级）  1=致命失败（首跑无缓存且拉取失败）  2=部分失败
"""
import gc
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from scraper.common.logging_setup import peak_rss_mb, setup_logger  # noqa: E402
from scraper.common.net import (  # noqa: E402
    NotFoundError,
    download_image_to,
    fetch_bytes,
    race_download,
)
from scraper.common.paths import DATA_DIR, atomic_write_json, now_bj, now_ms  # noqa: E402
from scraper.common.resilience import (  # noqa: E402
    CircuitBreaker,
    RetryQueue,
    load_state,
    save_state,
    try_offline_fallback,
)

DB_DIR = os.path.join(DATA_DIR, "db")
THUMB_DIR = os.path.join(DATA_DIR, "thumbs")
COSTUME_THUMB_DIR = os.path.join(DATA_DIR, "thumbs_costume")
ORIGINAL_DIR = os.path.join(DATA_DIR, "originals")
STATE_PATH = os.path.join(DATA_DIR, "state.json")
RETRY_PATH = os.path.join(DB_DIR, "retry.json")

META_SOURCES = [
    ("主源", "https://metadata.pjsk.moe/jp/master"),
    ("备源", "https://metadata.exmeaning.com/jp/master"),
]
TR_BASE = "https://translation.exmeaning.com/files/translation"
STORAGE_MAIN = "https://storage.pjsk.moe/sekai-jp-assets"
STORAGE_BACKUP = "https://storage.exmeaning.com/sekai-jp-assets"

WORKERS = 4
META_BUDGET = 300
TRAINABLE_RARITY = {"rarity_3", "rarity_4"}

UNIT_NAMES = {
    "light_sound": "Leo/need",
    "idol": "MORE MORE JUMP!",
    "street": "Vivid BAD SQUAD",
    "theme_park": "Wonderlands×Showtime",
    "school_refusal": "25时，Nightcord见。",
    "piapro": "虚拟歌手",
}

CHAR_ZH = {
    1: "星乃一歌", 2: "天马咲希", 3: "望月穗波", 4: "日野森志步",
    5: "花里实乃理", 6: "桐谷遥", 7: "桃井爱莉", 8: "日野森雫",
    9: "小豆泽心羽", 10: "白石杏", 11: "东云彰人", 12: "青柳冬弥",
    13: "天马司", 14: "凤笑梦", 15: "草薙宁宁", 16: "神代类",
    17: "宵崎奏", 18: "朝比奈真冬", 19: "东云绘名", 20: "晓山瑞希",
    21: "初音未来", 22: "镜音铃", 23: "镜音连", 24: "巡音流歌",
    25: "MEIKO", 26: "KAITO",
}

META_FILES = [
    "cards.json",
    "skills.json",
    "gameCharacters.json",
    "gameCharacterUnits.json",
    "moe_costume.json",
    "cardEpisodes.json",
]
TR_FILES = ["cards.json", "skills.json", "costumes.json"]

logger = setup_logger("scrape", "scrape.log")


def fetch_json_race(name, budget=META_BUDGET):
    final = os.path.join(DB_DIR, name)
    path, winner = race_download(
        [f"{b}/{name}" for _, b in META_SOURCES],
        out_path=final,
        budget=budget,
    )
    os.replace(path, final)
    tag = next((t for t, b in META_SOURCES if winner.startswith(b)), winner)
    logger.info("主数据 %s：来自%s（%.0f KB）", name, tag, os.path.getsize(final) / 1024)
    return final


def fetch_translation():
    tr = {}
    for name in TR_FILES:
        try:
            tr[name] = json.loads(fetch_bytes(f"{TR_BASE}/{name}", timeout=30).decode("utf-8", "replace"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("翻译层拉取失败 %s：%s（相关字段回退日文原文）", name, exc)
            tr[name] = {}
    return tr


def apply_zh(meta, tr):
    tc = tr.get("cards.json", {})
    pmap = tc.get("prefix", {})
    smap = tc.get("skillName", {})
    zh_names = 0
    for card in meta["cards.json"]:
        p = card.get("prefix")
        if p in pmap:
            card["prefix"] = pmap[p]
            zh_names += 1
        s = card.get("cardSkillName")
        if s in smap:
            card["cardSkillName"] = smap[s]
    dmap = tr.get("skills.json", {}).get("description", {})
    for s in meta["skills.json"]:
        d = s.get("description")
        if d in dmap:
            s["description"] = dmap[d]
    cmeta = meta["moe_costume.json"]
    nmap = tr.get("costumes.json", {}).get("name", {})
    dmap2 = tr.get("costumes.json", {}).get("designer", {})
    zh_cos = 0
    for cos in cmeta.get("costumes", []):
        n = cos.get("name")
        if n in nmap:
            cos["name"] = nmap[n]
            zh_cos += 1
        d = cos.get("designer")
        if d in dmap2 and dmap2[d]:
            cos["designer"] = dmap2[d]
    logger.info("翻译合并：卡名 zh %d/%d，服装 zh %d", zh_names, len(meta["cards.json"]), zh_cos)


def build_index(cards, characters, gcus, costumes):
    current_ms = now_ms()
    gcu_by_id = {}
    for e in gcus:
        gcu_by_id.setdefault(e["gameCharacterId"], e)
    costumes_by_card = {}
    for cos in costumes.get("costumes", []):
        for cid in cos.get("cardIds") or []:
            costumes_by_card.setdefault(cid, []).append({
                "costumeNumber": cos.get("costumeNumber"),
                "name": cos.get("name"),
                "source": cos.get("source"),
                "partTypes": cos.get("partTypes"),
                "designer": cos.get("designer"),
                "gender": cos.get("gender"),
                "bodyAsset": ((cos.get("parts") or {}).get("body") or [{}])[0].get("assetbundleName"),
            })

    rarity_num = {"rarity_1": 1, "rarity_2": 2, "rarity_3": 3, "rarity_4": 4, "rarity_birthday": 2}
    index = []
    for card in cards:
        cid = card["id"]
        rarity_type = card.get("cardRarityType", "rarity_1")
        gcu = gcu_by_id.get(card.get("characterId"), {})
        unit = gcu.get("unit") or "piapro"
        zh_name = CHAR_ZH.get(card.get("characterId"), "")
        trainable = rarity_type in TRAINABLE_RARITY
        rel_at = card.get("releaseAt") or 0
        index.append({
            "id": cid,
            "seq": card.get("seq"),
            "prefix": card.get("prefix", ""),
            "characterId": card.get("characterId"),
            "characterName": zh_name.split()[-1] if zh_name else "",
            "characterFullName": zh_name,
            "unit": unit,
            "unitName": UNIT_NAMES.get(unit, unit),
            "attr": card.get("attr"),
            "rarity": rarity_num.get(rarity_type, 1),
            "rarityType": rarity_type,
            "trainable": trainable,
            "skillId": card.get("skillId"),
            "skillName": card.get("cardSkillName", ""),
            "releaseAt": rel_at,
            "releaseJp": rel_at,
            "releaseCn": 0,
            "spoiler": rel_at > current_ms,
            "assetbundleName": card.get("assetbundleName"),
            "thumbNormal": f"thumbs/{cid}_normal.webp",
            "thumbTrained": f"thumbs/{cid}_trained.webp" if trainable else None,
            "costumes": costumes_by_card.get(cid, []),
        })
    index.sort(key=lambda c: c["id"], reverse=True)
    return index


def scrape_thumbs(index, state, retry_q, limit=None):
    os.makedirs(THUMB_DIR, exist_ok=True)
    trained_missing = set(state.get("trained_missing", []))
    current_ms = now_ms()
    breaker = CircuitBreaker(threshold=8)

    jobs = []
    for card in index:
        cid = card["id"]
        abn = card.get("assetbundleName")
        if not abn:
            continue
        normal_path = os.path.join(THUMB_DIR, f"{cid}_normal.webp")
        if not (os.path.isfile(normal_path) and os.path.getsize(normal_path) > 0):
            if retry_q.is_due(f"{cid}:normal", current_ms):
                jobs.append((cid, "normal", normal_path, f"{STORAGE_MAIN}/thumbnail/chara/{abn}_normal.webp"))
        if card["trainable"] and cid not in trained_missing:
            trained_path = os.path.join(THUMB_DIR, f"{cid}_trained.webp")
            if not (os.path.isfile(trained_path) and os.path.getsize(trained_path) > 0):
                if retry_q.is_due(f"{cid}:trained", current_ms):
                    jobs.append((
                        cid,
                        "trained",
                        trained_path,
                        f"{STORAGE_MAIN}/thumbnail/chara/{abn}_after_training.webp",
                    ))

    if limit:
        jobs = jobs[: int(limit)]

    total_slots = len(index) + sum(1 for c in index if c["trainable"])
    skipped = max(0, total_slots - len(jobs))
    logger.info("需要下载缩略图 %d 张（已存在或冷却中跳过 %d 张）", len(jobs), skipped)
    if not jobs:
        return 0, skipped, 0, 0

    def work(job):
        cid, kind, path, url = job
        if breaker.is_open:
            return cid, kind, "circuit_open", 0
        backup_url = url.replace(STORAGE_MAIN, STORAGE_BACKUP, 1)
        try:
            size = download_image_to(path, url, timeout=12)
            breaker.record_success()
            return cid, kind, "ok", size
        except NotFoundError:
            breaker.record_success()
            return cid, kind, "missing", 0
        except Exception:  # noqa: BLE001
            try:
                size = download_image_to(path, backup_url, timeout=30)
                breaker.record_success()
                return cid, kind, "ok", size
            except NotFoundError:
                breaker.record_success()
                return cid, kind, "missing", 0
            except Exception as exc:  # noqa: BLE001
                breaker.record_failure()
                return cid, kind, f"fail:{exc}", 0

    ok = failed = missing = circuit_skipped = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(work, j): j for j in jobs}
        done = 0
        for fut in as_completed(futures):
            done += 1
            cid, kind, status, _size = fut.result()
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
                    retry_q.record_failure(key, "404 暂未上架", kind="missing", current_ms=current_ms)
            elif status == "circuit_open":
                circuit_skipped += 1
            else:
                failed += 1
                retry_q.record_failure(key, status, kind="network", current_ms=current_ms)
                logger.error("缩略图下载失败：card %s %s -> %s", cid, kind, status)
            if done % 100 == 0:
                logger.info("进度 %d/%d", done, len(jobs))

    if circuit_skipped:
        logger.warning("网络连续异常触发熔断，跳过剩余 %d 张（下次运行自愈）", circuit_skipped)
        failed += circuit_skipped
    state["trained_missing"] = sorted(trained_missing)
    return ok, skipped, failed, missing


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else None
    os.makedirs(DB_DIR, exist_ok=True)
    os.makedirs(THUMB_DIR, exist_ok=True)
    os.makedirs(COSTUME_THUMB_DIR, exist_ok=True)
    os.makedirs(ORIGINAL_DIR, exist_ok=True)

    started = time.time()
    started_iso = now_bj().isoformat()
    state = load_state(STATE_PATH)
    retry_q = RetryQueue(RETRY_PATH)
    logger.info("=== Pjsk 卡牌雷达 抓取开始（第 %d 次运行，JP 服务器）===", state.get("runs", 0) + 1)

    meta = {}
    for name in META_FILES:
        try:
            path = fetch_json_race(name)
        except Exception as exc:  # noqa: BLE001
            if try_offline_fallback(
                os.path.join(DB_DIR, "index.json"),
                STATE_PATH,
                logger,
                started_iso,
                f"{name}: {exc}",
                prev_state=state,
            ):
                return 0
            return 1
        if name == "cardEpisodes.json":
            meta[name] = None
        else:
            with open(path, encoding="utf-8") as f:
                meta[name] = json.load(f)

    logger.info(
        "主数据 OK：cards=%d skills=%d characters=%d costumes=%d episodes=%.0fKB",
        len(meta["cards.json"]),
        len(meta["skills.json"]),
        len(meta["gameCharacters.json"]),
        len(meta["moe_costume.json"].get("costumes", [])),
        os.path.getsize(os.path.join(DB_DIR, "cardEpisodes.json")) / 1024,
    )

    tr = fetch_translation()
    apply_zh(meta, tr)

    index = build_index(
        meta["cards.json"],
        meta["gameCharacters.json"],
        meta["gameCharacterUnits.json"],
        meta["moe_costume.json"],
    )
    atomic_write_json(
        os.path.join(DB_DIR, "index.json"),
        {"updatedAt": now_ms(), "cards": index},
        separators=(",", ":"),
    )
    for name, obj in meta.items():
        if obj is None:
            continue
        atomic_write_json(os.path.join(DB_DIR, name), obj, separators=(",", ":"))
    logger.info("索引与主数据已写入 data/db（共 %d 张卡）", len(index))

    meta.clear()
    gc.collect()
    logger.info("主数据内存已释放（进程峰值内存 %.0f MB）", peak_rss_mb())

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
        "=== 抓取结束：新下载 %d，跳过 %d，失败 %d，特训缺图 %d，耗时 %.1fs ===",
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
