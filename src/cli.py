# -*- coding: utf-8 -*-
"""命令行入口。

    python run.py check                 看看 Cookie 还有效吗
    python run.py wbi                   看看当前 WBI key
    python run.py daily                 执行每日任务
    python run.py daily --dry-run       只列出要做什么
    python run.py daily --only coin     只投币
    python run.py init                  生成配置模板
    python run.py selftest              校验 WBI 算法（联网）
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import config as config_mod
from . import notify as notify_mod
from . import tasks as tasks_mod
from . import wbi as wbi_mod
from .client import API, ApiError, BiliClient


def _load(args: argparse.Namespace) -> Dict[str, Any]:
    try:
        return config_mod.load_config(getattr(args, "config", None))
    except FileNotFoundError as exc:
        print(f"[ERROR] {exc}")
        sys.exit(2)


def _make_client(cfg: Dict[str, Any]) -> BiliClient:
    if not (cfg.get("cookie") or "").strip():
        print(
            "[ERROR] 没有配置 Cookie。\n"
            "        方式一：在配置文件里填 cookie 字段\n"
            "        方式二：设置环境变量 BILI_COOKIE\n"
            "        Cookie 至少需要包含 SESSDATA 和 bili_jct 两个值。"
        )
        sys.exit(2)
    return BiliClient(cfg, verbose=True)


def cmd_check(args: argparse.Namespace) -> int:
    cfg = _load(args)
    client = _make_client(cfg)
    try:
        message = tasks_mod.task_check_login(client, cfg)
    except ApiError as exc:
        print(f"[FAIL] {exc}")
        if exc.code == -101:
            print("       Cookie 已过期，请重新从浏览器里取一次。")
        return 1
    print(f"[OK] {message}")
    return 0


def cmd_wbi(args: argparse.Namespace) -> int:
    cfg = _load(args)
    # 取 wbi key 不需要 Cookie，所以这里不强制要求
    client = BiliClient(cfg, verbose=False)
    try:
        mixin = client._wbi_signer.refresh()
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] 取 WBI key 失败: {exc}")
        return 1

    signer = client._wbi_signer
    print(f"img_key   = {signer._img_key}")
    print(f"sub_key   = {signer._sub_key}")
    print(f"mixin_key = {mixin}")

    if getattr(args, "params", None):
        params = {}
        for piece in args.params.split("&"):
            if "=" in piece:
                key, value = piece.split("=", 1)
                params[key] = value
        print(json.dumps(signer.sign(params), ensure_ascii=False, indent=2))
    return 0


def cmd_selftest(args: argparse.Namespace) -> int:
    """用公开视频接口验证 WBI 签名是否被服务端接受。"""
    print("1. 获取 WBI key ...")
    client = BiliClient({"cookie": "", "min_interval": 0.5}, verbose=False)
    try:
        signer = client._wbi_signer
        mixin = signer.refresh()
    except Exception as exc:  # noqa: BLE001
        print(f"   [FAIL] 取 key 失败: {exc}")
        return 1
    print(f"   [OK] mixin_key = {mixin}")

    print("2. 计算签名并请求需要签名的接口 ...")
    params = signer.sign({"bvid": "BV1GJ411x7h7"})
    url = f"{API}/x/web-interface/wbi/view?{urllib.parse.urlencode(params)}"
    try:
        payload = client._send(
            "GET", url, None, "https://www.bilibili.com/"
        )
    except Exception as exc:  # noqa: BLE001
        print(f"   [FAIL] 请求失败: {exc}")
        return 1

    if payload.get("code") == 0:
        data = payload.get("data") or {}
        print(f"   [OK] 服务端接受签名，视频标题 = {data.get('title')}")
    elif payload.get("code") == -404:
        # 海外 IP（例如 GitHub Actions 的美国机房）请求视频详情会被地区限制挡掉，
        # 返回 -404「啥都木有」。签名本身是没问题的（签名错会是 -403/-352），
        # 所以这里算通过，否则 Actions 上会永远红叉。
        print("   [OK] 服务端接受签名（视频内容受地区限制不可见，不影响签名校验）")
    else:
        print(f"   [FAIL] code={payload.get('code')} message={payload.get('message')}")
        return 1

    print("\nselftest: [OK] WBI 签名算法正确")
    return 0


def cmd_daily(args: argparse.Namespace) -> int:
    cfg = _load(args)
    client = _make_client(cfg)

    only: Optional[List[str]] = None
    if args.only:
        only = [piece.strip() for piece in args.only.split(",") if piece.strip()]
        unknown = [key for key in only if key not in tasks_mod.TASK_MAP]
        if unknown:
            print(f"[ERROR] 未知任务: {', '.join(unknown)}")
            print(f"        可选: {', '.join(tasks_mod.TASK_MAP)}")
            return 2

    print("=" * 60)
    print("B站每日任务")
    started = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"时间: {started}{'   [DRY-RUN]' if args.dry_run else ''}")
    print("=" * 60)

    results = tasks_mod.run_daily(client, cfg, only=only, dry_run=args.dry_run)
    ok, total = tasks_mod.summarize(results)

    print()
    print(f"结果：成功 {ok}/{total}")
    failed = [r for r in results if not r["ok"]]
    for item in failed:
        print(f"  [FAIL] {item['title']}: {item['message']}")

    lines = [f"{r['title']}: {r['message']}" for r in results]
    notify_mod.send(cfg, f"B站每日任务 {ok}/{total}", "\n".join(lines))

    return 0 if ok == total else 1


def cmd_init(args: argparse.Namespace) -> int:
    target = Path(args.output)
    if target.exists() and not args.force:
        print(f"[ERROR] {target} 已存在，加 --force 覆盖")
        return 1
    template = config_mod.DEFAULT_CONFIG
    target.write_text(json.dumps(template, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已生成 {target}")
    print("下一步：把 cookie 字段填上（或改用环境变量 BILI_COOKIE），然后跑 check。")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bili", description="B站每日任务工具")
    sub = parser.add_subparsers(dest="command")

    p_check = sub.add_parser("check", help="检查 Cookie 是否有效")
    p_check.add_argument("-c", "--config", default=None)
    p_check.set_defaults(func=cmd_check)

    p_wbi = sub.add_parser("wbi", help="查看当前 WBI key（可选签名示例）")
    p_wbi.add_argument("-c", "--config", default=None)
    p_wbi.add_argument("-p", "--params", default=None, help='额外参数，如 "aid=1&cid=2"')
    p_wbi.set_defaults(func=cmd_wbi)

    p_self = sub.add_parser("selftest", help="校验 WBI 算法（联网）")
    p_self.set_defaults(func=cmd_selftest)

    p_daily = sub.add_parser("daily", help="执行每日任务")
    p_daily.add_argument("-c", "--config", default=None)
    p_daily.add_argument("--dry-run", action="store_true", help="只列出要做什么，不发请求")
    p_daily.add_argument("--only", default=None, help="只跑指定任务，逗号分隔")
    p_daily.set_defaults(func=cmd_daily)

    p_init = sub.add_parser("init", help="生成配置模板")
    p_init.add_argument("-o", "--output", default="config.json")
    p_init.add_argument("--force", action="store_true")
    p_init.set_defaults(func=cmd_init)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
