FROM python:3.12-alpine

ENV TZ=Asia/Shanghai \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8

# 装 ca-certificates 才能正常验证 HTTPS 证书
RUN apk add --no-cache tzdata ca-certificates \
    && cp /usr/share/zoneinfo/Asia/Shanghai /etc/localtime \
    && echo "Asia/Shanghai" > /etc/timezone

WORKDIR /app

COPY run.py /app/run.py
COPY src /app/src
COPY deploy/entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh

ENV RUN_AT=09:10

ENTRYPOINT ["/entrypoint.sh"]
