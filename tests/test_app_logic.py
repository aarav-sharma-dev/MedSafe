"""End-to-end tests for the Congressional App Challenge demo journey,
DDInter importer CLI, and multilingual UI translations."""

from __future__ import annotations

from pathlib import Path

import ai_explain
import interactions
import medications
from interactions import CheckStatus, Ingredient, MedForCheck
from tools import convert_ddinter
from translations import SUPPORTED_LANGUAGES, check_status_label, severity_label, t


def test_congressional_app_challenge_demo_journey(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    demo_db = tmp_path / "demo_journey.sqlite3"
    problems = medications.ensure_demo_profile(demo_db, force=True)
    assert problems == []

    # Step 1-2: Inspect demonstration medication list
    meds = medications.list_medications(demo_db, active_only=True)
    names = {m.display_name for m in meds}
    assert "Lisinopril" in names
    assert "Metformin" in names
    assert "Atorvastatin (Lipitor)" in names
    assert "Golden Turmeric Root Complex" in names

    # Step 4-6: Check proposed Ibuprofen against active demo list
    proposed_ibu = MedForCheck(
        key="proposed",
        display_name="Ibuprofen",
        ingredients=(Ingredient("ibuprofen", "5640"),),
        identity_status="confirmed",
        is_proposed=True,
    )
    rep = interactions.check_medications(
        demo_db, [m.to_check_item() for m in meds], proposed=proposed_ibu
    )
    # Because Golden Turmeric Root Complex has identity_status='needs_review',
    # the overall report must honestly report complete=False!
    assert rep.complete is False
    assert any(m.display_name == "Golden Turmeric Root Complex" for m in rep.unusable_medicines)

    # Ibuprofen + Lisinopril -> MATCH_FOUND (major)
    hit = next(
        r for r in rep.results if r.med_b.display_name == "Lisinopril"
    )
    assert hit.status == CheckStatus.MATCH_FOUND
    assert hit.top_severity == "major"

    # Ibuprofen + Metformin -> NO_MATCHING_RECORD
    no_rec = next(
        r for r in rep.results if r.med_b.display_name == "Metformin"
    )
    assert no_rec.status == CheckStatus.NO_MATCHING_RECORD

    # Ibuprofen + Golden Turmeric Root Complex -> IDENTITY_REQUIRES_CONFIRMATION
    unconf = next(
        r for r in rep.results if r.med_b.display_name == "Golden Turmeric Root Complex"
    )
    assert unconf.status == CheckStatus.IDENTITY_REQUIRES_CONFIRMATION

    # Step 7-8: Plain-language explanation in English and Hindi while preserving source result
    exp_en = ai_explain.explain_structured(hit, "English")
    exp_hi = ai_explain.explain_structured(hit, "Hindi")
    assert exp_en.source == "template"
    assert exp_hi.source == "template"
    assert "Lisinopril" in exp_hi.explanation
    assert exp_hi.original_english == exp_en.original_english
    assert hit.status == CheckStatus.MATCH_FOUND
    assert hit.top_severity == "major"


def test_translations_complete_across_languages() -> None:
    en_keys = set(
        __import__("translations").TRANSLATIONS["English"].keys()
    )
    for lang in SUPPORTED_LANGUAGES:
        lang_keys = set(__import__("translations").TRANSLATIONS[lang].keys())
        assert en_keys == lang_keys, f"Missing keys in {lang}: {en_keys - lang_keys}"
        for status in CheckStatus:
            lbl = check_status_label(status.value, lang)
            assert lbl and not lbl.startswith("status_")
        for sev in ("major", "moderate", "minor", "unspecified"):
            s_lbl = severity_label(sev, lang)
            assert s_lbl and not s_lbl.startswith("severity_")
        assert t("no_record_explanation", lang)


def test_ddinter_converter_end_to_end(tmp_path: Path) -> None:
    target_db = tmp_path / "ddinter_target.sqlite3"
    dd_folder = tmp_path / "ddinter_files"
    dd_folder.mkdir()
    (dd_folder / "ddinter_downloads_code_A.csv").write_text(
        "DDInterID_A,Drug_A,DDInterID_B,Drug_B,Level\n"
        "DDInter10,Warfarin,DDInter20,Aspirin,Major\n"
        "DDInter10,Warfarin,DDInter30,SomeNewDrug,Unknown\n",
        encoding="utf-8",
    )
    rep = convert_ddinter.import_ddinter_folder(dd_folder, db_paths=[target_db], version="2.0-test")
    assert rep.ok is True
    assert rep.imported == 2
    assert rep.unspecified_severity == 1


def test_streamlit_ui_all_sections_render_cleanly(tmp_path: Path, monkeypatch) -> None:
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("MEDSAFE_DATA_DIR", str(tmp_path))

    app_path = Path(__file__).resolve().parent.parent / "app.py"
    at = AppTest.from_file(str(app_path))
    at.session_state["profile_mode"] = "demo"
    for section in ("overview", "medicines", "scanner", "safety", "schedule", "more", "reports", "settings", "help"):
        at.session_state["nav_section"] = section
        at.run(timeout=45)
        assert len(at.exception) == 0, f"Exception in section {section}: {[e.value for e in at.exception]}"


def test_ui_buttons_and_themes_work(tmp_path: Path, monkeypatch) -> None:
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("MEDSAFE_DATA_DIR", str(tmp_path))
    app_path = Path(__file__).resolve().parent.parent / "app.py"
    at = AppTest.from_file(str(app_path))
    at.session_state["skip_setup"] = True  # bypass first-launch wizard
    at.run(timeout=45)
    assert len(at.exception) == 0

    # 1. Click primary Quick Action "Add a medicine" button on Overview and verify navigation persists
    at.button(key="qa_add_med").click().run(timeout=45)
    assert len(at.exception) == 0
    assert at.session_state["active_section"] == "medicines"
    assert at.session_state["sidebar_nav_radio"] == "medicines"

    # 2. Click top navigation bar button for Safety Checker and verify navigation persists
    at.button(key="topnav_checker").click().run(timeout=45)
    assert len(at.exception) == 0
    assert at.session_state["active_section"] == "checker"

    # 3. Click a Demo Quick-Pick button in Safety Checker and verify text input updates
    at.button(key="dq_btn_Advil PM").click().run(timeout=45)
    assert len(at.exception) == 0
    assert at.session_state["checker_prop_input"] == "Advil PM"

    # 4. Verify all 3 appearance themes (Light, Dark, High-Contrast) render cleanly
    for mode in ("light", "dark", "high_contrast"):
        at.session_state["theme_mode"] = mode
        at.run(timeout=45)
        assert len(at.exception) == 0


def test_first_launch_setup_wizard(tmp_path: Path, monkeypatch) -> None:
    """Fresh install shows the two-question wizard; completing it saves the
    choices to the settings database and unblocks the main app."""
    from streamlit.testing.v1 import AppTest

    import config
    import db

    monkeypatch.setenv("MEDSAFE_DATA_DIR", str(tmp_path))
    app_path = Path(__file__).resolve().parent.parent / "app.py"

    at = AppTest.from_file(str(app_path))
    at.run(timeout=45)
    assert len(at.exception) == 0
    # Wizard is showing: its start button exists, main nav does not
    assert any(b.key == "setup_start" for b in at.button)
    assert not any(b.key == "topnav_checker" for b in at.button)

    # Pick Large text and Spanish, then start
    at.selectbox(key="setup_lang_select").select("Spanish").run(timeout=45)
    at.radio(key="setup_size_radio").set_value("large").run(timeout=45)
    at.button(key="setup_start").click().run(timeout=45)
    assert len(at.exception) == 0

    personal = config.personal_db_path()
    assert db.get_setting(personal, "setup_complete") == "1"
    assert db.get_setting(personal, "language") == "Spanish"
    assert db.get_setting(personal, "font_size") == "large"
    # Main app is now rendered (wizard gone, nav present)
    assert any(b.key == "topnav_checker" for b in at.button)
    assert not any(b.key == "setup_start" for b in at.button)
