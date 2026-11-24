# -*- coding: utf-8 -*-
"""单元测试：JobManager 持久化/恢复/并发 RLock、Pillow 超分与 ZIP 打包导出。"""
import io
import os
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PIL import Image  # noqa: E402

from server.config import atomic_write_json  # noqa: E402
from server.jobs import JobManager  # noqa: E402
from server.modules import ModuleRegistry  # noqa: E402
from server.upscaler import superres_pillow  # noqa: E402


def _make_sample_png(path, size=(120, 80), color=(40, 160, 210)):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img = Image.new("RGB", size, color)
    img.save(path, "PNG")


class TestJobsAndUpscaler(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.reg = ModuleRegistry(self.tmp.name)
        pjsk = self.reg.require("pjsk")
        atomic_write_json(
            pjsk.index_path,
            {
                "updatedAt": 1000,
                "cards": [{
                    "id": 7,
                    "prefix": "星空夜曲",
                    "characterName": "星乃一歌",
                    "characterFullName": "星乃一歌",
                    "unitName": "Leo/need",
                    "rarity": 4,
                    "trainable": True,
                    "assetbundleName": "res001_no007",
                }],
            },
        )
        _make_sample_png(pjsk.original_path(7, "normal"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_job_persistence_and_interrupted_recovery(self):
        persist = os.path.join(self.tmp.name, "jobs.json")
        atomic_write_json(
            persist,
            {
                "jobs": [{
                    "jobId": "dl1000_111",
                    "type": "download",
                    "mod": "pjsk",
                    "card": 7,
                    "kind": "normal",
                    "state": "running",
                    "label": "中断测试",
                }]
            },
        )
        jm = JobManager(self.reg, persist_path=persist)
        try:
            snap = jm.get("dl1000_111")
            self.assertEqual(snap["state"], "error")
            self.assertTrue(snap["interrupted"])
            ok, err, code = jm.remove("dl1000_111")
            self.assertTrue(ok)
            self.assertEqual(code, 200)
        finally:
            jm.shutdown()

    def test_pillow_upscale_real_image(self):
        src = self.reg.require("pjsk").original_path(7, "normal")
        dst = os.path.join(self.tmp.name, "out_2k.png")
        w, h = superres_pillow(src, dst, tier="2k")
        self.assertEqual(max(w, h), 2560)
        self.assertTrue(os.path.isfile(dst) and os.path.getsize(dst) > 0)

    def test_zip_export_grouping(self):
        jm = JobManager(self.reg)
        try:
            data, added, skipped = jm.build_zip_archive(
                [{"mod": "pjsk", "cardId": 7, "kind": "normal"}],
                group_by="unit",
                fetch_missing=False,
            )
            self.assertEqual(added, 1)
            self.assertEqual(skipped, 0)
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                names = zf.namelist()
                self.assertEqual(len(names), 1)
                self.assertIn("Leo", names[0])
                self.assertTrue(names[0].endswith(".png"))
        finally:
            jm.shutdown()


if __name__ == "__main__":
    unittest.main()
