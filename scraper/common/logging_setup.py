# -*- coding: utf-8 -*-
"""爬虫统一日志配置与 Windows 峰值物理内存观测。"""
import ctypes
import logging
import os
import sys
from ctypes import wintypes

from scraper.common.paths import LOG_DIR


def setup_logger(name, log_filename):
    os.makedirs(LOG_DIR, exist_ok=True)
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    fh = logging.FileHandler(os.path.join(LOG_DIR, log_filename), encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    logger.propagate = False
    return logger


class _PMC(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def peak_rss_mb():
    """64 位安全的进程峰值物理内存观测（MB）。"""
    if sys.platform != "win32":
        return 0.0
    try:
        pmc = _PMC()
        pmc.cb = ctypes.sizeof(_PMC)
        get_proc = ctypes.windll.kernel32.GetCurrentProcess
        get_proc.restype = wintypes.HANDLE
        k32 = ctypes.windll.kernel32.K32GetProcessMemoryInfo
        k32.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PMC), wintypes.DWORD]
        k32.restype = wintypes.BOOL
        if k32(get_proc(), ctypes.byref(pmc), pmc.cb):
            return pmc.PeakWorkingSetSize / 1048576
    except Exception:  # noqa: BLE001
        pass
    return 0.0
