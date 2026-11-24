# -*- coding: utf-8 -*-
"""端到端 HTTP 测试：拉起临时端口隔离服务器，真发 HTTP 请求验证 v2 + v1 API、缓存治理、收藏持久化与 ZIP 导出。"""
import io
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PIL import Image  # noqa: E402

from server.config import SERVER_VERSION, atomic_write_json  # noqa: E402
from server.server import create_server  # noqa: E402


def _write_img(path, fmt="PNG", size=(64, 64)):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Image.new("RGB", size, (100, 180, 240)).save(path, fmt)


class TestApiE2E(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = os.path.join(self.tmp.name, "data")
        self.dl_dir = os.path.join(self.tmp.name, "downloads")
        os.environ["CARD_RADAR_DOWNLOADS"] = self.dl_dir

        self.httpd = create_server("127.0.0.1", 0, data_dir=self.data_dir)
        self.port = self.httpd.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"
        self._seed_fixture()

        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.httpd.ctx.jobs.shutdown(wait=True)
        os.environ.pop("CARD_RADAR_DOWNLOADS", None)
        self.tmp.cleanup()

    def _seed_fixture(self):
        reg = self.httpd.ctx.registry
        # PJSK
        pjsk = reg.require("pjsk")
        atomic_write_json(pjsk.index_path, {
            "updatedAt": 1700000000000,
            "cards": [{
                "id": 1, "seq": 1, "prefix": "测试卡", "characterId": 21,
                "characterName": "初音未来", "characterFullName": "初音未来",
                "unitName": "虚拟歌手", "attr": "cool", "rarity": 4,
                "rarityType": "rarity_4", "trainable": True, "assetbundleName": "res021_no001",
            }],
        })
        atomic_write_json(os.path.join(pjsk.db_dir, "skills.json"), [])
        atomic_write_json(os.path.join(pjsk.db_dir, "gameCharacters.json"), [{"id": 21, "birthday": "8/31"}])
        atomic_write_json(os.path.join(pjsk.db_dir, "cardEpisodes.json"), [])
        _write_img(os.path.join(pjsk.thumb_dir, "1_normal.webp"), "WEBP")
        _write_img(pjsk.original_path(1, "normal"), "PNG")

        # Bandori
        bd = reg.require("bandori")
        atomic_write_json(bd.index_path, {
            "updatedAt": 1700000000000,
            "cards": [{
                "id": 5, "prefix": "邦多利卡", "characterName": "户山香澄",
                "unitName": "Poppin'Party", "attr": "powerful", "rarity": 4, "trainable": True,
                "releaseJp": 1700000000000, "releaseCn": 0, "assetbundleName": "res001001",
            }],
        })
        atomic_write_json(os.path.join(bd.db_dir, "card_5.json"), {"prefix": ["JP", "", "", "邦多利卡", ""]})
        _write_img(bd.original_path(5, "normal"), "PNG")

        # Our Notes（重叠 ID #1 角色卡 + 支援卡）
        on = reg.require("onotes")
        atomic_write_json(on.index_path, {
            "updatedAt": 1700000000000,
            "characters": [{"id": 1, "name": "高松灯"}],
            "cards": [
                {"id": 1, "cardKind": "card", "prefix": "角色卡1", "characterName": "高松灯", "unitName": "MyGO!!!!!", "rarity": "SSR", "attr": "Red"},
                {"id": 1, "cardKind": "support", "prefix": "支援卡1", "characterName": "丰川祥子", "unitName": "Ave Mujica", "rarity": "特殊", "attr": "Blue"},
            ],
        })
        atomic_write_json(os.path.join(on.db_dir, "card_1.json"), {"fields": {}, "flavor": "台词1", "skills": []})
        atomic_write_json(os.path.join(on.db_dir, "support_1.json"), {"fields": {}, "flavor": "支援2", "skills": []})

    def _req(self, method, path, body=None, headers=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        hdrs = dict(headers or {})
        if data is not None:
            hdrs["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=data, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, dict(resp.headers), resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, dict(exc.headers), exc.read()

    def test_health_and_etag_index(self):
        code, _, raw = self._req("GET", "/api/v2/health")
        self.assertEqual(code, 200)
        h = json.loads(raw)
        self.assertEqual(h["version"], SERVER_VERSION)
        self.assertEqual(h["totalCards"], 4)

        code1, hdrs1, _ = self._req("GET", "/api/v2/modules/pjsk/index")
        self.assertEqual(code1, 200)
        etag = hdrs1.get("ETag")
        self.assertTrue(etag)
        code2, _, _ = self._req("GET", "/api/v2/modules/pjsk/index", headers={"If-None-Match": etag})
        self.assertEqual(code2, 304)

    def test_onotes_composite_detail_endpoint(self):
        c1, _, r1 = self._req("GET", "/api/v2/modules/onotes/cards/card/1")
        c2, _, r2 = self._req("GET", "/api/v2/modules/onotes/cards/support/1")
        self.assertEqual(c1, 200)
        self.assertEqual(c2, 200)
        self.assertEqual(json.loads(r1)["flavor"], "台词1")
        self.assertEqual(json.loads(r2)["flavor"], "支援2")

    def test_multi_module_cache_stats_and_selective_clear(self):
        code, _, raw = self._req("GET", "/api/v2/cache")
        self.assertEqual(code, 200)
        st = json.loads(raw)
        self.assertEqual(st["count"], 2)  # pjsk + bandori

        # 仅清除 bandori 缓存，pjsk 必须完好保留
        code2, _, raw2 = self._req("DELETE", "/api/v2/cache?mod=bandori")
        self.assertEqual(code2, 200)
        self.assertEqual(json.loads(raw2)["removed"], 1)

        _, _, raw3 = self._req("GET", "/api/v2/cache")
        self.assertEqual(json.loads(raw3)["count"], 1)

    def test_user_data_roundtrip(self):
        payload = {"favorites": {"pjsk:card:1": {"mod": "pjsk", "id": 1, "kind": "card", "group": "精选"}}, "groups": ["精选", "壁纸"]}
        c_put, _, _ = self._req("PUT", "/api/v2/user-data", body=payload)
        self.assertEqual(c_put, 200)
        c_get, _, raw = self._req("GET", "/api/v2/user-data")
        self.assertEqual(c_get, 200)
        self.assertIn("pjsk:card:1", json.loads(raw)["favorites"])

    def test_v1_superres_no_query_string_and_zip_export(self):
        # 回归：无 ?query 的 v1 POST superres 不得 500 IndexError（预置 4k 缓存避免测试调用真实 GPU exe）
        pjsk = self.httpd.ctx.registry.require("pjsk")
        _write_img(pjsk.original_path(1, "normal", tier="4k"), "PNG")
        c, _, raw = self._req("POST", "/api/superres/1/normal")
        self.assertEqual(c, 200)
        self.assertTrue(json.loads(raw)["ok"])

        # ZIP 打包导出
        zc, zhdrs, zbytes = self._req(
            "POST",
            "/api/v2/export/zip",
            body={"items": [{"mod": "pjsk", "cardId": 1, "kind": "normal"}], "groupBy": "rarity", "fetchMissing": False},
        )
        self.assertEqual(zc, 200)
        self.assertEqual(zhdrs.get("Content-Type"), "application/zip")
        with zipfile.ZipFile(io.BytesIO(zbytes)) as zf:
            self.assertEqual(len(zf.namelist()), 1)

    def test_path_traversal_blocked(self):
        code, _, _ = self._req("GET", "/../../VERSION")
        self.assertEqual(code, 404)


if __name__ == "__main__":
    unittest.main()
