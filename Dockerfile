FROM python:3.11-slim

WORKDIR /app

COPY server/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 后端代码 + 前端页面（单容器同时提供 API 和 Web UI）
COPY server/app.py server/db.py server/lookup.py server/extract.py ./
COPY web/ /app/web/

# SQLite 数据目录（compose 挂载持久化）
RUN mkdir -p /app/data
ENV FLIGHTLOG_DATA_DIR=/app/data \
    FLIGHTLOG_WEB_DIR=/app/web

EXPOSE 8321

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8321/api/stats', timeout=2)" || exit 1

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8321"]
