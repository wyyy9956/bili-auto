# -*- coding: utf-8 -*-
"""B站每日任务。

每个任务是一个 ``(key, 标题, 函数)``，函数签名 ``(client, cfg) -> 说明文字``，
失败时抛 ``ApiError``。

关于「经验」
------------
B站每日任务的经验构成（2023 年之后的规则，可能继续调整）：

    观看视频   5 经验
    分享视频   5 经验
    投币       10 经验 / 币（每天最多 2 个）
    点赞       5 经验
    领取奖励   前面几项做完后，可在「每日任务」页领取 10 经验

所以本工具的价值不在于"签到"，而在于把这几步全部自动完成并领掉奖励。
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from .client import API, LIVE_API, ApiError, BiliClient

# 这些 code 表示"今天已经做过了"，不算失败
ALREADY_DONE = {
    34005: "今日投币已达上限",
    -101: "账号未登录",
    65004: "已经点过赞",
}


# 海外 IP（GitHub Actions 的美国机房等）请求热门榜、视频详情会被地区限制挡掉，
# 返回 -404「啥都木有」。这里内置一个长期存在的官方视频作为兜底，
# 保证观看 / 分享 / 点赞始终有对象可用，不至于整个流程直接失败。
FALLBACK_VIDEO = {
    "aid": 80433022,
    "bvid": "BV1GJ411x7h7",
    "cid": 137649199,
    "title": "【官方 MV】Never Gonna Give You Up - Rick Astley",
    "duration": 213,
}


def _pick_video(client: BiliClient) -> Dict[str, Any]:
    """从热门榜取第一个视频，作为今天要"看/赞/币/分享"的对象。

    取不到（网络异常、海外 IP 被地区限制、热门榜为空）时退回内置视频。
    """
    try:
        payload = client.get(
            f"{API}/x/web-interface/popular",
            params={"ps": 1, "pn": 1},
            referer="https://www.bilibili.com/v/popular/all",
        )
        items = (payload.get("data") or {}).get("list") or []
    except ApiError:
        items = []

    if items:
        video = items[0]
        # 热门榜里可能混进番剧/专栏，没有 cid 就没法做观看任务
        if video.get("cid") and video.get("aid"):
            return {
                "aid": video.get("aid"),
                "bvid": video.get("bvid"),
                "cid": video.get("cid"),
                "title": video.get("title", ""),
                "duration": video.get("duration", 0),
            }

    return dict(FALLBACK_VIDEO)


# ---------------------------------------------------------------- 具体任务


def task_check_login(client: BiliClient, cfg: Dict[str, Any]) -> str:
    payload = client.nav()
    data = payload.get("data") or {}
    if not data.get("isLogin"):
        raise ApiError(payload.get("code", -101), "Cookie 无效或已过期，请重新登录获取")
    name = data.get("uname", "?")
    level = (data.get("level_info") or {}).get("current_level", "?")
    coins = data.get("money", "?")
    vip = (data.get("vipStatus") or 0) == 1
    return f"已登录：{name}（Lv{level}，硬币 {coins}{'，大会员' if vip else ''}）"


def task_watch_video(client: BiliClient, cfg: Dict[str, Any]) -> str:
    """上报观看心跳，拿"观看视频"的 5 经验。

    真正被记账的是一次带 ``played_time`` 的心跳，所以要连发几次、
    让服务端看到"确实播放了若干秒"。
    """
    video = _pick_video(client)
    if not video.get("aid") or not video.get("cid"):
        raise ApiError(-1, "视频信息缺少 aid/cid", "popular")

    aid, cid, bvid = video["aid"], video["cid"], video["bvid"]
    start_ts = int(time.time()) - 4
    played = 0

    for i in range(3):
        played += 4
        client.post(
            f"{API}/x/click-interface/web/heartbeat",
            data={
                "aid": aid,
                "bvid": bvid,
                "cid": cid,
                "played_time": played,
                "realtime": played,
                "start_ts": start_ts,
                "type": 3,
                "sub_type": 0,
                "dt": 2,
                "play_type": 0,
            },
            referer=f"https://www.bilibili.com/video/{bvid}",
        )
        if i < 2:
            time.sleep(1.5)

    return f"已上报观看：{video['title'][:24]}（{played}s）"


def task_share_video(client: BiliClient, cfg: Dict[str, Any]) -> str:
    video = _pick_video(client)
    client.post(
        f"{API}/x/web-interface/share/add",
        data={"aid": video["aid"], "bvid": video["bvid"]},
        need_csrf=True,
        referer=f"https://www.bilibili.com/video/{video['bvid']}",
    )
    return "已分享视频"


def task_like(client: BiliClient, cfg: Dict[str, Any]) -> str:
    video = _pick_video(client)
    client.post(
        f"{API}/x/web-interface/archive/like",
        data={"aid": video["aid"], "like": 1},
        need_csrf=True,
        referer=f"https://www.bilibili.com/video/{video['bvid']}",
    )
    return "已点赞"


def task_coin(client: BiliClient, cfg: Dict[str, Any]) -> str:
    num = int((cfg.get("daily") or {}).get("coin_num") or 1)
    num = max(1, min(2, num))
    video = _pick_video(client)
    client.post(
        f"{API}/x/web-interface/coin/add",
        data={
            "aid": video["aid"],
            "bvid": video["bvid"],
            "multiply": num,
            # 投币时顺便点赞（1 表示选上，0 表示不选）
            "select_like": 0,
        },
        need_csrf=True,
        referer=f"https://www.bilibili.com/video/{video['bvid']}",
    )
    return f"已投 {num} 个币"


def task_claim_reward(client: BiliClient, cfg: Dict[str, Any]) -> str:
    """领取「每日任务」的奖励经验。"""
    payload = client.get(
        f"{API}/x/member/web/exp/reward",
        params={"csrf": client.csrf},
        referer="https://account.bilibili.com/account/home",
    )
    data = payload.get("data") or {}
    today = data.get("today_exp")
    total = data.get("total_exp")
    if today is not None:
        return f"今日已获得 {today} 经验（累计 {total}）"
    return "奖励状态已查询"


def task_live_sign(client: BiliClient, cfg: Dict[str, Any]) -> str:
    """直播区签到，主要给经验和辣条。"""
    payload = client.get(
        f"{LIVE_API}/xlive/web-ucenter/v1/sign/DoSign",
        referer="https://live.bilibili.com/",
        raise_on_error=False,
    )
    code = payload.get("code", 0)
    if code == 0:
        data = payload.get("data") or {}
        text = data.get("text") or data.get("specialText") or "签到成功"
        return f"直播签到：{text}"
    # 1011040 = 今天已签到
    if code == 1011040:
        return "直播今天已签过"
    message = payload.get("message") or payload.get("msg") or ""
    if "已" in message:
        return f"直播签到：{message}"
    raise ApiError(code, message, "live/DoSign")


# ---------------------------------------------------------------- 编排

TASKS: List[Tuple[str, str, Any]] = [
    ("check_login", "检查登录态", task_check_login),
    ("watch_video", "每日观看视频", task_watch_video),
    ("share_video", "每日分享视频", task_share_video),
    ("like", "每日点赞", task_like),
    ("coin", "每日投币", task_coin),
    ("claim_reward", "领取每日奖励", task_claim_reward),
    ("live_sign", "直播签到", task_live_sign),
]

TASK_MAP = {key: (title, func) for key, title, func in TASKS}


def run_daily(
    client: BiliClient,
    cfg: Dict[str, Any],
    only: Optional[List[str]] = None,
    dry_run: bool = False,
) -> List[Dict[str, Any]]:
    """按顺序执行启用的任务，返回结果列表。"""
    daily = cfg.get("daily") or {}
    results: List[Dict[str, Any]] = []

    selected = []
    for key, title, func in TASKS:
        if only:
            if key not in only:
                continue
        elif not daily.get(key, True):
            continue
        selected.append((key, title, func))

    for index, (key, title, func) in enumerate(selected, 1):
        print(f"[{index}/{len(selected)}] {title}", end=" ... ")
        if dry_run:
            print("dry-run 跳过")
            results.append({"key": key, "title": title, "ok": True, "message": "dry-run 未执行"})
            continue

        try:
            message = func(client, cfg)
            print(f"[OK] {message}")
            results.append({"key": key, "title": title, "ok": True, "message": message})
        except ApiError as exc:
            note = ALREADY_DONE.get(exc.code)
            if note:
                print(f"[SKIP] {note}")
                results.append({"key": key, "title": title, "ok": True, "message": note, "skipped": True})
            else:
                print(f"[FAIL] {exc}")
                results.append(
                    {"key": key, "title": title, "ok": False, "message": str(exc), "code": exc.code}
                )
        except Exception as exc:  # noqa: BLE001 网络/解析异常都归到这里
            print(f"[FAIL] {type(exc).__name__}: {exc}")
            results.append({"key": key, "title": title, "ok": False, "message": f"{type(exc).__name__}: {exc}"})

    return results


def summarize(results: List[Dict[str, Any]]) -> Tuple[int, int]:
    ok = sum(1 for r in results if r["ok"])
    return ok, len(results)
