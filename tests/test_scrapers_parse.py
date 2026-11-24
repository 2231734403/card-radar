# -*- coding: utf-8 -*-
"""单元测试：四大爬虫解析逻辑、技能模板、韧性组件（熔断器/重试队列/离线降级）。"""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scraper.bandori_scrape import build_index as build_bandori_index  # noqa: E402
from scraper.common.onotes_md import (  # noqa: E402
    detail_to_card_fields,
    parse_detail_md,
    parse_index_tables,
    parse_support_meta_html,
    strip_front_matter,
)
from scraper.common.paths import atomic_write_json  # noqa: E402
from scraper.common.resilience import CircuitBreaker, RetryQueue, try_offline_fallback  # noqa: E402
from scraper.scrape import apply_zh, build_index as build_pjsk_index  # noqa: E402
from scraper.shinycolors_scrape import build_index as build_shiny_index  # noqa: E402
from server.modules.pjsk import fmt_skill_description  # noqa: E402
from server.modules.shinycolors import build_shiny_source_urls  # noqa: E402


class TestScraperParsers(unittest.TestCase):
    def test_pjsk_skill_template_and_zh(self):
        effects = [
            {"id": 1, "skillEffectDetails": [{"level": 1, "activateEffectDuration": 5.0, "activateEffectValue": 80},
                                             {"level": 4, "activateEffectDuration": 5.0, "activateEffectValue": 120}]},
            {"id": 2, "skillEffectDetails": [{"level": 4, "activateEffectValue": 10}]},
        ]
        txt = fmt_skill_description("{{1;d}}秒内{{1;v}}%，合计{{1,2;u}}%，角色{{99;c}}", effects, "初音未来")
        self.assertEqual(txt, "5秒内120%，合计130%，角色初音未来")

        meta = {
            "cards.json": [{"id": 10, "characterId": 21, "prefix": "JP名", "cardSkillName": "JP技",
                            "cardRarityType": "rarity_4", "attr": "cool", "assetbundleName": "res021_no010"}],
            "skills.json": [{"id": 1, "description": "JP描"}],
            "moe_costume.json": {"costumes": [{"cardIds": [10], "costumeNumber": 1, "name": "JP服", "designer": "JP设"}]},
            "gameCharacters.json": [{"id": 21}],
            "gameCharacterUnits.json": [{"gameCharacterId": 21, "unit": "piapro"}],
        }
        tr = {
            "cards.json": {"prefix": {"JP名": "中文卡名"}, "skillName": {"JP技": "中文技能"}},
            "skills.json": {"description": {"JP描": "中文描述"}},
            "costumes.json": {"name": {"JP服": "中文服装"}, "designer": {"JP设": "设计师A"}},
        }
        apply_zh(meta, tr)
        idx = build_pjsk_index(
            meta["cards.json"], meta["gameCharacters.json"],
            meta["gameCharacterUnits.json"], meta["moe_costume.json"],
        )
        self.assertEqual(idx[0]["prefix"], "中文卡名")
        self.assertEqual(idx[0]["characterName"], "初音未来")
        self.assertTrue(idx[0]["trainable"])

    def test_bandori_dual_release_and_band_map(self):
        cards = {
            "100": {
                "characterId": 11,
                "rarity": 4,
                "attribute": "powerful",
                "prefix": ["日名", "EN", "繁名", "简名", "韩"],
                "releasedAt": ["1700000000000", None, None, "1710000000000", None],
                "resourceSetName": "res011001",
            }
        }
        chars = {"11": {"characterName": ["日", "EN", "繁", "大和麻弥", "韩"], "bandId": 4, "characterType": "band"}}
        idx = build_bandori_index(cards, chars)
        self.assertEqual(idx[0]["prefix"], "简名")
        self.assertEqual(idx[0]["unitName"], "Pastel*Palettes")  # bandId 4 绝不是 Roselia
        self.assertEqual(idx[0]["releaseJp"], 1700000000000)
        self.assertEqual(idx[0]["releaseCn"], 1710000000000)
        self.assertTrue(idx[0]["trainable"])

    def test_shiny_gameo_url_sanitization_and_index(self):
        card = {
            "prefix": "【A/B:C#’…】",
            "characterName": "浅倉透",
            "cardKind": "P",
            "enzaId": "1040200010",
            "releaseDate": "2025-01-10",
        }
        urls = build_shiny_source_urls(card, kind="fes")
        self.assertTrue(urls[0].endswith(".webp"))  # 2024-10-08 之后 webp 优先
        self.assertIn("2.webp", urls[0])
        self.assertIn("fes_card/1040200010.jpg", urls[-1])

        idols = [{
            "idolId": 20,
            "idolName": "浅倉透",
            "unit": {"unitName": "noctchill"},
            "cardLists": [{"cardIndex": 500, "enzaId": "1040200010", "cardType": "P_SSR",
                           "cardName": "【测试】浅倉透", "releaseDate": "2025-01-10"}],
        }]
        idx, warns = build_shiny_index(idols)
        self.assertEqual(warns, [])
        self.assertEqual(idx[0]["rarity"], "SSR")
        self.assertTrue(idx[0]["trainable"])

    def test_onotes_markdown_and_support_meta(self):
        cards_md = """---
data_version: "2026.11.24"
---
| ID | Character | Title | Band | Rarity | Attr | Power |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 高松灯 | [迷星叫](/cards/1.md) | MyGO!!!!! | SSR | Red | 35,000 |
"""
        support_md = """| ID | Character | Title | Band | Rarity | Power |
| --- | --- | --- | --- | --- | --- |
| 1 | 丰川祥子 | [纪念照](/support-cards/1.md) | Ave Mujica | 10 | 12,000 |
"""
        chars_md = """| ID | Name | Band | Part | CV | Birthday |
| --- | --- | --- | --- | --- | --- |
| 11 | [高松灯](/characters/11.md) | MyGO!!!!! | Vo. | CV. 羊宫妃那 | 11-22 |
"""
        fm, _ = strip_front_matter(cards_md)
        cards, chars, dv = parse_index_tables(fm, cards_md, support_md, chars_md)
        self.assertEqual(dv, "2026.11.24")
        self.assertEqual(len(cards), 2)
        self.assertEqual(cards[0]["characterId"], 11)
        # T25 回归：支援卡内部编号 10 -> 特殊
        self.assertEqual(cards[1]["rarity"], "特殊")

        detail_md = """---
title: test
---
> 台词测试

| Field | Value |
| --- | --- |
| Release | 2026-11-18 15:00:00 |
| Performance | 11,500 |
|  | [高松灯](/characters/11.md) |

### 星空之歌 (live)
| Level | Effect |
| --- | --- |
| Lv.5 | 分数提升 120% |
"""
        d = parse_detail_md(detail_md, kind="card")
        cf = detail_to_card_fields(d)
        self.assertEqual(cf["releaseDate"], "2026-11-18")
        self.assertEqual(cf["pf"], 11500)
        self.assertEqual(d["skills"][0]["kind"], "live")
        self.assertEqual(d["flavor"], "台词测试")

        meta = parse_support_meta_html('<img src="RarityIcon_EX.png" alt="特殊"><span>Purple</span>', "10")
        self.assertEqual(meta, {"rarity": "特殊", "attr": "Purple"})


class TestResilienceComponents(unittest.TestCase):
    def test_circuit_breaker(self):
        cb = CircuitBreaker(threshold=3)
        self.assertFalse(cb.is_open)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        self.assertEqual(cb.consecutive_failures, 0)
        for _ in range(3):
            cb.record_failure()
        self.assertTrue(cb.is_open)

    def test_retry_queue_exponential_backoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            q = RetryQueue(os.path.join(tmp, "retry.json"))
            t0 = 1_700_000_000_000
            self.assertTrue(q.is_due("1:normal", t0))
            e1 = q.record_failure("1:normal", "404", current_ms=t0)
            self.assertEqual(e1["backoffDays"], 1)
            self.assertFalse(q.is_due("1:normal", t0 + 3600 * 1000))
            self.assertTrue(q.is_due("1:normal", t0 + 86400 * 1000))
            e2 = q.record_failure("1:normal", "404", current_ms=t0 + 86400 * 1000)
            self.assertEqual(e2["backoffDays"], 3)
            q.save()

            q2 = RetryQueue(os.path.join(tmp, "retry.json"))
            self.assertEqual(q2.count(), 1)
            q2.record_success("1:normal")
            self.assertEqual(q2.count(), 0)

    def test_offline_fallback(self):
        import logging  # noqa: PLC0415

        log = logging.getLogger("test_offline")
        with tempfile.TemporaryDirectory() as tmp:
            idx = os.path.join(tmp, "index.json")
            st = os.path.join(tmp, "state.json")
            # 冷启动无缓存 -> 无法降级
            self.assertFalse(try_offline_fallback(idx, st, log, "2026-11-24T00:00:00+08:00", "timeout"))
            # 存在本地缓存 -> 降级成功
            atomic_write_json(idx, {"cards": [{"id": 1}]})
            self.assertTrue(try_offline_fallback(idx, st, log, "2026-11-24T00:00:00+08:00", "timeout"))


if __name__ == "__main__":
    unittest.main()
