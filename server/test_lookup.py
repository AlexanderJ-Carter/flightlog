"""lookup 单元测试：机型解析 + 数字消歧（不再使用瞎猜航司列表）。"""
import lookup as L


def _stub_enrich():
    """单测不打实时 ADS-B。"""
    orig = L._attach_enthusiast
    L._attach_enthusiast = lambda r: r
    return orig


def test_parse_flight_input():
    assert L._parse_flight_input("1902") == ("", "1902")
    assert L._parse_flight_input("CA1902") == ("CA1902", "")
    assert L._parse_flight_input("ca 1902") == ("CA1902", "")


def test_aircraft_code():
    assert L._aircraft_code({"aircraft": {"iata": "A320"}}) == "A320"
    assert L._aircraft_code({}) == ""


def test_hit_includes_aircraft():
    hit = {
        "flight_date": "2026-03-01",
        "flight_iata": "CA1902",
        "departure": {"iata": "PEK", "scheduled": "08:00"},
        "arrival": {"iata": "SHA", "scheduled": "10:20"},
        "airline": {"name": "Air China"},
        "aircraft": {"iata": "A333"},
    }
    r = L._hit_to_result(hit, "CA1902", "2026-03-01")
    assert r["aircraft"] == "A333"


def test_adsbdb_number_uses_real_hits_only():
    import config_store
    import route_cache
    orig = config_store.load_keys
    orig_http = L._http_json
    config_store.load_keys = lambda: {}
    # 避免脏缓存
    route_cache.set("num:1902", {"_miss": True})

    def fake_http(url, accept_404=False):
        if "CCA1902" in url or url.endswith("/CA1902"):
            return {
                "response": {
                    "flightroute": {
                        "callsign_iata": "CA1902",
                        "airline": {"name": "Air China"},
                        "origin": {"iata_code": "URC"},
                        "destination": {"iata_code": "PEK"},
                    }
                }
            }
        if accept_404:
            return None
        return None

    L._http_json = fake_http
    orig_en = _stub_enrich()
    try:
        import sqlite3
        with sqlite3.connect(route_cache.CACHE_DB) as conn:
            conn.execute("DELETE FROM route_cache WHERE key LIKE 'num:%' OR key LIKE 'cs:%'")
        r = L.lookup_flight("1902", "2026-03-01")
        assert r.get("found") or r.get("candidates"), r
        if r.get("found"):
            assert r["flight"] == "CA1902"
            assert r["from"] == "URC"
        else:
            assert any(c["flight"] == "CA1902" for c in r["candidates"])
        assert "常见航司" not in (r.get("reason") or "")
    finally:
        config_store.load_keys = orig
        L._http_json = orig_http
        L._attach_enthusiast = orig_en


def test_lookup_iata_with_mock():
    import config_store
    orig_load = config_store.load_keys
    orig_http = L._http_json
    orig_en = _stub_enrich()
    config_store.load_keys = lambda: {"aviationstack": "test-key"}

    def fake_http(url, accept_404=False):
        assert "flight_iata=CA1902" in url
        return {
            "data": [{
                "flight_date": "2026-03-01",
                "flight": {"iata": "CA1902"},
                "departure": {"iata": "PEK", "scheduled": "08:00"},
                "arrival": {"iata": "SHA", "scheduled": "10:20"},
                "airline": {"name": "Air China"},
                "aircraft": {"iata": "A320"},
            }]
        }

    L._http_json = fake_http
    try:
        r = L.lookup_flight("CA1902", "2026-03-01")
        assert r["found"] is True
        assert r["aircraft"] == "A320"
    finally:
        config_store.load_keys = orig_load
        L._http_json = orig_http
        L._attach_enthusiast = orig_en


def test_lookup_number_multi():
    import config_store
    orig_load = config_store.load_keys
    orig_http = L._http_json
    orig_en = _stub_enrich()
    config_store.load_keys = lambda: {"aviationstack": "test-key"}

    def fake_http(url, accept_404=False):
        assert "flight_number=1902" in url
        return {
            "data": [
                {
                    "flight_date": "2026-03-01",
                    "flight": {"iata": "UA1902"},
                    "departure": {"iata": "EWR"},
                    "arrival": {"iata": "ORD"},
                    "airline": {"name": "United"},
                    "aircraft": {"iata": "B738"},
                },
                {
                    "flight_date": "2026-03-01",
                    "flight": {"iata": "CA1902"},
                    "departure": {"iata": "PEK"},
                    "arrival": {"iata": "SHA"},
                    "airline": {"name": "Air China"},
                    "aircraft": {"iata": "A333"},
                },
            ]
        }

    L._http_json = fake_http
    try:
        r = L.lookup_flight("1902", "2026-03-01")
        assert r["found"] is False
        assert r["candidates"][0]["flight"] == "CA1902"
        assert r["candidates"][0]["aircraft"] == "A333"
    finally:
        config_store.load_keys = orig_load
        L._http_json = orig_http
        L._attach_enthusiast = orig_en


def test_airports_ourairports():
    import airports
    assert airports.count() > 1000
    assert airports.known("PEK")
    assert "北京" in airports.get("PEK")["name"]
    hits = airports.search("ZBAA", 5)
    assert any(h["code"] == "PEK" for h in hits)


if __name__ == "__main__":
    test_parse_flight_input()
    test_aircraft_code()
    test_hit_includes_aircraft()
    test_adsbdb_number_uses_real_hits_only()
    test_lookup_iata_with_mock()
    test_lookup_number_multi()
    test_airports_ourairports()
    print("lookup tests OK")
