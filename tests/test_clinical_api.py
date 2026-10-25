"""Tests for clinical_api.py (openFDA service layer).

Every test uses a fake HTTP session and fake clocks: NO real network calls
are made and nothing actually sleeps.
"""

from __future__ import annotations

import sqlite3
from datetime import date

import pytest
import requests

import clinical_api as ca


# --- Fakes -------------------------------------------------------------------

class FakeClock:
    """A pretend clock: sleep() just moves time forward instantly."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class FakeResponse:
    def __init__(self, status_code: int = 200, payload=None, headers=None, bad_json: bool = False):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self._bad_json = bad_json

    def json(self):
        if self._bad_json:
            raise ValueError("not json")
        return self._payload


class FakeSession:
    """Returns queued responses (or raises queued exceptions) and records every call."""

    def __init__(self, responses=None, handler=None):
        self.responses = list(responses or [])
        self.handler = handler
        self.calls: list[tuple[str, dict, float]] = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params or {}), timeout))
        item = self.handler(url, params or {}) if self.handler else self.responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def ok(payload) -> FakeResponse:
    return FakeResponse(200, payload)


NOT_FOUND = FakeResponse(404, {"error": {"code": "NOT_FOUND", "message": "No matches found!"}})


@pytest.fixture
def make_client(tmp_path):
    """Build a client wired to fakes; returns (client, session, sleeps)."""

    def _make(session, *, api_key: str = "", cache_clock=None, pacer=None, rng=lambda: 0.0):
        sleeps: list[float] = []
        cache = ca.OpenFdaCache(tmp_path / "cache.sqlite3", clock=cache_clock or (lambda: 1_700_000_000.0))
        clock = FakeClock()
        pacer = pacer or ca.TokenBucketPacer(100, 100.0, daily_limit=None, clock=clock, sleep=clock.sleep)
        client = ca.OpenFdaClient(
            session=session, pacer=pacer, cache=cache, api_key=api_key,
            sleep=sleeps.append, rng=rng, timeout=3.0,
        )
        return client, session, sleeps

    return _make


# --- TokenBucketPacer ----------------------------------------------------------

def test_pacer_blocks_when_empty_and_refills_over_time():
    clock = FakeClock()
    pacer = ca.TokenBucketPacer(2, 1.0, daily_limit=None, clock=clock, sleep=clock.sleep)
    assert pacer.acquire() is None
    assert pacer.acquire() is None
    assert clock.sleeps == []                       # burst of 2 did not wait
    assert pacer.acquire() is None                  # bucket empty -> must wait ~1s
    assert clock.sleeps and pytest.approx(sum(clock.sleeps), abs=1e-6) == 1.0
    clock.now += 5                                  # long idle: refill, capped at capacity
    before = len(clock.sleeps)
    assert pacer.acquire() is None and pacer.acquire() is None
    assert len(clock.sleeps) == before


def test_pacer_times_out_instead_of_hanging():
    clock = FakeClock()
    pacer = ca.TokenBucketPacer(1, 0.1, daily_limit=None, clock=clock, sleep=clock.sleep)
    assert pacer.acquire() is None
    assert pacer.acquire(timeout=1.0) == "rate_limited"   # would need 10s


def test_pacer_rejects_bad_settings():
    with pytest.raises(ValueError):
        ca.TokenBucketPacer(0, 1.0)


def test_daily_limit_enforced_and_resets_at_utc_midnight():
    clock = FakeClock()
    day = {"d": date(2026, 1, 1)}
    pacer = ca.TokenBucketPacer(100, 100.0, daily_limit=3, clock=clock, sleep=clock.sleep,
                                today=lambda: day["d"])
    assert [pacer.acquire() for _ in range(3)] == [None, None, None]
    assert pacer.acquire() == "daily_limit"
    day["d"] = date(2026, 1, 2)
    assert pacer.acquire() is None
    assert pacer.daily_used == 1


def test_daily_limit_blocks_network(make_client):
    clock = FakeClock()
    pacer = ca.TokenBucketPacer(10, 10.0, daily_limit=0, clock=clock, sleep=clock.sleep)
    client, session, _ = make_client(FakeSession([ok({"results": []})]), pacer=pacer)
    res = client._get(ca.OPENFDA_LABEL_URL, {"search": "x"})
    assert res.ok is False and res.error_code == "daily_limit"
    assert session.calls == []


def test_default_daily_limits_follow_verified_openfda_numbers(tmp_path):
    cache = ca.OpenFdaCache(tmp_path / "c.sqlite3")
    no_key = ca.OpenFdaClient(session=FakeSession(), cache=cache, api_key="")
    with_key = ca.OpenFdaClient(session=FakeSession(), cache=cache, api_key="abc")
    assert no_key.pacer.daily_limit == 1_000
    assert with_key.pacer.daily_limit == 120_000
    assert ca.OPENFDA_REQUESTS_PER_MINUTE == 240
    assert no_key.pacer.refill_per_second * 60 <= 240


def test_api_key_read_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENFDA_API_KEY", "  envkey  ")
    client = ca.OpenFdaClient(session=FakeSession(), cache=ca.OpenFdaCache(tmp_path / "c.sqlite3"))
    assert client.api_key == "envkey"
    monkeypatch.delenv("OPENFDA_API_KEY")
    client = ca.OpenFdaClient(session=FakeSession(), cache=ca.OpenFdaCache(tmp_path / "c.sqlite3"))
    assert client.api_key is None


# --- Cache ---------------------------------------------------------------------

def test_cache_hit_avoids_network(make_client):
    client, session, _ = make_client(FakeSession([ok({"results": [{"a": 1}]})]))
    first = client._get(ca.OPENFDA_LABEL_URL, {"search": "x", "limit": 1})
    second = client._get(ca.OPENFDA_LABEL_URL, {"limit": 1, "search": "x"})   # order irrelevant
    assert first.ok and not first.from_cache
    assert second.ok and second.from_cache and second.data == {"results": [{"a": 1}]}
    assert len(session.calls) == 1
    assert second.fetched_at and second.fetched_at.endswith("+00:00")


def test_cache_ttl_expiry_per_endpoint(make_client):
    now = {"t": 1_700_000_000.0}
    session = FakeSession(handler=lambda url, p: ok({"results": [{"url": url}]}))
    client, _, _ = make_client(session, cache_clock=lambda: now["t"])
    client._get(ca.OPENFDA_EVENT_URL, {"search": "x"})
    client._get(ca.OPENFDA_LABEL_URL, {"search": "x"})
    assert len(session.calls) == 2
    now["t"] += 2 * 24 * 3600            # 2 days later
    assert client._get(ca.OPENFDA_LABEL_URL, {"search": "x"}).from_cache   # labels live 7 days
    assert len(session.calls) == 2
    events = client._get(ca.OPENFDA_EVENT_URL, {"search": "x"})            # events live 1 day
    assert events.ok and not events.from_cache
    assert len(session.calls) == 3


def test_api_key_never_in_cache_key_or_stored_data(make_client, tmp_path):
    secret = "SECRET-KEY-123"
    client, session, _ = make_client(FakeSession([ok({"results": [{"x": 1}]})]), api_key=secret)
    res = client._get(ca.OPENFDA_LABEL_URL, {"search": "x"})
    assert res.ok
    assert session.calls[0][1]["api_key"] == secret          # sent to openFDA...
    assert ca.OpenFdaCache.make_key(ca.OPENFDA_LABEL_URL, {"search": "x", "api_key": secret}) == \
        ca.OpenFdaCache.make_key(ca.OPENFDA_LABEL_URL, {"search": "x"})
    with sqlite3.connect(tmp_path / "cache.sqlite3") as conn:
        rows = conn.execute("SELECT cache_key, endpoint, payload FROM openfda_cache").fetchall()
    assert rows and all(secret not in "".join(map(str, row)) for row in rows)
    assert secret.encode() not in (tmp_path / "cache.sqlite3").read_bytes()   # ...never stored


def test_response_echoing_secret_is_not_cached(make_client, tmp_path):
    secret = "SECRET-KEY-456"
    client, _, _ = make_client(FakeSession([ok({"meta": {"echo": secret}, "results": []})]), api_key=secret)
    assert client._get(ca.OPENFDA_LABEL_URL, {"search": "x"}).ok
    assert secret.encode() not in (tmp_path / "cache.sqlite3").read_bytes()


# --- HTTP error handling --------------------------------------------------------

def test_429_with_retry_after_then_success(make_client):
    session = FakeSession([FakeResponse(429, headers={"Retry-After": "2"}), ok({"results": []})])
    client, _, sleeps = make_client(session)
    res = client._get(ca.OPENFDA_EVENT_URL, {"search": "x"})
    assert res.ok and sleeps == [2.0] and len(session.calls) == 2


def test_429_exhausted_returns_rate_limited_with_exponential_backoff(make_client):
    session = FakeSession([FakeResponse(429) for _ in range(4)])
    client, _, sleeps = make_client(session)
    res = client._get(ca.OPENFDA_EVENT_URL, {"search": "x"})
    assert not res.ok and res.error_code == "rate_limited"
    assert sleeps == [1.0, 2.0, 4.0] and len(session.calls) == 4


def test_429_backoff_has_jitter(make_client):
    session = FakeSession([FakeResponse(429), ok({"results": []})])
    client, _, sleeps = make_client(session, rng=lambda: 0.5)
    assert client._get(ca.OPENFDA_EVENT_URL, {"search": "x"}).ok
    assert sleeps == [1.5]


def test_429_with_huge_retry_after_gives_up_immediately(make_client):
    session = FakeSession([FakeResponse(429, headers={"Retry-After": "3600"})])
    client, _, sleeps = make_client(session)
    assert client._get(ca.OPENFDA_EVENT_URL, {"search": "x"}).error_code == "rate_limited"
    assert sleeps == []


def test_404_not_found_is_empty_success_and_cached(make_client):
    client, session, _ = make_client(FakeSession([NOT_FOUND]))
    res = client._get(ca.OPENFDA_ENFORCEMENT_URL, {"search": "x"})
    assert res.ok and res.data["results"] == [] and res.error_code is None
    again = client._get(ca.OPENFDA_ENFORCEMENT_URL, {"search": "x"})
    assert again.ok and again.from_cache and len(session.calls) == 1


def test_404_without_not_found_body_is_error(make_client):
    client, _, _ = make_client(FakeSession([FakeResponse(404, bad_json=True)]))
    assert client._get(ca.OPENFDA_LABEL_URL, {"search": "x"}).error_code == "http_404"


def test_5xx_retried_once_then_server_error(make_client):
    client, session, _ = make_client(FakeSession([FakeResponse(503), FakeResponse(500)]))
    assert client._get(ca.OPENFDA_LABEL_URL, {"search": "x"}).error_code == "server_error"
    assert len(session.calls) == 2


def test_5xx_then_success(make_client):
    client, _, _ = make_client(FakeSession([FakeResponse(502), ok({"results": []})]))
    assert client._get(ca.OPENFDA_LABEL_URL, {"search": "x"}).ok


def test_400_bad_request_reports_status(make_client):
    client, _, _ = make_client(FakeSession([FakeResponse(400, {"error": {"code": "BAD_REQUEST"}})]))
    assert client._get(ca.OPENFDA_LABEL_URL, {"search": "x"}).error_code == "http_400"


@pytest.mark.parametrize(
    "exc, code",
    [
        (requests.Timeout("slow"), "timeout"),
        (requests.ConnectTimeout("slow connect"), "timeout"),
        (requests.ConnectionError("no route"), "network_error"),
    ],
)
def test_timeout_and_network_errors(make_client, exc, code):
    client, _, _ = make_client(FakeSession([exc]))
    res = client._get(ca.OPENFDA_LABEL_URL, {"search": "x"})
    assert not res.ok and res.error_code == code and res.data_sources


def test_invalid_json(make_client):
    client, _, _ = make_client(FakeSession([FakeResponse(200, bad_json=True)]))
    assert client._get(ca.OPENFDA_LABEL_URL, {"search": "x"}).error_code == "invalid_json"
    client, _, _ = make_client(FakeSession([ok(["not", "a", "dict"])]))
    assert client._get(ca.OPENFDA_SHORTAGES_URL, {"search": "x"}).error_code == "invalid_json"


def test_timeout_value_passed_to_session(make_client):
    client, session, _ = make_client(FakeSession([ok({"results": []})]))
    client._get(ca.OPENFDA_LABEL_URL, {"search": "x"})
    assert session.calls[0][2] == 3.0


# --- Query helpers ----------------------------------------------------------------

def test_faers_uses_exact_meddra_count_and_has_causation_caveat(make_client):
    payload = {"results": [{"term": "NAUSEA", "count": 50}, {"term": "DIFFICULTY SLEEPING", "count": 80},
                           {"term": "", "count": 3}, {"term": "BAD", "count": "x"}]}
    client, session, _ = make_client(FakeSession([ok(payload)]))
    res = ca.get_top_adverse_reactions("Metformin", limit=5, client=client)
    url, params, _ = session.calls[0]
    assert url == ca.OPENFDA_EVENT_URL
    assert params["count"] == "patient.reaction.reactionmeddrapt.exact"
    assert params["search"] == 'patient.drug.openfda.generic_name:"metformin"'
    assert params["limit"] == 5
    assert res.ok and res.data == [("DIFFICULTY SLEEPING", 80), ("NAUSEA", 50)]
    text = " ".join(res.limitations).lower()
    assert "do not establish" in text and "caus" in text and "duplicated" in text


def test_label_sections_parsing_fallback_and_truncation(make_client):
    long_text = "word " * 600                                  # ~3,000 chars
    label = {
        "boxed_warning": ["WARNING: LACTIC ACIDOSIS ..."],
        "contraindications": ["Severe renal impairment.", "Hypersensitivity."],
        "warnings_and_cautions": [long_text],
        "drug_interactions": ["7 DRUG INTERACTIONS   Carbonic anhydrase inhibitors..."],
        "effective_time": "20240515",
        "set_id": "abc-123",
        "openfda": {"brand_name": ["GLUCOPHAGE"], "generic_name": ["METFORMIN HYDROCHLORIDE"]},
    }
    client, session, _ = make_client(FakeSession([ok({"results": [label]})]))
    res = ca.get_label_safety_sections("metformin", client=client)
    search = session.calls[0][1]["search"]
    for field_name in ("openfda.generic_name", "openfda.brand_name", "openfda.substance_name"):
        assert f'{field_name}:"metformin"' in search
    d = res.data
    assert res.ok and d["found"] is True
    assert d["boxed_warning"].startswith("WARNING")
    assert d["contraindications"] == "Severe renal impairment. Hypersensitivity."
    assert len(d["warnings"]) <= ca.MAX_SECTION_CHARS + 1 and d["warnings"].endswith("\u2026")
    assert d["truncated_sections"] == ["warnings"]
    assert d["drug_interactions"] == "7 DRUG INTERACTIONS Carbonic anhydrase inhibitors..."
    assert d["effective_time"] == "2024-05-15" and d["set_id"] == "abc-123"
    assert d["brand_names"] == ["GLUCOPHAGE"] and d["generic_names"] == ["METFORMIN HYDROCHLORIDE"]


def test_label_prefers_warnings_over_warnings_and_cautions(make_client):
    label = {"warnings": ["Old-style warnings."], "warnings_and_cautions": ["New-style."]}
    client, _, _ = make_client(FakeSession([ok({"results": [label]})]))
    d = ca.get_label_safety_sections("aspirin", client=client).data
    assert d["warnings"] == "Old-style warnings." and d["boxed_warning"] is None


def test_label_not_found(make_client):
    client, _, _ = make_client(FakeSession([NOT_FOUND]))
    res = ca.get_label_safety_sections("zzzz", client=client)
    assert res.ok and res.data == {"found": False, "query": "zzzz"}


def test_recalls_filtered_to_ongoing_with_formatted_dates(make_client):
    payload = {"results": [
        {"recall_number": "D-1", "classification": "Class II", "status": "Ongoing",
         "reason_for_recall": "Failed dissolution", "product_description": "Metformin ER " + "x" * 500,
         "recall_initiation_date": "20230110", "recalling_firm": "Acme", "code_info": "Lot 123"},
        {"recall_number": "D-2", "status": "Terminated", "recall_initiation_date": "20240101"},
        {"recall_number": "D-3", "classification": "Class I", "status": "Ongoing",
         "recall_initiation_date": "20240301", "recalling_firm": "Beta"},
    ]}
    client, session, _ = make_client(FakeSession([ok(payload)]))
    res = ca.get_active_recalls("metformin", client=client)
    assert 'openfda.generic_name:"metformin" AND status:"Ongoing"' == session.calls[0][1]["search"]
    assert [r["recall_number"] for r in res.data] == ["D-3", "D-1"]     # newest first, D-2 dropped
    first_old = res.data[1]
    assert first_old["recall_initiation_date"] == "2023-01-10"
    assert len(first_old["product_description"]) <= ca.MAX_SHORT_TEXT_CHARS + 1
    assert first_old["code_info"] == "Lot 123"
    assert any("lot" in lim.lower() for lim in res.limitations)


def test_recalls_fall_back_to_product_description(make_client):
    hit = {"results": [{"recall_number": "D-9", "status": "Ongoing", "recall_initiation_date": "20240202"}]}
    client, session, _ = make_client(FakeSession([NOT_FOUND, ok(hit)]))
    res = ca.get_active_recalls("lisinopril", client=client)
    assert session.calls[1][1]["search"] == 'product_description:"lisinopril" AND status:"Ongoing"'
    assert res.ok and res.data[0]["recall_number"] == "D-9"


def test_recalls_no_fallback_after_error(make_client):
    client, session, _ = make_client(FakeSession([requests.ConnectionError("down")]))
    res = ca.get_active_recalls("lisinopril", client=client)
    assert res.error_code == "network_error" and len(session.calls) == 1


def test_shortage_parsing_is_defensive(make_client):
    payload = {"results": [
        {"generic_name": "Amoxicillin", "status": "Current", "availability": "Limited",
         "dosage_form": "Capsule", "shortage_reason": "Demand increase", "update_date": "03/15/2024"},
        {"proprietary_name": "Brandx", "updated_date": "2024-04-01"},
    ]}
    client, session, _ = make_client(FakeSession([ok(payload)]))
    res = ca.get_shortage_status("amoxicillin", client=client)
    assert session.calls[0][1]["search"] == 'generic_name:"amoxicillin"'
    assert res.data[0] == {"generic_name": "Amoxicillin", "status": "Current", "availability": "Limited",
                           "dosage_form": "Capsule", "shortage_reason": "Demand increase",
                           "update_date": "2024-03-15"}
    assert res.data[1]["generic_name"] == "Brandx" and res.data[1]["update_date"] == "2024-04-01"
    assert res.data[1]["status"] is None


def test_build_safety_profile_isolates_failures(make_client):
    def handler(url, params):
        if url == ca.OPENFDA_EVENT_URL:
            raise requests.Timeout("slow")
        if url == ca.OPENFDA_SHORTAGES_URL:
            return FakeResponse(200, bad_json=True)
        if url == ca.OPENFDA_LABEL_URL:
            return ok({"results": [{"boxed_warning": ["Box"]}]})
        return NOT_FOUND

    client, _, _ = make_client(FakeSession(handler=handler))
    profile = ca.build_safety_profile("warfarin", client=client)
    assert profile.query == "warfarin"
    assert profile.label.ok and profile.label.data["boxed_warning"] == "Box"
    assert profile.recalls.ok and profile.recalls.data == []
    assert profile.errors == {"adverse_reactions": "timeout", "shortages": "invalid_json"}
    assert profile.disclaimer == ca.OPENFDA_DISCLAIMER
    assert profile.disclaimer.startswith("Do not rely on openFDA to make decisions regarding medical care.")
    assert len(profile.data_sources) == 4 and profile.any_ok
    assert any("causation" in lim or "caused" in lim for lim in profile.limitations)


def test_build_safety_profile_survives_unexpected_exception(make_client, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("bug")

    monkeypatch.setattr(ca, "get_top_adverse_reactions", boom)
    client, _, _ = make_client(FakeSession(handler=lambda url, p: NOT_FOUND))
    profile = ca.build_safety_profile("warfarin", client=client)
    assert profile.errors == {"adverse_reactions": "unexpected_error"}
    assert profile.label.ok and profile.recalls.ok and profile.shortages.ok


# --- sanitize_drug_query ------------------------------------------------------------

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("  Metformin  ", "metformin"),
        ('metformin" OR openfda.brand_name:"x', "metformin or openfda.brand name x"),
        ("war\u200bfa\u200drin\ufeff", "warfarin"),                  # zero-width chars removed
        ("\ufb01nasteride", "finasteride"),                          # ligature fi
        ("\uff21\uff53\uff50\uff49\uff52\uff49\uff4e", "aspirin"),    # full-width letters
        ("a+b-c&&d||e!(f){g}[h]^i~j*k?l:m\\n/o", "a b c d e f g h i j k l m n o"),
        ("co-trimoxazole\n\t 800", "co trimoxazole 800"),
        ("\u201cIbuprofen\u201d", "ibuprofen"),
    ],
)
def test_sanitize_drug_query_cleans(raw, expected):
    cleaned = ca.sanitize_drug_query(raw)
    assert cleaned == expected
    for bad in '+-&|!(){}[]^"~*?:\\/':
        assert bad not in cleaned


@pytest.mark.parametrize("raw", ["", "   ", '"":()', "\u200b\u200b", "a" * 81, None, 42, "x" * 5000])
def test_sanitize_drug_query_rejects(raw):
    assert ca.sanitize_drug_query(raw) is None


def test_invalid_query_never_hits_network(make_client):
    client, session, _ = make_client(FakeSession())
    res = ca.get_label_safety_sections('"::"', client=client)
    assert res.error_code == "invalid_query" and session.calls == []


# --- Offline mode ---------------------------------------------------------------------

def test_offline_without_cache_returns_offline(make_client):
    client, session, _ = make_client(FakeSession())
    res = ca.get_shortage_status("amoxicillin", client=client, use_network=False)
    assert not res.ok and res.error_code == "offline" and session.calls == []


def test_offline_with_stale_cache_returns_saved_copy(make_client):
    now = {"t": 1_700_000_000.0}
    payload = {"results": [{"term": "NAUSEA", "count": 5}]}
    client, session, _ = make_client(FakeSession([ok(payload)]), cache_clock=lambda: now["t"])
    assert ca.get_top_adverse_reactions("metformin", client=client).ok
    now["t"] += 30 * 24 * 3600                       # far past the 1-day TTL
    res = ca.get_top_adverse_reactions("metformin", client=client, use_network=False)
    assert res.ok and res.from_cache and res.data == [("NAUSEA", 5)]
    assert any("Offline" in lim for lim in res.limitations)
    assert len(session.calls) == 1


def test_offline_profile_reports_offline_for_every_section(make_client):
    client, session, _ = make_client(FakeSession())
    profile = ca.build_safety_profile("metformin", client=client, use_network=False)
    assert set(profile.errors.values()) == {"offline"} and len(profile.errors) == 4
    assert session.calls == [] and not profile.any_ok

