# -*- coding: utf-8 -*-
"""Our Notes（bdon.moe）Markdown 索引与详情解析器（爬虫与服务端共用）。"""
import re
from datetime import datetime

# 支援卡的「稀有度」在 md 表格里是游戏内部档位编号，官方页显示名不同：
# 2=R、3=SR、4=SSR、10=特殊（乐团全员纪念卡，RarityIcon_EX）
SUPPORT_RARITY_MAP = {"2": "R", "3": "SR", "4": "SSR", "10": "特殊"}
ATTR_WORDS = ("Red", "Blue", "Green", "Yellow", "Purple")


def to_int(value, default=0):
    try:
        return int(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return default


def strip_front_matter(text):
    """返回 (frontmatter dict, 正文)。front matter 采用宽松 key: value 解析。"""
    fm = {}
    body = text or ""
    m = re.match(r"\s*---\s*\n(.*?)\n---\s*\n", body, re.S)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                fm[k.strip()] = v.strip().strip('"').strip("'")
        body = body[m.end():]
    return fm, body


def table_rows(body, header_keyword=None):
    """提取 Markdown 表格行（list[list[cell]]，过滤表头分隔行）。"""
    rows = []
    for line in (body or "").splitlines():
        s = line.strip()
        if s.startswith("|") and s.endswith("|"):
            rows.append([c.strip() for c in s.strip("|").split("|")])
    if header_keyword is not None:
        for i, row in enumerate(rows):
            if any(header_keyword in c for c in row):
                rows = rows[i:]
                break
    out = []
    for row in rows:
        if all(set(c) <= set("-: ") for c in row):
            continue
        out.append(row)
    return out


def link_id(cell):
    """[文本](/characters/11.md) -> (文本, 11)；无链接返回 (cell 原文, None)。"""
    for pat in (
        r"\[([^\]]+)\]\(/characters/(\d+)\.md\)",
        r"\[([^\]]+)\]\(/cards/(\d+)\.md\)",
        r"\[([^\]]+)\]\(/support-cards/(\d+)\.md\)",
    ):
        m = re.match(pat, cell or "")
        if m:
            return m.group(1), int(m.group(2))
    m_any = re.match(r"\[([^\]]+)\]\([^\)]+\)", cell or "")
    if m_any:
        return m_any.group(1), None
    return cell or "", None


def parse_release(s):
    """'2026-11-18 15:00:00' -> (date 字符串, 毫秒时间戳)。"""
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
    """三张 Markdown 索引表 -> (cards list, characters list, data_version)。"""
    data_version = (fm or {}).get("data_version", "")
    cards = []
    for r in table_rows(cards_body)[1:]:
        if len(r) < 7 or not r[0].strip().lstrip("-").isdigit():
            continue
        title, _cid = link_id(r[2])
        cards.append({
            "id": int(r[0]),
            "cardKind": "card",
            "prefix": title,
            "characterName": r[1],
            "characterId": None,
            "unitName": r[3],
            "rarity": r[4],
            "attr": r[5],
            "power": to_int(r[6]),
            "releaseDate": "",
            "releaseAt": 0,
        })
    for r in table_rows(support_body)[1:]:
        if len(r) < 6 or not r[0].strip().lstrip("-").isdigit():
            continue
        title, _cid = link_id(r[2])
        cards.append({
            "id": int(r[0]),
            "cardKind": "support",
            "prefix": title,
            "characterName": r[1],
            "characterId": None,
            "unitName": r[3],
            "rarity": SUPPORT_RARITY_MAP.get(str(r[4]).strip(), r[4]),
            "rawRarity": str(r[4]).strip(),
            "attr": "",
            "power": to_int(r[5]),
            "releaseDate": "",
            "releaseAt": 0,
        })
    chars = []
    for r in table_rows(chars_body)[1:]:
        if len(r) < 6 or not r[0].strip().lstrip("-").isdigit():
            continue
        name, cid = link_id(r[1])
        chars.append({
            "id": cid or int(r[0]),
            "name": name,
            "unitName": r[2],
            "part": r[3],
            "cv": r[4].replace("CV. ", ""),
            "birthday": r[5],
        })
    name_map = {c["name"]: c["id"] for c in chars}
    for c in cards:
        c["characterId"] = name_map.get(c["characterName"])
    return cards, chars, data_version


def parse_detail_md(text, kind="card"):
    """详情 Markdown -> 结构化 dict（字段表 + 技能 Lv 表 + 台词）。"""
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
                key, val = cells[0], cells[1]
                txt, cid = link_id(val)
                if key == "":
                    fields.setdefault("_charLinks", []).append({"name": txt, "id": cid})
                else:
                    fields[key] = {"text": txt, "id": cid}
    return {"fields": fields, "flavor": " ".join(flavors), "skills": skills, "kind": kind}


def parse_support_meta_html(html, fallback_rarity=""):
    """从官方支援卡 HTML 页提取显示稀有度（RarityIcon alt）与属性词。"""
    rarity = None
    attr = None
    m = re.search(r'RarityIcon_\w+\.png"\s+alt="([^"]+)"', html or "")
    if m and m.group(1):
        rarity = m.group(1).strip()
    idx = (html or "").find("RarityIcon_")
    if idx >= 0:
        m2 = re.search(r"\b(Red|Blue|Green|Yellow|Purple)\b", html[idx:idx + 600])
        if m2:
            attr = m2.group(1)
    if not rarity:
        rarity = SUPPORT_RARITY_MAP.get(str(fallback_rarity), fallback_rarity)
    return {"rarity": rarity, "attr": attr}


def detail_to_card_fields(detail):
    """把解析后的 fields 摘成统一索引字段（发布时间/数值）。"""
    f = (detail or {}).get("fields") or {}
    rel_date, rel_at = parse_release((f.get("Release") or {}).get("text", ""))
    return {
        "releaseDate": rel_date,
        "releaseAt": rel_at,
        "pf": to_int((f.get("Performance") or {}).get("text")),
        "tc": to_int((f.get("Technic") or {}).get("text")),
        "vi": to_int((f.get("Visual") or {}).get("text")),
        "total": to_int((f.get("Total Power") or {}).get("text")),
        "servers": (f.get("Servers") or {}).get("text", ""),
    }
