# -*- coding: utf-8 -*-
"""WBI 签名（B站 2023 年起对大量接口强制要求的签名机制）。

原理
----
1. 调 ``/x/web-interface/nav`` 拿到两个 key（不需要登录）：
   ``wbi_img.img_url`` 和 ``wbi_img.sub_url``，URL 形如
   ``https://i0.hdslb.com/bfs/wbi/7cd0....png``，取文件名去掉 ``.png`` 就是 key。
2. 把 img_key 和 sub_key 拼起来（长度 64），按一张固定的乱序表重排，
   取前 32 位，得到 ``mixin_key``。
3. 请求参数按 key 升序排列，URL 编码，末尾拼上当前时间戳 ``wts``，
   再拼 ``mixin_key`` 做 MD5，得到 ``w_rid``。
4. 最终请求带上 ``wts`` 和 ``w_rid`` 两个参数。

这张乱序表是前端 JS 里硬编码的，所以算法可以完整复现。
key 会每天轮换，所以必须动态取，不能写死。
"""

from __future__ import annotations

import hashlib
import re
import time
import urllib.parse
from typing import Any, Callable, Dict, Optional

# 前端 JS 里硬编码的乱序表，共 64 项
MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
]

# 参数名里的这些字符会被剔除（和前端的正则一致）
_INVALID_KEY_CHARS = re.compile(r"[!'()*]")


def get_mixin_key(orig: str) -> str:
    """把 64 位的 img_key+sub_key 重排并截取成 32 位 mixin_key。"""
    if len(orig) != 64:
        raise ValueError(f"img_key + sub_key 长度应为 64，实际 {len(orig)}")
    return "".join(orig[i] for i in MIXIN_KEY_ENC_TAB)[:32]


def extract_keys(img_url: str, sub_url: str) -> tuple:
    """从两个 wbi 图片 URL 里取出 (img_key, sub_key)。"""
    img_key = img_url.rsplit("/", 1)[-1].split(".")[0]
    sub_key = sub_url.rsplit("/", 1)[-1].split(".")[0]
    return img_key, sub_key


def sign(params: Dict[str, Any], mixin_key: str, wts: Optional[int] = None) -> Dict[str, Any]:
    """给参数加上 ``wts`` 和 ``w_rid``，返回新字典（不修改入参）。"""
    signed = dict(params)
    signed["wts"] = int(time.time()) if wts is None else wts

    # 1. 清洗参数名，统一转字符串
    cleaned = {
        _INVALID_KEY_CHARS.sub("", str(k)): str(v)
        for k, v in signed.items()
        if v is not None
    }
    # 2. 按 key 升序排列
    ordered = sorted(cleaned.items())
    # 3. URL 编码成查询串
    query = urllib.parse.urlencode(ordered)
    # 4. 拼 mixin_key 做 MD5
    w_rid = hashlib.md5((query + mixin_key).encode("utf-8")).hexdigest()
    signed["w_rid"] = w_rid
    return signed


class WbiSigner:
    """负责获取、缓存并在必要时刷新 WBI key。

    ``fetch_nav`` 是一个返回 nav 接口 JSON 的可调用对象，由 client 注入，
    这样可以避免 wbi 模块直接依赖网络层。
    """

    # key 每天轮换，缓存保守一点，10 分钟就重取
    CACHE_SECONDS = 600

    def __init__(self, fetch_nav: Callable[[], Dict[str, Any]], verbose: bool = True):
        self._fetch_nav = fetch_nav
        self.verbose = verbose
        self._mixin_key: Optional[str] = None
        self._img_key = ""
        self._sub_key = ""
        self._fetched_at = 0.0

    def refresh(self) -> str:
        nav = self._fetch_nav()
        data = nav.get("data") or {}
        wbi_img = data.get("wbi_img") or {}
        img_url = wbi_img.get("img_url", "")
        sub_url = wbi_img.get("sub_url", "")
        if not img_url or not sub_url:
            raise RuntimeError(
                "nav 接口没有返回 wbi_img，无法签名。"
                f"原始响应: {nav}"
            )

        self._img_key, self._sub_key = extract_keys(img_url, sub_url)
        self._mixin_key = get_mixin_key(self._img_key + self._sub_key)
        self._fetched_at = time.time()

        if self.verbose:
            print(f"    [wbi] 已刷新 mixin_key = {self._mixin_key}")
        return self._mixin_key

    @property
    def mixin_key(self) -> str:
        stale = (time.time() - self._fetched_at) > self.CACHE_SECONDS
        if self._mixin_key is None or stale:
            return self.refresh()
        return self._mixin_key

    def sign(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return sign(params, self.mixin_key)
