# -*- coding: utf-8 -*-
"""
本地用户档案持久化（data/user_profile.json）：
保存收藏夹（跨四游戏复合键）、自定义分组与偏好设置，
弥补纯浏览器 localStorage 清缓存/换浏览器即丢失的痛点。
"""
import os
import threading
import time

from server.config import DATA_DIR, atomic_write_json

DEFAULT_PROFILE = {
    "version": 1,
    "favorites": {},     # "{mod}:{kind}:{id}" -> {mod, id, kind, addedAt, group}
    "groups": ["精选", "待超分", "壁纸"],
    "settings": {},
    "updatedAt": 0,
}


class UserDataStore:
    def __init__(self, path=None):
        self.path = path or os.path.join(DATA_DIR, "user_profile.json")
        self._lock = threading.RLock()
        self._data = None

    def _load_locked(self):
        if self._data is not None:
            return self._data
        if os.path.exists(self.path):
            try:
                import json  # noqa: PLC0415
                with open(self.path, encoding="utf-8") as f:
                    raw = json.load(f)
                if isinstance(raw, dict):
                    merged = dict(DEFAULT_PROFILE)
                    merged.update(raw)
                    if not isinstance(merged.get("favorites"), dict):
                        merged["favorites"] = {}
                    if not isinstance(merged.get("groups"), list):
                        merged["groups"] = list(DEFAULT_PROFILE["groups"])
                    if not isinstance(merged.get("settings"), dict):
                        merged["settings"] = {}
                    self._data = merged
                    return self._data
            except Exception:  # noqa: BLE001
                pass
        self._data = {
            "version": 1,
            "favorites": {},
            "groups": list(DEFAULT_PROFILE["groups"]),
            "settings": {},
            "updatedAt": 0,
        }
        return self._data

    def get(self):
        with self._lock:
            d = self._load_locked()
            return {
                "version": d["version"],
                "favorites": dict(d["favorites"]),
                "groups": list(d["groups"]),
                "settings": dict(d["settings"]),
                "updatedAt": d["updatedAt"],
            }

    def update(self, payload):
        """合并更新档案并原子落盘。"""
        if not isinstance(payload, dict):
            raise ValueError("档案数据必须是 JSON 对象")
        with self._lock:
            d = self._load_locked()
            if "favorites" in payload:
                if not isinstance(payload["favorites"], dict):
                    raise ValueError("favorites 必须是对象")
                d["favorites"] = payload["favorites"]
            if "groups" in payload:
                if not isinstance(payload["groups"], list):
                    raise ValueError("groups 必须是数组")
                cleaned = []
                for g in payload["groups"]:
                    s = str(g).strip()
                    if s and s not in cleaned:
                        cleaned.append(s[:30])
                d["groups"] = cleaned or ["精选"]
            if "settings" in payload:
                if not isinstance(payload["settings"], dict):
                    raise ValueError("settings 必须是对象")
                d["settings"].update(payload["settings"])
            d["updatedAt"] = int(time.time() * 1000)
            atomic_write_json(self.path, d, indent=2)
            return self.get()
