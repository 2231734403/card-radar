# -*- coding: utf-8 -*-
"""
卡牌雷达（Card Radar）本地服务器启动入口（零第三方依赖，仅标准库 + Pillow）。
保持 `py -X utf8 server\\server.py` 100% 兼容现有 VBS 隐藏窗口与 Windows 计划任务。
"""
import ctypes
import logging
import os
import socket
import sys
from http.server import ThreadingHTTPServer

# 保证以 `py server\server.py` 直接运行时项目根目录位于 sys.path 首位
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from server.api import AppContext, build_router, make_handler  # noqa: E402
from server.config import DATA_DIR, HOST, PORT, SERVER_VERSION, WEB_DIR  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("server")


class CardRadarHTTPServer(ThreadingHTTPServer):
    # Windows 下启用 SO_EXCLUSIVEADDRUSE 并禁用 SO_REUSEADDR，由操作系统内核彻底禁止双实例抢端口（T19）
    allow_reuse_address = False
    daemon_threads = True

    def server_bind(self):
        if sys.platform == "win32" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            try:
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            except OSError:
                pass
        super().server_bind()


def _port_already_listening(host, port):
    """快速探测目标端口是否已有实例在监听（跨会话/跨权限通用幂等检查）。"""
    try:
        with socket.create_connection((host, port), timeout=0.35):
            return True
    except OSError:
        return False


def _acquire_single_instance_mutex(port):
    """Windows 命名互斥体单实例锁：彻底消灭 T19 双实例抢端口。"""
    if sys.platform != "win32":
        return None
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        name = f"Local\\CardRadarServer_{port}"
        handle = kernel32.CreateMutexW(None, False, name)
        if not handle:
            return None
        if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
            kernel32.CloseHandle(handle)
            return False
        return handle
    except Exception:  # noqa: BLE001
        return None


def create_server(host=HOST, port=PORT, data_dir=None, web_dir=None):
    """构造服务器实例（供主入口与自动化 E2E 测试复用）。"""
    ctx = AppContext(data_dir=data_dir or DATA_DIR, web_dir=web_dir or WEB_DIR)
    router = build_router(ctx)
    handler_cls = make_handler(ctx, router)
    httpd = CardRadarHTTPServer((host, port), handler_cls)
    httpd.ctx = ctx
    httpd.router = router
    return httpd


def main():
    if _port_already_listening(HOST, PORT):
        log.info("检测到 %s:%d 已有卡牌雷达服务监听，本次幂等退出。", HOST, PORT)
        return 0
    mutex = _acquire_single_instance_mutex(PORT)
    if mutex is False:
        log.info("检测到端口 %d 已有卡牌雷达服务互斥锁，本次幂等退出。", PORT)
        return 0

    try:
        httpd = create_server(HOST, PORT)
    except OSError as exc:
        log.error("端口 %s:%d 已被占用或绑定失败：%s", HOST, PORT, exc)
        return 1

    log.info(
        "卡牌雷达服务 v%s 已启动：http://%s:%d（已注册 %d 条路由，4 个游戏模块）",
        SERVER_VERSION,
        HOST,
        PORT,
        len(httpd.router.routes),
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log.info("收到中止信号，正在关闭服务…")
    finally:
        httpd.server_close()
        httpd.ctx.jobs.shutdown()
    return 0


if __name__ == "__main__":
    if sys.stdout:
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
