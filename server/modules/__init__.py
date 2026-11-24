# -*- coding: utf-8 -*-
"""游戏模块注册中心：集中管理四模块实例与别名解析。"""
from server.modules.bandori import BandoriModule
from server.modules.onotes import OnotesModule
from server.modules.pjsk import PjskModule
from server.modules.shinycolors import ShinyColorsModule

MODULE_CLASSES = (
    PjskModule,
    BandoriModule,
    OnotesModule,
    ShinyColorsModule,
)


class ModuleRegistry:
    def __init__(self, data_dir):
        self.data_dir = data_dir
        self._ordered = []
        self._by_key = {}
        for cls in MODULE_CLASSES:
            mod = cls(data_dir)
            self._ordered.append(mod)
            self._by_key[mod.id] = mod
            self._by_key[mod.route_id] = mod
            for alias in mod.aliases:
                self._by_key[alias] = mod

    def all(self):
        return list(self._ordered)

    def get(self, key):
        if not key:
            return None
        return self._by_key.get(str(key).lower())

    def require(self, key):
        mod = self.get(key)
        if mod is None:
            raise KeyError(f"未知游戏模块：{key}")
        return mod
