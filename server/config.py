# -*- coding: utf-8 -*-
"""
全局配置、路径、单一版本真源与线程安全 JSON 缓存。
严守零第三方依赖原则，仅使用 Python 标准库。
"""
import json
import os
import re
import threading

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.join(PROJECT_ROOT, "web")
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
AI_DIR = os.path.join(PROJECT_ROOT, "ai_engine")
AI_EXE = os.path.join(AI_DIR, "realesrgan-ncnn-vulkan.exe")
VERSION_FILE = os.path.join(PROJECT_ROOT, "VERSION")

HOST = os.environ.get("CARD_RADAR_HOST", "127.0.0.1")
PORT = int(os.environ.get("CARD_RADAR_PORT", "8819"))

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)

# 超分配置
SR_TIERS = {"2k": 2560, "4k": 3840}
AI_MODELS = ["realesr-animevideov3-x4", "realesrgan-x4plus-anime"]
AI_SCALE = "4"    # 固定 4x 推理，输出按档位长边 BOX 缩回
AI_TILE = "128"   # 分块推理防显存溢出
AI_GPU = os.environ.get("CARD_RADAR_GPU", "0")
AI_TIMEOUT = 600  # 单次推理超时（秒）


def read_version(default="2.0.0"):
    """从根目录 VERSION 读取单一版本真源。"""
    try:
        with open(VERSION_FILE, encoding="utf-8") as f:
            v = f.read().strip()
            if v:
                return v
    except OSError:
        pass
    return default


SERVER_VERSION = read_version()


def sanitize_name(name, maxlen=60):
    """文件名净化：移除 Windows 非法字符与首尾空白/点号。"""
    cleaned = re.sub(r'[\\/:*?"<>|\r\n\t]', "", str(name or ""))
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return cleaned[:maxlen].rstrip(" .") or "未命名"


def downloads_dir():
    """系统「下载」文件夹：优先读取 Windows 注册表（兼容 OneDrive 重定向），回退 ~/Downloads。"""
    custom = os.environ.get("CARD_RADAR_DOWNLOADS")
    if custom:
        os.makedirs(custom, exist_ok=True)
        return custom
    try:
        import winreg  # noqa: PLC0415
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
        ) as key:
            val, _ = winreg.QueryValueEx(key, "{374DE290-123F-4565-9164-39C4925E467B}")
            path = os.path.expandvars(val)
            if path and os.path.isdir(path):
                return path
    except Exception:  # noqa: BLE001
        pass
    return os.path.join(os.path.expanduser("~"), "Downloads")


def atomic_write_bytes(path, data):
    """原子写字节：写临时文件后 os.replace，避免半成品落盘。"""
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
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
    """原子写 UTF-8 JSON。"""
    kwargs = {"ensure_ascii": False}
    if indent is not None:
        kwargs["indent"] = indent
    if separators is not None:
        kwargs["separators"] = separators
    payload = json.dumps(obj, **kwargs).encode("utf-8")
    atomic_write_bytes(path, payload)


class JsonFileCache:
    """基于 (mtime_ns, size) 的线程安全 JSON 文件缓存。
    既避免每次详情/下载请求重读十几 MB JSON，又在爬虫原子替换文件后自动失效。"""

    def __init__(self):
        self._lock = threading.RLock()
        self._entries = {}  # path -> (mtime_ns, size, data)

    def read(self, path):
        st = os.stat(path)
        sig = (st.st_mtime_ns, st.st_size)
        with self._lock:
            cached = self._entries.get(path)
            if cached and cached[0] == sig:
                return cached[1]
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        with self._lock:
            self._entries[path] = (sig, data)
        return data

    def read_optional(self, path, default=None):
        try:
            return self.read(path)
        except Exception:  # noqa: BLE001
            return default

    def invalidate(self, path=None):
        with self._lock:
            if path is None:
                self._entries.clear()
            else:
                self._entries.pop(path, None)


JSON_CACHE = JsonFileCache()


def read_json(path):
    """读取 JSON（带 mtime 缓存）。"""
    return JSON_CACHE.read(path)
