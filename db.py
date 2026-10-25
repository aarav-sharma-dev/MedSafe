"""SQLite storage: connections, schema and migrations.

* One SQLite file per profile (personal and demo) so fictional demo data can
  never mix with a real medication list.
* The schema version lives in ``PRAGMA user_version``. Migrations only ever
  ADD tables/columns or rename legacy tables - user data is never dropped
  during an ordinary startup.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

SCHEMA_VERSION = 2

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS datasets (
    dataset_id    TEXT PRIMARY KEY,
    kind          TEXT NOT NULL CHECK (kind IN ('interactions', 'food', 'aliases')),
    name          TEXT NOT NULL,
    version       TEXT,
    source_url    TEXT,
    license       TEXT,
    attribution   TEXT,
    notes         TEXT,
    is_demo       INTEGER NOT NULL DEFAULT 0,
    imported_at   TEXT NOT NULL,
    record_count  INTEGER NOT NULL DEFAULT 0,
    source_file   TEXT,
    source_sha256 TEXT
);

CREATE TABLE IF NOT EXISTS interaction_records (
    record_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id       TEXT NOT NULL REFERENCES datasets(dataset_id) ON DELETE CASCADE,
    source_record_id TEXT,
    ingredient_a     TEXT NOT NULL,
    ingredient_b     TEXT NOT NULL,
    source_name_a    TEXT,
    source_name_b    TEXT,
    source_id_a      TEXT,
    source_id_b      TEXT,
    severity_raw     TEXT,
    severity_level   TEXT NOT NULL
                     CHECK (severity_level IN ('major', 'moderate', 'minor', 'unspecified')),
    mechanism        TEXT,
    management       TEXT,
    CHECK (ingredient_a < ingredient_b),
    UNIQUE (dataset_id, ingredient_a, ingredient_b)
);
CREATE INDEX IF NOT EXISTS idx_interaction_pair
    ON interaction_records (ingredient_a, ingredient_b);

CREATE TABLE IF NOT EXISTS food_records (
    record_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id       TEXT NOT NULL REFERENCES datasets(dataset_id) ON DELETE CASCADE,
    source_record_id TEXT,
    ingredient       TEXT NOT NULL,
    food             TEXT NOT NULL,
    severity_raw     TEXT,
    severity_level   TEXT NOT NULL
                     CHECK (severity_level IN ('major', 'moderate', 'minor', 'unspecified')),
    mechanism        TEXT,
    UNIQUE (dataset_id, ingredient, food)
);
CREATE INDEX IF NOT EXISTS idx_food_ingredient ON food_records (ingredient);

CREATE TABLE IF NOT EXISTS aliases (
    alias       TEXT NOT NULL,
    ingredient  TEXT NOT NULL,
    alias_type  TEXT NOT NULL CHECK (alias_type IN ('brand', 'combination', 'synonym')),
    dataset_id  TEXT NOT NULL REFERENCES datasets(dataset_id) ON DELETE CASCADE,
    PRIMARY KEY (alias, ingredient)
);

CREATE TABLE IF NOT EXISTS medications (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    display_name     TEXT NOT NULL,
    generic_name     TEXT,
    brand_name       TEXT,
    rxcui            TEXT,
    rxnorm_name      TEXT,
    rxnorm_tty       TEXT,
    strength         TEXT,
    dose_form        TEXT,
    route            TEXT,
    instructions     TEXT,
    category         TEXT NOT NULL DEFAULT 'prescription'
                     CHECK (category IN ('prescription', 'otc', 'supplement', 'herbal', 'other')),
    start_date       TEXT,
    end_date         TEXT,
    prescriber       TEXT,
    pharmacy         TEXT,
    notes            TEXT,
    active           INTEGER NOT NULL DEFAULT 1,
    entry_source     TEXT NOT NULL DEFAULT 'manual'
                     CHECK (entry_source IN ('manual', 'scanned', 'imported', 'demo')),
    identity_status  TEXT NOT NULL DEFAULT 'unidentified'
                     CHECK (identity_status IN ('confirmed', 'needs_review', 'unidentified')),
    identity_source  TEXT,
    original_text    TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS medication_ingredients (
    medication_id INTEGER NOT NULL REFERENCES medications(id) ON DELETE CASCADE,
    ingredient    TEXT NOT NULL,
    rxcui         TEXT,
    PRIMARY KEY (medication_id, ingredient)
);

CREATE TABLE IF NOT EXISTS schedule_entries (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    medication_id INTEGER NOT NULL REFERENCES medications(id) ON DELETE CASCADE,
    time_of_day   TEXT NOT NULL,          -- 24h HH:MM
    label         TEXT,
    created_at    TEXT NOT NULL,
    UNIQUE (medication_id, time_of_day)
);

CREATE TABLE IF NOT EXISTS dose_log (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    schedule_entry_id INTEGER NOT NULL REFERENCES schedule_entries(id) ON DELETE CASCADE,
    log_date          TEXT NOT NULL,      -- YYYY-MM-DD
    status            TEXT NOT NULL CHECK (status IN ('taken', 'skipped')),
    recorded_at       TEXT NOT NULL,
    UNIQUE (schedule_entry_id, log_date)
);

CREATE TABLE IF NOT EXISTS check_history (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    checked_at    TEXT NOT NULL,
    mode          TEXT NOT NULL,
    complete      INTEGER NOT NULL,
    summary_json  TEXT NOT NULL,
    dataset_label TEXT
);

CREATE TABLE IF NOT EXISTS report_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT NOT NULL,
    report_type TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

# Tables that hold the user's own information (cleared by "delete my data").
USER_TABLES = (
    "dose_log",
    "schedule_entries",
    "medication_ingredients",
    "medications",
    "check_history",
    "report_history",
)


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def connect(db_path: Path) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


@contextmanager
def transaction(db_path: Path) -> Iterator[sqlite3.Connection]:
    """Open a connection, commit on success, roll back on any error."""
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def reader(db_path: Path) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def _migrate_legacy_v1(conn: sqlite3.Connection) -> None:
    """Version 1 of MedSafe used `meds`, `interactions`, `food_interactions`
    and `meta` tables. Move the medication list into the new model and rename
    (never drop) the old tables so nothing the user typed is lost."""
    if _table_exists(conn, "meds"):
        stamp = now_iso()
        for row in conn.execute("SELECT * FROM meds").fetchall():
            name = (row["name"] or "").strip()
            if not name:
                continue
            cur = conn.execute(
                """INSERT INTO medications (display_name, instructions, entry_source,
                       identity_status, notes, created_at, updated_at)
                   VALUES (?, ?, 'imported', 'unidentified', ?, ?, ?)""",
                (
                    name.title(),
                    (row["dose"] or "").strip() or None,
                    "Imported from an earlier MedSafe version. Please review this "
                    "medicine's name so it can be checked.",
                    stamp,
                    stamp,
                ),
            )
            legacy_time = _legacy_time_to_hhmm(row["time_of_day"])
            if legacy_time:
                conn.execute(
                    "INSERT OR IGNORE INTO schedule_entries (medication_id, time_of_day, created_at) "
                    "VALUES (?, ?, ?)",
                    (cur.lastrowid, legacy_time, stamp),
                )
        conn.execute("ALTER TABLE meds RENAME TO legacy_meds_v1")
    for old in ("interactions", "food_interactions", "meta"):
        if _table_exists(conn, old):
            conn.execute(f"ALTER TABLE {old} RENAME TO legacy_{old}_v1")


def _legacy_time_to_hhmm(label: str | None) -> str | None:
    label = (label or "").strip().lower()
    if label == "bedtime":
        return "21:00"
    for fmt in ("%I:%M %p", "%H:%M"):
        try:
            return datetime.strptime(label, fmt).strftime("%H:%M")
        except ValueError:
            continue
    return None


def init_db(db_path: Path) -> None:
    """Create or upgrade the schema. Safe to call on every start-up."""
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA_SQL)  # CREATE ... IF NOT EXISTS: idempotent
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version < SCHEMA_VERSION:
            conn.execute("BEGIN")
            _migrate_legacy_v1(conn)
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def prepare(db_path: Path) -> list[str]:
    """Schema + reference data. Returns human-readable data problems (if any)."""
    import dataset_import  # local import avoids a circular dependency

    init_db(db_path)
    return dataset_import.ensure_seed_data(db_path)


# --- settings (key/value) -------------------------------------------------

def get_setting(db_path: Path, key: str, default: str | None = None) -> str | None:
    with reader(db_path) as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(db_path: Path, key: str, value: str | None) -> None:
    with transaction(db_path) as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


def clear_user_data(db_path: Path) -> None:
    """Delete the medication list, schedule, logs and history.
    Reference data (interaction datasets) and preferences are kept."""
    with transaction(db_path) as conn:
        for table in USER_TABLES:
            conn.execute(f"DELETE FROM {table}")
