#!/bin/sh
set -e
DATA_DIR="${FLIGHTLOG_DATA_DIR:-/app/data}"
mkdir -p "$DATA_DIR" "$DATA_DIR/cache"

# 单进程、有限并发：个人档案场景足够，省内存
UVICORN_ARGS="app:app --host 0.0.0.0 --port 8321 --proxy-headers --workers 1 --limit-concurrency 64 --timeout-keep-alive 30"

# 卷挂载时修正属主，再降权为非 root
if [ "$(id -u)" = "0" ]; then
  chown -R flightlog:flightlog "$DATA_DIR" 2>/dev/null || true
  # shellcheck disable=SC2086
  exec setpriv --reuid=flightlog --regid=flightlog --init-groups -- \
    uvicorn $UVICORN_ARGS
fi

# shellcheck disable=SC2086
exec uvicorn $UVICORN_ARGS
