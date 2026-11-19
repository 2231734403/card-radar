# -*- coding: utf-8 -*-
"""
Pjsk 卡牌雷达 —— 增量爬虫 v2（JP 服务器）
数据来源：pjsk.moe 官网自身使用的公开数据源
  - 主数据：metadata.pjsk.moe/jp/master（JP 最新）+ metadata.exmeaning.com 备源
  - 中文显示：translation.exmeaning.com/files/translation（日文原文→中文覆盖层，
    新卡未翻译时回退日文原文）
  - 图片：storage.pjsk.moe/sekai-jp-assets（备源 storage.exmeaning.com）
行为：
  1. 每次运行重新拉取主数据 JSON（主备源竞速，先完成者胜）
  2. 卡面缩略图只下载低清 webp；磁盘上已存在的直接跳过（增量）
  3. 原图（PNG）不在本脚本职责内 —— 由本地网站服务器在用户点击下载时按需抓取
  4. 全部输出写入 <项目根>/data，绝不写到别处
退出码：0=成功  1=致命失败（主数据/网络）  2=部分失败（个别卡面下载失败）
"""
import ctypes
import gc
import json
import logging
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from ctypes import wintypes
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta

# ---------------------------------------------------------------- 常量配置
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
DB_DIR = os.path.join(DATA_DIR, "db")
THUMB_DIR = os.path.join(DATA_DIR, "thumbs")
COSTUME_THUMB_DIR = os.path.join(DATA_DIR, "thumbs_costume")
ORIGINAL_DIR = os.path.join(DATA_DIR, "originals")
LOG_DIR = os.path.join(DATA_DIR, "logs")
STATE_PATH = os.path.join(DATA_DIR, "state.json")

# JP 服务器（最新资源）；主备竞速，先完成者胜
META_SOURCES = [
    ("主源", "https://metadata.pjsk.moe/jp/master"),
    ("备源", "https://metadata.exmeaning.com/jp/master"),
]
TR_BASE = "https://translation.exmeaning.com/files/translation"
STORAGE_MAIN = "https://storage.pjsk.moe/sekai-jp-assets"
STORAGE_BACKUP = "https://storage.exmeaning.com/sekai-jp-assets"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
TIMEOUT = 30
WORKERS = 4  # 缩略图并发限速（8→4：降低抓取启动期的内存/带宽/连接占用）

# 训练前后（突破前后）缩略图仅 3/4 星卡存在
TRAINABLE_RARITY = {"rarity_3", "rarity_4"}

UNIT_NAMES = {
    "light_sound": "Leo/need",
    "idol": "MORE MORE JUMP!",
    "street": "Vivid BAD SQUAD",
    "theme_park": "Wonderlands×Showtime",
    "school_refusal": "25时，Nightcord见。",
    "piapro": "虚拟歌手",
}

# 26 名角色中文名（JP 数据角色名为日文/片假名，虚拟歌手必须映射）
CHAR_ZH = {
    1: "星乃一歌", 2: "天马咲希", 3: "望月穗波", 4: "日野森志步",
    5: "花里实乃理", 6: "桐谷遥", 7: "桃井爱莉", 8: "日野森雫",
    9: "小豆泽心羽", 10: "白石杏", 11: "东云彰人", 12: "青柳冬弥",
    13: "天马司", 14: "凤笑梦", 15: "草薙宁宁", 16: "神代类",
    17: "宵崎奏", 18: "朝比奈真冬", 19: "东云绘名", 20: "晓山瑞希",
    21: "初音未来", 22: "镜音铃", 23: "镜音连", 24: "巡音流歌",
    25: "MEIKO", 26: "KAITO",
}

META_FILES = ["cards.json", "skills.json", "gameCharacters.json",
              "gameCharacterUnits.json", "moe_costume.json", "cardEpisodes.json"]
TR_FILES = ["cards.json", "skills.json", "costumes.json"]

META_BUDGET = 300  # JP cards.json 约 13MB，备源 150KB/s 时需 ~90s，预算放宽


class NotFoundError(Exception):
    """资源不存在（HTTP 404）。"""


class _RacerCancelled(Exception):
    """竞速败者的正常退出路径。"""


# ---------------------------------------------------------------- 日志
os.makedirs(DB_DIR, exist_ok=True)
os.makedirs(THUMB_DIR, exist_ok=True)
os.makedirs(COSTUME_THUMB_DIR, exist_ok=True)
os.makedirs(ORIGINAL_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

logger = logging.getLogger("scrape")
logger.setLevel(logging.INFO)
_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
_fh = logging.FileHandler(os.path.join(LOG_DIR, "scrape.log"), encoding="utf-8")
_fh.setFormatter(_fmt)
logger.addHandler(_fh)
_sh = logging.StreamHandler(sys.stdout)
_sh.setFormatter(_fmt)
logger.addHandler(_sh)


# ---------------------------------------------------------------- 网络工具
def _safe_unlink(path):
    """尽力删除临时文件（竞速败者清理用）。"""
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def _racer_worker(url, path, result, cancel, lock, budget, timeout):
    """竞速线程：流式把响应写进自己的临时文件（内存只驻留一个 128KB chunk，
    不再把整个响应堆在内存里）。先完成者登记胜出并通知对手取消；
    败者（取消/超时/异常）自行清理临时文件。"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            t0 = time.time()
            with open(path, "wb") as f:
                while True:
                    if cancel.is_set():
                        raise _RacerCancelled()
                    chunk = r.read(131072)
                    if not chunk:
                        break
                    f.write(chunk)
                    if time.time() - t0 > budget:
                        raise TimeoutError(
                            f"{budget}s 预算耗尽（已收 {os.path.getsize(path) // 1024}KB）")
        with lock:
            if result["path"] is None:
                result["path"] = path
                result["url"] = url
                cancel.set()  # 通知对手中止
    except _RacerCancelled:
        _safe_unlink(path)
    except Exception as e:  # noqa: BLE001
        _safe_unlink(path)
        with lock:
            if result["path"] is None and result["err"] is None:
                result["err"] = f"{url} -> {e}"


def race_download(urls, out_path, budget=25, timeout=TIMEOUT):
    """多源并发竞速 GET，流式落盘限内存：每路写自己的临时文件，
    先完成者胜、败者自动清理。返回 (winner_path, winner_url)。"""
    result = {"path": None, "url": None, "err": None}
    cancel = threading.Event()
    lock = threading.Lock()
    tmp_paths = [f"{out_path}.r{i}.part" for i in range(len(urls))]
    threads = [threading.Thread(target=_racer_worker,
                                args=(u, tp, result, cancel, lock, budget, timeout))
               for u, tp in zip(urls, tmp_paths)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    if result["path"] is None:
        raise ConnectionError(result["err"] or "全部源失败")
    for tp in tmp_paths:
        if tp != result["path"]:
            _safe_unlink(tp)  # 败者在胜者判定后才异常的极小窗口兜底
    return result["path"], result["url"]


def fetch_json_race(name, budget=META_BUDGET):
    """竞速下载主数据 JSON 并直接留档 data/db/{name}（原始字节流式落盘，
    全程不把大响应驻留内存）。返回落档路径；解析由调用方按需进行。"""
    final = os.path.join(DB_DIR, name)
    path, winner = race_download([f"{b}/{name}" for _, b in META_SOURCES],
                                 out_path=final, budget=budget)
    os.replace(path, final)
    tag = next((t for t, b in META_SOURCES if b == winner), winner)
    logger.info("主数据 %s：来自%s（%.0f KB）", name, tag, os.path.getsize(final) / 1024)
    return final


def fetch_translation():
    """拉取中文覆盖层（日文原文→中文）。失败时回退日文原文。"""
    tr = {}
    for name in TR_FILES:
        try:
            tr[name] = json.loads(fetch(f"{TR_BASE}/{name}"))
        except Exception as e:  # noqa: BLE001
            logger.warning("翻译层拉取失败 %s：%s（相关字段回退日文原文）", name, e)
            tr[name] = {}
    return tr


def fetch(url, timeout=TIMEOUT, retries=0):
    """单源 GET。404 抛 NotFoundError，其余异常直接抛出。"""
    last_err = None
    for attempt in range(1, max(retries, 1) + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise NotFoundError(url) from e
            last_err = e
        except Exception as e:  # noqa: BLE001
            last_err = e
        if attempt < max(retries, 1):
            wait = 2 ** attempt
            logger.warning("重试 %d/%d（%ds 后）：%s", attempt, retries, wait, url)
            time.sleep(wait)
    raise ConnectionError(f"{url} -> {last_err}")


def download_to(path, url, timeout=TIMEOUT):
    """下载文件到指定路径（原子写入）。返回 bytes 大小。"""
    data = fetch(url, timeout=timeout)
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)
    return len(data)


def apply_zh(meta, tr):
    """用翻译覆盖层（日文原文→中文）合并主数据；未翻译的字段保留日文。"""
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
    logger.info("翻译合并：卡名 zh %d/%d，服装 zh %d",
                zh_names, len(meta["cards.json"]), zh_cos)


# ---------------------------------------------------------------- 状态
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


# ---------------------------------------------------------------- 索引
def build_index(cards, characters, gcus, costumes):
    """把主数据拼成网站用的轻量索引（角色名用 CHAR_ZH 中文表）。"""
    now_ms = int(time.time() * 1000)
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
            "releaseAt": card.get("releaseAt", 0),
            "spoiler": (card.get("releaseAt") or 0) > now_ms,
            "assetbundleName": card.get("assetbundleName"),
            "thumbNormal": os.path.join("thumbs", f"{cid}_normal.webp").replace("\\", "/"),
            "thumbTrained": (os.path.join("thumbs", f"{cid}_trained.webp").replace("\\", "/")
                             if trainable else None),
            "costumes": costumes_by_card.get(cid, []),
        })
    index.sort(key=lambda c: c["id"], reverse=True)
    return index


# ---------------------------------------------------------------- 缩略图
MISSING_RETRY_MS = 14 * 86400 * 1000  # 未上架资源的 404：14 天后自动重试


def scrape_thumbs(index, state):
    """增量下载低清缩略图。返回 (成功数, 跳过数, 失败数, 新缺失数)。"""
    trained_missing = set(state.get("trained_missing", []))
    normal_missing = state.get("normal_missing", {})  # {str(id): 记录时间 ms}
    now_ms = int(time.time() * 1000)

    def pending_retry(cid, table):
        ts = table.get(str(cid))
        return ts is not None and now_ms - ts < MISSING_RETRY_MS

    jobs = []

    for card in index:
        cid = card["id"]
        abn = card["assetbundleName"]
        if not abn:
            continue
        normal_path = os.path.join(THUMB_DIR, f"{cid}_normal.webp")
        if (not (os.path.exists(normal_path) and os.path.getsize(normal_path) > 0)
                and not pending_retry(cid, normal_missing)):
            jobs.append((cid, "normal", normal_path,
                         f"{STORAGE_MAIN}/thumbnail/chara/{abn}_normal.webp"))
        if card["trainable"] and cid not in trained_missing:
            trained_path = os.path.join(THUMB_DIR, f"{cid}_trained.webp")
            if not (os.path.exists(trained_path) and os.path.getsize(trained_path) > 0):
                jobs.append((cid, "trained", trained_path,
                             f"{STORAGE_MAIN}/thumbnail/chara/{abn}_after_training.webp"))

    ok = skipped = failed = missing = 0
    total_slots = len(index) + sum(1 for c in index if c["trainable"])
    skipped = total_slots - len(jobs) + sum(1 for cid in normal_missing if pending_retry(cid, normal_missing) and os.path.exists(os.path.join(THUMB_DIR, f"{cid}_normal.webp")) is False)
    logger.info("需要下载缩略图 %d 张（已存在跳过 %d 张）", len(jobs), skipped)
    if not jobs:
        return 0, skipped, 0, 0

    def work(job):
        cid, kind, path, url = job
        # 主源快试（10s），失败切备源；404 视为「该图不存在」（源内容全局一致）
        backup_url = url.replace(STORAGE_MAIN, STORAGE_BACKUP, 1)
        try:
            size = download_to(path, url, timeout=10)
            return (cid, kind, "ok", size)
        except NotFoundError:
            return (cid, kind, "missing", 0)
        except Exception:  # noqa: BLE001 — 主源限速/不通，切备源
            try:
                size = download_to(path, backup_url, timeout=30)
                return (cid, kind, "ok", size)
            except NotFoundError:
                return (cid, kind, "missing", 0)
            except Exception as e:  # noqa: BLE001
                return (cid, kind, f"fail:{e}", 0)

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(work, j): j for j in jobs}
        done = 0
        for fut in as_completed(futures):
            done += 1
            cid, kind, status, size = fut.result()
            if status == "ok":
                ok += 1
                if kind == "normal":
                    normal_missing.pop(str(cid), None)  # 资源上架，移除缺失记录
            elif status == "missing":
                missing += 1
                if kind == "trained":
                    trained_missing.add(cid)
                else:
                    # 未上架新卡的 404：记忆 14 天后自动重试，不算失败、不触发弹窗
                    normal_missing[str(cid)] = now_ms
                    logger.info("卡面缩略图暂未上架（14 天后重试）：card %s", cid)
            else:
                failed += 1
                logger.error("缩略图下载失败：card %s %s -> %s", cid, kind, status)
            if done % 100 == 0:
                logger.info("进度 %d/%d", done, len(jobs))

    # 404 缺失的 trained 也算「已处理」，下次跳过
    state["trained_missing"] = sorted(trained_missing)
    state["normal_missing"] = normal_missing
    return ok, skipped, failed, missing


# ---------------------------------------------------------------- 主流程
class _PMC(ctypes.Structure):
    """GetProcessMemoryInfo 的 PROCESS_MEMORY_COUNTERS 结构。"""
    _fields_ = [("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t)]


def _peak_rss_mb():
    """进程峰值物理内存 MB（PeakWorkingSetSize），仅供日志观测限内存效果。
    ⚠️ 64 位 Python 必须显式声明 HANDLE/argtypes——否则伪句柄 -1 被按 32 位
    c_int 零扩展成无效句柄（ERROR_INVALID_HANDLE），API 恒失败返回 0。"""
    try:
        pmc = _PMC()
        pmc.cb = ctypes.sizeof(_PMC)
        get_proc = ctypes.windll.kernel32.GetCurrentProcess
        get_proc.restype = wintypes.HANDLE
        k32 = ctypes.windll.kernel32.K32GetProcessMemoryInfo
        k32.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PMC), wintypes.DWORD]
        k32.restype = wintypes.BOOL
        if k32(get_proc(), ctypes.byref(pmc), pmc.cb):
            return pmc.PeakWorkingSetSize / 1048576
    except Exception:  # noqa: BLE001 — 非 Windows / 权限问题时不阻塞抓取
        pass
    return 0.0


def main():
    started = time.time()
    state = load_state()
    logger.info("=== Pjsk 卡牌雷达 抓取开始（第 %d 次运行，JP 服务器）===",
                state.get("runs", 0) + 1)

    # 1. 主数据（主备源竞速、流式落盘限内存）。cardEpisodes.json 只留档不解析
    #    （详情接口直接读文件）；其余逐文件解析——任何时刻只有一个大 JSON 在解析
    meta = {}
    for name in META_FILES:
        try:
            path = fetch_json_race(name)
        except Exception as e:  # noqa: BLE001
            logger.error("主数据拉取失败：%s -> %s", name, e)
            logger.error("本次抓取中止（致命）。")
            return 1
        if name == "cardEpisodes.json":
            meta[name] = None
        else:
            with open(path, encoding="utf-8") as f:
                meta[name] = json.load(f)
    logger.info("主数据 OK：cards=%d skills=%d characters=%d costumes=%d episodes=%.0fKB",
                len(meta["cards.json"]), len(meta["skills.json"]),
                len(meta["gameCharacters.json"]),
                len(meta["moe_costume.json"].get("costumes", [])),
                os.path.getsize(os.path.join(DB_DIR, "cardEpisodes.json")) / 1024)

    # 2. 中文翻译合并（日文原文→中文，未翻译回退日文）
    tr = fetch_translation()
    apply_zh(meta, tr)

    # 3. 重建索引
    index = build_index(meta["cards.json"], meta["gameCharacters.json"],
                        meta["gameCharacterUnits.json"], meta["moe_costume.json"])
    idx_path = os.path.join(DB_DIR, "index.json")
    tmp = idx_path + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"updatedAt": int(time.time() * 1000), "cards": index}, f,
                  ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, idx_path)
    # 处理过的主数据留档（服装/剧情等详情接口要用）；episodes 已在下载阶段直接留档
    for name, obj in meta.items():
        if obj is None:
            continue
        p = os.path.join(DB_DIR, name)
        t = p + ".part"
        with open(t, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(t, p)
    logger.info("索引与主数据已写入 data/db（共 %d 张卡，JP 服务器）", len(index))
    # 释放全量主数据对象再进缩略图阶段，削掉抓取期内存峰值
    meta.clear()
    gc.collect()
    logger.info("主数据内存已释放（进程峰值内存 %.0f MB）", _peak_rss_mb())

    # 4. 增量下载缩略图
    ok, skipped, failed, missing = scrape_thumbs(index, state)

    # 5. 状态落盘
    state["runs"] = state.get("runs", 0) + 1
    state["last_run"] = datetime.now(timezone(timedelta(hours=8))).isoformat()
    state["last_result"] = "ok" if failed == 0 else "partial"
    state["counts"] = {"downloaded": ok, "skipped": skipped, "failed": failed,
                       "trained_missing": missing}
    save_state(state)

    elapsed = time.time() - started
    logger.info("=== 抓取结束：新下载 %d，跳过 %d，失败 %d，特训缺图 %d，耗时 %.1fs ===",
                ok, skipped, failed, missing, elapsed)

    if failed > 0:
        return 2
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
