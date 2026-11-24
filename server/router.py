# -*- coding: utf-8 -*-
"""
声明式正则路由器（零第三方依赖）。
通过集中式 (method, pattern, handler) 路由表取代巨型 if-elif 链，
支持启动期重复路由与完整性校验，杜绝 T22 类漏段 404。
"""
import re


class RouteEntry:
    __slots__ = ("method", "pattern_str", "regex", "handler", "name")

    def __init__(self, method, pattern_str, handler, name=None):
        self.method = method.upper()
        self.pattern_str = pattern_str
        self.regex = re.compile(pattern_str)
        self.handler = handler
        self.name = name or getattr(handler, "__name__", pattern_str)


class Router:
    def __init__(self):
        self.routes = []

    def add(self, method, pattern, handler, name=None):
        entry = RouteEntry(method, pattern, handler, name=name)
        for existing in self.routes:
            if existing.method == entry.method and existing.pattern_str == entry.pattern_str:
                raise ValueError(f"重复注册路由：{entry.method} {entry.pattern_str}")
        self.routes.append(entry)
        return handler

    def get(self, pattern, name=None):
        def deco(fn):
            return self.add("GET", pattern, fn, name=name)
        return deco

    def post(self, pattern, name=None):
        def deco(fn):
            return self.add("POST", pattern, fn, name=name)
        return deco

    def put(self, pattern, name=None):
        def deco(fn):
            return self.add("PUT", pattern, fn, name=name)
        return deco

    def delete(self, pattern, name=None):
        def deco(fn):
            return self.add("DELETE", pattern, fn, name=name)
        return deco

    def resolve(self, method, path):
        m_upper = method.upper()
        for entry in self.routes:
            if entry.method != m_upper:
                continue
            match = entry.regex.match(path)
            if match:
                return entry, match
        return None, None

    def summary(self):
        return [(r.method, r.pattern_str, r.name) for r in self.routes]
