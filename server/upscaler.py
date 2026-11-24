# -*- coding: utf-8 -*-
"""
三级超分管线（零第三方 Python 依赖，仅标准库 + Pillow + 可选 Real-ESRGAN exe）：
  1. AI 首选：realesrgan-ncnn-vulkan.exe（RGBA 防黑帧白底合成 → 双模型切换 → 三重校验 → BOX 下采样 → 轻 USM）
  2. GPU 串行锁：GPU_SEMAPHORE = Semaphore(1)，彻底杜绝批量超分并发占显存导致 OOM 或异常回退
  3. 失败回退：Pillow 渐进抗锯齿管线（每步 ≤1.3× + 平滑压阶梯 + 温和 USM）
  4. 严格上下文管理 + 原子写盘，杜绝 Windows 文件句柄泄漏与损坏缓存
"""
import logging
import os
import re
import subprocess
import threading

from server.config import (
    AI_DIR,
    AI_EXE,
    AI_GPU,
    AI_MODELS,
    AI_SCALE,
    AI_TILE,
    AI_TIMEOUT,
    SR_TIERS,
)

log = logging.getLogger("server.upscaler")

# 全局 GPU 互斥信号量：批量超分时下载可并行，但 Vulkan GPU 推理必须串行
GPU_SEMAPHORE = threading.Semaphore(1)


def ai_engine_available():
    return os.path.isfile(AI_EXE)


def progressive_upscale(img, target_long):
    """无模型渐进抗锯齿放大：每步 ≤1.3× + 中间轻平滑 + 末步收噪与温和 USM。"""
    from PIL import Image, ImageFilter  # noqa: PLC0415

    w, h = img.size
    long_side = max(w, h)
    if long_side >= target_long:
        return img.filter(ImageFilter.UnsharpMask(radius=2.2, percent=85, threshold=4))

    sizes = []
    cur = float(long_side)
    while cur < target_long:
        cur = min(float(target_long), cur * 1.3)
        sizes.append(cur)

    cur_img = img
    n = len(sizes)
    for i, s in enumerate(sizes):
        k = s / long_side
        nw, nh = max(1, int(round(w * k))), max(1, int(round(h * k)))
        cur_img = cur_img.resize((nw, nh), Image.LANCZOS)
        if i < n - 1:
            cur_img = cur_img.filter(ImageFilter.GaussianBlur(0.5))
    cur_img = cur_img.filter(ImageFilter.GaussianBlur(0.6))
    cur_img = cur_img.filter(ImageFilter.UnsharpMask(radius=2.2, percent=85, threshold=4))
    return cur_img


def superres_pillow(src, dst, tier="4k"):
    """Pillow 经典超分管线，原子落盘返回 (w, h)。"""
    from PIL import Image  # noqa: PLC0415

    target = SR_TIERS.get(tier, 3840)
    tmp = f"{dst}.{os.getpid()}.{threading.get_ident()}.pillow.png"
    try:
        with Image.open(src) as im:
            im.load()
            work = im.convert("RGB") if im.mode != "RGB" else im.copy()
        final = progressive_upscale(work, target)
        size = final.size
        os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
        final.save(tmp, "PNG", compress_level=6)
        os.replace(tmp, dst)
        return size
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _ai_prepare(src, work_png):
    """防黑帧通道预处理：animevideov3 对 RGBA 大图会输出全黑帧，真透明合成白底。"""
    from PIL import Image  # noqa: PLC0415

    with Image.open(src) as raw:
        raw.load()
        exp_w = raw.width * int(AI_SCALE)
        exp_h = raw.height * int(AI_SCALE)
        if raw.mode == "RGBA":
            lo, _ = raw.getchannel("A").getextrema()
            if lo < 250:
                bg = Image.new("RGB", raw.size, (255, 255, 255))
                bg.paste(raw, mask=raw.getchannel("A"))
                work = bg
            else:
                work = raw.convert("RGB")
        elif raw.mode != "RGB":
            work = raw.convert("RGB")
        else:
            work = raw.copy()
    work.save(work_png, "PNG")
    return exp_w, exp_h


def _ai_validate(out_png, exp_w, exp_h, in_png):
    """三重校验：尺寸一致 / 非空图 / 缩回后 MAD 与源图差异合理。"""
    from PIL import Image, ImageChops, ImageStat  # noqa: PLC0415

    with Image.open(out_png) as im:
        im.load()
        if im.size != (exp_w, exp_h) or im.mode not in ("RGB", "RGBA"):
            return f"输出尺寸异常 {im.size}"
        lo, hi = im.convert("L").getextrema()
        if hi - lo < 8:
            return "输出为空图（GPU 瞬时异常）"
        with Image.open(in_png) as ref:
            ref_rgb = ref.convert("RGB")
            out_small = im.convert("RGB").resize(ref.size, Image.LANCZOS)
        diff = ImageChops.difference(out_small, ref_rgb)
        mad = sum(ImageStat.Stat(diff).mean) / 3.0
        if mad > 40:
            return f"输出内容异常（与原图平均差 {mad:.0f}）"
    return None


def _ai_infer_once(in_png, out_png, model, progress_cb=None):
    cmd = [
        AI_EXE,
        "-i", in_png,
        "-o", out_png,
        "-n", model,
        "-s", AI_SCALE,
        "-m", os.path.join(AI_DIR, "models"),
        "-f", "png",
        "-t", AI_TILE,
        "-g", AI_GPU,
    ]
    log.info("AI 推理：%s（tile %s，GPU %s）", model, AI_TILE, AI_GPU)
    proc = subprocess.Popen(
        cmd,
        cwd=AI_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    def _pump():
        buf = ""
        while True:
            ch = proc.stderr.read(1)
            if not ch:
                break
            buf += ch
            if ch in ("\r", "\n"):
                matches = re.findall(r"(\d+(?:\.\d+)?)%", buf)
                if matches and progress_cb:
                    try:
                        pct = max(0, min(100, int(float(matches[-1]))))
                        progress_cb(pct)
                    except ValueError:
                        pass
                buf = ""

    pump = threading.Thread(target=_pump, daemon=True)
    pump.start()
    try:
        return proc.wait(timeout=AI_TIMEOUT)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        raise RuntimeError(f"AI 引擎推理超过 {AI_TIMEOUT}s，已中止") from None
    finally:
        pump.join(timeout=2)


def ai_upscale(src, dst, tier="4k", progress_cb=None):
    """Real-ESRGAN 串行 GPU 推理 + 双模型容错 + 三重校验 + BOX 下采样 + 原子落盘。"""
    from PIL import Image, ImageFilter  # noqa: PLC0415

    tag = f"{os.getpid()}.{threading.get_ident()}"
    work_png = f"{dst}.{tag}.ai.in.png"
    tmp_out = f"{dst}.{tag}.ai.out.png"
    tmp_final = f"{dst}.{tag}.ai.final.png"

    try:
        with GPU_SEMAPHORE:
            exp_w, exp_h = _ai_prepare(src, work_png)
            last_err = None
            for model in AI_MODELS:
                try:
                    if os.path.exists(tmp_out):
                        os.remove(tmp_out)
                    code = _ai_infer_once(work_png, tmp_out, model, progress_cb=progress_cb)
                    if code != 0:
                        raise RuntimeError(f"推理进程退出码 {code}（显卡/驱动问题）")
                    err = _ai_validate(tmp_out, exp_w, exp_h, work_png)
                    if err:
                        raise RuntimeError(err)
                    last_err = None
                    break
                except RuntimeError as exc:
                    last_err = f"{model}: {exc}"
                    log.warning("AI 推理失败，换模型重试：%s", exc)
            if last_err:
                raise RuntimeError(f"AI 推理全部模型失败：{last_err}")

        with Image.open(tmp_out) as raw_out:
            img = raw_out.convert("RGB") if raw_out.mode != "RGB" else raw_out.copy()
        w, h = img.size
        long_side = max(w, h)
        target_long = SR_TIERS.get(tier, 3840)
        if long_side > target_long:
            k = target_long / long_side
            img = img.resize(
                (max(1, int(round(w * k))), max(1, int(round(h * k)))),
                Image.BOX,
            )
        img = img.filter(ImageFilter.UnsharpMask(radius=1.0, percent=30, threshold=3))
        os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
        img.save(tmp_final, "PNG", compress_level=6)
        os.replace(tmp_final, dst)
        return img.size
    finally:
        for p in (tmp_out, work_png, tmp_final):
            if os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass


def run_upscale(src, dst, tier="4k", engine="ai", on_phase=None, on_progress=None):
    """统一超分入口：优先 AI，缺失或失败自动回退 Pillow。
    返回 dict: {engine, fallback, size}。"""
    used = "pillow"
    fallback = False
    size = None

    if engine == "ai":
        if ai_engine_available():
            try:
                if on_phase:
                    on_phase("ai", "AI")
                size = ai_upscale(src, dst, tier=tier, progress_cb=on_progress)
                used = "ai"
            except Exception as exc:  # noqa: BLE001
                log.warning("AI 超分失败，回退 Pillow 管线：%s", exc)
                fallback = True
        else:
            log.warning("AI 引擎缺失（%s），自动回退 Pillow 管线", AI_EXE)
            fallback = True

    if used == "pillow":
        if on_phase:
            on_phase("superres", "Pillow")
        if on_progress:
            on_progress(None)
        size = superres_pillow(src, dst, tier=tier)
    elif on_progress:
        on_progress(100)

    return {"engine": used, "fallback": fallback, "size": size}
