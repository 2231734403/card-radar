# -*- coding: utf-8 -*-
"""单元测试：声明式路由表、四游戏模块契约、历史回归护栏（T12/T20/T21/T22）、路径安全。"""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from server.config import atomic_write_bytes, atomic_write_json, sanitize_name  # noqa: E402
from server.http_utils import safe_join, split_path_query  # noqa: E402
from server.modules import ModuleRegistry  # noqa: E402
from server.net import is_valid_image_bytes  # noqa: E402
from server.router import Router  # noqa: E402


class TestRouterAndUtils(unittest.TestCase):
    def test_router_duplicate_rejected(self):
        r = Router()
        r.add("GET", r"^/api/v2/ping$", lambda h, m, q: None)
        with self.assertRaises(ValueError):
            r.add("GET", r"^/api/v2/ping$", lambda h, m, q: None)
        # 不同方法允许同路径
        r.add("POST", r"^/api/v2/ping$", lambda h, m, q: None)
        entry, match = r.resolve("POST", "/api/v2/ping")
        self.assertIsNotNone(entry)
        self.assertIsNotNone(match)

    def test_split_path_query_without_question_mark(self):
        path, qs = split_path_query("/api/superres/10/normal")
        self.assertEqual(path, "/api/superres/10/normal")
        self.assertEqual(qs, {})
        path2, qs2 = split_path_query("/api/superres/10/normal?target=2k&engine=pillow")
        self.assertEqual(path2, "/api/superres/10/normal")
        self.assertEqual(qs2["target"], ["2k"])
        self.assertEqual(qs2["engine"], ["pillow"])

    def test_sanitize_name(self):
        self.assertEqual(sanitize_name('  foo/bar:baz*?"<>|  ... '), "foobarbaz")
        self.assertEqual(sanitize_name(""), "未命名")
        self.assertEqual(len(sanitize_name("a" * 100, maxlen=30)), 30)

    def test_safe_join_blocks_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNotNone(safe_join(tmp, "/index.html"))
            self.assertIsNone(safe_join(tmp, "/../../VERSION"))
            self.assertIsNone(safe_join(tmp, "..\\..\\secret.txt"))
            self.assertIsNone(safe_join(tmp, "/"))

    def test_magic_bytes_validation(self):
        self.assertTrue(is_valid_image_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16))
        self.assertTrue(is_valid_image_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 16))
        self.assertTrue(is_valid_image_bytes(b"RIFF\x12\x00\x00\x00WEBP" + b"\x00" * 8))
        # T21: Bestdori SPA HTML 壳与 T7: 0 字节必须拒绝
        self.assertFalse(is_valid_image_bytes(b""))
        self.assertFalse(is_valid_image_bytes(b"<!DOCTYPE html><html></html>"))


class TestModuleContracts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.reg = ModuleRegistry(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_registry_aliases(self):
        self.assertEqual(self.reg.require("sc").id, "shinycolors")
        self.assertEqual(self.reg.require("shinycolors").route_id, "sc")
        self.assertEqual(len(self.reg.all()), 4)

    def test_pjsk_and_bandori_trained_superres_contract(self):
        """回归验证：修复旧版 _trained_{tier}.png 与 _after_training_{tier}.png 错位 404 Bug。"""
        for mod_id in ("pjsk", "bandori"):
            mod = self.reg.require(mod_id)
            self.assertEqual(mod.normalize_kind("trained"), "after_training")
            self.assertEqual(
                mod.original_filename_disk(42, "trained", tier="4k"),
                "42_after_training_4k.png",
            )
            # 历史遗留 _trained_4k.png 也能被兼容找到
            legacy_file = os.path.join(mod.original_dir, "42_trained_4k.png")
            atomic_write_bytes(legacy_file, b"\x89PNG\r\n\x1a\n" + b"x" * 32)
            found = mod.find_existing_original(42, "after_training", tier="4k")
            self.assertEqual(found, legacy_file)

    def test_onotes_composite_key_isolation(self):
        """回归验证 T12：Our Notes 角色卡 #1 与支援卡 #1 绝不互覆盖。"""
        mod = self.reg.require("onotes")
        atomic_write_json(
            mod.index_path,
            {
                "updatedAt": 1000,
                "cards": [
                    {"id": 1, "cardKind": "card", "prefix": "角色卡A", "unitName": "MyGO!!!!!", "rarity": "SSR", "attr": "Red"},
                    {"id": 1, "cardKind": "support", "prefix": "支援卡B", "unitName": "Ave Mujica", "rarity": "特殊", "attr": "Blue"},
                ],
            },
        )
        c1 = mod.find_card(1, kind="card")
        s1 = mod.find_card(1, kind="support")
        self.assertEqual(c1["prefix"], "角色卡A")
        self.assertEqual(s1["prefix"], "支援卡B")
        self.assertNotEqual(mod.original_path(1, "card"), mod.original_path(1, "support"))
        self.assertTrue(mod.download_filename(c1, "card").startswith("OurNotes卡牌_1_"))
        self.assertTrue(mod.download_filename(s1, "support").startswith("OurNotes支援卡_1_"))


if __name__ == "__main__":
    unittest.main()
