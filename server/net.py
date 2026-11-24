# -*- coding: utf-8 -*-
"""
统一网络层（零第三方依赖）：
  - 三通路自适应回退（直连 → 127.0.0.1:7890 → 7897）+ 按域名粘性缓存可用通路
  - 多源并发竞速 race_fetch（VPN 开关自适配）
  - Magic Bytes 图片验真（彻底免疫 T7 0 字节与 T21 SPA 壳假 200）
  - 轻量数据源探活 probe_url
"""
import os
import ssl
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from server.config import UA

DEFAULT_PROXIES = (
    ("直连", None),
    ("代理7890", "http://127.0.0.1:7890"),
    ("代理7897", "http://127.0.0.1:7897"),
)

_SSL_CTX = ssl.create_default_context()
_HOST_CHANNEL_LOCK = threading.Lock()
_HOST_PREFERRED = {}  # host -> (tag, proxy)


class NotFoundError(Exception):
    """资源不存在（HTTP 404 或 SPA 假壳）。"""


class _RacerAbort(Exception):
    """竞速败者正常退出路径。"""


def is_valid_image_bytes(data):
    """校验图片头 Magic Bytes（PNG / JPEG / WEBP / GIF），防止 SPA HTML 壳或 0 字节落盘。"""
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
    with _HOST_CHANNEL_LOCK:
        pref = _HOST_PREFERRED.get(host)
    if pref and pref in channels:
        channels.remove(pref)
        channels.insert(0, pref)
    return host, channels


def _remember_channel(host, channel):
    with _HOST_CHANNEL_LOCK:
        _HOST_PREFERRED[host] = channel


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
    progress_cb=None,
    proxies=None,
    headers=None,
    verify_ssl=True,
):
    """三通路回退 GET：返回 (bytes, channel_tag)。
    404 或非预期 HTML 壳抛出 NotFoundError（expect_image/allow_html=False 时）。"""
    host, channels = _ordered_channels(url, proxies)
    req_headers = {"User-Agent": UA}
    if headers:
        req_headers.update(headers)

    last_err = None
    for tag, proxy in channels:
        opener = _build_opener(proxy, verify_ssl=verify_ssl)
        req = urllib.request.Request(url, headers=req_headers)
        try:
            with opener.open(req, timeout=timeout) as resp:
                ct = (resp.headers.get("Content-Type") or "").lower()
                total = int(resp.headers.get("Content-Length") or 0)
                if not allow_html and ct.startswith("text/html"):
                    raise NotFoundError(f"{url} -> SPA HTML 壳")
                chunks = []
                done = 0
                while True:
                    chunk = resp.read(131072)
                    if not chunk:
                        break
                    chunks.append(chunk)
                    done += len(chunk)
                    if progress_cb:
                        progress_cb(done, total, tag)
                data = b"".join(chunks)
            if not data:
                raise ConnectionError(f"{url} -> 空响应")
            if expect_image and not is_valid_image_bytes(data):
                raise NotFoundError(f"{url} -> 非有效图片（疑似 SPA 壳或损坏）")
            _remember_channel(host, (tag, proxy))
            return data, tag
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise NotFoundError(url) from exc
            last_err = f"{tag}: HTTP {exc.code}"
        except NotFoundError:
            raise
        except Exception as exc:  # noqa: BLE001
            last_err = f"{tag}: {exc}"
        time.sleep(0.4)
    raise ConnectionError(f"{url} -> {last_err or '全部通路失败'}")


def fetch_to_file(
    url,
    dst_path,
    timeout=60,
    expect_image=True,
    progress_cb=None,
    proxies=None,
    verify_ssl=True,
):
    """三通路流式下载并原子落盘（带图片 Magic Bytes 校验）。返回 (size, tag)。"""
    data, tag = fetch_bytes(
        url,
        timeout=timeout,
        allow_html=False,
        expect_image=expect_image,
        progress_cb=progress_cb,
        proxies=proxies,
        verify_ssl=verify_ssl,
    )
    os.makedirs(os.path.dirname(os.path.abspath(dst_path)), exist_ok=True)
    tmp = f"{dst_path}.{os.getpid()}.{threading.get_ident()}.part"
    try:
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, dst_path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
    return len(data), tag


def race_fetch(urls, progress_cb=None, budget=25, timeout=30, expect_image=False):
    """多源并发竞速 GET：先完成的源胜出，其余线程立即中止。
    返回 (bytes, winner_url)。全部 404 抛 NotFoundError，否则抛 ConnectionError。"""
    result = {"data": None, "url": None, "err": None, "not_found": 0}
    cancel = threading.Event()
    lock = threading.Lock()

    def work(url):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as resp:
                ct = (resp.headers.get("Content-Type") or "").lower()
                if expect_image and ct.startswith("text/html"):
                    raise NotFoundError(url)
                total = int(resp.headers.get("Content-Length") or 0)
                chunks = []
                done = 0
                t0 = time.time()
                while True:
                    if cancel.is_set():
                        raise _RacerAbort()
                    chunk = resp.read(131072)
                    if not chunk:
                        break
                    chunks.append(chunk)
                    done += len(chunk)
                    with lock:
                        if result["data"] is None and progress_cb:
                            progress_cb(done, total, url)
                    if time.time() - t0 > budget:
                        raise TimeoutError(f"{budget}s 预算耗尽")
                data = b"".join(chunks)
            if not data or (expect_image and not is_valid_image_bytes(data)):
                raise ConnectionError(f"{url} -> 响应无效或非图片")
            with lock:
                if result["data"] is None:
                    result["data"] = data
                    result["url"] = url
                    cancel.set()
        except _RacerAbort:
            pass
        except urllib.error.HTTPError as exc:
            with lock:
                if exc.code == 404:
                    result["not_found"] += 1
                if result["data"] is None and result["err"] is None:
                    result["err"] = f"{url} -> HTTP {exc.code}"
        except NotFoundError:
            with lock:
                result["not_found"] += 1
                if result["data"] is None and result["err"] is None:
                    result["err"] = f"{url} -> 404"
        except Exception as exc:  # noqa: BLE001
            with lock:
                if result["data"] is None and result["err"] is None:
                    result["err"] = f"{url} -> {exc}"

    threads = [threading.Thread(target=work, args=(u,), daemon=True) for u in urls]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    if result["data"] is None:
        if result["not_found"] == len(urls):
            raise NotFoundError(result["err"] or "全部源 404")
        raise ConnectionError(result["err"] or "全部源失败")
    return result["data"], result["url"]


def probe_url(url, timeout=6):
    """轻量探测数据源可达性（支持三通路回退）。返回 {ok, latencyMs, channel, status, error}。"""
    t0 = time.perf_counter()
    _, channels = _ordered_channels(url)
    last_err = ""
    for tag, proxy in channels:
        opener = _build_opener(proxy)
        req = urllib.request.Request(
            url,
            method="GET",
            headers={"User-Agent": UA, "Range": "bytes=0-63"},
        )
        try:
            with opener.open(req, timeout=timeout) as resp:
                resp.read(64)
                ms = int((time.perf_counter() - t0) * 1000)
                return {
                    "ok": True,
                    "latencyMs": ms,
                    "channel": tag,
                    "status": getattr(resp, "status", 200),
                    "error": "",
                }
        except urllib.error.HTTPError as exc:
            # 416 Range Not Satisfiable 等说明源站已响应在线
            if exc.code in (200, 206, 304, 405, 416):
                ms = int((time.perf_counter() - t0) * 1000)
                return {"ok": True, "latencyMs": ms, "channel": tag, "status": exc.code, "error": ""}
            last_err = f"{tag}: HTTP {exc.code}"
        except Exception as exc:  # noqa: BLE001
            last_err = f"{tag}: {exc}"
    return {
        "ok": False,
        "latencyMs": int((time.perf_counter() - t0) * 1000),
        "channel": "",
        "status": 0,
        "error": last_err or "连接失败",
    }
