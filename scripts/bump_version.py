# -*- coding: utf-8 -*-
"""
单一版本真源同步脚本（零第三方依赖）。
用法：py -X utf8 scripts/bump_version.py <new_version>
功能：原子更新 VERSION、web/sw.js、web/index.html 与 web/js/**/*.js 内所有 ?v=。
内置体积收缩保护，防止误替换破坏文件。
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][A-Za-z0-9._-]+)?$")


def _safe_write(path, new_text, old_text):
    if new_text == old_text:
        return False
    if old_text and (not new_text.strip() or len(new_text) < len(old_text) * 0.85):
        raise RuntimeError(f"安全中止：{path} 体积异常收缩（{len(old_text)} -> {len(new_text)}）")
    tmp = path + ".bump.tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(new_text)
    os.replace(tmp, path)
    return True


def bump(new_ver):
    if not SEMVER_RE.match(new_ver):
        raise ValueError(f"非法版本号：{new_ver}（需符合 X.Y.Z 格式）")

    ver_file = os.path.join(ROOT, "VERSION")
    old_ver = ""
    if os.path.isfile(ver_file):
        with open(ver_file, encoding="utf-8") as f:
            old_ver = f.read().strip()
    _safe_write(ver_file, new_ver + "\n", "")

    changed = [ver_file]

    # 更新 web/sw.js 缓存名
    sw_path = os.path.join(ROOT, "web", "sw.js")
    if os.path.isfile(sw_path):
        with open(sw_path, encoding="utf-8") as f:
            src = f.read()
        updated = re.sub(r"card-radar-v[0-9A-Za-z._-]+", f"card-radar-v{new_ver}", src)
        if _safe_write(sw_path, updated, src):
            changed.append(sw_path)

    # 更新 web/index.html 与所有 web/js/**/*.js 中的 ?v=X.Y.Z
    targets = [os.path.join(ROOT, "web", "index.html")]
    js_root = os.path.join(ROOT, "web", "js")
    for dp, _, fns in os.walk(js_root):
        for fn in fns:
            if fn.endswith(".js"):
                targets.append(os.path.join(dp, fn))

    ver_qs_re = re.compile(r"(\?v=)\d+\.\d+\.\d+(?:[-+][A-Za-z0-9._-]+)?")
    for fp in targets:
        if not os.path.isfile(fp):
            continue
        with open(fp, encoding="utf-8") as f:
            src = f.read()
        updated = ver_qs_re.sub(rf"\g<1>{new_ver}", src)
        if _safe_write(fp, updated, src):
            changed.append(fp)

    print(f"bumped {old_ver or '(none)'} -> {new_ver} ({len(changed)} files updated)")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("用法：py -X utf8 scripts/bump_version.py <X.Y.Z>")
        sys.exit(2)
    bump(sys.argv[1].strip())
