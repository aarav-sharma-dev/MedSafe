"""Medication, schedule, demo-profile, and report persistence layer.

Separates user medication management and daily schedule tracking from both
the Streamlit UI and the deterministic interaction engine.
"""

from __future__ import annotations

import csv
import html
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import db
from dataset_import import normalize_name
from interactions import (
    CheckReport,
    CheckStatus,
    Ingredient,
    MedForCheck,
)

VALID_CATEGORIES = ("prescription", "otc", "supplement", "herbal", "other")
VALID_ENTRY_SOURCES = ("manual", "scanned", "imported", "demo")
VALID_IDENTITY_STATUSES = ("confirmed", "needs_review", "unidentified")
VALID_DOSE_STATUSES = ("taken", "skipped")

_TIME_24_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def normalize_time_hhmm(value: str | None) -> str | None:
    """Convert '8:00 am', '08:00', 'bedtime', etc. into 24-hour 'HH:MM'."""
    raw = (value or "").strip().lower()
    if not raw:
        return None
    named = {
        "morning": "08:00",
        "breakfast": "08:00",
        "noon": "12:00",
        "lunch": "12:30",
        "afternoon": "14:00",
        "evening": "18:00",
        "dinner": "18:00",
        "bedtime": "21:00",
        "night": "21:00",
    }
    if raw in named:
        return named[raw]
    if _TIME_24_RE.match(raw):
        return raw
    for fmt in ("%I:%M %p", "%I %p", "%H:%M"):
        try:
            return datetime.strptime(raw.upper(), fmt).strftime("%H:%M")
        except ValueError:
            continue
    return None


def format_time_12h(hhmm: str | None) -> str:
    """'08:00' -> '8:00 AM', '21:00' -> '9:00 PM'."""
    norm = normalize_time_hhmm(hhmm)
    if not norm:
        return (hhmm or "").strip()
    dt = datetime.strptime(norm, "%H:%M")
    return dt.strftime("%I:%M %p").lstrip("0")


@dataclass
class ScheduleEntry:
    id: int
    medication_id: int
    time_of_day: str  # HH:MM
    label: str | None = None
    created_at: str = ""

    @property
    def display_time(self) -> str:
        t = format_time_12h(self.time_of_day)
        return f"{t} ({self.label})" if self.label else t


@dataclass
class MedicationRecord:
    id: int
    display_name: str
    generic_name: str | None = None
    brand_name: str | None = None
    rxcui: str | None = None
    rxnorm_name: str | None = None
    rxnorm_tty: str | None = None
    strength: str | None = None
    dose_form: str | None = None
    route: str | None = None
    instructions: str | None = None
    category: str = "prescription"
    start_date: str | None = None
    end_date: str | None = None
    prescriber: str | None = None
    pharmacy: str | None = None
    notes: str | None = None
    active: bool = True
    entry_source: str = "manual"
    identity_status: str = "unidentified"
    identity_source: str | None = None
    original_text: str | None = None
    created_at: str = ""
    updated_at: str = ""
    ingredients: list[Ingredient] = field(default_factory=list)
    schedule: list[ScheduleEntry] = field(default_factory=list)

    @property
    def is_combination(self) -> bool:
        return len(self.ingredients) > 1

    @property
    def ingredient_names(self) -> list[str]:
        return [i.name for i in self.ingredients]

    def to_check_item(self) -> MedForCheck:
        return MedForCheck(
            key=f"med-{self.id}",
            display_name=self.display_name,
            ingredients=tuple(self.ingredients),
            identity_status=self.identity_status,
            is_proposed=False,
        )


def _clean_opt(val: str | None, max_len: int = 500) -> str | None:
    if val is None:
        return None
    cleaned = " ".join(str(val).strip().split())
    return cleaned[:max_len] if cleaned else None


def _normalize_ingredients(
    ingredients: list[Ingredient | dict | str] | None,
    fallback_generic: str | None = None,
    fallback_rxcui: str | None = None,
) -> list[Ingredient]:
    out: list[Ingredient] = []
    seen: set[str] = set()
    for item in ingredients or []:
        if isinstance(item, Ingredient):
            name = normalize_name(item.name)
            rxcui = _clean_opt(item.rxcui, 40)
        elif isinstance(item, dict):
            name = normalize_name(item.get("ingredient") or item.get("name") or "")
            rxcui = _clean_opt(item.get("rxcui"), 40)
        else:
            name = normalize_name(str(item))
            rxcui = None
        if name and name not in seen:
            seen.add(name)
            out.append(Ingredient(name=name, rxcui=rxcui))
    if not out and fallback_generic:
        for part in re.split(r"\s*[+/;]\s*", fallback_generic):
            name = normalize_name(part)
            if name and name not in seen:
                seen.add(name)
                out.append(
                    Ingredient(
                        name=name,
                        rxcui=fallback_rxcui if len(out) == 0 else None,
                    )
                )
    return out


# --- Medication CRUD -------------------------------------------------------

def add_medication(
    db_path: Path,
    display_name: str,
    *,
    generic_name: str | None = None,
    brand_name: str | None = None,
    rxcui: str | None = None,
    rxnorm_name: str | None = None,
    rxnorm_tty: str | None = None,
    strength: str | None = None,
    dose_form: str | None = None,
    route: str | None = None,
    instructions: str | None = None,
    category: str = "prescription",
    start_date: str | None = None,
    end_date: str | None = None,
    prescriber: str | None = None,
    pharmacy: str | None = None,
    notes: str | None = None,
    active: bool = True,
    entry_source: str = "manual",
    identity_status: str = "unidentified",
    identity_source: str | None = None,
    original_text: str | None = None,
    ingredients: list[Ingredient | dict | str] | None = None,
    schedule_times: list[str | tuple[str, str | None]] | None = None,
) -> int:
    """Insert a medication record, its ingredients, and optional schedule times."""
    clean_display = _clean_opt(display_name, 200)
    if not clean_display:
        raise ValueError("Medication display name is required.")

    cat = category.strip().lower() if category else "prescription"
    if cat not in VALID_CATEGORIES:
        cat = "other"

    src = entry_source.strip().lower() if entry_source else "manual"
    if src not in VALID_ENTRY_SOURCES:
        src = "manual"

    id_status = identity_status.strip().lower() if identity_status else "unidentified"
    if id_status not in VALID_IDENTITY_STATUSES:
        id_status = "unidentified"

    norm_ings = _normalize_ingredients(ingredients, generic_name, rxcui)
    # Conservative safety rule: a medication cannot be "confirmed" without at
    # least one identified active ingredient.
    if id_status == "confirmed" and not norm_ings:
        id_status = "unidentified"

    stamp = db.now_iso()
    with db.transaction(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO medications (
                   display_name, generic_name, brand_name, rxcui, rxnorm_name, rxnorm_tty,
                   strength, dose_form, route, instructions, category, start_date, end_date,
                   prescriber, pharmacy, notes, active, entry_source, identity_status,
                   identity_source, original_text, created_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                clean_display,
                _clean_opt(generic_name, 200),
                _clean_opt(brand_name, 200),
                _clean_opt(rxcui, 40),
                _clean_opt(rxnorm_name, 250),
                _clean_opt(rxnorm_tty, 20),
                _clean_opt(strength, 100),
                _clean_opt(dose_form, 100),
                _clean_opt(route, 80),
                _clean_opt(instructions, 500),
                cat,
                _clean_opt(start_date, 30),
                _clean_opt(end_date, 30),
                _clean_opt(prescriber, 150),
                _clean_opt(pharmacy, 150),
                _clean_opt(notes, 1000),
                1 if active else 0,
                src,
                id_status,
                _clean_opt(identity_source, 100),
                _clean_opt(original_text, 2000),
                stamp,
                stamp,
            ),
        )
        med_id = int(cur.lastrowid)
        for ing in norm_ings:
            conn.execute(
                "INSERT OR IGNORE INTO medication_ingredients (medication_id, ingredient, rxcui) "
                "VALUES (?, ?, ?)",
                (med_id, ing.name, ing.rxcui),
            )
        for item in schedule_times or []:
            if isinstance(item, (tuple, list)):
                raw_time, label = item[0], (item[1] if len(item) > 1 else None)
            else:
                raw_time, label = str(item), None
            hhmm = normalize_time_hhmm(raw_time)
            if hhmm:
                conn.execute(
                    "INSERT OR IGNORE INTO schedule_entries (medication_id, time_of_day, label, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (med_id, hhmm, _clean_opt(label, 80), stamp),
                )
    return med_id


def update_medication(
    db_path: Path,
    med_id: int,
    *,
    display_name: str | None = None,
    generic_name: str | None = None,
    brand_name: str | None = None,
    rxcui: str | None = None,
    rxnorm_name: str | None = None,
    rxnorm_tty: str | None = None,
    strength: str | None = None,
    dose_form: str | None = None,
    route: str | None = None,
    instructions: str | None = None,
    category: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    prescriber: str | None = None,
    pharmacy: str | None = None,
    notes: str | None = None,
    active: bool | None = None,
    identity_status: str | None = None,
    identity_source: str | None = None,
    ingredients: list[Ingredient | dict | str] | None = None,
    schedule_times: list[str | tuple[str, str | None]] | None = None,
) -> bool:
    """Update an existing medication record. Returns True if found and updated."""
    existing = get_medication(db_path, med_id)
    if existing is None:
        return False

    new_display = _clean_opt(display_name, 200) if display_name is not None else existing.display_name
    if not new_display:
        raise ValueError("Medication display name cannot be empty.")

    new_cat = (category or existing.category).strip().lower()
    if new_cat not in VALID_CATEGORIES:
        new_cat = existing.category

    new_id_status = (identity_status or existing.identity_status).strip().lower()
    if new_id_status not in VALID_IDENTITY_STATUSES:
        new_id_status = existing.identity_status

    new_generic = _clean_opt(generic_name, 200) if generic_name is not None else existing.generic_name
    new_rxcui = _clean_opt(rxcui, 40) if rxcui is not None else existing.rxcui

    if ingredients is not None:
        norm_ings = _normalize_ingredients(ingredients, new_generic, new_rxcui)
    else:
        norm_ings = existing.ingredients

    if new_id_status == "confirmed" and not norm_ings:
        new_id_status = "unidentified"

    stamp = db.now_iso()
    with db.transaction(db_path) as conn:
        conn.execute(
            """UPDATE medications SET
                   display_name=?, generic_name=?, brand_name=?, rxcui=?, rxnorm_name=?,
                   rxnorm_tty=?, strength=?, dose_form=?, route=?, instructions=?,
                   category=?, start_date=?, end_date=?, prescriber=?, pharmacy=?,
                   notes=?, active=?, identity_status=?, identity_source=?, updated_at=?
               WHERE id=?""",
            (
                new_display,
                new_generic,
                _clean_opt(brand_name, 200) if brand_name is not None else existing.brand_name,
                new_rxcui,
                _clean_opt(rxnorm_name, 250) if rxnorm_name is not None else existing.rxnorm_name,
                _clean_opt(rxnorm_tty, 20) if rxnorm_tty is not None else existing.rxnorm_tty,
                _clean_opt(strength, 100) if strength is not None else existing.strength,
                _clean_opt(dose_form, 100) if dose_form is not None else existing.dose_form,
                _clean_opt(route, 80) if route is not None else existing.route,
                _clean_opt(instructions, 500) if instructions is not None else existing.instructions,
                new_cat,
                _clean_opt(start_date, 30) if start_date is not None else existing.start_date,
                _clean_opt(end_date, 30) if end_date is not None else existing.end_date,
                _clean_opt(prescriber, 150) if prescriber is not None else existing.prescriber,
                _clean_opt(pharmacy, 150) if pharmacy is not None else existing.pharmacy,
                _clean_opt(notes, 1000) if notes is not None else existing.notes,
                (1 if active else 0) if active is not None else (1 if existing.active else 0),
                new_id_status,
                _clean_opt(identity_source, 100) if identity_source is not None else existing.identity_source,
                stamp,
                med_id,
            ),
        )
        if ingredients is not None:
            conn.execute("DELETE FROM medication_ingredients WHERE medication_id=?", (med_id,))
            for ing in norm_ings:
                conn.execute(
                    "INSERT OR IGNORE INTO medication_ingredients (medication_id, ingredient, rxcui) "
                    "VALUES (?, ?, ?)",
                    (med_id, ing.name, ing.rxcui),
                )
        if schedule_times is not None:
            # Preserve existing entries where time matches so dose_log stays intact
            existing_by_time = {s.time_of_day: s for s in existing.schedule}
            desired: dict[str, str | None] = {}
            for item in schedule_times:
                if isinstance(item, (tuple, list)):
                    raw_t, lbl = item[0], (item[1] if len(item) > 1 else None)
                else:
                    raw_t, lbl = str(item), None
                hhmm = normalize_time_hhmm(raw_t)
                if hhmm:
                    desired[hhmm] = _clean_opt(lbl, 80)
            for old_t, old_entry in existing_by_time.items():
                if old_t not in desired:
                    conn.execute("DELETE FROM schedule_entries WHERE id=?", (old_entry.id,))
            for hhmm, lbl in desired.items():
                if hhmm in existing_by_time:
                    conn.execute(
                        "UPDATE schedule_entries SET label=? WHERE id=?",
                        (lbl, existing_by_time[hhmm].id),
                    )
                else:
                    conn.execute(
                        "INSERT INTO schedule_entries (medication_id, time_of_day, label, created_at) "
                        "VALUES (?, ?, ?, ?)",
                        (med_id, hhmm, lbl, stamp),
                    )
    return True


def set_medication_active(db_path: Path, med_id: int, active: bool) -> bool:
    return update_medication(db_path, med_id, active=active)


def confirm_medication_identity(
    db_path: Path,
    med_id: int,
    *,
    generic_name: str | None = None,
    brand_name: str | None = None,
    rxcui: str | None = None,
    rxnorm_name: str | None = None,
    rxnorm_tty: str | None = None,
    strength: str | None = None,
    dose_form: str | None = None,
    route: str | None = None,
    ingredients: list[Ingredient | dict | str],
    identity_source: str = "user_confirmed",
) -> bool:
    """Mark a medication's identity as confirmed once the user verifies it."""
    norm_ings = _normalize_ingredients(ingredients, generic_name, rxcui)
    if not norm_ings:
        raise ValueError("Cannot confirm a medication identity without at least one active ingredient.")
    return update_medication(
        db_path,
        med_id,
        generic_name=generic_name,
        brand_name=brand_name,
        rxcui=rxcui,
        rxnorm_name=rxnorm_name,
        rxnorm_tty=rxnorm_tty,
        strength=strength,
        dose_form=dose_form,
        route=route,
        ingredients=norm_ings,
        identity_status="confirmed",
        identity_source=identity_source,
    )


def delete_medication(db_path: Path, med_id: int) -> bool:
    with db.transaction(db_path) as conn:
        cur = conn.execute("DELETE FROM medications WHERE id=?", (med_id,))
        return cur.rowcount > 0


def _hydrate_medications(conn, rows) -> list[MedicationRecord]:
    if not rows:
        return []
    ids = [r["id"] for r in rows]
    marks = ",".join("?" * len(ids))
    ings_by_med: dict[int, list[Ingredient]] = {i: [] for i in ids}
    for r in conn.execute(
        f"SELECT * FROM medication_ingredients WHERE medication_id IN ({marks}) ORDER BY ingredient",
        ids,
    ):
        ings_by_med[r["medication_id"]].append(Ingredient(name=r["ingredient"], rxcui=r["rxcui"]))

    sched_by_med: dict[int, list[ScheduleEntry]] = {i: [] for i in ids}
    for r in conn.execute(
        f"SELECT * FROM schedule_entries WHERE medication_id IN ({marks}) ORDER BY time_of_day",
        ids,
    ):
        sched_by_med[r["medication_id"]].append(
            ScheduleEntry(
                id=r["id"],
                medication_id=r["medication_id"],
                time_of_day=r["time_of_day"],
                label=r["label"],
                created_at=r["created_at"],
            )
        )

    out: list[MedicationRecord] = []
    for r in rows:
        mid = r["id"]
        out.append(
            MedicationRecord(
                id=mid,
                display_name=r["display_name"],
                generic_name=r["generic_name"],
                brand_name=r["brand_name"],
                rxcui=r["rxcui"],
                rxnorm_name=r["rxnorm_name"],
                rxnorm_tty=r["rxnorm_tty"],
                strength=r["strength"],
                dose_form=r["dose_form"],
                route=r["route"],
                instructions=r["instructions"],
                category=r["category"],
                start_date=r["start_date"],
                end_date=r["end_date"],
                prescriber=r["prescriber"],
                pharmacy=r["pharmacy"],
                notes=r["notes"],
                active=bool(r["active"]),
                entry_source=r["entry_source"],
                identity_status=r["identity_status"],
                identity_source=r["identity_source"],
                original_text=r["original_text"],
                created_at=r["created_at"],
                updated_at=r["updated_at"],
                ingredients=ings_by_med.get(mid, []),
                schedule=sched_by_med.get(mid, []),
            )
        )
    return out


def get_medication(db_path: Path, med_id: int) -> MedicationRecord | None:
    with db.reader(db_path) as conn:
        row = conn.execute("SELECT * FROM medications WHERE id=?", (med_id,)).fetchone()
        if not row:
            return None
        return _hydrate_medications(conn, [row])[0]


def list_medications(
    db_path: Path,
    *,
    active_only: bool = False,
    category: str | None = None,
    identity_status: str | None = None,
    search: str | None = None,
) -> list[MedicationRecord]:
    clauses: list[str] = []
    params: list[object] = []
    if active_only:
        clauses.append("active = 1")
    if category and category != "all":
        clauses.append("category = ?")
        params.append(category)
    if identity_status and identity_status != "all":
        clauses.append("identity_status = ?")
        params.append(identity_status)

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    with db.reader(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM medications {where} ORDER BY active DESC, display_name COLLATE NOCASE ASC",
            params,
        ).fetchall()
        meds = _hydrate_medications(conn, rows)

    if search and search.strip():
        q = normalize_name(search)
        meds = [
            m
            for m in meds
            if q in normalize_name(m.display_name)
            or q in normalize_name(m.generic_name or "")
            or q in normalize_name(m.brand_name or "")
            or any(q in normalize_name(i.name) for i in m.ingredients)
        ]
    return meds


def active_meds_for_check(db_path: Path) -> list[MedForCheck]:
    return [m.to_check_item() for m in list_medications(db_path, active_only=True)]


def find_duplicate_medications(
    meds: list[MedicationRecord],
) -> list[dict[str, object]]:
    """Detect possible duplicate entries by normalized name or shared active ingredients.
    Never deletes anything automatically - returned as a user review aid."""
    warnings: list[dict[str, object]] = []
    active_meds = [m for m in meds if m.active]

    by_name: dict[str, list[MedicationRecord]] = {}
    for m in active_meds:
        key = normalize_name(m.generic_name or m.display_name)
        if key:
            by_name.setdefault(key, []).append(m)
    for key, group in sorted(by_name.items()):
        if len(group) > 1:
            warnings.append(
                {
                    "kind": "duplicate_name",
                    "subject": key,
                    "medicines": [
                        f"{m.display_name}" + (f" ({m.strength})" if m.strength else "")
                        for m in group
                    ],
                }
            )

    by_ing: dict[str, list[MedicationRecord]] = {}
    for m in active_meds:
        for ing in m.ingredients:
            by_ing.setdefault(normalize_name(ing.name), []).append(m)
    for ing_name, group in sorted(by_ing.items()):
        if len(group) > 1:
            names = [
                f"{m.display_name}" + (f" ({m.strength})" if m.strength else "")
                for m in group
            ]
            # Avoid repeating the exact same warning if already caught by name
            if not any(w["subject"] == ing_name and w["medicines"] == names for w in warnings):
                warnings.append(
                    {
                        "kind": "shared_ingredient",
                        "subject": ing_name,
                        "medicines": names,
                    }
                )
    return warnings


# --- Daily Schedule & Dose Log ---------------------------------------------

@dataclass
class ScheduledDoseItem:
    schedule_entry_id: int
    medication_id: int
    medication_name: str
    strength: str | None
    dose_form: str | None
    instructions: str | None
    time_of_day: str  # HH:MM
    label: str | None
    log_date: str     # YYYY-MM-DD
    status: str | None  # 'taken' | 'skipped' | None
    recorded_at: str | None = None

    @property
    def display_time(self) -> str:
        return format_time_12h(self.time_of_day)


def add_schedule_entry(
    db_path: Path, medication_id: int, time_of_day: str, label: str | None = None
) -> int:
    hhmm = normalize_time_hhmm(time_of_day)
    if not hhmm:
        raise ValueError(f"Could not understand schedule time: {time_of_day!r}")
    stamp = db.now_iso()
    with db.transaction(db_path) as conn:
        conn.execute(
            """INSERT INTO schedule_entries (medication_id, time_of_day, label, created_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(medication_id, time_of_day)
               DO UPDATE SET label=excluded.label""",
            (medication_id, hhmm, _clean_opt(label, 80), stamp),
        )
        row = conn.execute(
            "SELECT id FROM schedule_entries WHERE medication_id=? AND time_of_day=?",
            (medication_id, hhmm),
        ).fetchone()
        return int(row["id"])


def remove_schedule_entry(db_path: Path, schedule_entry_id: int) -> bool:
    with db.transaction(db_path) as conn:
        cur = conn.execute("DELETE FROM schedule_entries WHERE id=?", (schedule_entry_id,))
        return cur.rowcount > 0


def record_dose_status(
    db_path: Path,
    schedule_entry_id: int,
    status: str | None,
    log_date: str | None = None,
) -> None:
    """Record 'taken', 'skipped', or None (clear status) for a schedule entry on log_date."""
    day = log_date or date.today().isoformat()
    with db.transaction(db_path) as conn:
        if status is None:
            conn.execute(
                "DELETE FROM dose_log WHERE schedule_entry_id=? AND log_date=?",
                (schedule_entry_id, day),
            )
            return
        norm_status = status.strip().lower()
        if norm_status not in VALID_DOSE_STATUSES:
            raise ValueError(f"Invalid dose status: {status!r}")
        conn.execute(
            """INSERT INTO dose_log (schedule_entry_id, log_date, status, recorded_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(schedule_entry_id, log_date)
               DO UPDATE SET status=excluded.status, recorded_at=excluded.recorded_at""",
            (schedule_entry_id, day, norm_status, db.now_iso()),
        )


def get_daily_schedule(
    db_path: Path, target_date: str | None = None
) -> list[ScheduledDoseItem]:
    day = target_date or date.today().isoformat()
    with db.reader(db_path) as conn:
        rows = conn.execute(
            """SELECT s.id AS schedule_entry_id, s.medication_id, s.time_of_day, s.label,
                      m.display_name, m.strength, m.dose_form, m.instructions,
                      l.status, l.recorded_at
               FROM schedule_entries s
               JOIN medications m ON m.id = s.medication_id
               LEFT JOIN dose_log l ON l.schedule_entry_id = s.id AND l.log_date = ?
               WHERE m.active = 1
               ORDER BY s.time_of_day ASC, m.display_name COLLATE NOCASE ASC""",
            (day,),
        ).fetchall()
    return [
        ScheduledDoseItem(
            schedule_entry_id=r["schedule_entry_id"],
            medication_id=r["medication_id"],
            medication_name=r["display_name"],
            strength=r["strength"],
            dose_form=r["dose_form"],
            instructions=r["instructions"],
            time_of_day=r["time_of_day"],
            label=r["label"],
            log_date=day,
            status=r["status"],
            recorded_at=r["recorded_at"],
        )
        for r in rows
    ]


def get_next_scheduled_dose(
    items: list[ScheduledDoseItem], now: datetime | None = None
) -> ScheduledDoseItem | None:
    """Return the next pending scheduled entry today, or the earliest unlogged entry."""
    pending = [i for i in items if i.status is None]
    if not pending:
        return None
    now_hhmm = (now or datetime.now()).strftime("%H:%M")
    upcoming = [i for i in pending if i.time_of_day >= now_hhmm]
    return upcoming[0] if upcoming else pending[0]


def get_recent_dose_history(db_path: Path, days: int = 7) -> list[dict]:
    """Return recorded dose log activity over the last N days."""
    since = (date.today() - timedelta(days=max(1, days))).isoformat()
    with db.reader(db_path) as conn:
        rows = conn.execute(
            """SELECT l.log_date, l.status, l.recorded_at,
                      s.time_of_day, s.label,
                      m.display_name, m.strength
               FROM dose_log l
               JOIN schedule_entries s ON s.id = l.schedule_entry_id
               JOIN medications m ON m.id = s.medication_id
               WHERE l.log_date >= ?
               ORDER BY l.log_date DESC, s.time_of_day ASC""",
            (since,),
        ).fetchall()
    return [dict(r) for r in rows]


def export_schedule_ics(db_path: Path, days_ahead: int = 7) -> str:
    """Generate a standard RFC 5545 iCalendar (.ics) file for the active schedule."""
    items = get_daily_schedule(db_path, date.today().isoformat())
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//MedSafe//Medication Schedule//EN",
        "CALSCALE:GREGORIAN",
    ]
    today = date.today()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for offset in range(max(1, days_ahead)):
        day = today + timedelta(days=offset)
        for item in items:
            hh, mm = item.time_of_day.split(":")
            start_dt = f"{day.strftime('%Y%m%d')}T{hh}{mm}00"
            end_dt = f"{day.strftime('%Y%m%d')}T{hh}{int(mm):02d}00"
            summary = f"Medication: {item.medication_name}" + (f" ({item.strength})" if item.strength else "")
            desc = item.instructions or "Review your prescription label instructions."
            uid = f"medsafe-{item.schedule_entry_id}-{day.strftime('%Y%m%d')}@medsafe.local"
            lines.extend(
                [
                    "BEGIN:VEVENT",
                    f"UID:{uid}",
                    f"DTSTAMP:{stamp}",
                    f"DTSTART:{start_dt}",
                    f"DTEND:{end_dt}",
                    f"SUMMARY:{summary}",
                    f"DESCRIPTION:{desc}",
                    "END:VEVENT",
                ]
            )
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


# --- Caregiver & Pharmacist Reports and Exports ----------------------------

def record_report_generation(db_path: Path, report_type: str) -> None:
    with db.transaction(db_path) as conn:
        conn.execute(
            "INSERT INTO report_history (created_at, report_type) VALUES (?, ?)",
            (db.now_iso(), report_type),
        )


def list_report_history(db_path: Path, limit: int = 10) -> list[dict]:
    with db.reader(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM report_history ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def build_pharmacist_questions(
    meds: list[MedicationRecord],
    report: CheckReport,
    proposed_name: str | None = None,
) -> list[str]:
    """Generate practical, non-prescriptive questions to ask a pharmacist or doctor."""
    questions: list[str] = []
    matches = report.by_status(CheckStatus.MATCH_FOUND)
    for pair in matches:
        sev = (pair.top_severity or "unspecified").upper()
        questions.append(
            f"My medication checker found a {sev.lower()} interaction record between "
            f"{pair.med_a.display_name} and {pair.med_b.display_name}. What does this mean "
            f"for me, and should we review my regimen or monitoring plan?"
        )
    if proposed_name:
        questions.append(
            f"I am considering taking {proposed_name}. Could you check whether it is "
            f"appropriate alongside my current prescription and over-the-counter medicines?"
        )
    unconfirmed = [m for m in meds if m.active and m.identity_status != "confirmed"]
    if unconfirmed:
        names = ", ".join(m.display_name for m in unconfirmed)
        questions.append(
            f"Could you help me confirm the exact active ingredients and strengths for: {names}?"
        )
    dups = find_duplicate_medications(meds)
    for d in dups:
        questions.append(
            f"My list includes {', '.join(d['medicines'])} which may share '{d['subject']}'. "
            f"Are both of these intended to be on my active medication list?"
        )
    if report.food_findings:
        foods = ", ".join(sorted({f"{f.medicine} ({f.food})" for f in report.food_findings}))
        questions.append(
            f"Are there specific food or drink timing precautions I should follow for: {foods}?"
        )
    questions.extend(
        [
            "Are any of the medicines or supplements on my list no longer needed or overlapping?",
            "Could you confirm the best time of day and food instructions for each of my daily medicines?",
            "Because the MedSafe app uses a limited reference dataset, could you run a full professional interaction screen on my complete list?",
        ]
    )
    return questions


def export_medications_csv(meds: list[MedicationRecord]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(
        [
            "display_name",
            "generic_name",
            "brand_name",
            "ingredients",
            "rxcui",
            "strength",
            "dose_form",
            "route",
            "category",
            "instructions",
            "schedule_times",
            "active",
            "identity_status",
            "entry_source",
            "prescriber",
            "pharmacy",
            "notes",
        ]
    )
    for m in meds:
        writer.writerow(
            [
                m.display_name,
                m.generic_name or "",
                m.brand_name or "",
                " + ".join(i.name for i in m.ingredients),
                m.rxcui or "",
                m.strength or "",
                m.dose_form or "",
                m.route or "",
                m.category,
                m.instructions or "",
                ", ".join(s.display_time for s in m.schedule),
                "active" if m.active else "inactive",
                m.identity_status,
                m.entry_source,
                m.prescriber or "",
                m.pharmacy or "",
                m.notes or "",
            ]
        )
    return buf.getvalue()


def export_summary_markdown(
    meds: list[MedicationRecord],
    report: CheckReport,
    *,
    is_demo: bool = False,
    proposed_name: str | None = None,
) -> str:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    active_meds = [m for m in meds if m.active]
    inactive_meds = [m for m in meds if not m.active]
    questions = build_pharmacist_questions(meds, report, proposed_name)

    lines = [
        "# MedSafe Medication & Interaction Summary",
        f"**Generated:** {stamp}",
    ]
    if is_demo:
        lines.append(
            "\n> **DEMO MODE NOTICE:** This report contains fictional demonstration "
            "data for the Congressional App Challenge and is not a real patient record."
        )
    lines.extend(
        [
            "",
            "> **Educational Prototype Disclaimer:** MedSafe is an educational medication "
            "organization tool. It is not clinically validated and does not replace a "
            "pharmacist or physician review. Absence of an interaction record never confirms "
            "that a combination is safe.",
            "",
            f"## 1. Active Medications ({len(active_meds)})",
        ]
    )
    if not active_meds:
        lines.append("_No active medications recorded._")
    else:
        for m in active_meds:
            ings = ", ".join(i.name for i in m.ingredients) or "Not yet identified"
            sched = ", ".join(s.display_time for s in m.schedule) or "No schedule configured"
            id_badge = {
                "confirmed": "Confirmed identity",
                "needs_review": "Needs identity confirmation",
                "unidentified": "Unidentified — could not be checked",
            }.get(m.identity_status, m.identity_status)
            details = " | ".join(
                x for x in [m.strength, m.dose_form, m.route, f"Category: {m.category}"] if x
            )
            lines.append(f"- **{m.display_name}** ({details})")
            lines.append(f"  - Active ingredient(s): {ings}" + (f" (RxCUI: {m.rxcui})" if m.rxcui else ""))
            if m.brand_name or m.generic_name:
                lines.append(
                    f"  - Generic / Brand: {m.generic_name or '—'} / {m.brand_name or '—'}"
                )
            lines.append(f"  - User-entered directions: {m.instructions or 'None recorded'}")
            lines.append(f"  - Daily schedule: {sched}")
            lines.append(f"  - Identification status: **{id_badge}** (Entry source: {m.entry_source})")
            if m.notes:
                lines.append(f"  - Notes: {m.notes}")

    if inactive_meds:
        lines.append(f"\n### Inactive / Past Medications ({len(inactive_meds)})")
        for m in inactive_meds:
            lines.append(f"- {m.display_name} ({m.strength or 'strength not listed'}) — Inactive")

    lines.extend(["", "## 2. Interaction Review Summary"])
    if not report.complete:
        lines.append(
            "**⚠️ INCOMPLETE CHECK:** Not all medication pairs could be checked because one "
            "or more medicines require identity confirmation or the dataset was unavailable."
        )
    matches = report.by_status(CheckStatus.MATCH_FOUND)
    no_records = report.by_status(CheckStatus.NO_MATCHING_RECORD)
    incomplete_pairs = [
        r for r in report.results if r.status not in (CheckStatus.MATCH_FOUND, CheckStatus.NO_MATCHING_RECORD)
    ]

    lines.append(f"\n### Matching Interaction Records Found ({len(matches)})")
    if not matches:
        lines.append("_No matching interaction records were found in the loaded dataset for the checked pairs._")
    else:
        for r in matches:
            for rec in r.records:
                lines.append(
                    f"- **{r.med_a.display_name} + {r.med_b.display_name}** — "
                    f"Recorded severity: **{rec.severity_raw or rec.severity_level}** "
                    f"(Source: {rec.dataset_name}, Record ID: {rec.source_record_id or rec.record_id})"
                )
                lines.append(f"  - Mechanism: {rec.mechanism or 'Not supplied by source dataset.'}")
                if rec.management:
                    lines.append(f"  - Source management note: {rec.management}")
                lines.append(
                    "  - Next step: Contact your pharmacist or prescriber to discuss what this "
                    "record means for your situation. Do not stop or change a prescribed dose on your own."
                )

    lines.append(f"\n### Pairs That Could Not Be Checked ({len(incomplete_pairs)})")
    if not incomplete_pairs:
        lines.append("_All active medication pairs had confirmed identities for lookup._")
    else:
        for r in incomplete_pairs:
            lines.append(
                f"- **{r.med_a.display_name} + {r.med_b.display_name}** — Status: `{r.status.value}` "
                "(Requires medication identity confirmation before lookup can run.)"
            )

    lines.append(f"\n### Pairs With No Matching Record in Loaded Dataset ({len(no_records)})")
    lines.append(
        "_Important: Having no matching record in the loaded dataset does **not** establish that "
        "these medicines are safe to take together. The dataset is incomplete._"
    )
    for r in no_records:
        lines.append(f"- {r.med_a.display_name} + {r.med_b.display_name}: No matching record in loaded dataset")

    lines.extend(["", "## 3. Questions for Your Pharmacist or Prescriber"])
    for q in questions:
        lines.append(f"1. {q}")

    lines.extend(
        [
            "",
            "## 4. Dataset Provenance & Limitations",
            f"- **Loaded dataset(s):** {report.dataset_status.label}",
            f"- **Total interaction records loaded:** {report.dataset_status.total_records}",
        ]
    )
    for d in report.dataset_status.datasets:
        lines.append(
            f"- **{d.name}** (Version: {d.version or 'unspecified'}, Imported: {d.imported_at}): "
            f"{d.attribution or ''} License: {d.license or 'unspecified'}. {d.notes or ''}"
        )
    return "\n".join(lines) + "\n"


def export_printable_html(
    meds: list[MedicationRecord],
    report: CheckReport,
    *,
    is_demo: bool = False,
    proposed_name: str | None = None,
) -> str:
    """Return a clean, print-friendly standalone HTML document for a caregiver or pharmacist."""
    md = export_summary_markdown(meds, report, is_demo=is_demo, proposed_name=proposed_name)
    escaped = html.escape(md)
    demo_banner = (
        '<div style="background:#FFF4E5;border:2px solid #9A5B00;padding:12px 16px;'
        'border-radius:8px;margin-bottom:16px;font-weight:600;color:#182433;">'
        "DEMONSTRATION DATA ONLY — Fictional sample medication list for MedSafe demo."
        "</div>"
        if is_demo
        else ""
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>MedSafe Medication &amp; Interaction Summary</title>
<style>
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    color: #182433;
    background: #FFFFFF;
    max-width: 840px;
    margin: 24px auto;
    padding: 0 20px;
    font-size: 16px;
    line-height: 1.55;
  }}
  h1 {{ color: #17324D; border-bottom: 2px solid #0F8B8D; padding-bottom: 8px; }}
  pre {{
    white-space: pre-wrap;
    word-wrap: break-word;
    font-family: inherit;
    font-size: 16px;
    background: #F6F8FB;
    border: 1px solid #DFE6EE;
    border-radius: 10px;
    padding: 20px;
  }}
  @media print {{
    body {{ margin: 0; max-width: 100%; }}
    pre {{ background: #FFFFFF; border: none; padding: 0; }}
  }}
</style>
</head>
<body>
{demo_banner}
<pre>{escaped}</pre>
</body>
</html>
"""


# --- Demo Profile Seeding --------------------------------------------------

def ensure_demo_profile(demo_db_path: Path, force: bool = False) -> list[str]:
    """Prepare the isolated demo SQLite database with a deterministic sample journey."""
    problems = db.prepare(demo_db_path)
    existing = list_medications(demo_db_path)
    if existing and not force:
        return problems

    db.clear_user_data(demo_db_path)

    # 1. Lisinopril 10 mg (confirmed ACE inhibitor)
    m_lis = add_medication(
        demo_db_path,
        "Lisinopril",
        generic_name="lisinopril",
        brand_name="Prinivil / Zestril",
        rxcui="29046",
        rxnorm_name="lisinopril 10 MG Oral Tablet",
        rxnorm_tty="SCD",
        strength="10 mg",
        dose_form="Oral Tablet",
        route="Oral",
        instructions="Take 1 tablet by mouth every morning.",
        category="prescription",
        start_date="2025-03-15",
        prescriber="Dr. Patel (Primary Care)",
        pharmacy="Community Corner Pharmacy",
        notes="DEMO RECORD — Blood pressure medicine.",
        active=True,
        entry_source="demo",
        identity_status="confirmed",
        identity_source="demo_seed",
        ingredients=[Ingredient("lisinopril", "29046")],
        schedule_times=[("08:00", "With breakfast")],
    )

    # 2. Metformin 500 mg (confirmed oral diabetes medicine)
    m_met = add_medication(
        demo_db_path,
        "Metformin",
        generic_name="metformin",
        brand_name="Glucophage",
        rxcui="6809",
        rxnorm_name="metformin hydrochloride 500 MG Oral Tablet",
        rxnorm_tty="SCD",
        strength="500 mg",
        dose_form="Oral Tablet",
        route="Oral",
        instructions="Take 1 tablet by mouth twice daily with morning and evening meals.",
        category="prescription",
        start_date="2024-11-01",
        prescriber="Dr. Patel (Primary Care)",
        pharmacy="Community Corner Pharmacy",
        notes="DEMO RECORD — Take with food.",
        active=True,
        entry_source="demo",
        identity_status="confirmed",
        identity_source="demo_seed",
        ingredients=[Ingredient("metformin", "6809")],
        schedule_times=[("08:00", "With breakfast"), ("18:00", "With dinner")],
    )

    # 3. Atorvastatin 20 mg (confirmed statin - has food interaction with grapefruit)
    m_ato = add_medication(
        demo_db_path,
        "Atorvastatin (Lipitor)",
        generic_name="atorvastatin",
        brand_name="Lipitor",
        rxcui="83367",
        rxnorm_name="atorvastatin 20 MG Oral Tablet",
        rxnorm_tty="SCD",
        strength="20 mg",
        dose_form="Oral Tablet",
        route="Oral",
        instructions="Take 1 tablet by mouth every evening at bedtime.",
        category="prescription",
        start_date="2025-01-10",
        prescriber="Dr. Gomez (Cardiology)",
        pharmacy="Community Corner Pharmacy",
        notes="DEMO RECORD — Cholesterol medicine.",
        active=True,
        entry_source="demo",
        identity_status="confirmed",
        identity_source="demo_seed",
        ingredients=[Ingredient("atorvastatin", "83367")],
        schedule_times=[("21:00", "Bedtime")],
    )

    # 4. Turmeric herbal supplement (needs_review - demonstrates how MedSafe
    # transparently flags unconfirmed items without pretending they were checked)
    add_medication(
        demo_db_path,
        "Golden Turmeric Root Complex",
        generic_name="curcuma longa extract",
        brand_name="DemoHerbs",
        strength="500 mg",
        dose_form="Oral Capsule",
        route="Oral",
        instructions="Take 1 capsule daily with water.",
        category="herbal",
        notes=(
            "DEMO RECORD — Herbal supplement added from bottle scan; awaiting "
            "ingredient confirmation."
        ),
        active=True,
        entry_source="demo",
        identity_status="needs_review",
        identity_source="ocr_unconfirmed",
        original_text="DEMO SAMPLE LABEL: GOLDEN TURMERIC ROOT COMPLEX 500MG CAPSULE",
        ingredients=[Ingredient("turmeric", "1114883")],
        schedule_times=[("12:30", "With lunch")],
    )

    # Record a couple of realistic dose log entries for today so the schedule
    # checklist shows live progress immediately.
    today_items = get_daily_schedule(demo_db_path, date.today().isoformat())
    for item in today_items:
        if item.medication_id in (m_lis, m_met) and item.time_of_day == "08:00":
            record_dose_status(demo_db_path, item.schedule_entry_id, "taken")
    _ = m_ato
    return problems
