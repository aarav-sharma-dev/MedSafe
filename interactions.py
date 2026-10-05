"""Interaction database: the authoritative source of truth.

Design principle: the DATABASE decides whether two drugs interact.
The AI (ai_explain.py) only explains an interaction we already confirmed.
Never let an LLM decide whether an interaction exists - it can hallucinate.

Data: starts with data/interactions_seed.csv (25 well-known pairs).
To upgrade, download the full DDInter 2.0 dataset (free, ~500K pairs) and
convert it to the same CSV columns: drug_a, drug_b, severity, mechanism.
"""

import csv
import itertools
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "medsafe.db"
SEED_CSV = Path(__file__).parent / "data" / "interactions_seed.csv"
FOOD_CSV = Path(__file__).parent / "data" / "food_interactions_seed.csv"

SEVERITY_ORDER = {"major": 0, "moderate": 1, "minor": 2}


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(force: bool = False) -> int:
    """Create tables and load the seed CSV. Returns number of pairs loaded."""
    conn = get_conn()
    cur = conn.cursor()
    if force:
        cur.execute("DROP TABLE IF EXISTS interactions")
    cur.execute(
        """CREATE TABLE IF NOT EXISTS interactions (
               drug_a TEXT NOT NULL,
               drug_b TEXT NOT NULL,
               severity TEXT NOT NULL,
               mechanism TEXT NOT NULL,
               PRIMARY KEY (drug_a, drug_b)
           )"""
    )
    cur.execute(
        """CREATE TABLE IF NOT EXISTS meds (
               name TEXT PRIMARY KEY,
               dose TEXT,
               time_of_day TEXT,
               taken_today INTEGER DEFAULT 0
           )"""
    )
    # migration: caregiver-alert flag (one alert per med per day)
    cols = [r[1] for r in cur.execute("PRAGMA table_info(meds)")]
    if "alerted_today" not in cols:
        cur.execute("ALTER TABLE meds ADD COLUMN alerted_today INTEGER DEFAULT 0")
    if force:
        cur.execute("DROP TABLE IF EXISTS food_interactions")
    cur.execute(
        """CREATE TABLE IF NOT EXISTS food_interactions (
               drug TEXT NOT NULL,
               food TEXT NOT NULL,
               severity TEXT NOT NULL,
               mechanism TEXT NOT NULL,
               PRIMARY KEY (drug, food)
           )"""
    )
    food_count = cur.execute("SELECT COUNT(*) FROM food_interactions").fetchone()[0]
    if food_count == 0 and FOOD_CSV.exists():
        with open(FOOD_CSV, newline="", encoding="utf-8") as f:
            cur.executemany(
                "INSERT OR IGNORE INTO food_interactions VALUES (?, ?, ?, ?)",
                [
                    (r["drug"].strip().lower(), r["food"].strip().lower(),
                     r["severity"].strip().lower(), r["mechanism"].strip())
                    for r in csv.DictReader(f)
                ],
            )
    count = cur.execute("SELECT COUNT(*) FROM interactions").fetchone()[0]
    if count == 0 and SEED_CSV.exists():
        with open(SEED_CSV, newline="", encoding="utf-8") as f:
            rows = []
            for row in csv.DictReader(f):
                a = row["drug_a"].strip().lower()
                b = row["drug_b"].strip().lower()
                # store alphabetically so lookup order never matters
                a, b = sorted([a, b])
                rows.append((a, b, row["severity"].strip().lower(), row["mechanism"].strip()))
        cur.executemany(
            "INSERT OR IGNORE INTO interactions VALUES (?, ?, ?, ?)", rows
        )
        count = cur.execute("SELECT COUNT(*) FROM interactions").fetchone()[0]
    conn.commit()
    conn.close()
    return count


def check_pair(drug_a: str, drug_b: str) -> "dict | None":
    """Return the interaction record for two drugs, or None."""
    a, b = sorted([drug_a.strip().lower(), drug_b.strip().lower()])
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM interactions WHERE drug_a = ? AND drug_b = ?", (a, b)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def check_list(drugs: list[str]) -> list[dict]:
    """Check every pair in a medication list. Sorted most-severe first."""
    found = []
    for a, b in itertools.combinations({d.strip().lower() for d in drugs if d.strip()}, 2):
        hit = check_pair(a, b)
        if hit:
            found.append(hit)
    found.sort(key=lambda r: SEVERITY_ORDER.get(r["severity"], 9))
    return found


def check_foods(drugs: list) -> list:
    """Return food warnings for every drug in the list, most severe first."""
    names = sorted({d.strip().lower() for d in drugs if d.strip()})
    if not names:
        return []
    conn = get_conn()
    marks = ",".join("?" * len(names))
    rows = [
        dict(r)
        for r in conn.execute(
            f"SELECT * FROM food_interactions WHERE drug IN ({marks})", names
        )
    ]
    conn.close()
    rows.sort(key=lambda r: SEVERITY_ORDER.get(r["severity"], 9))
    return rows


# --- medication list persistence (used by the Reminders tab) ---

def add_med(name: str, dose: str = "", time_of_day: str = "") -> None:
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO meds (name, dose, time_of_day, taken_today) VALUES (?, ?, ?, 0)",
        (name.strip().lower(), dose.strip(), time_of_day.strip()),
    )
    conn.commit()
    conn.close()


def list_meds() -> list[dict]:
    conn = get_conn()
    rows = [dict(r) for r in conn.execute("SELECT * FROM meds ORDER BY time_of_day")]
    conn.close()
    return rows


def mark_taken(name: str, taken: bool = True) -> None:
    conn = get_conn()
    conn.execute("UPDATE meds SET taken_today = ? WHERE name = ?", (int(taken), name))
    conn.commit()
    conn.close()


def mark_alerted(name: str, alerted: bool = True) -> None:
    conn = get_conn()
    conn.execute("UPDATE meds SET alerted_today = ? WHERE name = ?", (int(alerted), name))
    conn.commit()
    conn.close()


def reset_day() -> None:
    conn = get_conn()
    conn.execute("UPDATE meds SET taken_today = 0, alerted_today = 0")
    conn.commit()
    conn.close()


def remove_med(name: str) -> None:
    conn = get_conn()
    conn.execute("DELETE FROM meds WHERE name = ?", (name,))
    conn.commit()
    conn.close()


if __name__ == "__main__":
    n = init_db(force=True)
    print(f"Loaded {n} interaction pairs")
    demo = check_list(["Lisinopril", "Ibuprofen", "Metformin"])
    for d in demo:
        print(f"{d['severity'].upper()}: {d['drug_a']} + {d['drug_b']} -> {d['mechanism']}")
