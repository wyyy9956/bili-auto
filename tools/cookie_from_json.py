# -*- coding: utf-8 -*-
"""把浏览器插件导出的 Cookie JSON 转成 B站 需要的 Cookie 串，并写进配置。

为什么需要这个
--------------
B站 的 SESSDATA 是 HttpOnly 的，在控制台敲 ``document.cookie`` **拿不到**。
所以只能从开发者工具的「应用 / Application → Cookie」面板，或用 Cookie-Editor
这类插件导出。本脚本负责把导出的 JSON 变成 ``name=value; name=value`` 的形式。

支持两种输入
------------
1. Cookie-Editor / EditThisCookie 导出的 JSON 数组：
   ``[{"name": "SESSDATA", "value": "..."}, ...]``
2. 手动写的一行 Cookie 串：``SESSDATA=xxx; bili_jct=yyy``

用法
----
    python tools/cookie_from_json.py cookies.json --config config.json
    python tools/cookie_from_json.py cookies.json --print   # 只看，不写文件
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

# 这几个是必须的；buvid3 有就用，没有也能跑
REQUIRED = ["SESSDATA", "bili_jct"]
OPTIONAL = ["buvid3", "buvid4", "DedeUserID", "DedeUserID__ckMd5", "sid"]


def parse_input(text: str) -> Dict[str, str]:
    # 记事本 / PowerShell 保存的 UTF-8 文件常带 BOM，不去掉会解析失败
    text = text.lstrip("\ufeff").strip()
    if not text:
        return {}

    # 情况一：JSON（数组或对象）
    if text[0] in "[{":
        raw: Any = json.loads(text)
        items: List[Dict[str, Any]] = raw if isinstance(raw, list) else [raw]
        out: Dict[str, str] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("key")
            value = item.get("value")
            if name and value is not None:
                out[str(name)] = str(value)
        return out

    # 情况二：直接的 Cookie 串（忽略 # 开头的注释行，方便在文件里写说明）
    lines = [line for line in text.splitlines() if not line.strip().startswith("#")]
    body = " ".join(lines)
    out = {}
    for piece in body.split(";"):
        piece = piece.strip()
        if "=" in piece:
            key, value = piece.split("=", 1)
            out[key.strip()] = value.strip()
    return out


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="把 Cookie JSON 转成 B站 Cookie 串")
    parser.add_argument("input", help="cookies.json 或含 Cookie 串的文本文件")
    parser.add_argument("-c", "--config", default=None, help="要写入的 config.json")
    parser.add_argument("--print", dest="do_print", action="store_true", help="只打印，不写文件")
    args = parser.parse_args(argv)

    path = Path(args.input)
    if not path.exists():
        print(f"[ERROR] 文件不存在: {path}")
        return 1

    cookies = parse_input(path.read_text(encoding="utf-8"))
    if not cookies:
        print("[ERROR] 没解析出任何 Cookie")
        return 1

    missing = [name for name in REQUIRED if name not in cookies]
    if missing:
        print(f"[ERROR] 缺少必需的 Cookie: {', '.join(missing)}")
        print(f"        当前拿到: {', '.join(cookies)}")
        return 1

    ordered = [name for name in REQUIRED + OPTIONAL if name in cookies]
    # 其他不属于 B站 的（比如 msn 的）就别带进去了
    cookie_str = "; ".join(f"{name}={cookies[name]}" for name in ordered)

    print(f"解析到 {len(cookies)} 个 Cookie，其中 B站 相关 {len(ordered)} 个：")
    for name in ordered:
        value = cookies[name]
        masked = value[:6] + "..." if len(value) > 10 else value
        print(f"  {name} = {masked}")

    if args.do_print or not args.config:
        print()
        print("Cookie 串：")
        print(cookie_str)
        return 0

    cfg_path = Path(args.config)
    cfg: Dict[str, Any] = {}
    if cfg_path.exists():
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["cookie"] = cookie_str
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n已写入 {cfg_path}（注意别把这个文件提交到公开仓库）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
