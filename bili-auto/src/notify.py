# -*- coding: utf-8 -*-
"""执行结果推送。支持 Server酱 / PushPlus / Telegram / 自定义 webhook。"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any, Dict


def _post_json(url: str, payload: Dict[str, Any], timeout: int = 15) -> str:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def _post_form(url: str, payload: Dict[str, Any], timeout: int = 15) -> str:
    data = urllib.parse.urlencode(payload).encode()
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def send(cfg: Dict[str, Any], title: str, content: str) -> bool:
    """按配置推送，成功返回 True。任何异常都吞掉，不能影响打卡本身。"""
    notify = cfg.get("notify") or {}
    kind = (notify.get("type") or "none").strip().lower()
    key = (notify.get("key") or "").strip()

    if kind in ("", "none") or not key:
        return False

    try:
        if kind == "serverchan":
            # key 形如 SCT123456Txxxxxxxx
            _post_form(f"https://sctapi.ftqq.com/{key}.send", {"title": title, "desp": content})
            return True

        if kind == "pushplus":
            _post_json(
                "https://www.pushplus.plus/send",
                {"token": key, "title": title, "content": content, "template": "txt"},
            )
            return True

        if kind == "telegram":
            # key 形如 "bot_token|chat_id"
            token, _, chat_id = key.partition("|")
            _post_json(
                f"https://api.telegram.org/bot{token}/sendMessage",
                {"chat_id": chat_id, "text": f"{title}\n\n{content}"},
            )
            return True

        if kind == "webhook":
            _post_json(key, {"title": title, "content": content})
            return True
    except Exception as exc:  # noqa: BLE001
        print(f"[notify] 推送失败（不影响打卡）: {exc}")
        return False

    print(f"[notify] 未知的通知类型: {kind}")
    return False
