# -*- coding: utf-8 -*-
"""
爬虫统一网络层（零第三方依赖）：
  - 三通路自适应回退（直连 → 127.0.0.1:7890 → 7897）+ 按域名粘性缓存
  - Magic Bytes 图片验真（杜绝 T7 0 字节与 T21 SPA 壳误落盘）
  - allow_html 参数显式控制是否允许 HTML 响应（修复 Our Notes 支援卡页误拒 Bug）
  - 多源流式竞速 race_download（低内存峰值落盘）
"""
import json
import os
import ssl
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from scraper.common.paths import atomic_write_bytes

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)

DEFAULT_PROXIES = (
    ("直连", None),
    ("代理7890", "http://127.0.0.1:7890"),
    ("代理7897", "http://127.0.0.1:7897"),
)

_SSL_CTX = ssl.create_default_context()
_HOST_LOCK = threading.Lock()
_HOST_PREF = {}


class NotFoundError(Exception):
    """资源不存在（HTTP 404 或 SPA 假壳）。"""


class _RacerCancelled(Exception):
    """竞速败者正常退出路径。"""


def is_valid_image_bytes(data):
    if not data or len(data) < 12:
        return False
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return True
    if data.startswith(b"\xff\xd8\xff"):
        return True
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return True
    if data.startswith((b"GIF87a", b"GIF89a")):
        return True
    return False


def _ordered_channels(url, proxies=None):
    channels = list(proxies if proxies is not None else DEFAULT_PROXIES)
    host = urlsplit(url).netloc
    with _HOST_LOCK:
        pref = _HOST_PREF.get(host)
    if pref and pref in channels:
        channels.remove(pref)
        channels.insert(0, pref)
    return host, channels


def _remember_channel(host, channel):
    with _HOST_LOCK:
        _HOST_PREF[host] = channel


def _build_opener(proxy, verify_ssl=True):
    ctx = _SSL_CTX if verify_ssl else ssl._create_unverified_context()
    handlers = [urllib.request.HTTPSHandler(context=ctx)]
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    return urllib.request.build_opener(*handlers)


def fetch_bytes(
    url,
    timeout=60,
    allow_html=False,
    expect_image=False,
    proxies=None,
    verify_ssl=True,
    retries=1,
):
    """带三通路粘性回退的 GET。返回原始字节。"""
    host, channels = _ordered_channels(url, proxies)
    last_err = None
    for attempt in range(max(1, retries)):
        for tag, proxy in channels:
            opener = _build_opener(proxy, verify_ssl=verify_ssl)
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            try:
                with opener.open(req, timeout=timeout) as resp:
                    ct = (resp.headers.get("Content-Type") or "").lower()
                    data = resp.read()
                if not allow_html and ct.startswith("text/html"):
                    raise NotFoundError(f"{url} -> SPA HTML 壳")
                if not data:
                    raise ConnectionError(f"{url} -> 空响应")
                if expect_image and not is_valid_image_bytes(data):
                    raise NotFoundError(f"{url} -> 非有效图片数据")
                _remember_channel(host, (tag, proxy))
                return data
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    raise NotFoundError(url) from exc
                last_err = f"{tag}: HTTP {exc.code}"
            except NotFoundError:
                raise
            except Exception as exc:  # noqa: BLE001
                last_err = f"{tag}: {exc}"
            time.sleep(0.5)
        if attempt + 1 < retries:
            time.sleep(2 ** (attempt + 1))
    raise ConnectionError(f"{url} -> {last_err or '全部通路失败'}")


def fetch_json(url, timeout=90, retries=1, verify_ssl=True):
    data = fetch_bytes(url, timeout=timeout, allow_html=False, retries=retries, verify_ssl=verify_ssl)
    return json.loads(data.decode("utf-8", "replace"))


def download_image_to(path, url, timeout=30, verify_ssl=True):
    """下载图片并做 Magic Bytes 验真 + 原子落盘，返回字节数。"""
    data = fetch_bytes(url, timeout=timeout, expect_image=True, verify_ssl=verify_ssl)
    atomic_write_bytes(path, data)
    return len(data)


def _safe_unlink(path):
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def race_download(urls, out_path, budget=25, timeout=30):
    """多源并发竞速 GET 并流式落盘，先完成者胜出、败者自动清理临时文件。
    返回 (winner_tmp_path, winner_url)。"""
    result = {"path": None, "url": None, "err": None}
    cancel = threading.Event()
    lock = threading.Lock()
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    tmp_paths = [f"{out_path}.r{i}.part" for i in range(len(urls))]

    def work(url, path):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as resp:
                t0 = time.time()
                written = 0
                with open(path, "wb") as f:
                    while True:
                        if cancel.is_set():
                            raise _RacerCancelled()
                        chunk = resp.read(131072)
                        if not chunk:
                            break
                        f.write(chunk)
                        written += len(chunk)
                        if time.time() - t0 > budget:
                            raise TimeoutError(f"{budget}s 预算耗尽（已收 {written // 1024}KB）")
                if written <= 0:
                    raise ConnectionError("空响应")
            with lock:
                if result["path"] is None:
                    result["path"] = path
                    result["url"] = url
                    cancel.set()
        except _RacerCancelled:
            _safe_unlink(path)
        except Exception as exc:  # noqa: BLE001
            _safe_unlink(path)
            with lock:
                if result["path"] is None and result["err"] is None:
                    result["err"] = f"{url} -> {exc}"

    threads = [threading.Thread(target=work, args=(u, tp), daemon=True) for u, tp in zip(urls, tmp_paths)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    if result["path"] is None:
        raise ConnectionError(result["err"] or "全部源失败")
    for tp in tmp_paths:
        if tp != result["path"]:
            _safe_unlink(tp)
    return result["path"], result["url"]
