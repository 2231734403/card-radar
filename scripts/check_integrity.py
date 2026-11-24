# -*- coding: utf-8 -*-
"""
Card Radar 工程完整性与质量护栏检查脚本（本地开发与 GitHub Actions CI 共用，零第三方依赖）：
  1. 编译全部 Python 源码（py_compile）
  2. 校验 VERSION 单一真源 == server.config.SERVER_VERSION == sw.js == index.html == 全部 web/js ?v=
  3. 实例化路由器，校验零重复路由与 4 大模块完整注册
  4. 校验所有 .cmd / .vbs 文件均为纯 ASCII（防 Windows cmd GBK 乱码）
  5. 校验 run_server_hidden.vbs 绝不回调 run_server.cmd（防 T18 无限递归）
  6. 扫描跟踪源码目录，拦截硬编码本机路径 / 用户名泄露
"""
import os
import py_compile
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

SCAN_DIRS = ("server", "scraper", "web", "scripts", "tests")
LEAK_PATTERNS = (
    re.compile(r"E:\\ZCode", re.IGNORECASE),
    re.compile(r"C:\\Users\\[^\\\s\"']+", re.IGNORECASE),
)
VER_QS_RE = re.compile(r"\?v=(\d+\.\d+\.\d+(?:[-+][A-Za-z0-9._-]+)?)")


def check_py_compile(errors):
    count = 0
    for d in SCAN_DIRS:
        base = os.path.join(ROOT, d)
        if not os.path.isdir(base):
            continue
        for dp, _, fns in os.walk(base):
            if "__pycache__" in dp:
                continue
            for fn in fns:
                if not fn.endswith(".py"):
                    continue
                fp = os.path.join(dp, fn)
                count += 1
                try:
                    py_compile.compile(fp, doraise=True)
                except py_compile.PyCompileError as exc:
                    errors.append(f"[py_compile] {fp}: {exc}")
    print(f"[OK] py_compile scanned {count} python files")


def check_version_consistency(errors):
    from server.config import SERVER_VERSION  # noqa: PLC0415

    ver_file = os.path.join(ROOT, "VERSION")
    if not os.path.isfile(ver_file):
        errors.append("[version] 缺少根目录 VERSION 文件")
        return
    with open(ver_file, encoding="utf-8") as f:
        expected = f.read().strip()

    if SERVER_VERSION != expected:
        errors.append(f"[version] SERVER_VERSION({SERVER_VERSION}) != VERSION({expected})")

    sw = os.path.join(ROOT, "web", "sw.js")
    if os.path.isfile(sw):
        with open(sw, encoding="utf-8") as f:
            if f"card-radar-v{expected}" not in f.read():
                errors.append(f"[version] web/sw.js 缓存名未对齐 v{expected}")

    web_files = [os.path.join(ROOT, "web", "index.html")]
    for dp, _, fns in os.walk(os.path.join(ROOT, "web", "js")):
        for fn in fns:
            if fn.endswith(".js"):
                web_files.append(os.path.join(dp, fn))

    checked_refs = 0
    for fp in web_files:
        with open(fp, encoding="utf-8") as f:
            txt = f.read()
        for m in VER_QS_RE.finditer(txt):
            checked_refs += 1
            if m.group(1) != expected:
                rel = os.path.relpath(fp, ROOT)
                errors.append(f"[version] {rel} 发现过期版本号 ?v={m.group(1)}（期望 {expected}）")
    print(f"[OK] version consistency checked: v{expected} ({checked_refs} web asset refs)")


def check_router_and_modules(errors):
    from server.api import AppContext, build_router  # noqa: PLC0415

    ctx = AppContext()
    router = build_router(ctx)
    mod_ids = {m.id for m in ctx.registry.all()}
    expected_mods = {"pjsk", "bandori", "shinycolors", "onotes"}
    if mod_ids != expected_mods:
        errors.append(f"[modules] 注册模块不完整：{mod_ids} != {expected_mods}")
    print(f"[OK] router & modules validated: {len(router.routes)} routes, 4 modules")


def check_windows_scripts(errors):
    scripts_dir = os.path.join(ROOT, "scripts")
    for fn in os.listdir(scripts_dir):
        if fn.endswith((".cmd", ".vbs")):
            fp = os.path.join(scripts_dir, fn)
            with open(fp, "rb") as f:
                raw = f.read()
            try:
                text = raw.decode("ascii")
            except UnicodeDecodeError:
                errors.append(f"[ascii] scripts/{fn} 包含非 ASCII 字符（违背 Windows cmd/vbs 约束）")
                continue
            if fn == "run_server_hidden.vbs":
                code_lines = [ln.strip().lower() for ln in text.splitlines() if not ln.lstrip().startswith("'")]
                if any("run_server.cmd" in ln for ln in code_lines):
                    errors.append("[T18] run_server_hidden.vbs 禁止回调 run_server.cmd（会形成死循环）")
    print("[OK] Windows .cmd/.vbs pure-ASCII & anti-recursion check passed")


def check_privacy_leaks(errors):
    self_path = os.path.abspath(__file__)
    for d in SCAN_DIRS:
        base = os.path.join(ROOT, d)
        if not os.path.isdir(base):
            continue
        for dp, _, fns in os.walk(base):
            if "__pycache__" in dp:
                continue
            for fn in fns:
                if not fn.endswith((".py", ".js", ".mjs", ".css", ".html", ".cmd", ".vbs", ".ps1", ".json")):
                    continue
                fp = os.path.join(dp, fn)
                if os.path.abspath(fp) == self_path:
                    continue
                try:
                    with open(fp, encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                except OSError:
                    continue
                for pat in LEAK_PATTERNS:
                    if pat.search(content):
                        rel = os.path.relpath(fp, ROOT)
                        errors.append(f"[privacy] {rel} 命中禁止的本机路径模式：{pat.pattern}")
    print("[OK] privacy / hardcoded local path scan passed")


def main():
    errors = []
    check_py_compile(errors)
    check_version_consistency(errors)
    check_router_and_modules(errors)
    check_windows_scripts(errors)
    check_privacy_leaks(errors)
    if errors:
        print("\nINTEGRITY CHECK FAILED:")
        for err in errors:
            print("  -", err)
        return 1
    print("\nALL INTEGRITY CHECKS PASSED")
    return 0


if __name__ == "__main__":
    if sys.stdout:
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
