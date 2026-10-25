"""Deterministic interaction engine - the single source of truth.

Design principle: the LOADED DATASET decides whether a pair of medicines has
an interaction record. The AI layer (ai_explain.py) may only re-word a record
this module has already returned. Nothing here calls an AI model.

Result statuses (independent of how the UI styles them):

* MATCH_FOUND                     - a record exists for the pair
* NO_MATCHING_RECORD              - both identities usable, nothing in the data.
                                    This is NOT a safety confirmation.
* IDENTITY_REQUIRES_CONFIRMATION  - a medicine's identity hasn't been confirmed
* UNABLE_TO_CHECK                 - a medicine couldn't be identified or the
                                    lookup itself failed
* DATASET_UNAVAILABLE             - no usable interaction data is loaded
"""

from __future__ import annotations

import itertools
import json
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path

import db
from dataset_import import SEVERITY_RANK, normalize_name


class CheckStatus(str, Enum):
    MATCH_FOUND = "MATCH_FOUND"
    NO_MATCHING_RECORD = "NO_MATCHING_RECORD"
    IDENTITY_REQUIRES_CONFIRMATION = "IDENTITY_REQUIRES_CONFIRMATION"
    UNABLE_TO_CHECK = "UNABLE_TO_CHECK"
    DATASET_UNAVAILABLE = "DATASET_UNAVAILABLE"


# Statuses that mean "this pair was NOT fully checked".
INCOMPLETE_STATUSES = {
    CheckStatus.IDENTITY_REQUIRES_CONFIRMATION,
    CheckStatus.UNABLE_TO_CHECK,
    CheckStatus.DATASET_UNAVAILABLE,
}

_STATUS_ORDER = {
    CheckStatus.MATCH_FOUND: 0,
    CheckStatus.DATASET_UNAVAILABLE: 1,
    CheckStatus.UNABLE_TO_CHECK: 2,
    CheckStatus.IDENTITY_REQUIRES_CONFIRMATION: 3,
    CheckStatus.NO_MATCHING_RECORD: 4,
}


@dataclass(frozen=True)
class Ingredient:
    name: str
    rxcui: str | None = None


@dataclass
class MedForCheck:
    """The minimum the engine needs to know about a medicine."""

    key: str
    display_name: str
    ingredients: tuple[Ingredient, ...]
    identity_status: str  # confirmed | needs_review | unidentified
    is_proposed: bool = False

    @property
    def usable(self) -> bool:
        return self.identity_status == "confirmed" and len(self.ingredients) > 0

    @property
    def problem_status(self) -> CheckStatus | None:
        if self.usable:
            return None
        if self.identity_status == "needs_review" and self.ingredients:
            return CheckStatus.IDENTITY_REQUIRES_CONFIRMATION
        return CheckStatus.UNABLE_TO_CHECK


@dataclass
class InteractionRecord:
    record_id: int
    dataset_id: str
    dataset_name: str
    dataset_version: str | None
    dataset_is_demo: bool
    imported_at: str
    license: str | None
    attribution: str | None
    source_record_id: str | None
    ingredient_a: str
    ingredient_b: str
    source_name_a: str | None
    source_name_b: str | None
    severity_raw: str | None
    severity_level: str
    mechanism: str | None
    management: str | None


@dataclass
class PairResult:
    med_a: MedForCheck
    med_b: MedForCheck
    status: CheckStatus
    ingredient_pairs: list[tuple[str, str]] = field(default_factory=list)
    records: list[InteractionRecord] = field(default_factory=list)
    reason: str | None = None  # machine-readable reason code

    @property
    def top_severity(self) -> str | None:
        if not self.records:
            return None
        return min(self.records, key=lambda r: SEVERITY_RANK.get(r.severity_level, 9)).severity_level

    @property
    def pair_key(self) -> str:
        return "|".join(sorted([self.med_a.key, self.med_b.key]))


@dataclass
class DatasetInfo:
    dataset_id: str
    name: str
    version: str | None
    record_count: int
    imported_at: str
    license: str | None
    attribution: str | None
    notes: str | None
    is_demo: bool
    source_url: str | None
    source_file: str | None


@dataclass
class DatasetStatus:
    available: bool
    datasets: list[DatasetInfo]
    total_records: int
    problem: str | None = None

    @property
    def only_demo_data(self) -> bool:
        return bool(self.datasets) and all(d.is_demo for d in self.datasets)

    @property
    def label(self) -> str:
        if not self.datasets:
            return "no dataset"
        return "; ".join(f"{d.name} ({d.version or 'version not stated'})" for d in self.datasets)


@dataclass
class DuplicateWarning:
    ingredient: str
    medicines: list[str]


@dataclass
class FoodFinding:
    medicine: str
    ingredient: str
    food: str
    severity_raw: str | None
    severity_level: str
    mechanism: str | None
    dataset_name: str
    source_record_id: str | None


@dataclass
class CheckReport:
    mode: str  # "full_list" | "proposed"
    results: list[PairResult]
    dataset_status: DatasetStatus
    medicines: list[MedForCheck]
    duplicates: list[DuplicateWarning] = field(default_factory=list)
    food_findings: list[FoodFinding] = field(default_factory=list)
    checked_at: str = field(default_factory=lambda: datetime.now().replace(microsecond=0).isoformat())

    @property
    def unusable_medicines(self) -> list[MedForCheck]:
        return [m for m in self.medicines if not m.usable]

    @property
    def complete(self) -> bool:
        """True only when every pair was looked up against available data.
        Even a complete check does NOT mean the combination is safe."""
        if not self.dataset_status.available:
            return False
        if self.unusable_medicines:
            return False
        return all(r.status not in INCOMPLETE_STATUSES for r in self.results)

    def count(self, status: CheckStatus) -> int:
        return sum(1 for r in self.results if r.status == status)

    def by_status(self, status: CheckStatus) -> list[PairResult]:
        return [r for r in self.results if r.status == status]


# --- dataset status --------------------------------------------------------

def get_dataset_status(db_path: Path) -> DatasetStatus:
    if not Path(db_path).exists():
        return DatasetStatus(False, [], 0, "The local database file does not exist.")
    try:
        with db.reader(db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM datasets WHERE kind='interactions' ORDER BY is_demo, name"
            ).fetchall()
            counts = {
                r["dataset_id"]: r["n"]
                for r in conn.execute(
                    "SELECT dataset_id, COUNT(*) AS n FROM interaction_records GROUP BY dataset_id"
                )
            }
    except sqlite3.Error as exc:
        return DatasetStatus(False, [], 0, f"The interaction database could not be read ({type(exc).__name__}).")

    infos = []
    for r in rows:
        actual = counts.get(r["dataset_id"], 0)
        infos.append(
            DatasetInfo(
                dataset_id=r["dataset_id"], name=r["name"], version=r["version"],
                record_count=actual, imported_at=r["imported_at"], license=r["license"],
                attribution=r["attribution"], notes=r["notes"], is_demo=bool(r["is_demo"]),
                source_url=r["source_url"], source_file=r["source_file"],
            )
        )
    total = sum(i.record_count for i in infos)
    problem = None
    for r, info in zip(rows, infos):
        if info.record_count != r["record_count"]:
            problem = (
                f"{info.name}: expected {r['record_count']} records but found "
                f"{info.record_count}. The data may be damaged."
            )
    if total == 0:
        return DatasetStatus(False, infos, 0, problem or "No interaction records are loaded.")
    return DatasetStatus(True, infos, total, problem)


# --- lookup helpers --------------------------------------------------------

def _synonyms(conn: sqlite3.Connection, name: str) -> set[str]:
    """Explicitly listed synonyms only (e.g. paracetamol <-> acetaminophen)."""
    names = {name}
    for row in conn.execute(
        "SELECT ingredient FROM aliases WHERE alias=? AND alias_type='synonym' "
        "UNION SELECT alias FROM aliases WHERE ingredient=? AND alias_type='synonym'",
        (name, name),
    ):
        names.add(row[0])
    return names


def _row_to_record(row: sqlite3.Row) -> InteractionRecord:
    return InteractionRecord(
        record_id=row["record_id"], dataset_id=row["dataset_id"], dataset_name=row["name"],
        dataset_version=row["version"], dataset_is_demo=bool(row["is_demo"]),
        imported_at=row["imported_at"], license=row["license"], attribution=row["attribution"],
        source_record_id=row["source_record_id"], ingredient_a=row["ingredient_a"],
        ingredient_b=row["ingredient_b"], source_name_a=row["source_name_a"],
        source_name_b=row["source_name_b"], severity_raw=row["severity_raw"],
        severity_level=row["severity_level"], mechanism=row["mechanism"],
        management=row["management"],
    )


def lookup_records(conn: sqlite3.Connection, ingredient_a: str, ingredient_b: str) -> list[InteractionRecord]:
    """All records (from every loaded dataset) for one ingredient pair."""
    names_a = _synonyms(conn, normalize_name(ingredient_a))
    names_b = _synonyms(conn, normalize_name(ingredient_b))
    found: dict[int, InteractionRecord] = {}
    for a, b in itertools.product(names_a, names_b):
        if a == b:
            continue
        lo, hi = sorted([a, b])
        for row in conn.execute(
            """SELECT r.*, d.name, d.version, d.is_demo, d.imported_at, d.license, d.attribution
               FROM interaction_records r JOIN datasets d USING (dataset_id)
               WHERE r.ingredient_a=? AND r.ingredient_b=?""",
            (lo, hi),
        ):
            found[row["record_id"]] = _row_to_record(row)
    return sorted(found.values(), key=lambda r: (SEVERITY_RANK.get(r.severity_level, 9), r.dataset_name))


def check_pair(conn: sqlite3.Connection, a: MedForCheck, b: MedForCheck) -> PairResult:
    problem_a, problem_b = a.problem_status, b.problem_status
    if problem_a or problem_b:
        status = (
            CheckStatus.UNABLE_TO_CHECK
            if CheckStatus.UNABLE_TO_CHECK in (problem_a, problem_b)
            else CheckStatus.IDENTITY_REQUIRES_CONFIRMATION
        )
        reason = "unidentified_medicine" if status == CheckStatus.UNABLE_TO_CHECK else "identity_unconfirmed"
        return PairResult(a, b, status, reason=reason)

    pairs: list[tuple[str, str]] = []
    records: dict[int, InteractionRecord] = {}
    try:
        for ia, ib in itertools.product(a.ingredients, b.ingredients):
            na, nb = normalize_name(ia.name), normalize_name(ib.name)
            if na == nb:
                continue  # same ingredient: reported as a duplicate, not an interaction
            pairs.append(tuple(sorted([na, nb])))
            for rec in lookup_records(conn, na, nb):
                records[rec.record_id] = rec
    except sqlite3.Error:
        return PairResult(a, b, CheckStatus.UNABLE_TO_CHECK, pairs, reason="lookup_failed")

    if not pairs:
        # Both medicines contain only the same ingredient(s); nothing to compare.
        return PairResult(a, b, CheckStatus.NO_MATCHING_RECORD, [], [], reason="same_ingredients")
    ordered = sorted(records.values(), key=lambda r: SEVERITY_RANK.get(r.severity_level, 9))
    if ordered:
        return PairResult(a, b, CheckStatus.MATCH_FOUND, sorted(set(pairs)), ordered)
    return PairResult(a, b, CheckStatus.NO_MATCHING_RECORD, sorted(set(pairs)), [])


def find_duplicate_ingredients(meds: list[MedForCheck]) -> list[DuplicateWarning]:
    """Medicines that share an active ingredient - a review aid only."""
    seen: dict[str, list[str]] = {}
    for m in meds:
        for ing in {normalize_name(i.name) for i in m.ingredients}:
            seen.setdefault(ing, []).append(m.display_name)
    return [DuplicateWarning(ing, names) for ing, names in sorted(seen.items()) if len(names) > 1]


def check_foods(conn: sqlite3.Connection, meds: list[MedForCheck]) -> list[FoodFinding]:
    out = []
    for m in meds:
        if not m.usable:
            continue
        for ing in m.ingredients:
            for name in _synonyms(conn, normalize_name(ing.name)):
                for row in conn.execute(
                    """SELECT f.*, d.name FROM food_records f JOIN datasets d USING (dataset_id)
                       WHERE f.ingredient=?""",
                    (name,),
                ):
                    out.append(FoodFinding(
                        medicine=m.display_name, ingredient=row["ingredient"], food=row["food"],
                        severity_raw=row["severity_raw"], severity_level=row["severity_level"],
                        mechanism=row["mechanism"], dataset_name=row["name"],
                        source_record_id=row["source_record_id"],
                    ))
    out.sort(key=lambda f: (SEVERITY_RANK.get(f.severity_level, 9), f.medicine, f.food))
    return out


def check_medications(
    db_path: Path,
    meds: list[MedForCheck],
    proposed: MedForCheck | None = None,
) -> CheckReport:
    """Run a full-list review, or check one proposed medicine against `meds`."""
    mode = "proposed" if proposed is not None else "full_list"
    status = get_dataset_status(db_path)
    everyone = list(meds) + ([proposed] if proposed else [])

    if proposed is not None:
        pairs = [(proposed, m) for m in meds if m.key != proposed.key]
    else:
        pairs = list(itertools.combinations(meds, 2))

    if not status.available:
        results = [PairResult(a, b, CheckStatus.DATASET_UNAVAILABLE, reason="dataset_unavailable")
                   for a, b in pairs]
        return CheckReport(mode, results, status, everyone, find_duplicate_ingredients(everyone))

    results: list[PairResult] = []
    foods: list[FoodFinding] = []
    try:
        with db.reader(db_path) as conn:
            for a, b in pairs:
                results.append(check_pair(conn, a, b))
            food_targets = [proposed] if proposed is not None else meds
            foods = check_foods(conn, food_targets)
    except sqlite3.Error:
        results = [PairResult(a, b, CheckStatus.UNABLE_TO_CHECK, reason="lookup_failed") for a, b in pairs]

    results.sort(key=lambda r: (
        _STATUS_ORDER[r.status],
        SEVERITY_RANK.get(r.top_severity or "", 9),
        r.med_a.display_name.lower(), r.med_b.display_name.lower(),
    ))
    return CheckReport(mode, results, status, everyone, find_duplicate_ingredients(everyone), foods)


# --- history ---------------------------------------------------------------

def report_to_summary(report: CheckReport) -> dict:
    return {
        "mode": report.mode,
        "complete": report.complete,
        "pairs": [
            {
                "a": r.med_a.display_name,
                "b": r.med_b.display_name,
                "status": r.status.value,
                "severity": r.top_severity,
                "record_ids": [rec.source_record_id or str(rec.record_id) for rec in r.records],
            }
            for r in report.results
        ],
        "not_checked": [m.display_name for m in report.unusable_medicines],
        "medicines": [m.display_name for m in report.medicines],
    }


def save_history(db_path: Path, report: CheckReport) -> None:
    with db.transaction(db_path) as conn:
        conn.execute(
            "INSERT INTO check_history (checked_at, mode, complete, summary_json, dataset_label) "
            "VALUES (?, ?, ?, ?, ?)",
            (report.checked_at, report.mode, int(report.complete),
             json.dumps(report_to_summary(report)), report.dataset_status.label),
        )


def list_history(db_path: Path, limit: int = 10) -> list[dict]:
    with db.reader(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM check_history ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    out = []
    for r in rows:
        item = dict(r)
        try:
            item["summary"] = json.loads(r["summary_json"])
        except (TypeError, ValueError):
            item["summary"] = {}
        out.append(item)
    return out


def known_ingredients(db_path: Path) -> set[str]:
    """Every ingredient name that appears in loaded reference data."""
    with db.reader(db_path) as conn:
        names = {r[0] for r in conn.execute(
            "SELECT ingredient_a FROM interaction_records UNION SELECT ingredient_b FROM interaction_records "
            "UNION SELECT ingredient FROM food_records UNION SELECT ingredient FROM aliases"
        )}
    return names


if __name__ == "__main__":
    import tempfile

    import config

    path = Path(tempfile.mkdtemp()) / "demo.sqlite3"
    db.prepare(path)
    meds = [
        MedForCheck("1", "Lisinopril", (Ingredient("lisinopril"),), "confirmed"),
        MedForCheck("2", "Metformin", (Ingredient("metformin"),), "confirmed"),
    ]
    proposed = MedForCheck("p", "Ibuprofen", (Ingredient("ibuprofen"),), "confirmed", True)
    rep = check_medications(path, meds, proposed)
    print(f"Dataset: {rep.dataset_status.label} ({rep.dataset_status.total_records} records)")
    for r in rep.results:
        print(r.status.value, r.med_a.display_name, "+", r.med_b.display_name,
              [(x.severity_raw, x.mechanism) for x in r.records])
    _ = config, asdict
