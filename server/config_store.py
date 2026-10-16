"""本地密钥配置：读写 data/api_keys.json（不回传明文给前端列表接口）。"""
import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("FLIGHTLOG_DATA_DIR", os.path.join(BASE_DIR, "data"))
KEYS_FILE = os.path.join(DATA_DIR, "api_keys.json")


def keys_path() -> str:
    return KEYS_FILE


def load_keys() -> dict:
    try:
        with open(KEYS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if isinstance(v, str) and v.strip()}
    except (OSError, ValueError):
        pass
    return {}


def save_keys(patch: dict) -> dict:
    """合并写入密钥。空字符串表示删除该键。返回状态摘要（无明文）。"""
    cur = load_keys()
    for k, v in patch.items():
        if v is None:
            continue
        v = str(v).strip()
        if not v:
            cur.pop(k, None)
        else:
            cur[k] = v
    os.makedirs(os.path.dirname(KEYS_FILE) or ".", exist_ok=True)
    with open(KEYS_FILE, "w", encoding="utf-8") as f:
        json.dump(cur, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return status()


def status() -> dict:
    k = load_keys()
    llm = bool(k.get("llm") or os.environ.get("FLIGHTLOG_LLM_KEY"))
    live = bool(k.get("aviationstack") or k.get("variflight"))
    return {
        "aviationstack": bool(k.get("aviationstack")),
        "variflight": bool(k.get("variflight")),
        "llm": llm,
        "llm_base": bool(
            k.get("llm_base") or os.environ.get("FLIGHTLOG_LLM_BASE")
        ),
        "adsbdb": True,
        "live_lookup": live,
        "providers": (
            ["adsbdb"]
            + (["aviationstack"] if k.get("aviationstack") else [])
            + (["variflight"] if k.get("variflight") else [])
            + (["llm"] if llm else [])
        ),
        "keys_file": KEYS_FILE,
    }
