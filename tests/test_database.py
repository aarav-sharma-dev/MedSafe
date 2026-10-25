"""Automated tests for SQLite persistence, medication CRUD, schedule logs,
exports, legacy migration, and data clearing."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import db
import interactions
import medications


def test_medication_crud_and_deactivation(tmp_path: Path) -> None:
    db_path = tmp_path / "crud.sqlite3"
    db.prepare(db_path)

    med_id = medications.add_medication(
        db_path,
        "Lisinopril",
        generic_name="lisinopril",
        brand_name="Prinivil",
        rxcui="29046",
        strength="10 mg",
        dose_form="Oral Tablet",
        instructions="Take 1 tablet every morning",
        category="prescription",
        identity_status="confirmed",
        ingredients=["lisinopril"],
        schedule_times=[("8:00 am", "Morning")],
    )
    med = medications.get_medication(db_path, med_id)
    assert med is not None
    assert med.display_name == "Lisinopril"
    assert med.identity_status == "confirmed"
    assert [i.name for i in med.ingredients] == ["lisinopril"]
    assert len(med.schedule) == 1
    assert med.schedule[0].time_of_day == "08:00"

    # Update medication fields
    medications.update_medication(
        db_path,
        med_id,
        strength="20 mg",
        notes="Updated by doctor",
        schedule_times=[("08:00", "Breakfast"), ("20:00", "Evening")],
    )
    updated = medications.get_medication(db_path, med_id)
    assert updated is not None
    assert updated.strength == "20 mg"
    assert updated.notes == "Updated by doctor"
    assert len(updated.schedule) == 2

    # Deactivate and reactivate
    medications.set_medication_active(db_path, med_id, False)
    assert medications.list_medications(db_path, active_only=True) == []
    medications.set_medication_active(db_path, med_id, True)
    assert len(medications.list_medications(db_path, active_only=True)) == 1

    # Delete after confirmation
    assert medications.delete_medication(db_path, med_id) is True
    assert medications.get_medication(db_path, med_id) is None


def test_schedule_dose_logging_and_exports(tmp_path: Path) -> None:
    db_path = tmp_path / "sched.sqlite3"
    medications.ensure_demo_profile(db_path, force=True)

    sched = medications.get_daily_schedule(db_path, "2026-10-18")
    assert len(sched) >= 4
    first_id = sched[0].schedule_entry_id

    medications.record_dose_status(db_path, first_id, "taken", "2026-10-18")
    sched_after = medications.get_daily_schedule(db_path, "2026-10-18")
    assert next(s for s in sched_after if s.schedule_entry_id == first_id).status == "taken"

    medications.record_dose_status(db_path, first_id, "skipped", "2026-10-18")
    sched_skip = medications.get_daily_schedule(db_path, "2026-10-18")
    assert next(s for s in sched_skip if s.schedule_entry_id == first_id).status == "skipped"

    medications.record_dose_status(db_path, first_id, None, "2026-10-18")
    sched_clear = medications.get_daily_schedule(db_path, "2026-10-18")
    assert next(s for s in sched_clear if s.schedule_entry_id == first_id).status is None

    # Exports (CSV, Markdown, Printable HTML, iCalendar)
    meds = medications.list_medications(db_path)
    rep = interactions.check_medications(db_path, [m.to_check_item() for m in meds if m.active])

    csv_out = medications.export_medications_csv(meds)
    assert "Lisinopril" in csv_out
    assert "Golden Turmeric Root Complex" in csv_out

    md_out = medications.export_summary_markdown(meds, rep, is_demo=True, proposed_name="Ibuprofen")
    assert "DEMO MODE NOTICE" in md_out
    assert "INCOMPLETE CHECK" in md_out
    assert "does **not** establish that these medicines are safe" in md_out

    html_out = medications.export_printable_html(meds, rep, is_demo=True)
    assert "<!DOCTYPE html>" in html_out
    assert "DEMONSTRATION DATA ONLY" in html_out

    ics_out = medications.export_schedule_ics(db_path, days_ahead=3)
    assert "BEGIN:VCALENDAR" in ics_out
    assert "BEGIN:VEVENT" in ics_out


def test_clear_user_data_preserves_reference_datasets(tmp_path: Path) -> None:
    db_path = tmp_path / "clear.sqlite3"
    medications.ensure_demo_profile(db_path, force=True)
    assert len(medications.list_medications(db_path)) > 0

    db.clear_user_data(db_path)
    assert medications.list_medications(db_path) == []
    # Reference interaction records remain intact
    assert interactions.get_dataset_status(db_path).total_records == 24


def test_legacy_v1_schema_migration_preserves_user_meds(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy_v1.sqlite3"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE meds (name TEXT PRIMARY KEY, dose TEXT, time_of_day TEXT, taken_today INTEGER)"
    )
    conn.execute(
        "INSERT INTO meds VALUES ('lisinopril', '10 mg', '8:00 am', 1)"
    )
    conn.commit()
    conn.close()

    db.prepare(db_path)
    migrated = medications.list_medications(db_path)
    assert len(migrated) == 1
    assert migrated[0].display_name == "Lisinopril"
    assert migrated[0].entry_source == "imported"
    assert migrated[0].identity_status == "unidentified"
    assert len(migrated[0].schedule) == 1
    assert migrated[0].schedule[0].time_of_day == "08:00"

