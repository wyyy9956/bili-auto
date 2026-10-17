# -*- coding: utf-8 -*-
"""配置加载。

优先级：``--config`` 文件  >  环境变量  >  内置默认值

环境变量（给 GitHub Actions / Docker 用，避免把 Cookie 写进仓库）：

    BILI_COOKIE          账号 Cookie（整串，必须包含 SESSDATA 和 bili_jct）
    BILI_NOTIFY_TYPE     通知渠道：none / serverchan / pushplus / telegram / webhook
    BILI_NOTIFY_KEY      对应渠道的 key
    BILI_COIN_NUM        每日投币数（1 或 2）
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

DEFAULT_CONFIG: Dict[str, Any] = {
    # 整串 Cookie。至少要有 SESSDATA（登录态）和 bili_jct（CSRF）
    "cookie": "",
    "timeout": 15,
    # 两次请求的最小间隔（秒），别调太小
    "min_interval": 1.0,
    "retry": {"attempts": 3, "backoff": 2.0},
    "user_agent": "",
    "daily": {
        "check_login": True,
        "watch_video": True,
        "share_video": True,
        "like": True,
        # 投币会消耗自己的硬币，默认关闭（白嫖模式）
        "coin": False,
        # 每天投几个币：1 个得 10 经验，2 个得 20 经验，上限 2
        "coin_num": 1,
        "claim_reward": True,
        "live_sign": True,
    },
    "notify": {"type": "none", "key": ""},
}


def _deep_merge(base: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def apply_env(cfg: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(cfg)

    cookie = os.environ.get("BILI_COOKIE", "").strip()
    if cookie:
        out["cookie"] = cookie

    notify_type = os.environ.get("BILI_NOTIFY_TYPE", "").strip()
    if notify_type:
        out.setdefault("notify", {})["type"] = notify_type

    notify_key = os.environ.get("BILI_NOTIFY_KEY", "").strip()
    if notify_key:
        out.setdefault("notify", {})["key"] = notify_key

    coin_num = os.environ.get("BILI_COIN_NUM", "").strip()
    if coin_num.isdigit():
        out.setdefault("daily", {})["coin_num"] = int(coin_num)

    return out


def load_config(path: Optional[str] = None) -> Dict[str, Any]:
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    if path:
        file_path = Path(path)
        if not file_path.exists():
            raise FileNotFoundError(f"配置文件不存在: {file_path}")
        raw = json.loads(file_path.read_text(encoding="utf-8"))
        raw.pop("_comment", None)
        cfg = _deep_merge(cfg, raw)
    return apply_env(cfg)
