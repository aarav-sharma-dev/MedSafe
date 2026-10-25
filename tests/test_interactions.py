"""Automated tests for the deterministic interaction engine (interactions.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

import config
import dataset_import
import db
import interactions
import ui_theme
from interactions import CheckStatus, Ingredient, MedForCheck


@pytest.fixture()
def seeded_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "test_medsafe.sqlite3"
    problems = db.prepare(db_path)
    assert problems == []
    return db_path


def _med(
    key: str,
    name: str,
    ings: list[str],
    status: str = "confirmed",
    proposed: bool = False,
) -> MedForCheck:
    return MedForCheck(
        key=key,
        display_name=name,
        ingredients=tuple(Ingredient(i) for i in ings),
        identity_status=status,
        is_proposed=proposed,
    )


def test_seed_pair_match_and_reverse_order(seeded_db: Path) -> None:
    lis = _med("1", "Lisinopril", ["lisinopril"])
    ibu = _med("2", "Ibuprofen", ["ibuprofen"])

    rep_ab = interactions.check_medications(seeded_db, [lis, ibu])
    rep_ba = interactions.check_medications(seeded_db, [ibu, lis])

    assert len(rep_ab.results) == 1
    assert len(rep_ba.results) == 1
    assert rep_ab.results[0].status == CheckStatus.MATCH_FOUND
    assert rep_ba.results[0].status == CheckStatus.MATCH_FOUND
    assert rep_ab.results[0].top_severity == "major"
    assert rep_ba.results[0].top_severity == "major"
    assert rep_ab.results[0].records[0].source_record_id == "MS-DDI-001"
    assert rep_ab.complete is True


def test_case_insensitive_and_recognized_synonyms(seeded_db: Path) -> None:
    warfarin = _med("1", "Warfarin", ["WARFARIN"])
    # 'acetylsalicylic acid' is a documented synonym for 'aspirin' in aliases_seed.csv
    asa = _med("2", "Acetylsalicylic Acid", ["Acetylsalicylic Acid"])

    rep = interactions.check_medications(seeded_db, [warfarin, asa])
    assert len(rep.results) == 1
    assert rep.results[0].status == CheckStatus.MATCH_FOUND
    assert rep.results[0].top_severity == "major"


def test_unknown_and_unconfirmed_medication_statuses(seeded_db: Path) -> None:
    lis = _med("1", "Lisinopril", ["lisinopril"], status="confirmed")
    unconfirmed = _med("2", "Fuzzy Lisinopril", ["lisinopril"], status="needs_review")
    unknown = _med("3", "Mystery Pill", [], status="unidentified")

    rep1 = interactions.check_medications(seeded_db, [lis, unconfirmed])
    assert rep1.results[0].status == CheckStatus.IDENTITY_REQUIRES_CONFIRMATION
    assert rep1.complete is False
    assert len(rep1.unusable_medicines) == 1

    rep2 = interactions.check_medications(seeded_db, [lis, unknown])
    assert rep2.results[0].status == CheckStatus.UNABLE_TO_CHECK
    assert rep2.complete is False


def test_no_matching_record_never_claims_safety(seeded_db: Path) -> None:
    lis = _med("1", "Lisinopril", ["lisinopril"])
    met = _med("2", "Metformin", ["metformin"])

    rep = interactions.check_medications(seeded_db, [lis, met])
    assert len(rep.results) == 1
    res = rep.results[0]
    assert res.status == CheckStatus.NO_MATCHING_RECORD
    assert res.records == []

    # Verify UI badge and translated text never claim the pair is "Safe to take"
    badge = ui_theme.status_badge_html(res.status, "English")
    assert "NO RECORD IN DATASET" in badge
    assert "not proof of safety" in badge.lower()
    assert "safe to take" not in badge.lower()


def test_missing_database_returns_dataset_unavailable(tmp_path: Path) -> None:
    missing_path = tmp_path / "does_not_exist.sqlite3"
    lis = _med("1", "Lisinopril", ["lisinopril"])
    ibu = _med("2", "Ibuprofen", ["ibuprofen"])

    rep = interactions.check_medications(missing_path, [lis, ibu])
    assert rep.dataset_status.available is False
    assert rep.complete is False
    assert len(rep.results) == 1
    assert rep.results[0].status == CheckStatus.DATASET_UNAVAILABLE


def test_combination_product_expansion_and_duplicate_ingredients(seeded_db: Path) -> None:
    lis = _med("1", "Lisinopril", ["lisinopril"])
    # Advil PM contains both ibuprofen and diphenhydramine
    advil_pm = _med("2", "Advil PM", ["ibuprofen", "diphenhydramine"])
    plain_ibu = _med("3", "Ibuprofen", ["ibuprofen"])

    rep = interactions.check_medications(seeded_db, [lis, advil_pm, plain_ibu])
    # Lisinopril + Advil PM should match on (ibuprofen, lisinopril)
    pair_lis_advil = next(
        r for r in rep.results if {r.med_a.key, r.med_b.key} == {"1", "2"}
    )
    assert pair_lis_advil.status == CheckStatus.MATCH_FOUND
    assert pair_lis_advil.top_severity == "major"

    # Duplicate ingredient 'ibuprofen' should be flagged between Advil PM and Ibuprofen
    dup_ings = {d.ingredient for d in rep.duplicates}
    assert "ibuprofen" in dup_ings


def test_empty_and_proposed_otc_check(seeded_db: Path) -> None:
    empty_rep = interactions.check_medications(seeded_db, [])
    assert empty_rep.results == []

    lis = _med("1", "Lisinopril", ["lisinopril"])
    met = _med("2", "Metformin", ["metformin"])
    prop_ibu = _med("p", "Ibuprofen", ["ibuprofen"], proposed=True)

    rep = interactions.check_medications(seeded_db, [lis, met], proposed=prop_ibu)
    assert rep.mode == "proposed"
    assert len(rep.results) == 2
    statuses = {(r.med_a.display_name, r.med_b.display_name): r.status for r in rep.results}
    assert statuses[("Ibuprofen", "Lisinopril")] == CheckStatus.MATCH_FOUND
    assert statuses[("Ibuprofen", "Metformin")] == CheckStatus.NO_MATCHING_RECORD


def test_idempotent_seed_and_failed_import_rollback(seeded_db: Path, tmp_path: Path) -> None:
    before = interactions.get_dataset_status(seeded_db).total_records
    assert before == 24

    # Calling prepare a second time must not duplicate records
    db.prepare(seeded_db)
    after = interactions.get_dataset_status(seeded_db).total_records
    assert after == before

    # Malformed CSV import must fail cleanly without destroying existing records
    bad_csv = tmp_path / "malformed.csv"
    bad_csv.write_text("wrong_col_1,wrong_col_2\nfoo,bar\n", encoding="utf-8")
    rep = dataset_import.import_interactions(
        seeded_db, [bad_csv], config.STARTER_INTERACTIONS
    )
    assert rep.ok is False
    assert interactions.get_dataset_status(seeded_db).total_records == before


def test_unknown_severity_mapped_to_unspecified(seeded_db: Path, tmp_path: Path) -> None:
    dd_csv = tmp_path / "ddinter_sample.csv"
    dd_csv.write_text(
        "DDInterID_A,Drug_A,DDInterID_B,Drug_B,Level\n"
        "DDInter1,DrugAlpha,DDInter2,DrugBeta,Unknown\n"
        "DDInter3,DrugGamma,DDInter4,DrugDelta,Major\n",
        encoding="utf-8",
    )
    meta = {
        "dataset_id": "ddinter-test",
        "name": "DDInter Test",
        "version": "2.0",
        "license": "CC BY-NC-SA 4.0",
        "attribution": "DDInter 2.0",
        "is_demo": 0,
    }
    rep = dataset_import.import_interactions(seeded_db, [dd_csv], meta, fmt="ddinter")
    assert rep.ok is True
    assert rep.imported == 2
    assert rep.unspecified_severity == 1

    a = _med("a", "DrugAlpha", ["drugalpha"])
    b = _med("b", "DrugBeta", ["drugbeta"])
    check = interactions.check_medications(seeded_db, [a, b])
    assert check.results[0].status == CheckStatus.MATCH_FOUND
    rec = check.results[0].records[0]
    assert rec.severity_raw == "Unknown"
    assert rec.severity_level == "unspecified"
    assert rec.source_record_id == "DDInter1-DDInter2"

