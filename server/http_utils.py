# -*- coding: utf-8 -*-
"""HTTP 工具：安全路径拼接、查询参数与请求体解析、ETag 与统一响应封装。"""
import hashlib
import json
import mimetypes
import os
from urllib.parse import parse_qs, quote, urlsplit

# 补充标准库在部分 Windows 注册表下可能缺失的 MIME 类型
mimetypes.add_type("application/javascript; charset=utf-8", ".js")
mimetypes.add_type("application/javascript; charset=utf-8", ".mjs")
mimetypes.add_type("text/css; charset=utf-8", ".css")
mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("application/manifest+json; charset=utf-8", ".webmanifest")


def safe_join(base, sub):
    """防目录穿越：拼接后的绝对路径必须严格位于 base 内部。"""
    rel = (sub or "").lstrip("/\\")
    base_abs = os.path.abspath(base)
    full = os.path.abspath(os.path.join(base_abs, rel))
    if full == base_abs or not full.startswith(base_abs + os.sep):
        return None
    return full


def split_path_query(raw_path):
    """安全拆分 path 与 query dict（彻底避免缺少 '?' 时 split IndexError）。"""
    parsed = urlsplit(raw_path or "/")
    return parsed.path, parse_qs(parsed.query, keep_blank_values=False)


def query_first(qs, key, default=""):
    vals = qs.get(key)
    if vals and vals[0] is not None:
        return vals[0]
    return default


def read_json_body(handler, max_bytes=2 * 1024 * 1024):
    """读取 POST/PUT JSON 请求体；空请求体返回 {}。"""
    length_raw = handler.headers.get("Content-Length")
    if not length_raw:
        return {}
    try:
        length = int(length_raw)
    except ValueError as exc:
        raise ValueError("无效的 Content-Length") from exc
    if length <= 0:
        return {}
    if length > max_bytes:
        raise ValueError(f"请求体过大（上限 {max_bytes} 字节）")
    raw = handler.rfile.read(length)
    if not raw.strip():
        return {}
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"JSON 解析失败：{exc}") from exc


def file_etag(path):
    st = os.stat(path)
    raw = f"{st.st_mtime_ns}:{st.st_size}".encode("ascii")
    return '"' + hashlib.sha1(raw).hexdigest()[:16] + '"'


def send_json(handler, code, payload, cache_control="no-store", etag=None):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    if etag and handler.headers.get("If-None-Match") == etag:
        handler.send_response(304)
        handler.send_header("ETag", etag)
        handler.send_header("Cache-Control", cache_control)
        handler.end_headers()
        return
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", cache_control)
    if etag:
        handler.send_header("ETag", etag)
    handler.end_headers()
    handler.wfile.write(body)


def send_file(handler, path, ctype=None, cache_control=None):
    try:
        etag = file_etag(path)
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        send_json(handler, 404, {"error": "文件不存在"})
        return

    ext = os.path.splitext(path)[1].lower()
    if cache_control is None:
        if ext in (".html", ".js", ".css", ".mjs", ".vbs", ".json"):
            cache_control = "no-cache"
        else:
            cache_control = "public, max-age=600"

    if handler.headers.get("If-None-Match") == etag:
        handler.send_response(304)
        handler.send_header("ETag", etag)
        handler.send_header("Cache-Control", cache_control)
        handler.end_headers()
        return

    if ctype is None:
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        if ext == ".json":
            ctype = "application/json; charset=utf-8"
        elif ext == ".html":
            ctype = "text/html; charset=utf-8"

    handler.send_response(200)
    handler.send_header("Content-Type", ctype)
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Cache-Control", cache_control)
    handler.send_header("ETag", etag)
    handler.end_headers()
    handler.wfile.write(data)


def send_attachment_bytes(handler, data, filename, ascii_name, ctype="application/octet-stream"):
    handler.send_response(200)
    handler.send_header("Content-Type", ctype)
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header(
        "Content-Disposition",
        f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(filename)}',
    )
    handler.end_headers()
    handler.wfile.write(data)
