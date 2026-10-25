"""Resilient, testable service layer for U.S. FDA openFDA safety data.

MedSafe uses four openFDA endpoints to give seniors extra context about a
medicine they already take:

* Drug labeling (``/drug/label.json``): boxed warning, contraindications,
  warnings and the "Drug Interactions" section (Section 7) of the label.
* Adverse event reports, FAERS (``/drug/event.json``): the reactions people
  report most often. These are reports, NOT proof that the drug caused them.
* Recalls / enforcement reports (``/drug/enforcement.json``): ongoing recalls.
* Drug shortages (``/drug/shortages.json``): whether a drug is in short supply.

Design rules enforced here:
* Every user-typed name goes through :func:`sanitize_drug_query` before it is
  placed inside an openFDA search, so odd characters cannot break the query.
* A token-bucket pacer keeps us politely under openFDA's rate limits and a
  daily counter stops us before the daily cap is reached.
* Responses are cached in SQLite so repeated screens do not re-download data
  and the app still has something to show when the internet is down.
* The optional API key is only ever sent to openFDA. It is never part of a
  cache key and never written to disk.
* Every function returns a :class:`ClinicalApiResult` instead of raising, so
  one failing endpoint can never crash the page or the other sections.
"""

from __future__ import annotations

import hashlib
import json
import random
import sqlite3
import threading
import time
import unicodedata
from contextlib import closing
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

import requests

import config

OPENFDA_LABEL_URL = "https://api.fda.gov/drug/label.json"
OPENFDA_EVENT_URL = "https://api.fda.gov/drug/event.json"
OPENFDA_ENFORCEMENT_URL = "https://api.fda.gov/drug/enforcement.json"
OPENFDA_SHORTAGES_URL = "https://api.fda.gov/drug/shortages.json"

# --- Rate limits -------------------------------------------------------------
# Verified at https://open.fda.gov/apis/authentication/ :
#   * Without an API key: 240 requests per minute and 1,000 requests per day,
#     per IP address.
#   * With an API key:    240 requests per minute and 120,000 requests per day,
#     per key.
# Some websites claim the unauthenticated limit is 40 requests/minute; that is
# outdated/wrong according to the official page above.
OPENFDA_REQUESTS_PER_MINUTE = 240
OPENFDA_DAILY_LIMIT_NO_KEY = 1_000
OPENFDA_DAILY_LIMIT_WITH_KEY = 120_000

# We stay below the ceiling on purpose: 3 requests/second = 180 per minute
# (25% headroom under 240/min), with short bursts of up to 4 requests.
DEFAULT_BURST_CAPACITY = 4
DEFAULT_REFILL_PER_SECOND = 3.0

# --- Cache lifetimes ---------------------------------------------------------
# Labels change rarely; recalls and shortages can change within a day.
CACHE_TTL_SECONDS: dict[str, float] = {
    OPENFDA_LABEL_URL: 7 * 24 * 3600,      # 7 days
    OPENFDA_EVENT_URL: 24 * 3600,          # 1 day
    OPENFDA_ENFORCEMENT_URL: 12 * 3600,    # 12 hours
    OPENFDA_SHORTAGES_URL: 12 * 3600,      # 12 hours
}
DEFAULT_CACHE_TTL_SECONDS = 24 * 3600

# --- Retry and size limits ---------------------------------------------------
MAX_RATE_LIMIT_RETRIES = 3        # retries after HTTP 429
MAX_SERVER_RETRIES = 1            # retries after HTTP 5xx
BACKOFF_BASE_SECONDS = 1.0        # 1s, 2s, 4s (+ random jitter)
MAX_RETRY_AFTER_SECONDS = 30.0    # never freeze the screen longer than this
MAX_SECTION_CHARS = 1500          # label sections are long; keep them readable
MAX_SHORT_TEXT_CHARS = 300        # recall descriptions, lot codes
MAX_QUERY_CHARS = 80              # longest drug name we accept

OPENFDA_DISCLAIMER = (
    "Do not rely on openFDA to make decisions regarding medical care. Always "
    "speak to your health provider about the risks and benefits of "
    "FDA-regulated products."
)

SOURCE_NAMES: dict[str, str] = {
    OPENFDA_LABEL_URL: "U.S. FDA openFDA Drug Labeling API (api.fda.gov/drug/label.json)",
    OPENFDA_EVENT_URL: "U.S. FDA openFDA Adverse Event Reporting System, FAERS (api.fda.gov/drug/event.json)",
    OPENFDA_ENFORCEMENT_URL: "U.S. FDA openFDA Recall Enforcement Reports (api.fda.gov/drug/enforcement.json)",
    OPENFDA_SHORTAGES_URL: "U.S. FDA openFDA Drug Shortages (api.fda.gov/drug/shortages.json)",
}

LABEL_LIMITATIONS = [
    "Label sections are shortened excerpts; read the full label on DailyMed or ask a pharmacist.",
    "The matched label may be for a different manufacturer, strength or combination product.",
]
FAERS_LIMITATIONS = [
    "FAERS reports do not establish that the drug caused the reaction.",
    "Report counts reflect reporting volume and how widely a drug is used, "
    "not how risky it is; reports may be duplicated or incomplete.",
]
RECALL_LIMITATIONS = [
    "Recalls are lot-specific: compare the lot number on your package with "
    "your pharmacist before stopping any medicine.",
]
SHORTAGE_LIMITATIONS = [
    "Shortage status reflects FDA's database at its last update; your local "
    "pharmacy may have different stock.",
]

# Error codes returned in ClinicalApiResult.error_code:
#   invalid_query, offline, daily_limit, rate_limited, server_error, timeout,
#   network_error, invalid_json, http_<status>, unexpected_error


@dataclass
class ClinicalApiResult:
    """Uniform answer from every openFDA call: data OR an error code, never an exception."""

    ok: bool
    data: Any = None
    error_code: str | None = None
    from_cache: bool = False
    fetched_at: str | None = None          # ISO-8601 UTC time the data was downloaded
    endpoint: str = ""
    data_sources: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)


@dataclass
class SafetyProfile:
    """All four openFDA sections for one medicine, each succeeding or failing on its own."""

    query: str | None
    label: ClinicalApiResult
    adverse_reactions: ClinicalApiResult
    recalls: ClinicalApiResult
    shortages: ClinicalApiResult
    data_sources: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)
    disclaimer: str = OPENFDA_DISCLAIMER

    @property
    def any_ok(self) -> bool:
        """True if at least one section returned usable data."""
        return any(r.ok for r in (self.label, self.adverse_reactions, self.recalls, self.shortages))


def _utc_today() -> date:
    """Today's date in UTC, because openFDA's daily quota resets at midnight UTC."""
    return datetime.now(timezone.utc).date()


def _iso_utc(timestamp: float) -> str:
    """Turn a Unix timestamp into a readable ISO-8601 UTC string."""
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat(timespec="seconds")


# --- Rate limiting -----------------------------------------------------------

class TokenBucketPacer:
    """Token-bucket rate limiter plus a daily request counter.

    Picture a bucket that holds ``capacity`` tokens and refills at
    ``refill_per_second``. Each request takes one token. If the bucket is
    empty we wait until it refills. This allows short bursts but keeps the
    long-run average under openFDA's limit. ``clock``/``sleep``/``today`` are
    injectable so tests can fake time and run instantly. A lock makes it safe
    when Streamlit serves several users from different threads.
    """

    def __init__(
        self,
        capacity: float = DEFAULT_BURST_CAPACITY,
        refill_per_second: float = DEFAULT_REFILL_PER_SECOND,
        daily_limit: int | None = OPENFDA_DAILY_LIMIT_NO_KEY,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        today: Callable[[], date] = _utc_today,
    ) -> None:
        if capacity <= 0 or refill_per_second <= 0:
            raise ValueError("capacity and refill_per_second must be positive")
        self.capacity = float(capacity)
        self.refill_per_second = float(refill_per_second)
        self.daily_limit = daily_limit          # None means "no daily cap"
        self._clock = clock
        self._sleep = sleep
        self._today = today
        self._lock = threading.Lock()
        self._tokens = float(capacity)          # start full
        self._last_refill = clock()
        self._day = today()
        self._daily_count = 0

    def _refill_locked(self) -> None:
        """Add tokens for the time that passed and reset the daily count at UTC midnight.

        Must be called while holding ``self._lock``.
        """
        now = self._clock()
        elapsed = max(0.0, now - self._last_refill)
        self._tokens = min(self.capacity, self._tokens + elapsed * self.refill_per_second)
        self._last_refill = now
        today = self._today()
        if today != self._day:
            self._day = today
            self._daily_count = 0

    @property
    def daily_used(self) -> int:
        """How many requests were sent today (UTC)."""
        with self._lock:
            self._refill_locked()
            return self._daily_count

    def acquire(self, timeout: float = 10.0) -> str | None:
        """Take one token, waiting if needed. Returns None on success or an error code.

        Returns ``"daily_limit"`` when today's quota is used up (so we never even
        try the network) and ``"rate_limited"`` if no token frees up within
        ``timeout`` seconds (so the screen never hangs forever).
        """
        deadline = self._clock() + timeout
        while True:
            with self._lock:
                self._refill_locked()
                if self.daily_limit is not None and self._daily_count >= self.daily_limit:
                    return "daily_limit"
                if self._tokens >= 1.0 - 1e-9:      # tiny tolerance for float rounding
                    self._tokens = max(0.0, self._tokens - 1.0)
                    self._daily_count += 1
                    return None
                wait = (1.0 - self._tokens) / self.refill_per_second
            # Sleep OUTSIDE the lock so other threads are not blocked meanwhile.
            if self._clock() + wait > deadline:
                return "rate_limited"
            self._sleep(wait)


# --- Persistent cache --------------------------------------------------------

class OpenFdaCache:
    """SQLite cache of openFDA JSON responses so we do not re-download the same data.

    Each row is keyed by a SHA-256 fingerprint of the endpoint plus the sorted
    query parameters. The ``api_key`` parameter is always removed before
    fingerprinting, so the secret never reaches the disk. Any database problem
    is swallowed: a broken cache must only make the app slower, never break it.
    """

    def __init__(self, path: Path | str | None = None, *, clock: Callable[[], float] = time.time) -> None:
        self.path = Path(path) if path else config.data_dir() / "openfda_cache.sqlite3"
        self._clock = clock
        self._lock = threading.Lock()
        self._table_ready = False

    def now(self) -> float:
        """Current wall-clock time (injectable for tests)."""
        return self._clock()

    @staticmethod
    def make_key(endpoint: str, params: dict | None) -> str:
        """Fingerprint a request. Sorting makes {a,b} and {b,a} the same; api_key is dropped."""
        safe = sorted(
            (str(k), str(v)) for k, v in (params or {}).items() if str(k).lower() != "api_key"
        )
        raw = endpoint + "?" + json.dumps(safe, ensure_ascii=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _connect(self) -> sqlite3.Connection:
        """Open the database (creating the folder and table the first time)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.path), timeout=5)
        if not self._table_ready:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS openfda_cache ("
                " cache_key TEXT PRIMARY KEY,"
                " endpoint TEXT NOT NULL,"
                " payload TEXT NOT NULL,"
                " fetched_at REAL NOT NULL)"
            )
            conn.commit()
            self._table_ready = True
        return conn

    def get(self, endpoint: str, params: dict | None, max_age_seconds: float | None) -> tuple[dict, float] | None:
        """Return (data, fetched_at) if cached and young enough; None otherwise.

        ``max_age_seconds=None`` accepts any age (used in offline mode, where an
        old copy is better than nothing).
        """
        key = self.make_key(endpoint, params)
        try:
            with self._lock, closing(self._connect()) as conn:
                row = conn.execute(
                    "SELECT payload, fetched_at FROM openfda_cache WHERE cache_key = ?", (key,)
                ).fetchone()
        except (sqlite3.Error, OSError):
            return None
        if not row:
            return None
        payload, fetched_at = row
        if max_age_seconds is not None and (self.now() - fetched_at) > max_age_seconds:
            return None
        try:
            data = json.loads(payload)
        except ValueError:
            return None
        return (data, fetched_at) if isinstance(data, dict) else None

    def put(self, endpoint: str, params: dict | None, data: dict, *, secret: str | None = None) -> float:
        """Store a response and return the time it was saved.

        If ``secret`` (the API key) somehow appears inside the response text we
        refuse to store it: secrets must never be written to disk.
        """
        fetched_at = self.now()
        try:
            payload = json.dumps(data, ensure_ascii=False)
        except (TypeError, ValueError):
            return fetched_at
        if secret and secret in payload:
            return fetched_at
        key = self.make_key(endpoint, params)
        try:
            with self._lock, closing(self._connect()) as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO openfda_cache (cache_key, endpoint, payload, fetched_at)"
                    " VALUES (?, ?, ?, ?)",
                    (key, endpoint, payload, fetched_at),
                )
                conn.commit()
        except (sqlite3.Error, OSError):
            pass
        return fetched_at

    def clear(self) -> None:
        """Delete every cached response (e.g. from a settings screen)."""
        try:
            with self._lock, closing(self._connect()) as conn:
                conn.execute("DELETE FROM openfda_cache")
                conn.commit()
        except (sqlite3.Error, OSError):
            pass


# --- HTTP client -------------------------------------------------------------

def _error_result(endpoint: str, code: str) -> ClinicalApiResult:
    """Build a failed result that still says which source we tried."""
    return ClinicalApiResult(
        ok=False, error_code=code, endpoint=endpoint,
        data_sources=[SOURCE_NAMES.get(endpoint, endpoint)],
    )


def _is_not_found_body(resp: Any) -> bool:
    """openFDA answers "no matches" with HTTP 404 and {"error": {"code": "NOT_FOUND"}}."""
    try:
        body = resp.json()
    except ValueError:
        return False
    return isinstance(body, dict) and isinstance(body.get("error"), dict) and (
        body["error"].get("code") == "NOT_FOUND"
    )


class OpenFdaClient:
    """Talks to openFDA with caching, pacing, retries and friendly error codes.

    Everything that touches the outside world (HTTP session, pacer, cache,
    sleep, random jitter) can be passed in, so tests can replace them with
    fakes and never use the real network.
    """

    def __init__(
        self,
        *,
        session: Any = None,
        pacer: TokenBucketPacer | None = None,
        cache: OpenFdaCache | None = None,
        api_key: str | None = None,
        sleep: Callable[[float], None] = time.sleep,
        rng: Callable[[], float] = random.random,
        timeout: float | None = None,
        max_rate_limit_retries: int = MAX_RATE_LIMIT_RETRIES,
        pacer_timeout: float = 10.0,
    ) -> None:
        # api_key=None means "read OPENFDA_API_KEY"; api_key="" means "no key".
        raw_key = api_key if api_key is not None else config.openfda_api_key()
        self.api_key = (raw_key or "").strip() or None
        # The stateless `requests` module is safe to share across threads.
        self.session = session if session is not None else requests
        daily = OPENFDA_DAILY_LIMIT_WITH_KEY if self.api_key else OPENFDA_DAILY_LIMIT_NO_KEY
        self.pacer = pacer if pacer is not None else TokenBucketPacer(daily_limit=daily)
        self.cache = cache if cache is not None else OpenFdaCache()
        self.timeout = timeout if timeout is not None else config.HTTP_TIMEOUT
        self.max_rate_limit_retries = max_rate_limit_retries
        self.pacer_timeout = pacer_timeout
        self._sleep = sleep
        self._rng = rng

    def _ok(self, endpoint: str, data: dict, fetched_at: float, from_cache: bool) -> ClinicalApiResult:
        """Build a successful result with its source attribution."""
        return ClinicalApiResult(
            ok=True, data=data, from_cache=from_cache, fetched_at=_iso_utc(fetched_at),
            endpoint=endpoint, data_sources=[SOURCE_NAMES.get(endpoint, endpoint)],
        )

    def _retry_delay(self, resp: Any, attempt: int) -> float | None:
        """How long to wait after HTTP 429. None means "too long, give up now".

        If the server sends ``Retry-After: <seconds>`` we obey it. Otherwise we
        use exponential backoff (1s, 2s, 4s) plus random jitter so many users
        do not all retry at the same instant.
        """
        headers = getattr(resp, "headers", None) or {}
        raw = headers.get("Retry-After")
        if raw is not None:
            try:
                seconds = float(str(raw).strip())
            except ValueError:
                seconds = -1.0      # an HTTP-date we do not parse: fall back to backoff
            if seconds >= 0:
                return seconds if seconds <= MAX_RETRY_AFTER_SECONDS else None
        return BACKOFF_BASE_SECONDS * (2 ** attempt) + self._rng() * BACKOFF_BASE_SECONDS

    def _get(self, endpoint: str, params: dict, *, use_network: bool = True) -> ClinicalApiResult:
        """Fetch JSON from openFDA: cache first, then a paced, retried network call.

        Steps: (1) fresh cache hit -> return it; (2) offline -> return any saved
        copy or "offline"; (3) wait for a pacer token; (4) GET with a timeout;
        (5) turn every failure into a short error code instead of an exception.
        """
        ttl = CACHE_TTL_SECONDS.get(endpoint, DEFAULT_CACHE_TTL_SECONDS)
        hit = self.cache.get(endpoint, params, ttl)
        if hit:
            return self._ok(endpoint, hit[0], hit[1], from_cache=True)

        if not use_network:
            stale = self.cache.get(endpoint, params, None)
            if stale:
                result = self._ok(endpoint, stale[0], stale[1], from_cache=True)
                result.limitations.append(
                    f"Offline: showing a saved copy from {result.fetched_at}; it may be out of date."
                )
                return result
            return _error_result(endpoint, "offline")

        # The key is added only to the outgoing request, never to `params`
        # (which is what the cache fingerprints).
        request_params = dict(params)
        if self.api_key:
            request_params["api_key"] = self.api_key

        rate_retries = 0
        server_retries = 0
        while True:
            pacer_error = self.pacer.acquire(self.pacer_timeout)
            if pacer_error:
                return _error_result(endpoint, pacer_error)
            try:
                resp = self.session.get(endpoint, params=request_params, timeout=self.timeout)
            except requests.Timeout:            # check Timeout first: ConnectTimeout is both
                return _error_result(endpoint, "timeout")
            except requests.RequestException:
                return _error_result(endpoint, "network_error")

            status = int(getattr(resp, "status_code", 0) or 0)
            if status == 429:
                if rate_retries >= self.max_rate_limit_retries:
                    return _error_result(endpoint, "rate_limited")
                delay = self._retry_delay(resp, rate_retries)
                if delay is None:
                    return _error_result(endpoint, "rate_limited")
                rate_retries += 1
                self._sleep(delay)
                continue
            if 500 <= status < 600:
                if server_retries >= MAX_SERVER_RETRIES:
                    return _error_result(endpoint, "server_error")
                server_retries += 1
                self._sleep(BACKOFF_BASE_SECONDS)
                continue
            if status == 404:
                if _is_not_found_body(resp):
                    # "No matches" is a real answer, so cache it as an empty result.
                    empty = {"meta": {}, "results": []}
                    fetched = self.cache.put(endpoint, params, empty, secret=self.api_key)
                    return self._ok(endpoint, empty, fetched, from_cache=False)
                return _error_result(endpoint, "http_404")
            if status >= 400 or status < 200:
                return _error_result(endpoint, f"http_{status}")

            try:
                data = resp.json()
            except ValueError:
                return _error_result(endpoint, "invalid_json")
            if not isinstance(data, dict):
                return _error_result(endpoint, "invalid_json")
            fetched = self.cache.put(endpoint, params, data, secret=self.api_key)
            return self._ok(endpoint, data, fetched, from_cache=False)


_DEFAULT_CLIENT: OpenFdaClient | None = None
_DEFAULT_CLIENT_LOCK = threading.Lock()


def get_default_client() -> OpenFdaClient:
    """One shared client for the whole app, so every page shares one pacer and cache."""
    global _DEFAULT_CLIENT
    with _DEFAULT_CLIENT_LOCK:
        if _DEFAULT_CLIENT is None:
            _DEFAULT_CLIENT = OpenFdaClient()
        return _DEFAULT_CLIENT


# --- Input cleaning & small parsing helpers ----------------------------------

# Characters with special meaning in openFDA's (Lucene/Elasticsearch) search
# syntax: + - && || ! ( ) { } [ ] ^ " ~ * ? : \ /
_LUCENE_SPECIALS = frozenset('+-&|!(){}[]^"~*?:\\/')
_EXTRA_QUOTES = frozenset("'`\u00b4\u2018\u2019\u201a\u201b\u201c\u201d\u201e\u201f")


def sanitize_drug_query(raw: Any) -> str | None:
    """Clean a typed or OCR'd drug name so it is safe inside an openFDA phrase search.

    Why: a stray quote, colon or bracket would change the meaning of the
    search (or make openFDA reject it), and invisible zero-width characters
    from copy/paste would make an exact match fail. Returns the cleaned,
    lowercase name, or None if nothing usable is left or it is too long.
    """
    if not isinstance(raw, str) or len(raw) > 10 * MAX_QUERY_CHARS:
        return None
    text = unicodedata.normalize("NFKC", raw)   # e.g. ligature "\ufb01" -> "fi", full-width -> ASCII
    chars: list[str] = []
    for ch in text:
        category = unicodedata.category(ch)
        if category == "Cf":                    # zero-width space/joiner, BOM, soft hyphen
            continue
        if ch in _LUCENE_SPECIALS or ch in _EXTRA_QUOTES:
            chars.append(" ")
        elif category[0] in "LN" or ch in ".,":  # letters, digits and harmless punctuation
            chars.append(ch)
        else:                                    # spaces, control chars, other symbols
            chars.append(" ")
    cleaned = " ".join("".join(chars).split()).lower()
    if not cleaned or len(cleaned) > MAX_QUERY_CHARS or not any(c.isalnum() for c in cleaned):
        return None
    return cleaned


def _phrase_search(query: str, fields: tuple[str, ...]) -> str:
    """Build `field:"query" OR field2:"query"`; quotes make multi-word names one phrase."""
    return " OR ".join(f'{name}:"{query}"' for name in fields)


def _results(data: Any) -> list[dict]:
    """Safely pull the `results` list out of an openFDA response."""
    rows = data.get("results") if isinstance(data, dict) else None
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def _clean_text(value: Any) -> str | None:
    """Label fields arrive as lists of paragraphs; join them and squash extra spaces."""
    if isinstance(value, list):
        value = " ".join(v for v in value if isinstance(v, str))
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    return text or None


def _truncate(text: str, limit: int) -> tuple[str, bool]:
    """Shorten text to about `limit` characters at a word boundary. Returns (text, was_cut)."""
    if len(text) <= limit:
        return text, False
    cut = text[:limit]
    space = cut.rfind(" ")
    if space > limit * 0.8:
        cut = cut[:space]
    return cut.rstrip() + "\u2026", True


def _format_date(raw: Any) -> str | None:
    """Normalize openFDA dates ('20240515', '2024-05-15', '05/15/2024') to 'YYYY-MM-DD'."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    for piece, fmt in ((text[:8], "%Y%m%d"), (text[:10], "%Y-%m-%d"), (text[:10], "%m/%d/%Y")):
        try:
            return datetime.strptime(piece, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _first_text(record: dict, *keys: str) -> str | None:
    """Return the first non-empty value among several possible field names."""
    for key in keys:
        text = _clean_text(record.get(key))
        if text:
            return text
    return None


def _with_limitations(result: ClinicalApiResult, extra: list[str], data: Any = None) -> ClinicalApiResult:
    """Copy a raw result, attaching parsed data (if ok) and the section's caveats."""
    return replace(
        result,
        data=data if result.ok else None,
        limitations=list(result.limitations) + list(extra),
        data_sources=list(result.data_sources),
    )


# --- Query helpers -----------------------------------------------------------

def get_label_safety_sections(
    name: str, *, client: OpenFdaClient | None = None, use_network: bool = True
) -> ClinicalApiResult:
    """Fetch the most safety-relevant sections of the official FDA label.

    Returns a dict with ``found``, ``boxed_warning``, ``contraindications``,
    ``warnings`` (falls back to ``warnings_and_cautions`` on newer labels),
    ``drug_interactions`` (Section 7), ``effective_time``, ``set_id``,
    ``brand_names``, ``generic_names`` and ``truncated_sections`` (which
    sections were shortened to keep them readable).
    """
    query = sanitize_drug_query(name)
    if query is None:
        return _with_limitations(_error_result(OPENFDA_LABEL_URL, "invalid_query"), LABEL_LIMITATIONS)
    client = client or get_default_client()
    search = _phrase_search(query, ("openfda.generic_name", "openfda.brand_name", "openfda.substance_name"))
    raw = client._get(OPENFDA_LABEL_URL, {"search": search, "limit": 1}, use_network=use_network)
    if not raw.ok:
        return _with_limitations(raw, LABEL_LIMITATIONS)

    rows = _results(raw.data)
    if not rows:
        return _with_limitations(raw, LABEL_LIMITATIONS, {"found": False, "query": query})
    label = rows[0]
    meta = label.get("openfda") if isinstance(label.get("openfda"), dict) else {}
    parsed: dict[str, Any] = {"found": True, "query": query, "truncated_sections": []}
    sections = {
        "boxed_warning": ("boxed_warning",),
        "contraindications": ("contraindications",),
        "warnings": ("warnings", "warnings_and_cautions"),
        "drug_interactions": ("drug_interactions",),
    }
    for out_key, source_keys in sections.items():
        text = _first_text(label, *source_keys)
        if text:
            text, was_cut = _truncate(text, MAX_SECTION_CHARS)
            if was_cut:
                parsed["truncated_sections"].append(out_key)
        parsed[out_key] = text
    spl_ids = meta.get("spl_set_id")
    parsed["set_id"] = label.get("set_id") or (spl_ids[0] if isinstance(spl_ids, list) and spl_ids else None)
    parsed["effective_time"] = _format_date(label.get("effective_time"))
    parsed["brand_names"] = [b for b in meta.get("brand_name") or [] if isinstance(b, str)]
    parsed["generic_names"] = [g for g in meta.get("generic_name") or [] if isinstance(g, str)]
    return _with_limitations(raw, LABEL_LIMITATIONS, parsed)


def get_top_adverse_reactions(
    name: str, limit: int = 10, *, client: OpenFdaClient | None = None, use_network: bool = True
) -> ClinicalApiResult:
    """Count the reactions most often reported to FDA (FAERS) for this drug.

    Returns a list of ``(term, count)`` tuples, most-reported first. These are
    voluntary reports: they do NOT prove the drug caused the reaction.
    """
    query = sanitize_drug_query(name)
    if query is None:
        return _with_limitations(_error_result(OPENFDA_EVENT_URL, "invalid_query"), FAERS_LIMITATIONS)
    client = client or get_default_client()
    params = {
        "search": f'patient.drug.openfda.generic_name:"{query}"',
        # The `.exact` suffix is REQUIRED: without it openFDA counts single
        # words, so "DIFFICULTY SLEEPING" would be split into "difficulty" and
        # "sleeping". `.exact` counts each MedDRA term as one whole phrase.
        "count": "patient.reaction.reactionmeddrapt.exact",
        "limit": max(1, min(int(limit), 100)),
    }
    raw = client._get(OPENFDA_EVENT_URL, params, use_network=use_network)
    if not raw.ok:
        return _with_limitations(raw, FAERS_LIMITATIONS)
    terms: list[tuple[str, int]] = []
    for row in _results(raw.data):
        term, count = row.get("term"), row.get("count")
        if isinstance(term, str) and term.strip() and isinstance(count, int):
            terms.append((term.strip(), count))
    terms.sort(key=lambda pair: pair[1], reverse=True)
    return _with_limitations(raw, FAERS_LIMITATIONS, terms[: params["limit"]])


def _parse_recall(row: dict) -> dict:
    """Keep only the recall fields a senior and pharmacist need, in a tidy form."""
    description = _clean_text(row.get("product_description"))
    lots = _clean_text(row.get("code_info"))
    return {
        "recall_number": row.get("recall_number"),
        "classification": row.get("classification"),
        "status": row.get("status"),
        "reason_for_recall": _clean_text(row.get("reason_for_recall")),
        "product_description": _truncate(description, MAX_SHORT_TEXT_CHARS)[0] if description else None,
        "code_info": _truncate(lots, MAX_SHORT_TEXT_CHARS)[0] if lots else None,
        "recall_initiation_date": _format_date(row.get("recall_initiation_date")),
        "recalling_firm": row.get("recalling_firm"),
    }


def get_active_recalls(
    name: str, limit: int = 5, *, client: OpenFdaClient | None = None, use_network: bool = True
) -> ClinicalApiResult:
    """List ONGOING FDA recalls for this drug, newest first.

    Searches the structured ``openfda.generic_name`` field first; many recall
    records lack that field, so if nothing matches we retry on the free-text
    ``product_description``. Results are re-checked locally for "Ongoing".
    """
    query = sanitize_drug_query(name)
    if query is None:
        return _with_limitations(_error_result(OPENFDA_ENFORCEMENT_URL, "invalid_query"), RECALL_LIMITATIONS)
    client = client or get_default_client()

    def search(field_name: str) -> ClinicalApiResult:
        params = {"search": f'{field_name}:"{query}" AND status:"Ongoing"', "limit": 25}
        return client._get(OPENFDA_ENFORCEMENT_URL, params, use_network=use_network)

    raw = search("openfda.generic_name")
    if raw.ok and not _results(raw.data):
        # Only fall back on "no matches"; after an error we stop (no doubled traffic).
        raw = search("product_description")
    if not raw.ok:
        return _with_limitations(raw, RECALL_LIMITATIONS)
    recalls = [
        _parse_recall(row) for row in _results(raw.data)
        if str(row.get("status", "")).strip().lower() == "ongoing"
    ]
    recalls.sort(key=lambda r: r["recall_initiation_date"] or "", reverse=True)
    return _with_limitations(raw, RECALL_LIMITATIONS, recalls[: max(1, int(limit))])


def get_shortage_status(
    name: str, *, client: OpenFdaClient | None = None, use_network: bool = True
) -> ClinicalApiResult:
    """Check FDA's drug-shortage database for this drug.

    Field names in this newer endpoint have varied, so every field is read
    defensively with ``.get`` and a few alternative spellings.
    """
    query = sanitize_drug_query(name)
    if query is None:
        return _with_limitations(_error_result(OPENFDA_SHORTAGES_URL, "invalid_query"), SHORTAGE_LIMITATIONS)
    client = client or get_default_client()
    raw = client._get(OPENFDA_SHORTAGES_URL, {"search": f'generic_name:"{query}"', "limit": 10},
                      use_network=use_network)
    if not raw.ok:
        return _with_limitations(raw, SHORTAGE_LIMITATIONS)
    shortages = []
    for row in _results(raw.data):
        shortages.append({
            "generic_name": _first_text(row, "generic_name", "proprietary_name"),
            "status": _first_text(row, "status", "shortage_status"),
            "availability": _first_text(row, "availability"),
            "dosage_form": _first_text(row, "dosage_form"),
            "shortage_reason": _first_text(row, "shortage_reason", "reason"),
            "update_date": _format_date(row.get("update_date") or row.get("updated_date")),
        })
    return _with_limitations(raw, SHORTAGE_LIMITATIONS, shortages)


def _unique(items: list[str]) -> list[str]:
    """Remove duplicates but keep the original order."""
    return list(dict.fromkeys(items))


def build_safety_profile(
    name: str, *, client: OpenFdaClient | None = None, use_network: bool = True
) -> SafetyProfile:
    """Gather label, FAERS, recall and shortage data for one medicine.

    Each section is fetched on its own and wrapped in try/except, so a failing
    endpoint (or even an unexpected bug) only marks that section as failed;
    the other sections still show. The FDA's required disclaimer is attached.
    """
    client = client or get_default_client()
    plan = (
        ("label", get_label_safety_sections, OPENFDA_LABEL_URL, LABEL_LIMITATIONS),
        ("adverse_reactions", get_top_adverse_reactions, OPENFDA_EVENT_URL, FAERS_LIMITATIONS),
        ("recalls", get_active_recalls, OPENFDA_ENFORCEMENT_URL, RECALL_LIMITATIONS),
        ("shortages", get_shortage_status, OPENFDA_SHORTAGES_URL, SHORTAGE_LIMITATIONS),
    )
    results: dict[str, ClinicalApiResult] = {}
    for key, fetch, endpoint, caveats in plan:
        try:
            results[key] = fetch(name, client=client, use_network=use_network)
        except Exception:   # isolation: one bad section must never break the others
            results[key] = _with_limitations(_error_result(endpoint, "unexpected_error"), caveats)

    sources: list[str] = []
    limitations: list[str] = []
    errors: dict[str, str] = {}
    for key, result in results.items():
        sources.extend(result.data_sources)
        limitations.extend(result.limitations)
        if not result.ok:
            errors[key] = result.error_code or "unknown_error"
    return SafetyProfile(
        query=sanitize_drug_query(name),
        label=results["label"],
        adverse_reactions=results["adverse_reactions"],
        recalls=results["recalls"],
        shortages=results["shortages"],
        data_sources=_unique(sources),
        limitations=_unique(limitations),
        errors=errors,
    )
