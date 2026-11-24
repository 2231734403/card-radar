# -*- coding: utf-8 -*-
"""
爬虫韧性公共组件（四模块共享）：
  - CircuitBreaker：连续连接失败达到阈值即熔断，断网/限流时快速收工
  - RetryQueue（retry.json）：显式化失败重试队列 + 指数退避（1d → 3d → 7d → 14d）
  - OfflineFallback：主索引拉取失败时若本地有旧索引则无缝离线降级，绝不破坏现网数据
  - 状态文件原子读写
"""
import os
import threading

from scraper.common.paths import atomic_write_json, now_ms, read_json_optional

# 指数退避阶梯（天）：第 1 次失败等 1 天，第 2 次 3 天，第 3 次 7 天，之后 14 天
BACKOFF_DAYS = (1, 3, 7, 14)


class CircuitBreaker:
    """线程安全连续失败熔断器。"""

    def __init__(self, threshold=5):
        self.threshold = max(1, int(threshold))
        self._lock = threading.Lock()
        self._consecutive = 0
        self._tripped = False

    def record_success(self):
        with self._lock:
            self._consecutive = 0

    def record_failure(self):
        with self._lock:
            self._consecutive += 1
            if self._consecutive >= self.threshold:
                self._tripped = True
            return self._tripped

    @property
    def is_open(self):
        with self._lock:
            return self._tripped

    @property
    def consecutive_failures(self):
        with self._lock:
            return self._consecutive


class RetryQueue:
    """显式化重试队列（持久化到 data/<mod>/retry.json），支持指数退避。"""

    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()
        raw = read_json_optional(path, {}) or {}
        items = raw.get("items") if isinstance(raw, dict) else {}
        self.items = dict(items) if isinstance(items, dict) else {}

    def is_due(self, key, current_ms=None):
        """该资源是否到了可以重试的时间（不在队列中则返回 True）。"""
        ts = current_ms if current_ms is not None else now_ms()
        with self._lock:
            entry = self.items.get(str(key))
            if not entry:
                return True
            return ts >= int(entry.get("nextRetryAt") or 0)

    def record_failure(self, key, reason="", kind="missing", current_ms=None):
        ts = current_ms if current_ms is not None else now_ms()
        k = str(key)
        with self._lock:
            prev = self.items.get(k) or {}
            attempts = int(prev.get("attempts") or 0) + 1
            days = BACKOFF_DAYS[min(attempts - 1, len(BACKOFF_DAYS) - 1)]
            self.items[k] = {
                "attempts": attempts,
                "kind": kind,
                "reason": str(reason)[:200],
                "lastFailedAt": ts,
                "nextRetryAt": ts + days * 86400 * 1000,
                "backoffDays": days,
            }
            return self.items[k]

    def record_success(self, key):
        with self._lock:
            self.items.pop(str(key), None)

    def count(self):
        with self._lock:
            return len(self.items)

    def save(self):
        with self._lock:
            payload = {
                "updatedAt": now_ms(),
                "count": len(self.items),
                "items": self.items,
            }
        atomic_write_json(self.path, payload, indent=1)


def load_state(path, defaults=None):
    base = dict(defaults or {"trained_missing": [], "runs": 0, "last_run": None})
    data = read_json_optional(path)
    if isinstance(data, dict):
        base.update(data)
    return base


def save_state(path, state):
    atomic_write_json(path, state, indent=1)


def try_offline_fallback(index_path, state_path, logger, started_iso, err, prev_state=None):
    """主数据源不可达时的统一离线降级：
    - 若本地已有有效 index.json：保留旧索引，写 offline=True 状态，返回 True（退出码 0）
    - 若首次运行无旧索引：无法降级，返回 False（调用方应退出码 1）"""
    old = read_json_optional(index_path)
    if not isinstance(old, dict) or not old.get("cards"):
        logger.error("主数据源不可达且本地无可用缓存索引，本次中止：%s", err)
        return False

    cards_n = len(old.get("cards") or [])
    logger.warning("主数据源不可达，已触发离线降级（保留本地 %d 张卡索引）：%s", cards_n, err)
    st = dict(prev_state or {})
    st["runs"] = int(st.get("runs") or 0) + 1
    st["last_run"] = started_iso
    st["last_result"] = "ok"
    st["counts"] = {"downloaded": 0, "skipped": cards_n, "failed": 0, "offline": True}
    save_state(state_path, st)
    return True
