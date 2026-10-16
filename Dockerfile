# syntax=docker/dockerfile:1
# 多阶段：uv 解析依赖 → 精简运行镜像（非 root）

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS deps
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project --no-dev

FROM python:3.12-slim-bookworm AS runtime
LABEL org.opencontainers.image.title="FlightLog" \
      org.opencontainers.image.description="Personal flight archive" \
      org.opencontainers.image.source="https://github.com/local/flightlog"

RUN useradd --create-home --uid 1000 --shell /usr/sbin/nologin flightlog \
    && mkdir -p /app/data \
    && chown flightlog:flightlog /app/data

WORKDIR /app

COPY --from=deps /app/.venv /app/.venv
COPY server/ /app/
COPY web/ /app/web/
COPY LICENSE docs/THIRD_PARTY_NOTICES.md /app/
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh \
    && chown -R flightlog:flightlog /app/web \
    && find /app -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FLIGHTLOG_DATA_DIR=/app/data \
    FLIGHTLOG_WEB_DIR=/app/web \
    FLIGHTLOG_HARVEST_AUTO=1 \
    FLIGHTLOG_HARVEST_LIGHT=1 \
    FLIGHTLOG_HARVEST_INTERVAL_HOURS=12 \
    FLIGHTLOG_CATALOG_AUTO=0 \
    FLIGHTLOG_CATALOG_SKIP_FAA=1

EXPOSE 8321

HEALTHCHECK --interval=60s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8321/api/health', timeout=3)"

# 以 root 进 entrypoint（修 data 权限），再降权运行
ENTRYPOINT ["/entrypoint.sh"]
