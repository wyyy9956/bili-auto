#!/bin/sh
# 每天在 RUN_AT（默认 09:10）执行一次每日任务。
set -eu

RUN_AT="${RUN_AT:-09:10}"
CONFIG="${CONFIG:-/app/config.json}"

# 没挂配置文件时退回内置默认配置（Cookie 从环境变量读）
if [ -f "$CONFIG" ]; then
    ARGS="--config $CONFIG"
else
    echo "[bili] 未找到 $CONFIG，使用内置默认配置"
    ARGS=""
fi

echo "[bili] 启动完成，每日执行时间(本地时区): ${RUN_AT}"

if [ "${RUN_NOW:-1}" = "1" ]; then
    echo "[bili] $(date '+%F %T') 启动即执行一次"
    python /app/run.py daily $ARGS || echo "[bili] 本次失败，等待下次"
fi

while true; do
    SECS=$(python -c '
import datetime, sys
hh, mm = sys.argv[1].split(":")
now = datetime.datetime.now()
target = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
if target <= now:
    target += datetime.timedelta(days=1)
print(int((target - now).total_seconds()))
' "$RUN_AT")

    echo "[bili] 睡眠 ${SECS}s 到下次执行"
    sleep "$SECS"

    echo "[bili] $(date '+%F %T') 开始执行"
    python /app/run.py daily $ARGS || echo "[bili] 本次失败，等待下次"
done
