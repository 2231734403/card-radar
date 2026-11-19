# -*- coding: utf-8 -*-
"""
BanG Dream! Our Notes（バンドリ！ Our Notes）卡面爬虫 —— 数据源 bdon.moe（Moenotes）
  - 角色卡索引：https://bdon.moe/cards.md（81 卡，简体中文免翻译层）
  - 支援卡索引：https://bdon.moe/support-cards.md（85 张，稀有度 3/4/10）
  - 角色索引：https://bdon.moe/characters.md（26 人，含 Part/CV/生日）
  - 详情：任意页面 URL 加 .md 即 Markdown（ robots 全开放 + llms.txt 明示程序化访问）
  - 图源：https://assets.bdon.moe/zh-Hans/
      MemberCard/{id}/member_thumbnail/member_thumbnail.webp   （384×512 缩略）
      SupportCard/{id}/snap_thumbnail/snap_thumbnail.webp      （支援卡缩略）
      MemberCard/{id}/member_full/member_full.webp             （1440×1920 原图，下载时按需抓）
      SupportCard/{id}/snap_full/snap_full.webp                （支援卡原图）
每卡单立绘（分层设计，无特训后独立图），故只有 card/support 两类各一张。
网络层：三通路自动回退（直连 → 127.0.0.1:7890 → 7897）；本机直连即可达。
行为对齐 bandori/shinycolors 模块：index + 增量缩略 + 详情缓存 + state 记忆。
输出：data/onotes（index.json / card_{id}.json / state.json）+ data/thumbs_onotes。
用法：py -X utf8 scraper/onotes_scrape.py [limit]  （limit：仅前 N 张待下载缩略）
"""
import json
import logging
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta

# ---------------------------------------------------------------- 常量配置
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
DB_DIR = os.path.join(DATA_DIR, "onotes")
THUMB_DIR = os.path.join(DATA_DIR, "thumbs_onotes")
LOG_DIR = os.path.join(DATA_DIR, "logs")
STATE_PATH = os.path.join(DB_DIR, "state.json")

SITE = "https://bdon.moe"
MD_CARDS = SITE + "/cards.md"
MD_SUPPORT = SITE + "/support-cards.md"
MD_CHARS = SITE + "/characters.md"
MD_CARD_DETAIL = SITE + "/cards/{id}.md"
MD_SUPPORT_DETAIL = SITE + "/support-cards/{id}.md"

ASSET_BASE = "https://assets.bdon.moe/zh-Hans"
ASSET_MEMBER_THUMB = ASSET_BASE + "/MemberCard/{id}/member_thumbnail/member_thumbnail.webp"
ASSET_SUPPORT_THUMB = ASSET_BASE + "/SupportCard/{id}/snap_thumbnail/snap_thumbnail.webp"

# 支援卡的「稀有度」在 md 表格里是游戏内部档位编号，官方页显示名不同：
#   2=R、3=SR、4=SSR、10=特殊（乐团全员纪念卡，RarityIcon_EX）
SUPPORT_RARITY_MAP = {"2": "R", "3": "SR", "4": "SSR", "10": "特殊"}
# 支援卡属性同样不在 md 里，从 HTML 页的 RarityIcon 附近提取
ATTR_WORDS = ("Red", "Blue", "Green", "Yellow", "Purple")
SUPPORT_PAGE = "https://bdon.moe/en/support-cards/{id}"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
POLITE_DELAY = 0.25  # 静态站礼貌间隔
DETAIL_DELAY = 0.3

log_path = os.path.join(LOG_DIR, "onotes_scrape.log")
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(log_path, encoding="utf-8"),
              logging.StreamHandler()])
log = logging.getLogger("onotes_scrape")

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


class NotFoundError(Exception):
    pass


def make_opener(tag="direct"):
    """三通路 opener：direct → 127.0.0.1:7890 → 7897。"""
    handlers = [urllib.request.HTTPSHandler(context=CTX)]
    if tag == "proxy1":
        handlers.append(urllib.request.ProxyHandler(
            {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"}))
    elif tag == "proxy2":
        handlers.append(urllib.request.ProxyHandler(
            {"http": "http://127.0.0.1:7897", "https": "http://127.0.0.1:7897"}))
    return urllib.request.build_opener(*handlers)


def fetch_bytes(url, timeout=60, limit=3):
    """带三通路回退的 GET；404 抛 NotFoundError，其他错误重试后抛 ConnectionError。"""
    last = None
    for tag in ("direct", "proxy1", "proxy2")[:limit]:
        opener = make_opener(tag)
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with opener.open(req, timeout=timeout) as r:
                ct = r.headers.get("Content-Type") or ""
                data = r.read()
            if ct.startswith("text/html"):
                raise ConnectionError(f"{url} -> 异常 HTML 壳")
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


# ---------------------------------------------------------------- Markdown 解析
def strip_front_matter(text):
    """返回 (frontmatter dict, 正文)。front matter 用宽松 key: value 解析。"""
    fm = {}
    body = text
    m = re.match(r"\s*---\s*\n(.*?)\n---\s*\n", text, re.S)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                fm[k.strip()] = v.strip().strip('"')
        body = text[m.end():]
    return fm, body


def table_rows(body, header_keyword=None):
    """抓 Markdown 表格行（list[list[cell]]，去掉表头分隔行）。
    header_keyword：出现该词的表才收录（None = 第一张表）。"""
    rows = []
    for line in body.splitlines():
        s = line.strip()
        if s.startswith("|") and s.endswith("|"):
            rows.append([c.strip() for c in s.strip("|").split("|")])
    if header_keyword is not None:
        for i, r in enumerate(rows):
            if any(header_keyword in c for c in r):
                rows = rows[i:]
                break
    out = []
    for r in rows:
        if all(set(c) <= set("-: ") for c in r):  # 分隔行 | --- | --- |
            continue
        out.append(r)
    return out


def link_id(cell):
    """[文本](/characters/11.md) -> (文本, 11)；无链接返回 (cell原文, None)。"""
    m = re.match(r"\[([^\]]+)\]\(/characters/(\d+)\.md\)", cell)
    if m:
        return m.group(1), int(m.group(2))
    m = re.match(r"\[([^\]]+)\]\(/cards/(\d+)\.md\)", cell)
    if m:
        return m.group(1), int(m.group(2))
    m = re.match(r"\[([^\]]+)\]\(/support-cards/(\d+)\.md\)", cell)
    if m:
        return m.group(1), int(m.group(2))
    return cell, None


def to_int(s, default=0):
    try:
        return int(str(s).replace(",", ""))
    except (TypeError, ValueError):
        return default


def parse_release(s):
    """'2026-11-18 15:00:00' -> (date字符串, 毫秒时间戳)。"""
    s = (s or "").strip()
    if not s:
        return "", 0
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.strftime("%Y-%m-%d"), int(dt.timestamp() * 1000)
        except ValueError:
            continue
    return s, 0


def parse_index_tables(fm, cards_body, support_body, chars_body):
    """三张索引表 -> (cards list, characters list, data_version)。"""
    data_version = fm.get("data_version", "")
    cards = []
    for r in table_rows(cards_body)[1:]:
        if len(r) < 7 or not r[0].strip().lstrip("-").isdigit():
            continue
        title, _cid = link_id(r[2])
        cards.append({
            "id": int(r[0]), "cardKind": "card",
            "prefix": title,
            "characterName": r[1], "characterId": None,
            "unitName": r[3], "rarity": r[4], "attr": r[5],
            "power": to_int(r[6]),
            "releaseDate": "", "releaseAt": 0,
        })
    for r in table_rows(support_body)[1:]:
        if len(r) < 6 or not r[0].strip().lstrip("-").isdigit():
            continue
        title, _cid = link_id(r[2])
        cards.append({
            "id": int(r[0]), "cardKind": "support",
            "prefix": title,
            "characterName": r[1], "characterId": None,
            "unitName": r[3], "rarity": r[4], "attr": "",
            "power": to_int(r[5]),
            "releaseDate": "", "releaseAt": 0,
        })
    chars = []
    for r in table_rows(chars_body)[1:]:
        if len(r) < 6 or not r[0].strip().lstrip("-").isdigit():
            continue
        name, cid = link_id(r[1])
        chars.append({
            "id": cid or int(r[0]), "name": name, "unitName": r[2],
            "part": r[3], "cv": r[4].replace("CV. ", ""), "birthday": r[5],
        })
    # 角色名 -> characterId（卡面索引第 2 列与角色表同名）
    name_map = {c["name"]: c["id"] for c in chars}
    for c in cards:
        c["characterId"] = name_map.get(c["characterName"])
    return cards, chars, data_version


def parse_detail_md(text, kind):
    """详情 md -> 结构化 dict（字段表 + 技能 Lv 表 + 台词）。"""
    _fm, body = strip_front_matter(text)
    fields = {}
    flavors = []
    skills = []
    cur_skill = None
    in_level_table = False
    for line in body.splitlines():
        s = line.strip()
        if s.startswith(">") and s[1:].strip():
            flavors.append(s[1:].strip())
            continue
        if s.startswith("### ") and s != "### ":
            name = s[4:].strip()
            kind_tag = ""
            m = re.search(r"\((leader|live|gekisou|support)\)\s*$", name)
            if m:
                kind_tag = m.group(1)
                name = name[:m.start()].strip()
            cur_skill = {"name": name, "kind": kind_tag, "levels": []}
            skills.append(cur_skill)
            in_level_table = False
            continue
        if s.startswith("|") and s.endswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if all(set(c) <= set("-: ") for c in cells):
                continue
            if cells and cells[0] == "Field":
                in_level_table = False
                continue
            if cells and cells[0] == "Level":
                in_level_table = True
                continue
            if in_level_table and cur_skill is not None:
                cur_skill["levels"].append([cells[0], cells[1] if len(cells) > 1 else ""])
                continue
            if len(cells) >= 2:
                key = cells[0]
                val = cells[1]
                txt, cid = link_id(val)
                if key == "":
                    # 角色行： |  | [仲町阿拉蕾](/characters/11.md) |
                    fields.setdefault("_charLinks", []).append({"name": txt, "id": cid})
                else:
                    fields[key] = {"text": txt, "id": cid}
    return {"fields": fields, "flavor": " ".join(flavors), "skills": skills}


def detail_to_card_fields(d):
    """把解析后的 fields 摘成统一索引字段（发布时间/数值）。"""
    f = d["fields"]
    rel_date, rel_at = parse_release(f.get("Release", {}).get("text", ""))
    num = lambda k: to_int(f.get(k, {}).get("text"))  # noqa: E731
    return {
        "releaseDate": rel_date, "releaseAt": rel_at,
        "pf": num("Performance"), "tc": num("Technic"), "vi": num("Visual"),
        "total": num("Total Power"),
        "servers": f.get("Servers", {}).get("text", ""),
    }


# ---------------------------------------------------------------- 主流程
def build_index():
    log.info("拉取三张索引表 …")
    cards_body = fetch_bytes(MD_CARDS).decode("utf-8", "replace")
    time.sleep(POLITE_DELAY)
    support_body = fetch_bytes(MD_SUPPORT).decode("utf-8", "replace")
    time.sleep(POLITE_DELAY)
    chars_body = fetch_bytes(MD_CHARS).decode("utf-8", "replace")
    fm, _ = strip_front_matter(cards_body)
    fm2, _ = strip_front_matter(support_body)
    cards, chars, dv = parse_index_tables(fm, cards_body, support_body, chars_body)
    return cards, chars, dv or fm2.get("data_version", "")


def scrape_thumbs(cards, limit=0):
    """增量下载缩略图（已是 webp，直接落盘）。"""
    os.makedirs(THUMB_DIR, exist_ok=True)
    counts = {"downloaded": 0, "skipped": 0, "failed": 0}
    todo = []
    for c in cards:
        fname = f"{c['id']}_{c['cardKind']}.webp"
        path = os.path.join(THUMB_DIR, fname)
        if os.path.exists(path) and os.path.getsize(path) > 0:
            counts["skipped"] += 1
            continue
        todo.append((c, path))
    if limit:
        todo = todo[:limit]
    for c, path in todo:
        tmpl = ASSET_MEMBER_THUMB if c["cardKind"] == "card" else ASSET_SUPPORT_THUMB
        try:
            data = fetch_bytes(tmpl.format(id=c["id"]))
            tmp = path + ".part"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, path)
            counts["downloaded"] += 1
            log.info("缩略图 %s/%s ✓（%.1f KB）", c["id"], c["cardKind"], len(data) / 1024)
        except NotFoundError:
            counts["failed"] += 1
            log.warning("缩略图 404：%s/%s（图床未提供）", c["id"], c["cardKind"])
        except Exception as e:  # noqa: BLE001
            counts["failed"] += 1
            log.warning("缩略图失败：%s/%s -> %s", c["id"], c["cardKind"], e)
        time.sleep(POLITE_DELAY)
    return counts


def fetch_details(cards, limit=0):
    """详情 md -> data/onotes/{kind}_{id}.json 缓存 + 回填索引发布时间。
    ⚠️ 角色卡与支援卡 ID 序列重叠（1~81 双方都有），缓存文件名必须带 kind。
    每次运行都重新拉取（主人要求：扫描不止确认卡面存在，还需校准上线时间——
    未实装卡的 Release 会随官方公开而变化），缓存内容有变才落盘。"""
    os.makedirs(DB_DIR, exist_ok=True)
    counts = {"cached": 0, "skipped": 0, "failed": 0}
    todo = list(cards)
    if limit:
        todo = todo[:limit]
    for c in todo:
        url = (MD_CARD_DETAIL if c["cardKind"] == "card" else MD_SUPPORT_DETAIL).format(id=c["id"])
        cache = os.path.join(DB_DIR, f"{c['cardKind']}_{c['id']}.json")
        try:
            d = parse_detail_md(fetch_bytes(url).decode("utf-8", "replace"), c["cardKind"])
            cf = detail_to_card_fields(d)
            payload = json.dumps(d, ensure_ascii=False, sort_keys=True)
            old = None
            if os.path.exists(cache) and os.path.getsize(cache) > 0:
                try:
                    old = json.dumps(json.load(open(cache, encoding="utf-8")),
                                     ensure_ascii=False, sort_keys=True)
                except Exception:  # noqa: BLE001
                    old = None
            if payload != old:  # 内容有变化才写盘（Release/技能更新等）
                c["releaseDate"], c["releaseAt"] = cf["releaseDate"], cf["releaseAt"]
                tmp = cache + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(d, f, ensure_ascii=False)
                os.replace(tmp, cache)
                counts["cached"] += 1
                log.info("详情 %s/%s 已校准（技能 %d 条）", c["id"], c["cardKind"],
                         len(d["skills"]))
            else:
                c["releaseDate"], c["releaseAt"] = cf["releaseDate"], cf["releaseAt"]
                counts["skipped"] += 1
        except Exception as e:  # noqa: BLE001
            counts["failed"] += 1
            log.warning("详情失败：%s -> %s", c["id"], e)
        time.sleep(DETAIL_DELAY)
    return counts


def support_meta_cache(id_):
    return os.path.join(DB_DIR, f"support_meta_{id_}.json")


def enrich_support_meta(cards):
    """支援卡稀有度/属性补全：md 表格缺这两项（稀有度给的是内部档位编号）。
    从官方 HTML 页提取显示名（RarityIcon alt + 邻近属性词），缓存后增量跳过。
    ⚠️ 本项失败属于「可自愈的增量补全」，不参与 last_result=partial 判定；
    连续 3 次连接失败即熔断跳过剩余（映射兜底），避免断网时整轮空耗。"""
    counts = {"ok": 0, "cached": 0, "failed": 0, "skipped": 0}
    misses = 0
    for c in cards:
        if c["cardKind"] != "support":
            continue
        cache = support_meta_cache(c["id"])
        meta = None
        if os.path.exists(cache) and os.path.getsize(cache) > 0:
            try:
                meta = json.load(open(cache, encoding="utf-8"))
                counts["cached"] += 1
            except Exception:  # noqa: BLE001
                meta = None
        if meta is None and misses >= 3:
            counts["skipped"] += 1  # 熔断：站点不可达，剩余用映射兜底，下次运行自愈
            meta = {"rarity": SUPPORT_RARITY_MAP.get(str(c["rarity"]), c["rarity"]),
                    "attr": None}
        if meta is None:
            try:
                html = fetch_bytes(SUPPORT_PAGE.format(id=c["id"])).decode("utf-8", "replace")
                rarity, attr = None, None
                m = re.search(r'RarityIcon_\w+\.png"\s+alt="([^"]+)"', html)
                if m and m.group(1):
                    rarity = m.group(1)
                i = html.find("RarityIcon_")
                if i >= 0:
                    m2 = re.search(r"\b(Red|Blue|Green|Yellow|Purple)\b", html[i:i + 600])
                    if m2:
                        attr = m2.group(1)
                if rarity is None:
                    rarity = SUPPORT_RARITY_MAP.get(str(c["rarity"]), c["rarity"])
                meta = {"rarity": rarity, "attr": attr}
                tmp = cache + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(meta, f, ensure_ascii=False)
                os.replace(tmp, cache)
                counts["ok"] += 1
                misses = 0
                log.info("支援卡元数据 %s：%s / %s", c["id"], rarity, attr)
            except Exception as e:  # noqa: BLE001
                counts["failed"] += 1
                misses += 1
                if misses < 3:
                    log.warning("支援卡元数据失败：%s -> %s", c["id"], e)
                meta = {"rarity": SUPPORT_RARITY_MAP.get(str(c["rarity"]), c["rarity"]),
                        "attr": None}
            time.sleep(DETAIL_DELAY)
        if meta:
            c["rarity"] = meta.get("rarity") or c["rarity"]
            c["attr"] = meta.get("attr") or ""
    if counts["skipped"]:
        log.warning("支援卡元数据熔断跳过 %d 张（站点不可达，下次运行自愈）", counts["skipped"])
    return counts


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    started = datetime.now(timezone(timedelta(hours=8)))
    log.info("=== Our Notes 卡面抓取开始（limit=%s） ===", limit or "全量")
    offline = False
    try:
        cards, chars, data_version = build_index()
    except Exception as e:  # noqa: BLE001
        # 站点不可达：沿用本地索引离线运行（绝不空转重试网络步骤），
        # 有旧索引才降级，否则首跑没数据只能报错
        old = None
        try:
            old = json.load(open(os.path.join(DB_DIR, "index.json"), encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
        if not old:
            raise
        offline = True
        cards, chars, data_version = old["cards"], old["characters"], old.get("dataVersion", "")
        log.warning("站点不可达，离线运行（沿用本地索引）：%s", e)
    log.info("索引：角色卡+支援卡 %d 张，角色 %d 人（data_version=%s）",
             len(cards), len(chars), data_version[:40])
    if offline:
        # 离线：跳过一切网络步骤，state 保持 ok（首页不报警；下次联网自愈校准）
        counts = {"skipped": len(cards), "offline": True}
        state = {"last_run": started.isoformat(), "last_result": "ok", "counts": counts}
        tmp = os.path.join(DB_DIR, "state.json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
        os.replace(tmp, STATE_PATH)
        log.info("=== 离线运行结束：%s ===", counts)
        return
    meta_counts = enrich_support_meta(cards)
    thumb_counts = scrape_thumbs(cards, limit=limit)
    detail_counts = fetch_details(cards, limit=0)  # 每次全量校准（上线时间/技能变更）
    index = {
        "updatedAt": int(started.timestamp() * 1000),
        "dataVersion": data_version,
        "site": SITE,
        "characters": chars,
        "cards": cards,
    }
    tmp = os.path.join(DB_DIR, "index.json.tmp")
    os.makedirs(DB_DIR, exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False)
    os.replace(tmp, os.path.join(DB_DIR, "index.json"))
    counts = {
        "downloaded": thumb_counts["downloaded"],
        "skipped": thumb_counts["skipped"],
        "failed": thumb_counts["failed"],
        "details_cached": detail_counts["cached"],
        "details_failed": detail_counts["failed"],
        "support_meta": meta_counts["ok"],
        "support_meta_cached": meta_counts["cached"],
        "support_meta_skipped": meta_counts["skipped"],
    }
    # ⚠️ partial 只由「真正影响内容」的失败决定（缩略图/详情）。
    # 支援卡稀有度/属性补全是可自愈的增量增强：失败走映射兜底、下次运行自愈，
    # 不计入 partial（否则首页会误报「部分图片失败」——主人已指正）
    ok = counts["failed"] == 0 and counts["details_failed"] == 0
    state = {
        "last_run": started.isoformat(),
        "last_result": "ok" if ok else "partial",
        "counts": counts,
    }
    tmp = os.path.join(DB_DIR, "state.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)
    os.replace(tmp, STATE_PATH)
    log.info("=== 抓取结束：%s ===", counts)


if __name__ == "__main__":
    main()
