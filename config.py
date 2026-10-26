"""Central configuration for MedSafe.

Everything optional is read from environment variables at call time so the
app (and the tests) can change behaviour without editing code. No secret is
ever stored in this file.
"""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SEED_DIR = BASE_DIR / "data"          # seed CSVs ship with the code
ASSETS_DIR = BASE_DIR / "assets"

SEED_INTERACTIONS_CSV = SEED_DIR / "interactions_seed.csv"
SEED_FOOD_CSV = SEED_DIR / "food_interactions_seed.csv"
SEED_ALIASES_CSV = SEED_DIR / "aliases_seed.csv"

# Network settings (seconds)
HTTP_TIMEOUT = float(os.environ.get("MEDSAFE_HTTP_TIMEOUT", "8"))
AI_TIMEOUT = float(os.environ.get("MEDSAFE_AI_TIMEOUT", "25"))

# Gemini (optional). Interactions API, documented at
# https://ai.google.dev/gemini-api/docs/interactions
GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/interactions"
# Free-tier Gemini keys created in 2026 are limited to 3.x-generation models,
# and each model has its own (small) free quota. MedSafe walks this chain until
# one call succeeds, so a quota-exhausted model never silently disables AI.
DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"
GEMINI_FALLBACK_MODELS = [
    "gemini-3.8-flash",
    "gemini-3.6-flash",
    "gemini-3.1-flash-lite",
]
# kept for backward compatibility with earlier call sites
GEMINI_FALLBACK_MODEL = GEMINI_FALLBACK_MODELS[1]
GEMINI_MODEL = os.environ.get("MEDSAFE_GEMINI_MODEL", "").strip() or DEFAULT_GEMINI_MODEL


def gemini_model_chain() -> list:
    """Configured model first, then the free-tier fallbacks, deduplicated."""
    chain = [os.environ.get("MEDSAFE_GEMINI_MODEL", "").strip() or DEFAULT_GEMINI_MODEL]
    for m in GEMINI_FALLBACK_MODELS:
        if m not in chain:
            chain.append(m)
    return chain

# Metadata for the interaction data that ships with the project. These are
# hand-entered demonstration records - NOT a professionally verified source.
STARTER_INTERACTIONS = {
    "dataset_id": "medsafe-starter",
    "name": "MedSafe starter interaction set",
    "version": "starter-1",
    "source_url": None,
    "license": "Distributed with the MedSafe project under its MIT license.",
    "attribution": (
        "Hand-entered by the MedSafe developer from general drug-reference "
        "knowledge. Not independently or professionally verified."
    ),
    "notes": (
        "A small demonstration set of well-known drug pairs. It is not a "
        "comprehensive interaction reference: most real combinations are "
        "simply not in it."
    ),
    "is_demo": 1,
}

STARTER_FOOD = {
    "dataset_id": "medsafe-starter-food",
    "name": "MedSafe starter food & drink notes",
    "version": "starter-1",
    "source_url": None,
    "license": "Distributed with the MedSafe project under its MIT license.",
    "attribution": "Hand-entered by the MedSafe developer. Not professionally verified.",
    "notes": "A small demonstration list of well-known food and drink cautions.",
    "is_demo": 1,
}

STARTER_ALIASES = {
    "dataset_id": "medsafe-aliases",
    "name": "MedSafe brand-name and synonym list",
    "version": "starter-1",
    "source_url": None,
    "license": "Distributed with the MedSafe project under its MIT license.",
    "attribution": (
        "Common US brand names mapped to active ingredients by the MedSafe "
        "developer. Used only to suggest identities that the user must confirm."
    ),
    "notes": "Offline fallback when RxNorm is unavailable.",
    "is_demo": 1,
}


def data_dir() -> Path:
    """Folder that holds the local SQLite files (personal + demo)."""
    return Path(os.environ.get("MEDSAFE_DATA_DIR", str(BASE_DIR / "data")))


def personal_db_path() -> Path:
    return data_dir() / "medsafe.sqlite3"


def demo_db_path() -> Path:
    return data_dir() / "medsafe_demo.sqlite3"


def get_gemini_api_key() -> str:
    """Return the trimmed GEMINI_API_KEY string, or '' if not set."""
    return os.environ.get("GEMINI_API_KEY", "").strip()


def gemini_api_key() -> str | None:
    """Return the trimmed GEMINI_API_KEY string, or None if not set."""
    key = get_gemini_api_key()
    return key or None


def has_gemini_key() -> bool:
    """Return True if a non-empty GEMINI_API_KEY is configured in the environment."""
    return bool(get_gemini_api_key())


def gemini_model() -> str:
    return os.environ.get("MEDSAFE_GEMINI_MODEL", "").strip() or DEFAULT_GEMINI_MODEL


def load_dotenv(path: Path | None = None) -> None:
    """Minimal .env loader (KEY=VALUE lines). Never overrides real env vars."""
    path = path or (BASE_DIR / ".env")
    if not path.exists():
        return
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except OSError:
        pass


def openfda_api_key() -> str | None:
    """Return the trimmed OPENFDA_API_KEY, or None if not set.

    The key is optional. openFDA allows 240 requests/minute with or without
    a key, but the daily cap rises from 1,000/day (per IP, no key) to
    120,000/day (per key). See https://open.fda.gov/apis/authentication/
    """
    key = os.environ.get("OPENFDA_API_KEY", "").strip()
    return key or None


def openfda_cache_path() -> Path:
    """SQLite file that stores cached openFDA responses (never the API key)."""
    return data_dir() / "openfda_cache.sqlite3"