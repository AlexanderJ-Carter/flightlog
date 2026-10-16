"""可选 LLM 辅助：航班号消歧、短信结构化。

OpenAI 兼容接口（OpenAI / DeepSeek / 硅基流动 / 本地 Ollama 等）。
配置：api_keys.json 的 llm + llm_base + llm_model，或环境变量
FLIGHTLOG_LLM_KEY / FLIGHTLOG_LLM_BASE / FLIGHTLOG_LLM_MODEL。
"""
import json
import os
import re
import urllib.error
import urllib.request

import config_store

TIMEOUT = 45


def _llm_conf():
    keys = config_store.load_keys()
    api_key = (keys.get("llm") or os.environ.get("FLIGHTLOG_LLM_KEY") or "").strip()
    base = (
        keys.get("llm_base")
        or os.environ.get("FLIGHTLOG_LLM_BASE")
        or "https://api.openai.com/v1"
    ).rstrip("/")
    model = (
        keys.get("llm_model")
        or os.environ.get("FLIGHTLOG_LLM_MODEL")
        or "gpt-4o-mini"
    )
    return api_key, base, model


def available() -> bool:
    return bool(_llm_conf()[0])


def _chat_json(system: str, user: str) -> dict | list | None:
    api_key, base, model = _llm_conf()
    if not api_key:
        return None
    body = {
        "model": model,
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "response_format": {"type": "json_object"},
    }
    # Ollama 等可能不支持 response_format，失败时降级重试一次
    raw = _post_chat(base, api_key, body)
    if raw is None:
        body.pop("response_format", None)
        raw = _post_chat(base, api_key, body)
    if not raw:
        return None
    content = ((raw.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    content = content.strip()
    # 容错：模型包了 ```json
    m = re.search(r"\{[\s\S]*\}|\[[\s\S]*\]", content)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except ValueError:
        return None


def _post_chat(base: str, api_key: str, body: dict) -> dict | None:
    url = base + "/chat/completions"
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError):
        return None


def resolve_flight_number(number: str, date_str: str) -> list[dict]:
    """纯数字航班号 → AI 候选（需人工/实时 API 再确认）。

    返回 [{flight, airline, from, to, aircraft, note}]，字段可能部分为空。
    """
    system = (
        "你是民航航班助手。根据航班数字编号与日期，推断最可能的完整 IATA 航班号"
        "（尤其中国大陆航司）。只输出 JSON："
        '{"candidates":[{"flight":"CA1902","airline":"中国国际航空",'
        '"from":"PEK","to":"SHA","aircraft":"A333","confidence":0.8,'
        '"note":"说明"}]}。最多 5 条，按可能性排序。不确定就少给，禁止编造不存在的航司码。'
    )
    user = f"航班数字编号：{number}\n日期：{date_str}\n请给出最可能的完整航班号候选。"
    data = _chat_json(system, user)
    if not isinstance(data, dict):
        return []
    rows = data.get("candidates") or []
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        flight = re.sub(r"\s+", "", str(r.get("flight") or "")).upper()
        if not re.fullmatch(r"(?:[0-9][A-Z]|[A-Z][0-9]|[A-Z]{2})\d{3,4}", flight):
            continue
        out.append({
            "flight": flight,
            "airline": str(r.get("airline") or ""),
            "from": str(r.get("from") or "").upper()[:3],
            "to": str(r.get("to") or "").upper()[:3],
            "aircraft": str(r.get("aircraft") or ""),
            "date": date_str,
            "dep_time": "",
            "arr_time": "",
            "suggested": True,
            "source": "ai",
            "note": str(r.get("note") or ""),
        })
    return out[:5]


def extract_flights(text: str) -> list[dict]:
    """短信/邮件 → 航班行列表（与 extract.extract 同构）。"""
    system = (
        "从订票短信或行程文本提取航班。只输出 JSON："
        '{"rows":[{"date":"YYYY-MM-DD","flight":"MU5101","from":"PEK",'
        '"to":"SHA","seat":"32A","note":"","aircraft":""}]}。'
        "机场用 IATA 三字码；识别不到的字段用空字符串。可多段。"
    )
    data = _chat_json(system, f"文本：\n{text}")
    if not isinstance(data, dict):
        return []
    rows = data.get("rows") or []
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        out.append({
            "date": str(r.get("date") or ""),
            "flight": re.sub(r"\s+", "", str(r.get("flight") or "")).upper(),
            "from": str(r.get("from") or "").upper()[:3],
            "to": str(r.get("to") or "").upper()[:3],
            "seat": str(r.get("seat") or ""),
            "note": str(r.get("note") or ""),
            "aircraft": str(r.get("aircraft") or ""),
        })
    return out
