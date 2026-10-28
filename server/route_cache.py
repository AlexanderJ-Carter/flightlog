"""航线查询本地缓存：降低对公开 API 的重复请求。"""
import json
import os
import sqlite3
import threading
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("FLIGHTLOG_DATA_DIR", os.path.join(BASE_DIR, "data"))
CACHE_DB = os.path.join(DATA_DIR, "route_cache.db")

# 典型航线相对稳定；负缓存（未命中）短一些
TTL_HIT = 7 * 24 * 3600
TTL_MISS = 6 * 3600

_lock = threading.Lock()
_ready = False


def _connect():
    os.makedirs(os.path.dirname(CACHE_DB) or ".", exist_ok=True)
    conn = sqlite3.connect(CACHE_DB, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA mmap_size=33554432")
    conn.execute("PRAGMA cache_size=-8192")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def init():
    global _ready
    with _lock:
        with _connect() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS route_cache(
                       key TEXT PRIMARY KEY,
                       payload TEXT NOT NULL,
                       updated_at REAL NOT NULL
                   )"""
            )
        _ready = True


def get(key: str):
    """返回缓存的 Python 对象；过期或不存在返回 None。"""
    if not _ready:
        init()
    now = time.time()
    with _lock:
        with _connect() as conn:
            row = conn.execute(
                "SELECT payload, updated_at FROM route_cache WHERE key=?",
                (key,),
            ).fetchone()
    if not row:
        return None
    payload, updated_at = row
    try:
        data = json.loads(payload)
    except ValueError:
        return None
    ttl = TTL_MISS if data.get("_miss") else TTL_HIT
    if now - updated_at > ttl:
        return None
    return data


def set(key: str, data: dict):
    if not _ready:
        init()
    with _lock:
        with _connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO route_cache(key, payload, updated_at) VALUES(?,?,?)",
                (key, json.dumps(data, ensure_ascii=False), time.time()),
            )


def set_miss(key: str):
    set(key, {"_miss": True})
