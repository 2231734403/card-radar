# -*- coding: utf-8 -*-
"""公共图片缩略处理（Magic Bytes 验真 + 上下文安全关闭 + 原子写盘）。"""
import io

from scraper.common.net import is_valid_image_bytes
from scraper.common.paths import atomic_write_bytes


def shrink_to_webp(src_bytes, dst_path, max_h=240, quality=80):
    """把内存图片字节缩放到指定高度并原子保存为 webp。返回落盘字节数。"""
    if not is_valid_image_bytes(src_bytes):
        raise ValueError("非有效图片字节流")
    from PIL import Image  # noqa: PLC0415

    buf = io.BytesIO()
    with Image.open(io.BytesIO(src_bytes)) as img:
        rgb = img.convert("RGB") if img.mode != "RGB" else img.copy()
    w, h = rgb.size
    if max_h and h > max_h:
        k = max_h / h
        rgb = rgb.resize((max(1, int(round(w * k))), max_h), Image.LANCZOS)
    rgb.save(buf, "WEBP", quality=quality)
    out = buf.getvalue()
    if not out:
        raise ValueError("生成 webp 为空")
    atomic_write_bytes(dst_path, out)
    return len(out)
