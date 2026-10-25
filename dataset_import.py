"""Importing and validating interaction datasets.

Supported interaction file formats
----------------------------------
* ``medsafe`` - columns ``drug_a, drug_b, severity`` plus optional
  ``mechanism, management, record_id`` (the bundled starter CSV).
* ``ddinter`` - DDInter 2.0 download files with columns
  ``DDInterID_A, Drug_A, DDInterID_B, Drug_B, Level``. DDInter download files
  do not contain mechanism or management text, so those fields stay empty -
  MedSafe never writes invented descriptions.

Safety rules enforced here
--------------------------
* Raw source severity is always preserved in ``severity_raw``.
* Severity is mapped with the documented ``SEVERITY_MAP``. Anything not in the
  map (including DDInter "Unknown") becomes ``unspecified`` - never a guess.
* If the same pair appears twice with different severities, the MORE severe
  record is kept and the conflict is reported (we never silently downgrade).
* An import is all-or-nothing: the dataset is validated first and written in
  one transaction, so a failed import leaves the previous data untouched.
"""

from __future__ import annotations

import csv
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

import config
import db

# Documented mapping from source severity wording to MedSafe display levels.
SEVERITY_MAP = {
    "major": "major",
    "moderate": "moderate",
    "minor": "minor",
}
SEVERITY_RANK = {"major": 0, "moderate": 1, "minor": 2, "unspecified": 3}

MAX_NAME_LEN = 200
MAX_TEXT_LEN = 4000
# If more than this share of rows is rejected the file is probably the wrong
# format, so nothing is imported.
MAX_REJECT_RATIO = 0.5

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SPACES = re.compile(r"\s+")


def normalize_name(value: str | None) -> str:
    """Conservative normalisation: lower-case, trim, collapse whitespace.
    This is NOT fuzzy matching - 'ibuprofen' and 'ibuprofin' stay different."""
    value = _CONTROL_CHARS.sub("", value or "")
    return _SPACES.sub(" ", value).strip().strip(".,;:").strip().lower()


def map_severity(raw: str | None) -> str:
    return SEVERITY_MAP.get(normalize_name(raw), "unspecified")


def file_sha256(paths: list[Path]) -> str:
    h = hashlib.sha256()
    for p in sorted(Path(x) for x in paths):
        h.update(p.read_bytes())
    return h.hexdigest()


@dataclass
class ParsedInteraction:
    ingredient_a: str
    ingredient_b: str
    source_name_a: str
    source_name_b: str
    source_id_a: str | None
    source_id_b: str | None
    severity_raw: str
    severity_level: str
    mechanism: str | None
    management: str | None
    source_record_id: str | None


@dataclass
class ImportReport:
    dataset_id: str
    source_format: str | None = None
    rows_read: int = 0
    imported: int = 0
    duplicates: int = 0
    severity_conflicts: int = 0
    unspecified_severity: int = 0
    rejected: list[tuple[str, int, str]] = field(default_factory=list)  # (file, row, reason)
    errors: list[str] = field(default_factory=list)
    ok: bool = False

    def summary(self) -> str:
        status = "Imported" if self.ok else "Import failed"
        parts = [
            f"{status}: {self.imported} records from {self.rows_read} rows "
            f"(format: {self.source_format or 'unknown'})",
            f"duplicates merged: {self.duplicates}",
            f"severity conflicts (kept more severe): {self.severity_conflicts}",
            f"unspecified severity: {self.unspecified_severity}",
            f"rejected rows: {len(self.rejected)}",
        ]
        if self.errors:
            parts.append("errors: " + "; ".join(self.errors))
        return "\n".join(parts)


# --- format detection ------------------------------------------------------

def detect_format(fieldnames: list[str] | None) -> str | None:
    cols = {normalize_name(c) for c in (fieldnames or [])}
    if {"ddinterid_a", "drug_a", "ddinterid_b", "drug_b", "level"} <= cols:
        return "ddinter"
    if {"drug_a", "drug_b", "severity"} <= cols:
        return "medsafe"
    return None


def _clean_text(value: str | None) -> str | None:
    value = _CONTROL_CHARS.sub("", value or "").strip()
    if not value:
        return None
    return value[:MAX_TEXT_LEN]


def _row_get(row: dict, name: str) -> str:
    """Case-insensitive column access."""
    for key, value in row.items():
        if key is not None and normalize_name(key) == name:
            return value or ""
    return ""


def parse_interaction_files(
    paths: list[Path], fmt: str | None = None
) -> tuple[list[ParsedInteraction], ImportReport]:
    report = ImportReport(dataset_id="")
    records: dict[tuple[str, str], ParsedInteraction] = {}

    for path in paths:
        path = Path(path)
        if not path.exists():
            report.errors.append(f"File not found: {path.name}")
            continue
        try:
            with open(path, newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                file_fmt = detect_format(reader.fieldnames)
                if fmt and file_fmt != fmt:
                    report.errors.append(
                        f"{path.name}: expected {fmt} columns, found {reader.fieldnames}"
                    )
                    continue
                if file_fmt is None:
                    report.errors.append(
                        f"{path.name}: unrecognised columns {reader.fieldnames}. "
                        "Expected MedSafe (drug_a, drug_b, severity) or DDInter "
                        "(DDInterID_A, Drug_A, DDInterID_B, Drug_B, Level)."
                    )
                    continue
                if report.source_format and report.source_format != file_fmt:
                    report.errors.append(f"{path.name}: mixed file formats in one import")
                    continue
                report.source_format = file_fmt
                for row_no, row in enumerate(reader, start=2):
                    report.rows_read += 1
                    parsed, reason = _parse_row(row, file_fmt)
                    if parsed is None:
                        report.rejected.append((path.name, row_no, reason))
                        continue
                    key = (parsed.ingredient_a, parsed.ingredient_b)
                    existing = records.get(key)
                    if existing is None:
                        records[key] = parsed
                        continue
                    report.duplicates += 1
                    if existing.severity_level != parsed.severity_level:
                        report.severity_conflicts += 1
                        if SEVERITY_RANK[parsed.severity_level] < SEVERITY_RANK[existing.severity_level]:
                            records[key] = parsed
        except (OSError, UnicodeDecodeError, csv.Error) as exc:
            report.errors.append(f"{path.name}: could not be read ({type(exc).__name__})")

    report.unspecified_severity = sum(
        1 for r in records.values() if r.severity_level == "unspecified"
    )
    return list(records.values()), report


def _parse_row(row: dict, fmt: str) -> tuple[ParsedInteraction | None, str]:
    if fmt == "ddinter":
        raw_a, raw_b = _row_get(row, "drug_a"), _row_get(row, "drug_b")
        id_a, id_b = _row_get(row, "ddinterid_a").strip(), _row_get(row, "ddinterid_b").strip()
        severity_raw = _row_get(row, "level").strip()
        mechanism = management = None
        record_id = f"{id_a}-{id_b}" if id_a and id_b else None
    else:
        raw_a, raw_b = _row_get(row, "drug_a"), _row_get(row, "drug_b")
        id_a = id_b = None
        severity_raw = _row_get(row, "severity").strip()
        mechanism = _clean_text(_row_get(row, "mechanism"))
        management = _clean_text(_row_get(row, "management"))
        record_id = _row_get(row, "record_id").strip() or None

    a, b = normalize_name(raw_a), normalize_name(raw_b)
    if not a or not b:
        return None, "missing drug name"
    if a == b:
        return None, "both drug names are the same"
    if len(a) > MAX_NAME_LEN or len(b) > MAX_NAME_LEN:
        return None, "drug name too long"
    if not severity_raw:
        return None, "missing severity"

    if b < a:  # store alphabetically so lookup order never matters
        a, b = b, a
        raw_a, raw_b = raw_b, raw_a
        id_a, id_b = id_b, id_a
    return (
        ParsedInteraction(
            ingredient_a=a,
            ingredient_b=b,
            source_name_a=raw_a.strip(),
            source_name_b=raw_b.strip(),
            source_id_a=id_a or None,
            source_id_b=id_b or None,
            severity_raw=severity_raw,
            severity_level=map_severity(severity_raw),
            mechanism=mechanism,
            management=management,
            source_record_id=record_id,
        ),
        "",
    )


def import_interactions(
    db_path: Path,
    paths: list[Path],
    meta: dict,
    fmt: str | None = None,
) -> ImportReport:
    """Validate then atomically (re)place one interaction dataset."""
    paths = [Path(p) for p in paths]
    records, report = parse_interaction_files(paths, fmt)
    report.dataset_id = meta["dataset_id"]

    if not paths:
        report.errors.append("No files supplied")
    if report.rows_read and len(report.rejected) / report.rows_read > MAX_REJECT_RATIO:
        report.errors.append(
            f"{len(report.rejected)} of {report.rows_read} rows were rejected - "
            "this does not look like a valid interaction file"
        )
    if not records and not report.errors:
        report.errors.append("No valid interaction records found")
    if report.errors:
        return report  # nothing written: existing data stays intact

    try:
        sha = file_sha256(paths)
        with db.transaction(db_path) as conn:
            conn.execute("DELETE FROM datasets WHERE dataset_id=?", (meta["dataset_id"],))
            conn.execute(
                """INSERT INTO datasets (dataset_id, kind, name, version, source_url, license,
                       attribution, notes, is_demo, imported_at, record_count, source_file,
                       source_sha256)
                   VALUES (?, 'interactions', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    meta["dataset_id"], meta["name"], meta.get("version"),
                    meta.get("source_url"), meta.get("license"), meta.get("attribution"),
                    meta.get("notes"), int(meta.get("is_demo", 0)), db.now_iso(),
                    len(records), ", ".join(p.name for p in paths), sha,
                ),
            )
            conn.executemany(
                """INSERT INTO interaction_records (dataset_id, source_record_id, ingredient_a,
                       ingredient_b, source_name_a, source_name_b, source_id_a, source_id_b,
                       severity_raw, severity_level, mechanism, management)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        meta["dataset_id"], r.source_record_id, r.ingredient_a, r.ingredient_b,
                        r.source_name_a, r.source_name_b, r.source_id_a, r.source_id_b,
                        r.severity_raw, r.severity_level, r.mechanism, r.management,
                    )
                    for r in records
                ],
            )
    except Exception as exc:  # transaction rolled back by db.transaction
        report.errors.append(f"Database write failed ({type(exc).__name__}); previous data kept")
        return report

    report.imported = len(records)
    report.ok = True
    return report


# --- food notes and aliases (bundled CSVs only) ----------------------------

def import_food(db_path: Path, path: Path, meta: dict) -> ImportReport:
    report = ImportReport(dataset_id=meta["dataset_id"], source_format="medsafe-food")
    rows = []
    seen = set()
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            for row_no, row in enumerate(csv.DictReader(f), start=2):
                report.rows_read += 1
                drug, food = normalize_name(_row_get(row, "drug")), normalize_name(_row_get(row, "food"))
                sev = _row_get(row, "severity").strip()
                if not drug or not food or not sev:
                    report.rejected.append((path.name, row_no, "missing field"))
                    continue
                if (drug, food) in seen:
                    report.duplicates += 1
                    continue
                seen.add((drug, food))
                rows.append((
                    meta["dataset_id"], _row_get(row, "record_id").strip() or None, drug, food,
                    sev, map_severity(sev), _clean_text(_row_get(row, "mechanism")),
                ))
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        report.errors.append(f"{Path(path).name}: could not be read ({type(exc).__name__})")
        return report
    if not rows:
        report.errors.append("No valid food records")
        return report
    try:
        with db.transaction(db_path) as conn:
            _replace_dataset_row(conn, meta, "food", len(rows), path)
            conn.executemany(
                """INSERT INTO food_records (dataset_id, source_record_id, ingredient, food,
                       severity_raw, severity_level, mechanism) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                rows,
            )
    except Exception as exc:
        report.errors.append(f"Database write failed ({type(exc).__name__}); previous data kept")
        return report
    report.imported = len(rows)
    report.ok = True
    return report


def import_aliases(db_path: Path, path: Path, meta: dict) -> ImportReport:
    report = ImportReport(dataset_id=meta["dataset_id"], source_format="medsafe-aliases")
    rows = set()
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            for row_no, row in enumerate(csv.DictReader(f), start=2):
                report.rows_read += 1
                alias = normalize_name(_row_get(row, "alias"))
                kind = normalize_name(_row_get(row, "alias_type"))
                ingredients = [
                    normalize_name(x) for x in _row_get(row, "ingredients").split("+")
                ]
                ingredients = [x for x in ingredients if x]
                if not alias or not ingredients or kind not in {"brand", "combination", "synonym"}:
                    report.rejected.append((Path(path).name, row_no, "invalid alias row"))
                    continue
                if kind == "combination" and len(ingredients) < 2:
                    report.rejected.append((Path(path).name, row_no, "combination needs 2+ ingredients"))
                    continue
                for ing in ingredients:
                    rows.add((alias, ing, kind, meta["dataset_id"]))
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        report.errors.append(f"{Path(path).name}: could not be read ({type(exc).__name__})")
        return report
    if not rows:
        report.errors.append("No valid aliases")
        return report
    try:
        with db.transaction(db_path) as conn:
            _replace_dataset_row(conn, meta, "aliases", len(rows), path)
            conn.executemany(
                "INSERT OR IGNORE INTO aliases (alias, ingredient, alias_type, dataset_id) "
                "VALUES (?, ?, ?, ?)",
                sorted(rows),
            )
    except Exception as exc:
        report.errors.append(f"Database write failed ({type(exc).__name__}); previous data kept")
        return report
    report.imported = len(rows)
    report.ok = True
    return report


def _replace_dataset_row(conn, meta: dict, kind: str, count: int, path: Path) -> None:
    conn.execute("DELETE FROM datasets WHERE dataset_id=?", (meta["dataset_id"],))
    conn.execute(
        """INSERT INTO datasets (dataset_id, kind, name, version, source_url, license,
               attribution, notes, is_demo, imported_at, record_count, source_file, source_sha256)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            meta["dataset_id"], kind, meta["name"], meta.get("version"), meta.get("source_url"),
            meta.get("license"), meta.get("attribution"), meta.get("notes"),
            int(meta.get("is_demo", 0)), db.now_iso(), count, Path(path).name,
            file_sha256([Path(path)]),
        ),
    )


def _stored_sha(db_path: Path, dataset_id: str) -> str | None:
    with db.reader(db_path) as conn:
        row = conn.execute(
            "SELECT source_sha256 FROM datasets WHERE dataset_id=?", (dataset_id,)
        ).fetchone()
    return row["source_sha256"] if row else None


def ensure_seed_data(db_path: Path) -> list[str]:
    """Load the bundled CSVs if missing or changed. Idempotent: running it
    twice never duplicates data. Returns a list of problems (empty if fine)."""
    problems: list[str] = []
    jobs = [
        (config.SEED_INTERACTIONS_CSV, config.STARTER_INTERACTIONS,
         lambda p, m: import_interactions(db_path, [p], m, fmt="medsafe")),
        (config.SEED_FOOD_CSV, config.STARTER_FOOD, lambda p, m: import_food(db_path, p, m)),
        (config.SEED_ALIASES_CSV, config.STARTER_ALIASES, lambda p, m: import_aliases(db_path, p, m)),
    ]
    for path, meta, run in jobs:
        if not Path(path).exists():
            if _stored_sha(db_path, meta["dataset_id"]) is None:
                problems.append(f"Bundled file missing: {Path(path).name}")
            continue
        try:
            current = file_sha256([path])
        except OSError:
            problems.append(f"Could not read {Path(path).name}")
            continue
        if _stored_sha(db_path, meta["dataset_id"]) == current:
            continue
        report = run(path, meta)
        if not report.ok:
            kept = _stored_sha(db_path, meta["dataset_id"]) is not None
            problems.append(
                f"{meta['name']}: {'; '.join(report.errors) or 'import failed'}"
                + (" (the previously loaded copy is still in use)" if kept else "")
            )
    return problems

