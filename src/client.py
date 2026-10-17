# -*- coding: utf-8 -*-
"""B站 API 客户端：Cookie 管理、CSRF、WBI 签名、重试和限速。

只用标准库，不依赖 requests。
"""

from __future__ import annotations

import gzip
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from typing import Any, Dict, Optional

from . import wbi

API = "https://api.bilibili.com"
LIVE_API = "https://api.live.bilibili.com"
MANGA_API = "https://manga.bilibili.com"

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# 服务端明确表示"请求被拦截 / 签名错误"的 code，遇到就刷新 WBI key 重试
WBI_ERROR_CODES = {-403, -352, -401, 352}

# 这些 code 是明确的业务结果（重复操作、未登录、超限……），
# 重试一百次也是同样的答案，只会白白拖慢流程。
NO_RETRY_CODES = {
    -101,   # 账号未登录
    -111,   # csrf 校验失败
    -400,   # 请求错误
    -404,   # 资源不存在（海外 IP 常见）
    34005,  # 今日投币已达上限
    65004,  # 已经点过赞了
    65006,  # 重复点赞
    71000,  # 重复分享
}


class ApiError(Exception):
    """B站业务错误（HTTP 200 但 code != 0）。"""

    def __init__(self, code: int, message: str, url: str = "", data: Any = None):
        self.code = code
        self.message = message
        self.url = url
        self.data = data
        super().__init__(f"code={code} message={message}")


def parse_cookie(cookie: str) -> Dict[str, str]:
    """把 Cookie 字符串解析成字典。"""
    out: Dict[str, str] = {}
    for piece in (cookie or "").split(";"):
        piece = piece.strip()
        if not piece or "=" not in piece:
            continue
        key, value = piece.split("=", 1)
        out[key.strip()] = value.strip()
    return out


class BiliClient:
    def __init__(self, cfg: Dict[str, Any], verbose: bool = True):
        self.cfg = cfg or {}
        self.verbose = verbose
        self.cookie = (self.cfg.get("cookie") or "").strip()
        self.cookies = parse_cookie(self.cookie)
        # csrf 就是 bili_jct，所有写操作都要带
        self.csrf = self.cookies.get("bili_jct", "")
        self.ua = self.cfg.get("user_agent") or DEFAULT_UA
        self.timeout = int(self.cfg.get("timeout") or 15)
        self.min_interval = float(self.cfg.get("min_interval") or 1.0)
        retry_cfg = self.cfg.get("retry") or {}
        self.attempts = int(retry_cfg.get("attempts") or 3)
        self.backoff = float(retry_cfg.get("backoff") or 2.0)

        self._last_request = 0.0
        self._wbi_signer = wbi.WbiSigner(self._fetch_nav, verbose=verbose)

    # ---------- 底层 ----------

    def _throttle(self) -> None:
        elapsed = time.time() - self._last_request
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_request = time.time()

    def _headers(self, referer: str) -> Dict[str, str]:
        headers = {
            "User-Agent": self.ua,
            "Referer": referer,
            "Accept": "application/json, text/plain, */*",
            "Accept-Encoding": "gzip, deflate",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        if self.cookie:
            headers["Cookie"] = self.cookie
        return headers

    def _send(self, method: str, url: str, data: Optional[bytes], referer: str) -> Dict[str, Any]:
        headers = self._headers(referer)
        if data is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
                encoding = (resp.headers.get("Content-Encoding") or "").lower()
                if "gzip" in encoding:
                    raw = gzip.decompress(raw)
                elif "deflate" in encoding:
                    raw = zlib.decompress(raw)
                text = raw.decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            raise ApiError(exc.code, f"HTTP {exc.code}: {body[:200]}", url) from exc

        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ApiError(-1, f"响应不是 JSON: {text[:200]}", url) from exc

    def _fetch_nav(self) -> Dict[str, Any]:
        """拿 nav 接口（不需要登录），供 WBI 取 key。"""
        return self._send(
            "GET",
            f"{API}/x/web-interface/nav",
            None,
            "https://www.bilibili.com/",
        )

    def request(
        self,
        method: str,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        need_wbi: bool = False,
        need_csrf: bool = False,
        referer: str = "https://www.bilibili.com/",
        raise_on_error: bool = True,
    ) -> Dict[str, Any]:
        """发一个请求。

        - ``need_wbi``：给 query 加 ``wts`` / ``w_rid``
        - ``need_csrf``：给 body 加 ``csrf``
        - ``raise_on_error``：code != 0 时抛 ApiError，否则原样返回
        """
        for attempt in range(1, self.attempts + 1):
            query = dict(params or {})
            if need_wbi:
                query = self._wbi_signer.sign(query)

            body = dict(data or {})
            if need_csrf:
                body["csrf"] = self.csrf

            full = url
            if query:
                full = f"{url}?{urllib.parse.urlencode(query)}"
            encoded = urllib.parse.urlencode(body).encode() if body else None

            self._throttle()
            try:
                payload = self._send(method, full, encoded, referer)
            except urllib.error.URLError as exc:
                if attempt >= self.attempts:
                    raise ApiError(-1, f"网络错误: {exc}", full) from exc
                wait = self.backoff * attempt
                print(f"    [net] 第 {attempt} 次失败（{exc}），{wait:.1f}s 后重试")
                time.sleep(wait)
                continue

            code = payload.get("code", 0)
            if code == 0 or not raise_on_error:
                return payload

            # 签名过期 → 刷新 key 再来一次
            if need_wbi and code in WBI_ERROR_CODES and attempt == 1:
                print(f"    [wbi] code={code}，刷新 key 后重试")
                self._wbi_signer.refresh()
                continue

            # 账号级 / 业务级问题，重试没有意义，直接抛给上层判定
            if code in NO_RETRY_CODES or attempt >= self.attempts:
                raise ApiError(code, payload.get("message") or payload.get("msg") or "", full, payload)

            wait = self.backoff * attempt
            print(f"    [api] code={code} {payload.get('message')}，{wait:.1f}s 后重试")
            time.sleep(wait)

        raise ApiError(-1, "重试次数用尽", url)

    # ---------- 便捷方法 ----------

    def get(self, url: str, **kwargs: Any) -> Dict[str, Any]:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> Dict[str, Any]:
        return self.request("POST", url, **kwargs)

    # ---------- 账号 ----------

    def nav(self) -> Dict[str, Any]:
        payload = self._fetch_nav()
        return payload

    def is_login(self) -> bool:
        try:
            payload = self.nav()
        except ApiError:
            return False
        return bool((payload.get("data") or {}).get("isLogin"))
