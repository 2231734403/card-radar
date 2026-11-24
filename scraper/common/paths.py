# -*- coding: utf-8 -*-
"""爬虫公共路径、原子落盘与北京时间工具（零第三方依赖）。"""
import json
import os
import threading
from datetime import datetime, timedelta, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
LOG_DIR = os.path.join(DATA_DIR, "logs")
TZ_CN = timezone(timedelta(hours=8))


def now_bj():
    return datetime.now(TZ_CN)


def now_ms():
    return int(now_bj().timestamp() * 1000)


def atomic_write_bytes(path, data):
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.part"
    try:
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def atomic_write_json(path, obj, indent=None, separators=None):
    kwargs = {"ensure_ascii": False}
    if indent is not None:
        kwargs["indent"] = indent
    if separators is not None:
        kwargs["separators"] = separators
    payload = json.dumps(obj, **kwargs).encode("utf-8")
    atomic_write_bytes(path, payload)


def read_json_optional(path, default=None):
    if not os.path.isfile(path):
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return default
