"""MedSafe — Medication Safety and Daily Routine Companion for Senior Adults.

Run with:
    streamlit run app.py

Core safety architecture:
* Deterministic database authority: `interactions.py` (SQLite) is the sole
  authority for whether an interaction record exists in the loaded dataset.
* Non-equivalence of missing records: `NO_MATCHING_RECORD` is never displayed
  as "Safe".
* Conservative identity verification: fuzzy matches, brand names, combination
  products, and OCR scans require explicit user confirmation.
* Grounded AI explanations: `ai_explain.py` only rewrites confirmed database
  records into plain language (or translates them) with strict output
  validation and deterministic template fallbacks.
"""

from __future__ import annotations

import datetime as dt
import html
from io import BytesIO
from pathlib import Path

import streamlit as st

import ai_explain
import alerts
import config
import dataset_import
import db
import drug_data
import interactions
import medications
import ocr_service
import ui_theme
from interactions import CheckStatus, Ingredient, MedForCheck
from translations import (
    SUPPORTED_LANGUAGES,
    TTS_LANG_CODES,
    category_label,
    check_status_label,
    identity_status_label,
    normalize_language,
    severity_label,
    t,
)

# Optional text-to-speech (degrades gracefully when offline or uninstalled)
try:
    from gtts import gTTS

    TTS_AVAILABLE = True
except ImportError:
    TTS_AVAILABLE = False


def synthesize_speech(text: str, language: str) -> bytes | None:
    """Return MP3 bytes for read-aloud, or None if gTTS is unavailable/offline."""
    if not TTS_AVAILABLE or not (text or "").strip():
        return None
    try:
        buf = BytesIO()
        lang_code = TTS_LANG_CODES.get(normalize_language(language), "en")
        gTTS(text=text[:900], lang=lang_code).write_to_fp(buf)
        return buf.getvalue()
    except Exception:
        return None


# --- Startup & Session State Initialization --------------------------------

config.load_dotenv()

st.set_page_config(
    page_title="MedSafe — Medication Safety Companion",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_resource
def bootstrap_environment(personal_db_str: str, demo_db_str: str) -> dict[str, list[str]]:
    """Ensure assets and both personal & demo SQLite databases are ready."""
    ocr_service.ensure_logo_svg()
    ocr_service.ensure_sample_labels()
    personal_problems = db.prepare(Path(personal_db_str))
    demo_problems = medications.ensure_demo_profile(Path(demo_db_str))
    return {"personal": personal_problems, "demo": demo_problems}


STARTUP_PROBLEMS = bootstrap_environment(
    str(config.personal_db_path()),
    str(config.demo_db_path()),
)

SECTION_KEYS = (
    "overview",
    "medicines",
    "scan",
    "checker",
    "schedule",
    "reports",
    "settings",
)

# Alias map so tests or external callers using "scanner" or "safety" resolve cleanly
_SECTION_ALIASES = {
    "overview": "overview",
    "medicines": "medicines",
    "scan": "scan",
    "scanner": "scan",
    "checker": "checker",
    "safety": "checker",
    "schedule": "schedule",
    "reports": "reports",
    "settings": "settings",
}


def _normalize_section(sec: str | None) -> str:
    if not sec:
        return "overview"
    return _SECTION_ALIASES.get(sec.strip().lower(), "overview")


def _init_session_state() -> None:
    personal_path = config.personal_db_path()
    # Support test harness `profile_mode = "demo"` if passed via AppTest
    if st.session_state.get("profile_mode") == "demo":
        st.session_state.demo_mode = True

    if "demo_mode" not in st.session_state:
        saved_demo = db.get_setting(personal_path, "demo_mode")
        if saved_demo is not None:
            st.session_state.demo_mode = saved_demo == "1"
        else:
            has_personal = len(medications.list_medications(personal_path)) > 0
            st.session_state.demo_mode = not has_personal

    if "language" not in st.session_state:
        st.session_state.language = normalize_language(
            db.get_setting(personal_path, "language", "English")
        )
    if "font_size" not in st.session_state:
        st.session_state.font_size = (
            db.get_setting(personal_path, "font_size", "standard") or "standard"
        )
    if "theme_mode" not in st.session_state:
        saved_theme = db.get_setting(personal_path, "theme_mode")
        if saved_theme in ui_theme.THEME_MODES:
            st.session_state.theme_mode = saved_theme
        else:
            hc_legacy = db.get_setting(personal_path, "high_contrast", "0") == "1"
            st.session_state.theme_mode = "high_contrast" if hc_legacy else "light"
    st.session_state.high_contrast = st.session_state.theme_mode == "high_contrast"

    # Support `nav_section` if set by tests or external callers
    if "nav_section" in st.session_state:
        mapped = _normalize_section(str(st.session_state.nav_section))
        if st.session_state.get("_last_nav_section") != st.session_state.nav_section:
            st.session_state.active_section = mapped
            st.session_state._last_nav_section = st.session_state.nav_section

    if "active_section" not in st.session_state:
        st.session_state.active_section = "overview"
    else:
        st.session_state.active_section = _normalize_section(st.session_state.active_section)

    if "show_onboarding" not in st.session_state:
        st.session_state.show_onboarding = True


_init_session_state()


def active_db_path() -> Path:
    return config.demo_db_path() if st.session_state.demo_mode else config.personal_db_path()


def set_flash(message: str, level: str = "success") -> None:
    """Persist a status banner across `st.rerun()` so button feedback is always visible."""
    st.session_state.flash_banner = {"message": message, "level": level}


def render_flash() -> None:
    banner = st.session_state.pop("flash_banner", None)
    if not banner:
        return
    lvl = banner.get("level", "success")
    msg = banner.get("message", "")
    if lvl == "error":
        st.error(msg)
    elif lvl == "warning":
        st.warning(msg)
    elif lvl == "info":
        st.info(msg)
    else:
        st.success(msg)


def navigate_to(section_key: str) -> None:
    """Switch active section; render_sidebar syncs sidebar_nav_radio before creating the widget."""
    norm_sec = _normalize_section(section_key)
    st.session_state.active_section = norm_sec
    st.session_state.nav_section = norm_sec
    st.session_state._last_nav_section = norm_sec


def _populate_add_med_form_state(
    cand: drug_data.DrugCandidate | None,
    norm: drug_data.NormalizationResult | None,
    raw_query: str = "",
) -> None:
    """Synchronize the Add Medicine form input states whenever a lookup or
    candidate selection occurs so form text boxes update immediately."""
    st.session_state["f_disp_in"] = (
        cand.display_name if cand else (raw_query.strip().title() if raw_query else "")
    )
    st.session_state["f_gen_in"] = (
        cand.generic_name if cand else (norm.parsed_name if norm else "")
    )
    st.session_state["f_brand_in"] = (cand.brand_name or "") if cand else ""
    st.session_state["f_ings_in"] = (
        " + ".join(i.name for i in cand.ingredients) if cand else ""
    )
    st.session_state["f_rxcui_in"] = (cand.rxcui or "") if cand else ""
    st.session_state["f_str_in"] = (
        (cand.strength if cand else None)
        or (norm.extracted_strength if norm else None)
        or ""
    )
    st.session_state["f_form_in"] = (
        (cand.dose_form if cand else None)
        or (norm.extracted_form if norm else None)
        or "Oral Tablet"
    )
    st.session_state["f_cat_in"] = (
        cand.category
        if (cand and cand.category in medications.VALID_CATEGORIES)
        else "prescription"
    )
    st.session_state["f_confirm_in"] = bool(cand and norm and norm.exact_match)


# --- Sidebar Navigation & Quick Accessibility Controls ---------------------

def _on_sidebar_radio_change() -> None:
    chosen = st.session_state.get("sidebar_nav_radio", "overview")
    navigate_to(chosen)


def render_sidebar() -> None:
    lang = st.session_state.language
    personal_path = config.personal_db_path()

    # Keep sidebar radio synced with any button-driven navigation
    st.session_state.sidebar_nav_radio = st.session_state.active_section

    with st.sidebar:
        st.markdown("### 🛡️ MedSafe")
        st.caption(t("app_tagline", lang))

        nav_labels = {
            "overview": f"🏠  {t('nav_overview', lang)}",
            "medicines": f"💊  {t('nav_medicines', lang)}",
            "scan": f"📷  {t('nav_scan', lang)}",
            "checker": f"🔍  {t('nav_checker', lang)}",
            "schedule": f"⏰  {t('nav_schedule', lang)}",
            "reports": f"📋  {t('nav_reports', lang)}",
            "settings": f"⚙️  {t('nav_settings', lang)}",
        }
        st.radio(
            t("nav_title", lang),
            options=list(SECTION_KEYS),
            format_func=lambda k: nav_labels[k],
            key="sidebar_nav_radio",
            on_change=_on_sidebar_radio_change,
        )

        st.divider()
        st.markdown("#### 🎨 Appearance (Light / Dark)")
        theme_keys = list(ui_theme.THEME_MODES.keys())
        cur_theme = (
            st.session_state.theme_mode
            if st.session_state.theme_mode in theme_keys
            else "light"
        )
        new_theme = st.selectbox(
            "Appearance mode",
            options=theme_keys,
            index=theme_keys.index(cur_theme),
            format_func=lambda k: ui_theme.THEME_MODES[k],
            help=ui_theme.THEME_DESCRIPTIONS[cur_theme],
        )
        if new_theme != cur_theme:
            st.session_state.theme_mode = new_theme
            st.session_state.high_contrast = new_theme == "high_contrast"
            db.set_setting(personal_path, "theme_mode", new_theme)
            db.set_setting(personal_path, "high_contrast", "1" if new_theme == "high_contrast" else "0")
            st.rerun()
        st.caption(ui_theme.THEME_DESCRIPTIONS[cur_theme])

        st.markdown("#### 🔤 Text Size")
        size_labels = {
            "standard": "Standard (18 px)",
            "large": "Large (20 px)",
            "xlarge": "Extra Large (22 px)",
        }
        size_keys = list(size_labels.keys())
        new_size = st.selectbox(
            "Text size",
            options=size_keys,
            index=size_keys.index(st.session_state.font_size)
            if st.session_state.font_size in size_keys
            else 0,
            format_func=lambda k: size_labels[k],
        )
        if new_size != st.session_state.font_size:
            st.session_state.font_size = new_size
            db.set_setting(personal_path, "font_size", new_size)
            st.rerun()

        st.markdown("#### 🌐 Language")
        lang_options = list(SUPPORTED_LANGUAGES.keys())
        new_lang = st.selectbox(
            "Display language",
            options=lang_options,
            index=lang_options.index(lang) if lang in lang_options else 0,
            format_func=lambda k: SUPPORTED_LANGUAGES[k],
        )
        if new_lang != lang:
            st.session_state.language = new_lang
            db.set_setting(personal_path, "language", new_lang)
            st.rerun()

        st.divider()
        st.markdown("#### 🧪 Demonstration Mode")
        new_demo = st.checkbox(
            "Use Demo Sample Data",
            value=st.session_state.demo_mode,
            help=(
                "Loads a deterministic set of fictional sample medications "
                "(Lisinopril, Metformin, Atorvastatin, and an unconfirmed herbal "
                "supplement) in an isolated database file."
            ),
        )
        if new_demo != st.session_state.demo_mode:
            st.session_state.demo_mode = new_demo
            db.set_setting(personal_path, "demo_mode", "1" if new_demo else "0")
            st.rerun()


def render_top_navigation_bar(lang: str) -> None:
    """Render large, senior-accessible top navigation buttons so users can
    switch sections with one tap without relying only on the sidebar."""
    nav_items = [
        ("overview", f"🏠 {t('nav_overview', lang)}"),
        ("medicines", f"💊 {t('nav_medicines', lang)}"),
        ("scan", f"📷 {t('nav_scan', lang)}"),
        ("checker", f"🔍 {t('nav_checker', lang)}"),
        ("schedule", f"⏰ {t('nav_schedule', lang)}"),
        ("reports", f"📋 {t('nav_reports', lang)}"),
        ("settings", f"⚙️ {t('nav_settings', lang)}"),
    ]
    cols = st.columns(len(nav_items))
    active = st.session_state.active_section
    for col, (sec_key, label) in zip(cols, nav_items):
        is_current = active == sec_key
        if col.button(
            label,
            key=f"topnav_{sec_key}",
            type="primary" if is_current else "secondary",
            use_container_width=True,
        ):
            if not is_current:
                navigate_to(sec_key)
                st.rerun()


# --- Section 1: Overview Dashboard -----------------------------------------

def render_overview(db_path: Path, lang: str, is_demo: bool) -> None:
    st.header(t("overview_heading", lang))
    st.write(t("overview_subtitle", lang))

    # Onboarding & Demo Walkthrough
    with st.expander(f"ℹ️ {t('onboarding_title', lang)}", expanded=st.session_state.show_onboarding):
        for step_key in (
            "onboarding_step_1",
            "onboarding_step_2",
            "onboarding_step_3",
            "onboarding_step_4",
            "onboarding_step_5",
        ):
            st.markdown(f"- {t(step_key, lang)}")
        if is_demo:
            st.info(
                "**Congressional App Challenge Quick Demo Walkthrough:**\n"
                "1. Inspect the 4 sample entries in **My Medicines** (3 confirmed prescriptions + 1 unconfirmed herbal supplement).\n"
                "2. Open **Scan a Bottle** and test local OCR on a **DEMO SAMPLE LABEL** with automatic PII redaction.\n"
                "3. Open **Safety Checker**, pick **Ibuprofen 200 mg (Advil)** as a proposed OTC pain reliever, confirm its identity, and run the deterministic lookup against **Lisinopril + Metformin**.\n"
                "4. Switch the language selector in the sidebar to **Español**, **हिन्दी**, **中文**, **Tagalog**, **Tiếng Việt**, or **Français** to see the localized plain-language explanation alongside the original English source record.\n"
                "5. Open **Daily Schedule** and **Caregiver & Reports** to review the timeline and downloadable pharmacist summary."
            )

    all_meds = medications.list_medications(db_path)
    active_meds = [m for m in all_meds if m.active]
    unconfirmed_meds = [m for m in active_meds if m.identity_status != "confirmed"]
    check_report = interactions.check_medications(
        db_path, [m.to_check_item() for m in active_meds]
    )
    unresolved_pairs = [
        r for r in check_report.results if r.status in interactions.INCOMPLETE_STATUSES
    ]
    matches_found = check_report.by_status(CheckStatus.MATCH_FOUND)
    today_sched = medications.get_daily_schedule(db_path)
    taken_today = sum(1 for s in today_sched if s.status == "taken")

    # Summary Stat Cards (never a safety score or percentage!)
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        ui_theme.render_stat_card(
            len(active_meds),
            t("stat_active_meds", lang),
            f"{len(all_meds) - len(active_meds)} inactive" if len(all_meds) > len(active_meds) else "In current list",
        )
    with c2:
        ui_theme.render_stat_card(
            len(unconfirmed_meds),
            t("stat_needs_confirmation", lang),
            "Require review before checking" if unconfirmed_meds else "All active meds confirmed",
        )
    with c3:
        ui_theme.render_stat_card(
            len(unresolved_pairs) + len(matches_found),
            t("stat_unresolved_checks", lang),
            f"{len(matches_found)} record match(es), {len(unresolved_pairs)} unchecked pair(s)",
        )
    with c4:
        sched_val = f"{taken_today} / {len(today_sched)}" if today_sched else "0"
        ui_theme.render_stat_card(
            sched_val,
            t("stat_today_schedule", lang),
            "Marked taken today" if today_sched else "No reminder times set",
        )
    with c5:
        ds = check_report.dataset_status
        ui_theme.render_stat_card(
            ds.total_records if ds.available else "Unavailable",
            t("stat_dataset_records", lang),
            "Starter dataset (incomplete coverage)" if ds.only_demo_data else ds.label[:38],
        )

    st.markdown(f"### {t('quick_actions_title', lang)}")
    qa1, qa2, qa3, qa4, qa5 = st.columns(5)
    if qa1.button(f"➕ {t('btn_add_medicine', lang)}", key="qa_add_med", type="primary", use_container_width=True):
        st.session_state.expand_add_med = True
        navigate_to("medicines")
        st.rerun()
    if qa2.button(f"📷 {t('btn_scan_bottle', lang)}", key="qa_scan", use_container_width=True):
        navigate_to("scan")
        st.rerun()
    if qa3.button(f"🔍 {t('btn_check_interaction', lang)}", key="qa_check", use_container_width=True):
        navigate_to("checker")
        st.rerun()
    if qa4.button(f"⏰ {t('btn_review_schedule', lang)}", key="qa_sched", use_container_width=True):
        navigate_to("schedule")
        st.rerun()
    if qa5.button(f"📋 {t('btn_prepare_summary', lang)}", key="qa_rep", use_container_width=True):
        navigate_to("reports")
        st.rerun()

    if not all_meds:
        st.markdown("---")
        with st.container(border=True):
            st.subheader(t("empty_meds_title", lang))
            st.write(t("empty_meds_body", lang))
            ec1, ec2 = st.columns(2)
            if ec1.button(f"➕ {t('btn_add_first_med', lang)}", key="empty_add_btn", type="primary"):
                st.session_state.expand_add_med = True
                navigate_to("medicines")
                st.rerun()
            if ec2.button("🧪 Switch to Demo Sample Journey", key="empty_demo_btn"):
                st.session_state.demo_mode = True
                db.set_setting(config.personal_db_path(), "demo_mode", "1")
                set_flash("Switched to Demonstration Mode with 4 sample medications.")
                st.rerun()
        return

    st.markdown("---")
    st.subheader(t("recent_activity_title", lang))
    col_left, col_right = st.columns(2)

    with col_left:
        if unconfirmed_meds:
            with st.container(border=True):
                st.markdown("#### [▲] Medicines awaiting identity confirmation")
                st.write(
                    "Interaction checks involving these medicines cannot be completed "
                    "until you confirm their active ingredients:"
                )
                for m in unconfirmed_meds:
                    st.markdown(
                        f"- **{html.escape(m.display_name)}** ({html.escape(m.strength or 'strength not set')}) "
                        f"— *{html.escape(identity_status_label(m.identity_status, lang))}*"
                    )
                if st.button("Review & confirm in My Medicines", key="ov_confirm_btn", type="primary"):
                    navigate_to("medicines")
                    st.rerun()

        with st.container(border=True):
            st.markdown("#### 💊 Current active medicines")
            for m in active_meds[:6]:
                ings = " + ".join(i.name for i in m.ingredients) or "Unidentified"
                st.markdown(
                    f"- **{html.escape(m.display_name)}** ({html.escape(m.strength or '—')}) · "
                    f"Ingredient(s): `{html.escape(ings)}` · "
                    f"*{html.escape(identity_status_label(m.identity_status, lang))}*"
                )
            if st.button("Manage all medicines →", key="ov_manage_meds_btn"):
                navigate_to("medicines")
                st.rerun()

    with col_right:
        with st.container(border=True):
            st.markdown("#### 🗄️ Interaction database status & limitations")
            ds = check_report.dataset_status
            if not ds.available:
                st.error(f"Dataset unavailable: {ds.problem}")
            else:
                for d in ds.datasets:
                    badge = "[STARTER DEMO DATASET]" if d.is_demo else "[IMPORTED DATASET]"
                    st.markdown(
                        f"**{badge} {html.escape(d.name)}** (Version: `{html.escape(d.version or 'n/a')}`, "
                        f"Records: **{d.record_count}**, Imported: `{html.escape(d.imported_at[:10])}`)"
                    )
                    if d.notes:
                        st.caption(d.notes)
                st.warning(
                    "Coverage limitation: Having no matching interaction record in the loaded "
                    "dataset never proves that two medicines are safe to take together. Always "
                    "confirm with a pharmacist or prescriber."
                )

        history = interactions.list_history(db_path, limit=4)
        with st.container(border=True):
            st.markdown("#### 🕒 Recent interaction checks")
            if not history:
                st.caption("No interaction checks recorded in this profile yet.")
            else:
                for h in history:
                    summary = h.get("summary") or {}
                    pairs = summary.get("pairs") or []
                    hits = sum(1 for p in pairs if p.get("status") == "MATCH_FOUND")
                    comp = "Complete lookup" if h["complete"] else "Incomplete lookup"
                    st.markdown(
                        f"- `{h['checked_at']}` ({h['mode']}, {comp}): "
                        f"**{hits}** record match(es) across {len(pairs)} pair(s) · "
                        f"*Dataset: {h.get('dataset_label') or 'n/a'}*"
                    )


# --- Section 2: My Medicines (Complete Medication Manager) -----------------

def render_my_medicines(db_path: Path, lang: str) -> None:
    st.header(t("meds_heading", lang))
    st.write(t("meds_subtitle", lang))
    st.info(t("coverage_note_categories", lang))

    all_meds = medications.list_medications(db_path)
    dup_warnings = medications.find_duplicate_medications(all_meds)
    if dup_warnings:
        with st.container(border=True):
            st.warning(f"**[▲] {t('duplicate_warning_title', lang)}**\n\n{t('duplicate_warning_body', lang)}")
            for w in dup_warnings:
                kind_str = "Shared active ingredient" if w["kind"] == "shared_ingredient" else "Similar medication name"
                st.markdown(
                    f"- **{kind_str} (`{w['subject']}`):** {', '.join(w['medicines'])}"
                )

    # --- Add a Medicine Workflow (with Conservative Candidate Verification) ---
    if st.session_state.pop("_reset_add_form", False):
        _populate_add_med_form_state(None, None, "")
        st.session_state["med_add_query_input"] = ""

    expand_add = st.session_state.get("expand_add_med", not bool(all_meds)) or bool(
        st.session_state.get("add_med_norm")
    )
    with st.expander("➕ Add a medicine (with ingredient verification)", expanded=expand_add):
        st.markdown(
            "**Step 1:** Type a medicine name below (or click one of the quick-fill examples) and click "
            "**🔎 Look up identity** to pre-fill verified ingredients, strength, and RxNorm ID."
        )
        st.caption("Quick-fill examples (click any button to test):")
        qf1, qf2, qf3, qf4 = st.columns(4)
        quick_examples = [
            (qf1, "💊 Warfarin 5 mg", "Warfarin 5 mg"),
            (qf2, "💊 Ibuprofen 200 mg (Advil)", "Ibuprofen 200 mg"),
            (qf3, "💊 Norco 5/325 mg (Combo)", "Norco"),
            (qf4, "💊 Omeprazole 20 mg", "Omeprazole 20 mg"),
        ]
        for qcol, qlabel, qval in quick_examples:
            if qcol.button(qlabel, key=f"qf_add_{qval}", use_container_width=True):
                st.session_state["med_add_query_input"] = qval
                res_norm = drug_data.resolve_drug_candidates(qval)
                st.session_state["add_med_norm"] = res_norm
                st.session_state["add_med_cand_radio"] = 0 if res_norm.candidates else -1
                top_c = res_norm.candidates[0] if res_norm.candidates else None
                _populate_add_med_form_state(top_c, res_norm, qval)
                st.session_state.expand_add_med = True
                st.rerun()

        col_q, col_btn = st.columns([3, 1])
        lookup_input = col_q.text_input(
            "Medicine name to look up",
            placeholder="e.g. Lisinopril 10 mg, Advil PM, Synthroid, or Warfarin 5 mg",
            key="med_add_query_input",
        )
        if col_btn.button("🔎 Look up identity", key="btn_lookup_add_med", type="primary", use_container_width=True):
            if not lookup_input.strip():
                st.error("Please type a medicine name in the box first (for example: 'Lisinopril 10 mg').")
            else:
                with st.spinner("Searching RxNorm & local reference catalog..."):
                    res_norm = drug_data.resolve_drug_candidates(lookup_input.strip())
                    st.session_state.add_med_norm = res_norm
                    default_radio = 0 if res_norm.auto_select_candidate else -1
                    st.session_state["add_med_cand_radio"] = default_radio
                    top_c = res_norm.candidates[0] if (default_radio == 0 and res_norm.candidates) else None
                    _populate_add_med_form_state(top_c, res_norm, lookup_input.strip())
                    st.session_state.expand_add_med = True
                    st.rerun()

        norm: drug_data.NormalizationResult | None = st.session_state.get("add_med_norm")
        selected_cand: drug_data.DrugCandidate | None = None
        if norm and norm.query:
            if norm.error_message:
                st.warning(norm.error_message)
            for reason in norm.uncertainty_reasons:
                st.info(f"ℹ️ {reason}")

            if norm.candidates:
                cand_options = list(range(len(norm.candidates))) + [-1]

                def _on_add_cand_change() -> None:
                    c_idx = st.session_state.get("add_med_cand_radio", -1)
                    c_obj = norm.candidates[c_idx] if (0 <= c_idx < len(norm.candidates)) else None
                    _populate_add_med_form_state(c_obj, norm, norm.query)

                chosen_idx = st.radio(
                    "Select the matching medication identity (or choose 'None of these / Enter manually'):",
                    options=cand_options,
                    format_func=lambda idx: (
                        norm.candidates[idx].summary_label
                        if idx >= 0
                        else "None of these — I will enter or select the medication manually below"
                    ),
                    key="add_med_cand_radio",
                    on_change=_on_add_cand_change,
                )
                if chosen_idx >= 0 and chosen_idx < len(norm.candidates):
                    selected_cand = norm.candidates[chosen_idx]
                    if selected_cand.is_combination:
                        st.warning(
                            "**Combination product:** This medicine contains multiple active "
                            f"ingredients (`{' + '.join(i.name for i in selected_cand.ingredients)}`). "
                            "MedSafe will check each active ingredient separately."
                        )
                    if selected_cand.lasa_warning:
                        ui_theme.render_lasa_warning_card(selected_cand.lasa_warning)
                elif norm.lasa_warnings:
                    for lw in norm.lasa_warnings:
                        ui_theme.render_lasa_warning_card(lw)
            else:
                st.warning(
                    f"No standardized match was found for **{norm.query}**. You can still save "
                    "it to your list; it will be marked as needing identity confirmation so "
                    "MedSafe never pretends an interaction check involving it is complete."
                )

        # Initialize form input keys if not set yet
        for k_init, v_init in (
            ("f_disp_in", ""),
            ("f_gen_in", ""),
            ("f_brand_in", ""),
            ("f_ings_in", ""),
            ("f_str_in", ""),
            ("f_form_in", "Oral Tablet"),
            ("f_cat_in", "prescription"),
            ("f_route_in", "Oral"),
            ("f_rxcui_in", ""),
            ("f_instr_in", ""),
            ("f_sched_in", ""),
            ("f_presc_in", ""),
            ("f_pharm_in", ""),
            ("f_notes_in", ""),
            ("f_confirm_in", False),
        ):
            if k_init not in st.session_state:
                st.session_state[k_init] = v_init

        st.markdown("**Step 2:** Review or fill in the medication details below and click **Save medicine to my list**.")
        with st.form("add_medication_form", clear_on_submit=False):
            fc1, fc2, fc3 = st.columns(3)
            f_display = fc1.text_input(
                "Display name *",
                placeholder="e.g. Lisinopril, Advil, or Warfarin",
                key="f_disp_in",
            )
            f_generic = fc2.text_input(
                "Generic name",
                placeholder="e.g. lisinopril",
                key="f_gen_in",
            )
            f_brand = fc3.text_input(
                "Brand name (optional)",
                placeholder="e.g. Prinivil, Zestril",
                key="f_brand_in",
            )

            fc4, fc5, fc6 = st.columns(3)
            f_ings = fc4.text_input(
                "Active ingredient(s) (separate multiple with '+')",
                placeholder="e.g. lisinopril (or hydrocodone + acetaminophen)",
                help="Required to confirm identity for interaction checking.",
                key="f_ings_in",
            )
            f_strength = fc5.text_input(
                "Strength",
                placeholder="e.g. 10 mg, 500 mg, 20 mEq",
                key="f_str_in",
            )
            f_form = fc6.text_input(
                "Dosage form",
                placeholder="e.g. Oral Tablet, Capsule",
                key="f_form_in",
            )

            fc7, fc8, fc9 = st.columns(3)
            cat_options = list(medications.VALID_CATEGORIES)
            f_cat = fc7.selectbox(
                "Category",
                options=cat_options,
                format_func=lambda c: category_label(c, lang),
                key="f_cat_in",
            )
            f_route = fc8.text_input(
                "Route",
                placeholder="e.g. Oral, Topical, Inhaled",
                key="f_route_in",
            )
            f_rxcui = fc9.text_input(
                "Standardized RxNorm ID (RxCUI, optional)",
                placeholder="e.g. 29046",
                key="f_rxcui_in",
            )

            f_instructions = st.text_input(
                "Prescribed / label directions (never modified by MedSafe)",
                placeholder="e.g. Take 1 tablet by mouth every morning with food",
                key="f_instr_in",
            )
            sc1, sc2, sc3 = st.columns(3)
            f_sched = sc1.text_input(
                "Daily reminder time(s) (optional, comma-separated)",
                placeholder="e.g. 8:00 AM, 6:00 PM",
                key="f_sched_in",
            )
            f_prescriber = sc2.text_input(
                "Prescriber (optional)",
                placeholder="e.g. Dr. Patel",
                key="f_presc_in",
            )
            f_pharmacy = sc3.text_input(
                "Pharmacy (optional)",
                placeholder="e.g. Community Pharmacy",
                key="f_pharm_in",
            )
            f_notes = st.text_area(
                "Notes (optional)",
                placeholder="e.g. Taking for blood pressure; started in May.",
                height=68,
                key="f_notes_in",
            )

            confirm_check = st.checkbox(
                "I have reviewed the active ingredient(s), strength, and dosage form above "
                "and confirm they match my medication.",
                key="f_confirm_in",
            )
            submitted = st.form_submit_button("✓ Save medicine to my list", type="primary", use_container_width=True)
            if submitted:
                effective_display = f_display.strip() or lookup_input.strip()
                if not effective_display:
                    st.error("Please enter a Display name for the medicine (e.g., 'Lisinopril').")
                else:
                    ing_parts = [p.strip() for p in f_ings.split("+") if p.strip()]
                    auto_cand = selected_cand
                    auto_norm = norm
                    # If the user typed a medicine name directly without clicking "Look up identity",
                    # try resolving it conservatively so known generics/brands populate cleanly.
                    if not ing_parts:
                        auto_norm = drug_data.resolve_drug_candidates(effective_display, use_network=False)
                        if auto_norm.candidates:
                            auto_cand = auto_norm.candidates[0]
                            ing_parts = [i.name for i in auto_cand.ingredients]

                    if confirm_check and ing_parts:
                        id_status = "confirmed"
                    elif auto_norm and auto_norm.exact_match and ing_parts:
                        id_status = "confirmed"
                    elif ing_parts:
                        id_status = "needs_review"
                    else:
                        id_status = "unidentified"

                    sched_list = [s.strip() for s in f_sched.split(",") if s.strip()]
                    medications.add_medication(
                        db_path,
                        effective_display,
                        generic_name=(f_generic.strip() or (auto_cand.generic_name if auto_cand else None)),
                        brand_name=(f_brand.strip() or (auto_cand.brand_name if auto_cand else None)),
                        rxcui=(f_rxcui.strip() or (auto_cand.rxcui if auto_cand else None)),
                        rxnorm_name=auto_cand.display_name if auto_cand else None,
                        rxnorm_tty=auto_cand.tty if auto_cand else None,
                        strength=(f_strength.strip() or (auto_norm.extracted_strength if auto_norm else None)),
                        dose_form=f_form.strip() or None,
                        route=f_route.strip() or None,
                        instructions=f_instructions.strip() or None,
                        category=f_cat,
                        prescriber=f_prescriber.strip() or None,
                        pharmacy=f_pharmacy.strip() or None,
                        notes=f_notes.strip() or None,
                        active=True,
                        entry_source="manual",
                        identity_status=id_status,
                        identity_source=auto_cand.source if auto_cand else "user_manual",
                        ingredients=ing_parts,
                        schedule_times=sched_list,
                    )
                    st.session_state.pop("add_med_norm", None)
                    st.session_state.expand_add_med = False
                    st.session_state._reset_add_form = True
                    set_flash(
                        f"✓ Saved **{effective_display}** ({identity_status_label(id_status, lang)}) to your medication list."
                    )
                    st.rerun()

    # --- Search & Filter Bar ---
    st.markdown("---")
    sf1, sf2, sf3, sf4 = st.columns([2.2, 1.3, 1.3, 1.2])
    search_q = sf1.text_input(
        "Search by name, brand, or active ingredient",
        placeholder="Type to filter (e.g. lisinopril, statin, herbal)...",
        key="med_filter_search",
    )
    cat_filter = sf2.selectbox(
        "Filter by category",
        options=["all"] + list(medications.VALID_CATEGORIES),
        format_func=lambda c: "All categories" if c == "all" else category_label(c, lang),
    )
    id_filter = sf3.selectbox(
        "Filter by identity status",
        options=["all", "confirmed", "needs_review", "unidentified"],
        format_func=lambda s: "All identity statuses" if s == "all" else identity_status_label(s, lang),
    )
    state_filter = sf4.selectbox(
        "Filter by state",
        options=["active", "inactive", "all"],
        format_func=lambda s: {
            "active": "Active medicines",
            "inactive": "Inactive / past",
            "all": "All (active + inactive)",
        }[s],
    )

    filtered = medications.list_medications(
        db_path,
        active_only=(state_filter == "active"),
        category=cat_filter,
        identity_status=id_filter,
        search=search_q,
    )
    if state_filter == "inactive":
        filtered = [m for m in filtered if not m.active]

    if not filtered:
        st.info("No medications match the current search or filter settings.")
        return

    for med in filtered:
        ui_theme.render_medication_card_header(med, lang)
        b1, b2, b3, b4 = st.columns([1.4, 1.3, 1.3, 1.3])

        # 1. Confirm identity quick action if not yet confirmed
        if med.identity_status != "confirmed":
            if b1.button("✓ Confirm identity", key=f"btn_conf_{med.id}", type="primary", use_container_width=True):
                st.session_state[f"confirming_{med.id}"] = not st.session_state.get(f"confirming_{med.id}", False)
                st.rerun()
        else:
            b1.caption(f"✓ Confirmed ({med.identity_source or 'verified'})")

        # 2. Edit toggle
        if b2.button("✏️ View / Edit details", key=f"btn_edit_{med.id}", use_container_width=True):
            st.session_state[f"editing_{med.id}"] = not st.session_state.get(f"editing_{med.id}", False)
            st.rerun()

        # 3. Active / Inactive toggle
        if med.active:
            if b3.button("⏸️ Mark inactive", key=f"btn_deact_{med.id}", use_container_width=True):
                medications.set_medication_active(db_path, med.id, False)
                set_flash(f"Marked **{med.display_name}** as inactive (paused).")
                st.rerun()
        else:
            if b3.button("▶️ Reactivate", key=f"btn_react_{med.id}", use_container_width=True):
                medications.set_medication_active(db_path, med.id, True)
                set_flash(f"Reactivated **{med.display_name}**.")
                st.rerun()

        # 4. Two-step Delete confirmation
        if b4.button("🗑️ Remove", key=f"btn_del_ask_{med.id}", use_container_width=True):
            st.session_state[f"confirm_del_{med.id}"] = True
            st.rerun()

        if st.session_state.get(f"confirm_del_{med.id}"):
            with st.container(border=True):
                st.warning(
                    f"Are you sure you want to permanently remove **{med.display_name}** from your list?"
                )
                dc1, dc2 = st.columns(2)
                if dc1.button("Yes, permanently remove", key=f"btn_del_yes_{med.id}", type="primary", use_container_width=True):
                    medications.delete_medication(db_path, med.id)
                    st.session_state.pop(f"confirm_del_{med.id}", None)
                    set_flash(f"Removed **{med.display_name}** from your medication list.")
                    st.rerun()
                if dc2.button("Cancel", key=f"btn_del_no_{med.id}", use_container_width=True):
                    st.session_state.pop(f"confirm_del_{med.id}", None)
                    st.rerun()

        # Confirm identity drawer
        if st.session_state.get(f"confirming_{med.id}"):
            with st.container(border=True):
                st.markdown(f"#### Confirm medication identity for **{html.escape(med.display_name)}**")
                if med.original_text:
                    st.caption(f"Original scanned / imported text: `{med.original_text}`")
                cand_res = drug_data.resolve_drug_candidates(
                    med.generic_name or med.display_name
                )
                if cand_res.candidates:
                    st.write("Suggested standardized matches:")
                    for c in cand_res.candidates:
                        st.markdown(f"- `{c.summary_label}`")
                conf_ings_default = (
                    " + ".join(i.name for i in med.ingredients)
                    or (
                        " + ".join(i.name for i in cand_res.candidates[0].ingredients)
                        if cand_res.candidates
                        else (med.generic_name or med.display_name).lower()
                    )
                )
                conf_ings = st.text_input(
                    "Confirmed active ingredient(s) (separate multiple with '+')",
                    value=conf_ings_default,
                    placeholder="e.g. lisinopril or ginkgo biloba",
                    key=f"conf_ing_in_{med.id}",
                )
                conf_str = st.text_input(
                    "Confirmed strength",
                    value=med.strength or (cand_res.candidates[0].strength if cand_res.candidates else "") or "",
                    placeholder="e.g. 10 mg, 120 mg",
                    key=f"conf_str_in_{med.id}",
                )
                cc1, cc2 = st.columns(2)
                if cc1.button("✓ Save confirmed identity", key=f"conf_save_{med.id}", type="primary", use_container_width=True):
                    parts = [p.strip() for p in conf_ings.split("+") if p.strip()]
                    if not parts:
                        st.error("Please enter at least one active ingredient to confirm.")
                    else:
                        medications.confirm_medication_identity(
                            db_path,
                            med.id,
                            generic_name=" / ".join(parts),
                            strength=conf_str.strip() or None,
                            ingredients=parts,
                            identity_source="user_confirmed",
                        )
                        st.session_state.pop(f"confirming_{med.id}", None)
                        set_flash(f"✓ Confirmed identity for **{med.display_name}** (`{' + '.join(parts)}`).")
                        st.rerun()
                if cc2.button("Close", key=f"conf_cancel_{med.id}", use_container_width=True):
                    st.session_state.pop(f"confirming_{med.id}", None)
                    st.rerun()

        # Full Edit / Detail drawer
        if st.session_state.get(f"editing_{med.id}"):
            with st.container(border=True):
                st.markdown(f"#### Edit details: **{html.escape(med.display_name)}**")
                st.caption(
                    f"Record ID: {med.id} · Created: {med.created_at} · Last updated: {med.updated_at} "
                    f"· Entry source: {med.entry_source}"
                )
                with st.form(f"edit_med_form_{med.id}"):
                    ec1, ec2, ec3 = st.columns(3)
                    e_disp = ec1.text_input("Display name", value=med.display_name, placeholder="e.g. Lisinopril")
                    e_gen = ec2.text_input("Generic name", value=med.generic_name or "", placeholder="e.g. lisinopril")
                    e_brand = ec3.text_input("Brand name", value=med.brand_name or "", placeholder="e.g. Zestril")

                    ec4, ec5, ec6 = st.columns(3)
                    e_ings = ec4.text_input(
                        "Active ingredient(s) ('+' separated)",
                        value=" + ".join(i.name for i in med.ingredients),
                        placeholder="e.g. lisinopril",
                    )
                    e_str = ec5.text_input("Strength", value=med.strength or "", placeholder="e.g. 10 mg")
                    e_form = ec6.text_input("Dosage form", value=med.dose_form or "", placeholder="e.g. Oral Tablet")

                    ec7, ec8, ec9 = st.columns(3)
                    cat_opts = list(medications.VALID_CATEGORIES)
                    e_cat = ec7.selectbox(
                        "Category",
                        options=cat_opts,
                        index=cat_opts.index(med.category) if med.category in cat_opts else 0,
                        format_func=lambda c: category_label(c, lang),
                    )
                    id_opts = list(medications.VALID_IDENTITY_STATUSES)
                    e_id_status = ec8.selectbox(
                        "Identity status",
                        options=id_opts,
                        index=id_opts.index(med.identity_status) if med.identity_status in id_opts else 0,
                        format_func=lambda s: identity_status_label(s, lang),
                    )
                    e_rxcui = ec9.text_input("RxCUI", value=med.rxcui or "", placeholder="e.g. 29046")

                    e_instr = st.text_input(
                        "Prescribed directions",
                        value=med.instructions or "",
                        placeholder="e.g. Take 1 tablet daily",
                    )
                    e_sched = st.text_input(
                        "Schedule times (comma-separated, e.g. 08:00, 18:00)",
                        value=", ".join(s.time_of_day for s in med.schedule),
                        placeholder="e.g. 08:00, 20:00",
                    )
                    ec10, ec11 = st.columns(2)
                    e_presc = ec10.text_input("Prescriber", value=med.prescriber or "", placeholder="e.g. Dr. Smith")
                    e_pharm = ec11.text_input("Pharmacy", value=med.pharmacy or "", placeholder="e.g. Local Pharmacy")
                    e_notes = st.text_area(
                        "Notes",
                        value=med.notes or "",
                        placeholder="Optional personal notes...",
                        height=68,
                    )

                    sc_save, sc_close = st.columns(2)
                    save_clicked = sc_save.form_submit_button("✓ Save changes", type="primary", use_container_width=True)
                    close_clicked = sc_close.form_submit_button("Close without saving", use_container_width=True)
                    if save_clicked:
                        ing_list = [p.strip() for p in e_ings.split("+") if p.strip()]
                        sched_list = [s.strip() for s in e_sched.split(",") if s.strip()]
                        medications.update_medication(
                            db_path,
                            med.id,
                            display_name=e_disp.strip(),
                            generic_name=e_gen.strip() or None,
                            brand_name=e_brand.strip() or None,
                            rxcui=e_rxcui.strip() or None,
                            strength=e_str.strip() or None,
                            dose_form=e_form.strip() or None,
                            instructions=e_instr.strip() or None,
                            category=e_cat,
                            prescriber=e_presc.strip() or None,
                            pharmacy=e_pharm.strip() or None,
                            notes=e_notes.strip() or None,
                            identity_status=e_id_status,
                            ingredients=ing_list,
                            schedule_times=sched_list,
                        )
                        st.session_state.pop(f"editing_{med.id}", None)
                        set_flash(f"✓ Updated **{e_disp.strip()}**.")
                        st.rerun()
                    elif close_clicked:
                        st.session_state.pop(f"editing_{med.id}", None)
                        st.rerun()


# --- Section 3: Scan a Bottle (OCR + Mandatory Human Review) ---------------

def render_scan_bottle(db_path: Path, lang: str) -> None:
    st.header(t("scan_heading", lang))
    st.write(t("scan_subtitle", lang))

    ocr_status = ocr_service.detect_tesseract()
    if ocr_status.available:
        st.success(f"✓ Local OCR engine ready: {ocr_status.message}")
    else:
        st.warning(
            f"⚠️ {ocr_status.message}\n\n"
            "You can still explore the built-in **DEMO SAMPLE LABELS** below or enter "
            "medication details manually."
        )

    source_mode = st.radio(
        "Choose an image source:",
        options=["sample", "upload", "camera"],
        format_func=lambda m: {
            "sample": "🧪 Try a built-in DEMO SAMPLE LABEL (no camera needed)",
            "upload": "📁 Upload a photo of a pill bottle label (.png, .jpg)",
            "camera": "📷 Capture a photo with your device camera",
        }[m],
        horizontal=True,
    )

    chosen_image = None
    sample_spec = None
    spec_idx = 0

    if source_mode == "sample":
        sample_paths = ocr_service.ensure_sample_labels()
        spec_idx = st.selectbox(
            "Select a demonstration label:",
            options=list(range(len(ocr_service.SAMPLE_LABELS))),
            format_func=lambda i: ocr_service.SAMPLE_LABELS[i]["title"],
        )
        sample_spec = ocr_service.SAMPLE_LABELS[spec_idx]
        chosen_image = sample_paths[spec_idx]
    elif source_mode == "upload":
        uploaded = st.file_uploader(
            "Upload a clear photo of the prescription or OTC label",
            type=["png", "jpg", "jpeg"],
        )
        if uploaded is not None:
            chosen_image = uploaded.getvalue()
    else:
        cam_photo = st.camera_input("Point the camera at the medication label in good lighting")
        if cam_photo is not None:
            chosen_image = cam_photo.getvalue()

    if chosen_image is None:
        st.info("Select a sample label, upload a photo, or take a picture above to start the review step.")
        return

    with st.spinner("Running pre-scan quality diagnostics and multi-pass OCR..."):
        ocr_res, processed_img, _ = ocr_service.scan_label_image(chosen_image)
        if not ocr_status.available and sample_spec is not None:
            ocr_res = ocr_service.parse_label_text(
                sample_spec["fallback_text"],
                engine_used="demo_sample_text_fallback",
                image_quality=ocr_res.image_quality,
            )

    # Pre-Scan Image Quality Diagnostics Banner
    iq = ocr_res.image_quality
    if iq is not None:
        if not iq.ok:
            with st.container(border=True):
                st.warning(
                    "**📷 Helpful Photo Quality Coaching (No Worries!)**\n\n"
                    + "\n".join(f"- {tip}" for tip in iq.coaching_tips)
                )
        else:
            st.caption(
                f"✓ Photo quality check passed (Brightness: {iq.mean_brightness:.0f}/255 · "
                f"Contrast: {iq.contrast_std:.0f} · Edge clarity: {iq.edge_sharpness:.0f})."
            )

    img_col1, img_col2, img_col3 = st.columns(3)
    with img_col1:
        st.markdown("##### 1. Original label image")
        st.image(chosen_image, use_container_width=True)
    with img_col2:
        st.markdown("##### 2. Multi-pass highlight-box removal")
        st.image(processed_img, use_container_width=True)
    with img_col3:
        st.markdown("##### 3. 🔍 Zoomed Label Loupe (Large Print)")
        loupe_band = st.slider(
            "Slide to move magnifier up or down the bottle label",
            min_value=10,
            max_value=80,
            value=42,
            step=5,
            key=f"loupe_slider_{source_mode}_{spec_idx}",
        )
        pw, ph = processed_img.size
        y_top = max(0, int(ph * (loupe_band - 22) / 100.0))
        y_bot = min(ph, int(ph * (loupe_band + 22) / 100.0))
        x_left = max(0, int(pw * 0.04))
        x_right = min(pw, int(pw * 0.96))
        loupe_crop = processed_img.crop((x_left, y_top, max(x_left + 10, x_right), max(y_top + 10, y_bot)))
        st.image(loupe_crop, use_container_width=True)

    st.markdown("---")
    st.subheader(t("ocr_review_heading", lang))
    st.warning(f"**[▲] {t('ocr_uncertainty_banner', lang)}**")

    for note in ocr_res.uncertainty_notes:
        st.info(f"• {note}")

    st.text_area(
        "Extracted label text (personal identifiers automatically redacted)",
        value=ocr_res.redacted_text or "(No text extracted)",
        height=120,
        disabled=True,
    )

    selected_cand: drug_data.DrugCandidate | None = None
    cand_idx = -1
    if ocr_res.candidates:
        cand_options = list(range(len(ocr_res.candidates))) + [-1]
        default_cand_idx = (
            0
            if (ocr_res.candidates[0].is_high_confidence)
            else len(ocr_res.candidates)  # index of -1 in cand_options
        )
        cand_idx = st.radio(
            "Standardized medication candidate(s) found — select the one matching your bottle:",
            options=cand_options,
            index=default_cand_idx,
            format_func=lambda idx: (
                ocr_res.candidates[idx].summary_label
                if idx >= 0
                else "None of these — I will enter or select the medication manually below"
            ),
            key=f"ocr_candidate_radio_{source_mode}_{spec_idx}_{hash(ocr_res.redacted_text)}",
        )
        if cand_idx >= 0 and cand_idx < len(ocr_res.candidates):
            selected_cand = ocr_res.candidates[cand_idx]

    # Senior-Friendly Quick Letter & Common Medicine Picker (especially helpful when a photo is blurry or partial)
    with st.container(border=True):
        st.markdown("#### 🔤 Quick Letter & Common Medicine Picker (Optional Helper)")
        st.caption(
            "If the bottle photo was blurry or had glare, type just the **first 2–3 letters** you can see "
            "on the label (for example `Amo` for Amoxicillin, `Lis` for Lisinopril, or `Met` for Metformin) "
            "or pick from the list below to auto-fill verified ingredients:"
        )
        qp1, qp2 = st.columns([1.2, 2.3])
        prefix_filter = qp1.text_input(
            "First 2–3 letters on bottle",
            placeholder="e.g. Amo, Lis, Met, Hyd...",
            key=f"ocr_quick_prefix_{source_mode}_{spec_idx}",
        )
        filtered_catalog = drug_data.search_catalog_by_prefix(prefix_filter)
        picker_options = [-1] + list(range(len(filtered_catalog)))
        picked_catalog_idx = qp2.selectbox(
            "Or choose a matching medicine from the reference list",
            options=picker_options,
            format_func=lambda idx: (
                "— Use scanned candidate above or type manually below —"
                if idx < 0
                else (
                    f"{filtered_catalog[idx].display_name} "
                    f"(generic: {filtered_catalog[idx].generic_name}"
                    + (f", brands: {filtered_catalog[idx].brand_name}" if filtered_catalog[idx].brand_name else "")
                    + ")"
                )
            ),
            key=f"ocr_quick_select_{source_mode}_{spec_idx}_{prefix_filter.strip().lower()}",
        )
        if picked_catalog_idx >= 0 and picked_catalog_idx < len(filtered_catalog):
            selected_cand = filtered_catalog[picked_catalog_idx]

    # FDA Look-Alike / Sound-Alike (LASA) Confusion Guard with Tall-Man Lettering
    active_lasa = (
        selected_cand.lasa_warning
        if (selected_cand and selected_cand.lasa_warning)
        else (
            drug_data.get_lasa_warning(selected_cand.generic_name)
            if selected_cand
            else (ocr_res.lasa_warnings[0] if ocr_res.lasa_warnings else None)
        )
    )
    if active_lasa:
        ui_theme.render_lasa_warning_card(active_lasa)

    # Never pre-fill random OCR fragments when no candidate is selected!
    prop_disp = selected_cand.display_name if selected_cand else ""
    prop_gen = selected_cand.generic_name if selected_cand else ""
    prop_brand = (selected_cand.brand_name or "") if selected_cand else ""
    prop_ings = (
        " + ".join(i.name for i in selected_cand.ingredients)
        if selected_cand
        else ""
    )
    prop_str = ocr_res.proposed_strength or (selected_cand.strength if selected_cand else "") or ""
    prop_form = ocr_res.proposed_form or (selected_cand.dose_form if selected_cand else "") or "Oral Tablet"
    prop_rxcui = (selected_cand.rxcui or "") if selected_cand else ""
    prop_cat = selected_cand.category if selected_cand else "prescription"

    # Key the form by source, candidate & quick-picker so switching selections immediately updates all text inputs!
    form_sig = f"{source_mode}_{spec_idx}_{cand_idx}_{picked_catalog_idx}_{hash(ocr_res.redacted_text)}"
    with st.form(f"ocr_review_confirm_form_{form_sig}"):
        rc1, rc2, rc3 = st.columns(3)
        r_disp = rc1.text_input(
            "Medication display name *",
            value=prop_disp,
            placeholder="e.g. Amoxicillin or Lisinopril",
        )
        r_gen = rc2.text_input(
            "Generic name",
            value=prop_gen,
            placeholder="e.g. amoxicillin or lisinopril",
        )
        r_brand = rc3.text_input(
            "Brand name (if shown)",
            value=prop_brand,
            placeholder="e.g. Prinivil, Zestril",
        )

        rc4, rc5, rc6 = st.columns(3)
        r_ings = rc4.text_input(
            "Active ingredient(s) ('+' separated) *",
            value=prop_ings,
            placeholder="e.g. lisinopril",
        )
        r_str = rc5.text_input(
            "Strength (verify against bottle)",
            value=prop_str,
            placeholder="e.g. 10 mg",
        )
        r_form = rc6.text_input(
            "Dosage form",
            value=prop_form,
            placeholder="e.g. Oral Tablet",
        )

        rc7, rc8 = st.columns(2)
        cat_opts = list(medications.VALID_CATEGORIES)
        r_cat = rc7.selectbox(
            "Category",
            options=cat_opts,
            index=cat_opts.index(prop_cat) if prop_cat in cat_opts else 0,
            format_func=lambda c: category_label(c, lang),
        )
        r_sched = rc8.text_input(
            "Daily reminder time(s) (optional)",
            value="8:00 AM" if "morning" in (ocr_res.proposed_instructions or "").lower() else "",
            placeholder="e.g. 8:00 AM, 8:00 PM",
        )
        r_instr = st.text_input(
            "Directions on label (verify carefully — left blank if unclear)",
            value=ocr_res.proposed_instructions or "",
            placeholder="e.g. Take 1 tablet by mouth every morning",
        )

        human_verified = st.checkbox(
            "I have compared these fields with my physical medication bottle and confirm "
            "that the medication name, active ingredient(s), and strength are accurate.",
            value=True,
        )
        sb1, sb2 = st.columns(2)
        save_confirmed = sb1.form_submit_button(
            "✓ Confirm identity & save to My Medicines",
            type="primary",
            use_container_width=True,
        )
        save_unconfirmed = sb2.form_submit_button(
            "Save as 'Needs confirmation' (review later)",
            use_container_width=True,
        )

        if save_confirmed or save_unconfirmed:
            if not r_disp.strip():
                st.error("Please enter the medication name before saving.")
            elif save_confirmed and not human_verified:
                st.error(
                    "Please check the confirmation box above to save as a confirmed identity, "
                    "or click 'Save as Needs confirmation' if you are unsure."
                )
            elif save_confirmed and not r_ings.strip():
                st.error(
                    "At least one active ingredient is required to confirm a medication identity."
                )
            else:
                ing_list = [p.strip() for p in r_ings.split("+") if p.strip()]
                sched_list = [s.strip() for s in r_sched.split(",") if s.strip()]
                status_val = "confirmed" if (save_confirmed and human_verified and ing_list) else (
                    "needs_review" if ing_list else "unidentified"
                )
                medications.add_medication(
                    db_path,
                    r_disp.strip(),
                    generic_name=r_gen.strip() or None,
                    brand_name=r_brand.strip() or None,
                    rxcui=prop_rxcui.strip() or None,
                    strength=r_str.strip() or None,
                    dose_form=r_form.strip() or None,
                    route="Oral",
                    instructions=r_instr.strip() or None,
                    category=r_cat,
                    active=True,
                    entry_source="scanned",
                    identity_status=status_val,
                    identity_source="ocr_user_confirmed" if status_val == "confirmed" else "ocr_unconfirmed",
                    original_text=ocr_res.redacted_text[:1000],
                    ingredients=ing_list,
                    schedule_times=sched_list,
                )
                set_flash(
                    f"✓ Saved scanned bottle **{r_disp.strip()}** ({identity_status_label(status_val, lang)}) to My Medicines!"
                )
                st.rerun()


# --- Section 4: Safety Checker (The Signature Feature) ---------------------

def render_safety_checker(db_path: Path, lang: str, is_demo: bool) -> None:
    st.header(t("checker_heading", lang))
    st.write(t("checker_subtitle", lang))

    active_meds = medications.list_medications(db_path, active_only=True)
    if not active_meds:
        st.info("Your active medication list is currently empty. Add a medicine first or switch on Demo Mode.")
        if st.button("➕ Go to My Medicines", key="checker_go_meds_btn", type="primary"):
            st.session_state.expand_add_med = True
            navigate_to("medicines")
            st.rerun()
        return

    with st.container(border=True):
        st.markdown("#### Your active medication list included in this check")
        for m in active_meds:
            ings = " + ".join(i.name for i in m.ingredients) or "Unidentified"
            badge = identity_status_label(m.identity_status, lang)
            st.markdown(
                f"- **{html.escape(m.display_name)}** ({html.escape(m.strength or '—')}) — "
                f"Active ingredient(s): `{html.escape(ings)}` — **{html.escape(badge)}**"
            )

    check_mode = st.radio(
        "Choose what you would like to check:",
        options=["proposed", "full_list"],
        format_func=lambda m: (
            t("checker_mode_proposed", lang)
            if m == "proposed"
            else t("checker_mode_full", lang)
        ),
        horizontal=True,
    )

    proposed_med: MedForCheck | None = None

    if check_mode == "proposed":
        with st.container(border=True):
            st.markdown("#### Step 1: Identify & confirm the medicine you are considering adding")
            st.caption(
                "Quick-pick examples (click any button below to test checking a proposed medicine):"
            )
            dq1, dq2, dq3, dq4 = st.columns(4)
            demo_picks = [
                (dq1, "🧪 Ibuprofen 200 mg (Advil)", "Ibuprofen 200 mg"),
                (dq2, "🧪 Advil PM (Combination)", "Advil PM"),
                (dq3, "🧪 Clarithromycin 500 mg", "Clarithromycin 500 mg"),
                (dq4, "🧪 Acetaminophen 500 mg (Tylenol)", "Acetaminophen 500 mg"),
            ]
            for dcol, dlabel, dval in demo_picks:
                if dcol.button(dlabel, key=f"dq_btn_{dval}", use_container_width=True):
                    st.session_state["checker_prop_input"] = dval
                    st.session_state["prop_query"] = dval
                    st.session_state["prop_norm"] = drug_data.resolve_drug_candidates(dval)
                    st.session_state["last_resolved_prop_q"] = dval
                    st.session_state["checker_prop_cand_radio"] = 0
                    st.rerun()

            if "checker_prop_input" not in st.session_state:
                st.session_state["checker_prop_input"] = st.session_state.get(
                    "prop_query", "Ibuprofen 200 mg" if is_demo else ""
                )

            pc1, pc2 = st.columns([3, 1])
            prop_q = pc1.text_input(
                "Proposed medicine name",
                placeholder="e.g. Ibuprofen 200 mg, Advil PM, Potassium Chloride, or Tylenol",
                key="checker_prop_input",
            )
            lookup_clicked = pc2.button(
                "🔎 Look up proposed medicine",
                key="btn_lookup_prop",
                type="primary",
                use_container_width=True,
            )
            if lookup_clicked or (
                prop_q.strip() and prop_q.strip() != st.session_state.get("last_resolved_prop_q")
            ):
                st.session_state.prop_query = prop_q.strip()
                st.session_state.prop_norm = (
                    drug_data.resolve_drug_candidates(prop_q.strip()) if prop_q.strip() else None
                )
                st.session_state.last_resolved_prop_q = prop_q.strip()
                st.session_state["checker_prop_cand_radio"] = 0

            p_norm: drug_data.NormalizationResult | None = st.session_state.get("prop_norm")
            if p_norm and p_norm.candidates and prop_q.strip():
                cand_idx = st.radio(
                    "Confirm the proposed medication's standardized identity:",
                    options=list(range(len(p_norm.candidates))) + [-1],
                    format_func=lambda idx: (
                        p_norm.candidates[idx].summary_label
                        if idx >= 0
                        else "None of these — medication identity is unconfirmed"
                    ),
                    key="checker_prop_cand_radio",
                )
                if cand_idx >= 0 and cand_idx < len(p_norm.candidates):
                    chosen_c = p_norm.candidates[cand_idx]
                    prop_confirmed = st.checkbox(
                        f"I confirm that I want to check **{chosen_c.display_name}** "
                        f"(active ingredient(s): `{' + '.join(i.name for i in chosen_c.ingredients)}`).",
                        value=True,
                        key="checker_prop_confirm_box",
                    )
                    proposed_med = MedForCheck(
                        key="proposed",
                        display_name=chosen_c.display_name,
                        ingredients=chosen_c.ingredients,
                        identity_status="confirmed" if prop_confirmed else "needs_review",
                        is_proposed=True,
                    )
                else:
                    proposed_med = MedForCheck(
                        key="proposed",
                        display_name=prop_q.strip() or "Unidentified medicine",
                        ingredients=(),
                        identity_status="unidentified",
                        is_proposed=True,
                    )
            elif prop_q.strip():
                st.warning(
                    f"Could not resolve **{prop_q.strip()}** to a standardized active ingredient. "
                    "Running the check will report pairs involving this medicine as `UNABLE_TO_CHECK`."
                )
                proposed_med = MedForCheck(
                    key="proposed",
                    display_name=prop_q.strip(),
                    ingredients=(),
                    identity_status="unidentified",
                    is_proposed=True,
                )

    # Run deterministic lookup
    med_items = [m.to_check_item() for m in active_meds]
    report = interactions.check_medications(
        db_path,
        med_items,
        proposed=proposed_med if check_mode == "proposed" else None,
    )

    if st.button(
        f"🔍 {t('checker_run_btn', lang)} & log to check history",
        key="btn_run_checker_main",
        type="primary",
        use_container_width=True,
    ):
        interactions.save_history(db_path, report)
        hits_n = len(report.by_status(CheckStatus.MATCH_FOUND))
        now_str = dt.datetime.now().strftime("%I:%M:%S %p")
        st.success(
            f"✓ **Interaction lookup completed and saved to local history at {now_str}:** "
            f"Compared **{len(report.results)}** medication pair(s) against "
            f"**{report.dataset_status.total_records}** loaded dataset records — "
            f"**{hits_n}** interaction record match(es) found."
        )

    st.markdown("---")

    # 1. Incomplete Check Banner (if any medicine lacks a confirmed identity or dataset unavailable)
    if not report.complete:
        unusable_names = ", ".join(m.display_name for m in report.unusable_medicines)
        st.warning(
            f"**[▲] {t('incomplete_check_banner', lang)}**\n\n"
            + (
                f"Medicines requiring confirmation or identification: **{unusable_names}**."
                if unusable_names
                else f"Dataset problem: {report.dataset_status.problem}"
            )
        )

    # 2. Duplicate Active Ingredient Warning
    if report.duplicates:
        for dup in report.duplicates:
            st.warning(
                f"**[▲] Duplicate Active Ingredient Detected (`{dup.ingredient}`):** "
                f"Both **{'** and **'.join(dup.medicines)}** contain `{dup.ingredient}`. "
                "Taking multiple products with the same active ingredient can accidentally "
                "exceed recommended doses. Ask your pharmacist before combining them."
            )

    # 3. Severity & Status Legend
    with st.expander("📖 Severity & Result Status Legend (How to read these results)", expanded=False):
        st.markdown(
            f"- {ui_theme.status_badge_html(CheckStatus.MATCH_FOUND, lang)} — "
            "A matching interaction record exists in the loaded dataset.\n"
            f"- {ui_theme.status_badge_html(CheckStatus.NO_MATCHING_RECORD, lang)} — "
            "Both medicines were identified, and no record was found in the loaded dataset. "
            "**Because the dataset is incomplete, this does NOT establish safety.**\n"
            f"- {ui_theme.status_badge_html(CheckStatus.IDENTITY_REQUIRES_CONFIRMATION, lang)} / "
            f"{ui_theme.status_badge_html(CheckStatus.UNABLE_TO_CHECK, lang)} — "
            "A medicine's active ingredient has not been confirmed or identified, so the pair could not be checked.\n"
            f"- **Severity classifications:** {ui_theme.severity_badge_html('major', 'major', lang)} "
            f"{ui_theme.severity_badge_html('moderate', 'moderate', lang)} "
            f"{ui_theme.severity_badge_html('minor', 'minor', lang)} "
            f"{ui_theme.severity_badge_html('unspecified', 'unspecified', lang)}",
            unsafe_allow_html=True,
        )

    # 4. Pairwise Results
    st.subheader(f"Pairwise Interaction Results ({len(report.results)} pair(s))")
    if not report.results:
        st.info("At least two medicines are needed to compare a pair.")

    for idx, pair in enumerate(report.results):
        border_cls = ui_theme.pair_card_border_class(pair)
        status_html = ui_theme.status_badge_html(pair.status, lang)
        ing_pairs_str = (
            ", ".join(f"{a} + {b}" for a, b in pair.ingredient_pairs)
            if pair.ingredient_pairs
            else "Active ingredients not confirmed for both medicines"
        )

        rec = pair.records[0] if pair.records else None
        sev_html = (
            ui_theme.severity_badge_html(rec.severity_level, rec.severity_raw, lang)
            if rec
            else ""
        )

        st.markdown(
            f"""
            <div class="ms-card {border_cls}">
                <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:8px;">
                    <div class="ms-card-title">
                        {html.escape(pair.med_a.display_name)} &nbsp;+&nbsp; {html.escape(pair.med_b.display_name)}
                    </div>
                    <div>{status_html} {sev_html}</div>
                </div>
                <div class="ms-card-subtitle" style="margin-top:6px;font-size:0.92em;">
                    <strong>Standardized ingredient pair compared:</strong> {html.escape(ing_pairs_str)}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if pair.status == CheckStatus.MATCH_FOUND and rec:
            with st.container(border=True):
                if rec.severity_level == "major":
                    st.error(f"**[!] {t('action_caution_major', lang)}**")
                else:
                    st.warning(f"**[▲] {t('action_caution_match', lang)}**")

                exp_res = ai_explain.explain_structured(pair, language=lang)
                src_badge = (
                    t("badge_source_ai", lang)
                    if exp_res.source == "ai"
                    else t("badge_source_template", lang)
                )
                st.caption(f"Explanation source: **{src_badge}**")
                st.markdown(f"**What the record says:** {html.escape(exp_res.explanation)}")
                st.markdown(f"**Why it matters:** {html.escape(exp_res.why_it_matters)}")
                st.markdown(f"**What to do next:** {html.escape(exp_res.what_to_do_next)}")
                st.caption(f"**Limitations:** {exp_res.limitations}")

                if lang != "English":
                    with st.expander(f"🌐 {t('show_original_english', lang)}"):
                        eng = exp_res.original_english
                        st.markdown(f"- **Explanation:** {eng['explanation']}")
                        st.markdown(f"- **Why it matters:** {eng['why_it_matters']}")
                        st.markdown(f"- **What to do next:** {eng['what_to_do_next']}")
                        st.markdown(f"- **Raw source mechanism:** `{rec.mechanism or 'Not supplied by source'}`")

                if st.button("🔊 Read explanation aloud", key=f"tts_pair_{idx}"):
                    audio_bytes = synthesize_speech(exp_res.as_text(), lang)
                    if audio_bytes:
                        st.audio(audio_bytes, format="audio/mp3")
                    else:
                        st.caption("Audio synthesis is currently offline or unavailable.")

                with st.expander("🔎 Source dataset provenance & supplementary FDA label text"):
                    st.markdown(
                        f"- **Dataset name:** {rec.dataset_name} (Version: `{rec.dataset_version or 'n/a'}`)\n"
                        f"- **Source record ID:** `{rec.source_record_id or rec.record_id}`\n"
                        f"- **Source severity field:** `{rec.severity_raw}` (mapped to `{rec.severity_level}`)\n"
                        f"- **Source mechanism text:** {rec.mechanism or 'Not provided by source dataset.'}\n"
                        f"- **Source management text:** {rec.management or 'Not provided by source dataset.'}\n"
                        f"- **Dataset imported at:** `{rec.imported_at}`\n"
                        f"- **Attribution & License:** {rec.attribution or '—'} ({rec.license or '—'})"
                    )
                    if st.button(
                        "Fetch supplementary official U.S. FDA label excerpt (openFDA)",
                        key=f"fda_btn_{idx}",
                    ):
                        for ing_name in (rec.ingredient_a, rec.ingredient_b):
                            info = drug_data.get_label_info(ing_name)
                            if info:
                                st.markdown(
                                    f"**Official FDA Label Excerpt for `{ing_name.title()}`** "
                                    f"(Effective date: `{info.get('effective_date')}` · "
                                    f"[View on NLM DailyMed]({info.get('label_url')})):"
                                )
                                st.write(
                                    info.get("drug_interactions")
                                    or info.get("ask_doctor_or_pharmacist")
                                    or info.get("warnings_and_cautions")
                                    or info.get("warnings")
                                )
                                st.caption(str(info.get("disclaimer")))
                                break
                        else:
                            st.caption("No openFDA label excerpt was returned (or you are offline).")

        elif pair.status == CheckStatus.NO_MATCHING_RECORD:
            with st.container(border=True):
                if pair.reason == "same_ingredients":
                    st.warning(
                        "Both medicines contain the exact same active ingredient(s). "
                        "See the duplicate ingredient warning above."
                    )
                else:
                    st.write(f"ℹ️ {t('no_record_explanation', lang)}")
                    st.caption(
                        f"Checked against: {report.dataset_status.label} "
                        f"({report.dataset_status.total_records} loaded pairs). "
                        "What remains unknown: Any interaction not included in this starter dataset, "
                        "dose-specific effects, and patient-specific conditions."
                    )

        else:
            with st.container(border=True):
                st.warning(
                    "This pair could not be checked because at least one medicine's active "
                    "ingredient has not been confirmed (or the dataset is unavailable)."
                )
                if st.button("Confirm medication identity in My Medicines →", key=f"pair_conf_nav_{idx}"):
                    navigate_to("medicines")
                    st.rerun()

    # 5. Food & Drink Cautions
    st.markdown("---")
    st.subheader("🍊 Food & Drink Cautions from Loaded Dataset")
    if not report.food_findings:
        st.caption(
            "No food or drink interaction records matched in the loaded starter food dataset. "
            "As with drug-drug checks, absence of a record does not guarantee no food interactions exist."
        )
    else:
        for f_idx, f_row in enumerate(report.food_findings):
            sev_b = ui_theme.severity_badge_html(f_row.severity_level, f_row.severity_raw, lang)
            with st.container(border=True):
                st.markdown(
                    f"**{html.escape(f_row.medicine)} (`{html.escape(f_row.ingredient)}`) + "
                    f"{html.escape(f_row.food.title())}** &nbsp; {sev_b}",
                    unsafe_allow_html=True,
                )
                f_exp = ai_explain.explain_food_structured(f_row, language=lang)
                st.write(f_exp.explanation)
                st.write(f_exp.why_it_matters)
                st.caption(
                    f"{f_exp.what_to_do_next} · Source: {f_row.dataset_name} "
                    f"(Record ID: `{f_row.source_record_id or 'n/a'}`)"
                )
                if st.button("🔊 Read food caution aloud", key=f"tts_food_{f_idx}"):
                    audio_bytes = synthesize_speech(f_exp.as_text(), lang)
                    if audio_bytes:
                        st.audio(audio_bytes, format="audio/mp3")


# --- Section 5: Daily Schedule & In-App Checklist --------------------------

def render_daily_schedule(db_path: Path, lang: str) -> None:
    st.header(t("schedule_heading", lang))
    st.write(t("schedule_subtitle", lang))
    st.info(f"ℹ️ {t('schedule_honest_notice', lang)}")

    sc_top1, sc_top2 = st.columns([1.4, 2.6])
    chosen_date = sc_top1.date_input("Schedule date", value=dt.date.today())
    day_iso = chosen_date.isoformat()

    items = medications.get_daily_schedule(db_path, day_iso)
    next_dose = medications.get_next_scheduled_dose(items) if chosen_date == dt.date.today() else None

    with sc_top2:
        if next_dose:
            st.success(
                f"⏰ **Next scheduled dose today:** **{next_dose.medication_name}** "
                f"({next_dose.strength or 'strength not set'}) at **{next_dose.display_time}** "
                + (f"— *{next_dose.label}*" if next_dose.label else "")
            )
        elif items:
            st.success("✓ All scheduled doses for this date have been recorded.")
        else:
            st.caption("No schedule times configured yet. Add reminder times below.")

    if any(i.status == "skipped" for i in items):
        st.warning(f"**[▲] {t('missed_dose_warning', lang)}**")

    if items:
        taken_n = sum(1 for i in items if i.status == "taken")
        skipped_n = sum(1 for i in items if i.status == "skipped")
        pending_n = len(items) - taken_n - skipped_n
        st.progress(taken_n / len(items))
        st.caption(
            f"**{taken_n}** marked taken · **{skipped_n}** marked skipped · "
            f"**{pending_n}** not yet recorded (total: {len(items)})"
        )

        for item in items:
            status_badge = {
                "taken": f'<span class="ms-badge ms-badge-teal">[✓] {html.escape(t("dose_taken", lang))}</span>',
                "skipped": f'<span class="ms-badge ms-badge-moderate">[▲] {html.escape(t("dose_skipped", lang))}</span>',
                None: f'<span class="ms-badge ms-badge-neutral">[•] {html.escape(t("dose_pending", lang))}</span>',
            }[item.status]
            late_min = (
                alerts.minutes_overdue({"time_of_day": item.time_of_day, "status": item.status})
                if chosen_date == dt.date.today()
                else 0
            )
            late_note = f" · ⚠️ {alerts.format_lateness(late_min)}" if late_min > 0 else ""

            with st.container(border=True):
                row1, row2, row3, row4 = st.columns([2.8, 1.1, 1.1, 1.0])
                with row1:
                    st.markdown(
                        f"**{html.escape(item.display_time)}** — "
                        f"**{html.escape(item.medication_name)}** "
                        f"({html.escape(item.strength or '—')}) &nbsp; {status_badge}",
                        unsafe_allow_html=True,
                    )
                    st.caption(
                        f"Prescribed directions: {item.instructions or 'None recorded'}"
                        + (f" · Note: {item.label}" if item.label else "")
                        + late_note
                    )
                if row2.button(
                    "✓ Mark taken",
                    key=f"sch_take_{item.schedule_entry_id}_{day_iso}",
                    type="primary" if item.status != "taken" else "secondary",
                    use_container_width=True,
                ):
                    medications.record_dose_status(db_path, item.schedule_entry_id, "taken", day_iso)
                    set_flash(f"✓ Marked **{item.medication_name}** ({item.display_time}) as taken.")
                    st.rerun()
                if row3.button(
                    "⏭️ Mark skipped",
                    key=f"sch_skip_{item.schedule_entry_id}_{day_iso}",
                    use_container_width=True,
                ):
                    medications.record_dose_status(db_path, item.schedule_entry_id, "skipped", day_iso)
                    set_flash(f"Marked **{item.medication_name}** ({item.display_time}) as skipped.", level="warning")
                    st.rerun()
                if row4.button(
                    "↺ Clear",
                    key=f"sch_clr_{item.schedule_entry_id}_{day_iso}",
                    use_container_width=True,
                ):
                    medications.record_dose_status(db_path, item.schedule_entry_id, None, day_iso)
                    set_flash(f"Cleared dose status for **{item.medication_name}** ({item.display_time}).", level="info")
                    st.rerun()

    st.markdown("---")
    col_manage, col_export = st.columns(2)

    with col_manage:
        with st.container(border=True):
            st.markdown("#### ➕ Add or remove reminder times")
            active_meds = medications.list_medications(db_path, active_only=True)
            if not active_meds:
                st.caption("Add an active medicine first to configure reminder times.")
            else:
                chosen_med = st.selectbox(
                    "Medicine",
                    options=active_meds,
                    format_func=lambda m: f"{m.display_name} ({m.strength or '—'})",
                )
                tc1, tc2 = st.columns(2)
                picked_time = tc1.time_input("Reminder time", value=dt.time(8, 0))
                picked_label = tc2.text_input(
                    "Optional note",
                    placeholder="e.g. With breakfast, Before bed",
                )
                if st.button("➕ Add reminder time", key="btn_add_reminder_time", type="primary", use_container_width=True):
                    medications.add_schedule_entry(
                        db_path,
                        chosen_med.id,
                        picked_time.strftime("%H:%M"),
                        picked_label.strip() or None,
                    )
                    set_flash(
                        f"✓ Added {picked_time.strftime('%I:%M %p').lstrip('0')} reminder for **{chosen_med.display_name}**."
                    )
                    st.rerun()

                if chosen_med.schedule:
                    st.markdown("**Configured times for this medicine:**")
                    for s in chosen_med.schedule:
                        rm_c1, rm_c2 = st.columns([3, 1])
                        rm_c1.write(f"• {s.display_time}")
                        if rm_c2.button("Remove", key=f"rm_sched_{s.id}", use_container_width=True):
                            medications.remove_schedule_entry(db_path, s.id)
                            set_flash(f"Removed {s.display_time} reminder for **{chosen_med.display_name}**.", level="info")
                            st.rerun()

    with col_export:
        with st.container(border=True):
            st.markdown("#### 📅 Calendar Export & Recent Checklist Log")
            if items:
                ics_data = medications.export_schedule_ics(db_path, days_ahead=7)
                st.download_button(
                    "📥 Download 7-day calendar reminders (.ics)",
                    data=ics_data,
                    file_name="medsafe_schedule.ics",
                    mime="text/calendar",
                    use_container_width=True,
                )
            recent_logs = medications.get_recent_dose_history(db_path, days=7)
            if not recent_logs:
                st.caption("No checklist entries recorded in the past 7 days.")
            else:
                for lg in recent_logs[:8]:
                    st.markdown(
                        f"- `{lg['log_date']}` at `{medications.format_time_12h(lg['time_of_day'])}`: "
                        f"**{html.escape(lg['display_name'])}** — **{lg['status'].upper()}**"
                    )


# --- Section 6: Caregiver & Pharmacist Reports -----------------------------

def render_caregiver_reports(db_path: Path, lang: str, is_demo: bool) -> None:
    st.header(t("reports_heading", lang))
    st.write(t("reports_subtitle", lang))
    st.info(f"🔒 {t('caregiver_privacy_note', lang)}")

    all_meds = medications.list_medications(db_path)
    active_meds = [m for m in all_meds if m.active]
    prop_question_med = st.text_input(
        "Optional: Include a medicine you are considering asking your pharmacist about",
        placeholder="e.g. Ibuprofen 200 mg, Advil PM, or Melatonin",
    )

    report = interactions.check_medications(
        db_path, [m.to_check_item() for m in active_meds]
    )
    md_summary = medications.export_summary_markdown(
        all_meds,
        report,
        is_demo=is_demo,
        proposed_name=prop_question_med.strip() or None,
    )
    csv_data = medications.export_medications_csv(all_meds)
    html_data = medications.export_printable_html(
        all_meds,
        report,
        is_demo=is_demo,
        proposed_name=prop_question_med.strip() or None,
    )
    questions = medications.build_pharmacist_questions(
        all_meds, report, prop_question_med.strip() or None
    )

    st.subheader("1. Review Report Before Downloading")
    tab_summary, tab_questions, tab_csv = st.tabs(
        [
            "📄 Full Medication & Interaction Summary",
            "❓ Questions for Your Pharmacist",
            "📊 CSV Preview",
        ]
    )
    with tab_summary:
        st.markdown(md_summary)
    with tab_questions:
        st.markdown("Bring these non-prescriptive questions to your next pharmacy or doctor visit:")
        for q in questions:
            st.markdown(f"1. {q}")
    with tab_csv:
        st.code(csv_data, language="csv")

    st.subheader("2. Export & Print Options")
    dl1, dl2, dl3, dl4 = st.columns(4)
    if dl1.download_button(
        "📥 Download CSV List (.csv)",
        data=csv_data,
        file_name="medsafe_medications.csv",
        mime="text/csv",
        use_container_width=True,
    ):
        medications.record_report_generation(db_path, "csv")
    if dl2.download_button(
        "📥 Download Markdown (.md)",
        data=md_summary,
        file_name="medsafe_summary.md",
        mime="text/markdown",
        use_container_width=True,
    ):
        medications.record_report_generation(db_path, "markdown")
    if dl3.download_button(
        "📥 Download Plain Text (.txt)",
        data=md_summary,
        file_name="medsafe_summary.txt",
        mime="text/plain",
        use_container_width=True,
    ):
        medications.record_report_generation(db_path, "text")
    if dl4.download_button(
        "🖨️ Download Print-Friendly (.html)",
        data=html_data,
        file_name="medsafe_printable_report.html",
        mime="text/html",
        use_container_width=True,
    ):
        medications.record_report_generation(db_path, "printable_html")


# --- Section 7: Settings, Accessibility & Privacy --------------------------

def render_settings_privacy(db_path: Path, lang: str, is_demo: bool) -> None:
    st.header(t("settings_heading", lang))
    st.write(t("settings_subtitle", lang))
    personal_path = config.personal_db_path()

    # Dedicated Appearance & Senior Accessibility Card inside Settings too
    with st.container(border=True):
        st.subheader("🎨 Appearance, Theme & Senior Accessibility")
        st.write(
            "Customize MedSafe's visual appearance, text size, and display language. "
            "Your preferences are saved automatically on this device."
        )
        ac1, ac2, ac3 = st.columns(3)
        theme_keys = list(ui_theme.THEME_MODES.keys())
        cur_theme = (
            st.session_state.theme_mode
            if st.session_state.theme_mode in theme_keys
            else "light"
        )
        picked_theme = ac1.radio(
            "Color theme mode",
            options=theme_keys,
            index=theme_keys.index(cur_theme),
            format_func=lambda k: ui_theme.THEME_MODES[k],
            key="settings_theme_radio",
        )
        if picked_theme != cur_theme:
            st.session_state.theme_mode = picked_theme
            st.session_state.high_contrast = picked_theme == "high_contrast"
            db.set_setting(personal_path, "theme_mode", picked_theme)
            db.set_setting(personal_path, "high_contrast", "1" if picked_theme == "high_contrast" else "0")
            set_flash(f"Switched appearance to **{ui_theme.THEME_MODES[picked_theme]}**.")
            st.rerun()

        size_labels = {
            "standard": "Standard (18 px)",
            "large": "Large (20 px)",
            "xlarge": "Extra Large (22 px)",
        }
        size_keys = list(size_labels.keys())
        picked_size = ac2.radio(
            "Text size",
            options=size_keys,
            index=size_keys.index(st.session_state.font_size)
            if st.session_state.font_size in size_keys
            else 0,
            format_func=lambda k: size_labels[k],
            key="settings_size_radio",
        )
        if picked_size != st.session_state.font_size:
            st.session_state.font_size = picked_size
            db.set_setting(personal_path, "font_size", picked_size)
            set_flash(f"Updated text size to **{size_labels[picked_size]}**.")
            st.rerun()

        lang_keys = list(SUPPORTED_LANGUAGES.keys())
        picked_lang = ac3.selectbox(
            "Interface & explanation language (7 languages)",
            options=lang_keys,
            index=lang_keys.index(lang) if lang in lang_keys else 0,
            format_func=lambda k: SUPPORTED_LANGUAGES[k],
            key="settings_lang_select",
        )
        if picked_lang != lang:
            st.session_state.language = picked_lang
            db.set_setting(personal_path, "language", picked_lang)
            set_flash(f"Language changed to **{SUPPORTED_LANGUAGES[picked_lang]}**.")
            st.rerun()

        st.info(
            "**What do the 3 theme modes do?**\n"
            "- **☀️ Light Mode (Daylight):** Warm daylight background (`#F4F7FB`) with white cards and dark slate text.\n"
            "- **🌙 Dark Mode (Low Glare):** Soothing dark slate background (`#0B132B`) with bright off-white text for comfortable evening reading.\n"
            "- **👁️ High Contrast (AAA Low Vision):** Maximum-legibility pitch-black background (`#000000`), pure white text, bright yellow headings (`#FFD60A`), and bold `2.5 px` outlines designed for seniors with low vision or cataract glare sensitivity."
        )

    col_s1, col_s2 = st.columns(2)

    with col_s1:
        with st.container(border=True):
            st.subheader("🔍 System & Service Status")
            ds = interactions.get_dataset_status(db_path)
            ocr_st = ocr_service.detect_tesseract()
            has_gemini = config.gemini_api_key() is not None

            st.markdown(
                f"- **Active SQLite database file:** `{db_path.name}` (Schema v{db.SCHEMA_VERSION})\n"
                f"- **Profile mode:** `{'Demonstration Mode (fictional data)' if is_demo else 'Personal Mode (local data)'}`\n"
                f"- **Interaction dataset status:** `{'Available' if ds.available else 'Unavailable'}` "
                f"({ds.total_records} records across {len(ds.datasets)} dataset(s))\n"
                f"- **Local Tesseract OCR engine:** `{'Available' if ocr_st.available else 'Not installed'}` "
                f"({ocr_st.message})\n"
                f"- **NLM RxNorm & U.S. FDA openFDA APIs:** Public HTTPS endpoints (no API key required; "
                f"timeout={config.HTTP_TIMEOUT}s; automatic local catalog fallback when offline)\n"
                f"- **Optional Gemini plain-language AI:** "
                f"`{'Configured (' + config.gemini_model() + ')' if has_gemini else 'Not configured — using deterministic verified templates'}`"
            )

        with st.container(border=True):
            st.subheader("📦 Import DDInter 2.0 CSV Dataset")
            st.write(
                "Upload one or more DDInter 2.0 CSV files (`DDInterID_A, Drug_A, DDInterID_B, Drug_B, Level`) "
                "to expand the local interaction database. Imports are validated before writing; "
                "a failed import never overwrites your existing database."
            )
            uploaded_dd = st.file_uploader(
                "Select DDInter 2.0 CSV file(s)",
                type=["csv"],
                accept_multiple_files=True,
                key="ddinter_uploader",
            )
            if uploaded_dd and st.button("Validate & import DDInter CSV(s)", type="primary"):
                import tempfile

                tmp_dir = Path(tempfile.mkdtemp())
                saved_paths: list[Path] = []
                for uf in uploaded_dd:
                    p = tmp_dir / uf.name
                    p.write_bytes(uf.getvalue())
                    saved_paths.append(p)
                meta = {
                    "dataset_id": "ddinter-2.0",
                    "name": "DDInter 2.0 Drug-Drug Interaction Database",
                    "version": "2.0",
                    "source_url": "https://ddinter2.scbdd.com/",
                    "license": "CC BY-NC-SA 4.0 (NonCommercial)",
                    "attribution": "Xiong G. et al., DDInter 2.0 (https://ddinter2.scbdd.com/).",
                    "notes": "Imported via MedSafe Settings; 'Unknown' mapped to 'unspecified'.",
                    "is_demo": 0,
                }
                rep = dataset_import.import_interactions(db_path, saved_paths, meta, fmt="ddinter")
                if rep.ok:
                    st.success(rep.summary())
                else:
                    st.error(rep.summary())

    with col_s2:
        with st.container(border=True):
            st.subheader("🔒 Local-First Privacy & Data Transmission")
            st.markdown(
                """
                * **Where your data lives:** Your medication list, schedule, and dose logs are stored locally on this computer in SQLite (`data/medsafe.sqlite3` for Personal Mode, `data/medsafe_demo.sqlite3` for Demo Mode). MedSafe does not use cloud sync.
                * **Local OCR & PII Redaction:** Bottle images are processed in memory by local Tesseract OCR. Prescription numbers, patient names, birth dates, phone numbers, and street addresses are automatically redacted and never stored.
                * **What is sent to external APIs (only when online):**
                  1. **NLM RxNorm:** Only the medication name string you look up to resolve standardized ingredients and RxCUIs.
                  2. **U.S. FDA openFDA:** Only the generic/brand drug name when you click *Fetch supplementary official FDA label excerpt*.
                  3. **Google Gemini API (optional, only if `GEMINI_API_KEY` is set):** Only the two confirmed generic drug names, recorded source severity, and source mechanism text (`store=False`). Personal notes, schedules, and patient identifiers are never sent.
                * **Storage note:** Local SQLite files are standard unencrypted database files protected by your operating system user account permissions.
                """
            )

        with st.container(border=True):
            st.subheader("🧹 Data Control & Reset")
            if is_demo:
                if st.button("🔄 Reset Demo Sample Medications to Default", use_container_width=True):
                    medications.ensure_demo_profile(config.demo_db_path(), force=True)
                    set_flash("✓ Demo sample profile reset to its initial 4 demonstration medications.")
                    st.rerun()

            if st.button("🗑️ Clear all local medication data in current profile", use_container_width=True):
                st.session_state.confirm_clear_all = True
                st.rerun()

            if st.session_state.get("confirm_clear_all"):
                st.warning(
                    "Are you sure you want to delete all medications, schedules, dose logs, "
                    f"and check history in `{db_path.name}`? Loaded interaction datasets will be kept."
                )
                cc1, cc2 = st.columns(2)
                if cc1.button("Yes, delete local medication data", type="primary", use_container_width=True):
                    db.clear_user_data(db_path)
                    st.session_state.pop("confirm_clear_all", None)
                    set_flash("Cleared local medication data.")
                    st.rerun()
                if cc2.button("Cancel", key="cancel_clear_all", use_container_width=True):
                    st.session_state.pop("confirm_clear_all", None)
                    st.rerun()


# --- Main App Render -------------------------------------------------------

ui_theme.inject_theme_css(
    font_size=st.session_state.font_size,
    theme_mode=st.session_state.theme_mode,
    high_contrast=st.session_state.high_contrast,
)
render_sidebar()

current_lang = st.session_state.language
current_demo = st.session_state.demo_mode
current_db = active_db_path()
sec_key = st.session_state.active_section

section_title_map = {
    "overview": t("nav_overview", current_lang),
    "medicines": t("nav_medicines", current_lang),
    "scan": t("nav_scan", current_lang),
    "checker": t("nav_checker", current_lang),
    "schedule": t("nav_schedule", current_lang),
    "reports": t("nav_reports", current_lang),
    "settings": t("nav_settings", current_lang),
}

ui_theme.render_app_header(
    section_title_map.get(sec_key, "MedSafe"),
    language=current_lang,
    is_demo=current_demo,
    theme_mode=st.session_state.theme_mode,
)

render_top_navigation_bar(current_lang)
render_flash()

for prob in STARTUP_PROBLEMS.get("demo" if current_demo else "personal", []):
    st.error(f"Startup dataset notice: {prob}")

if sec_key == "overview":
    render_overview(current_db, current_lang, current_demo)
elif sec_key == "medicines":
    render_my_medicines(current_db, current_lang)
elif sec_key == "scan":
    render_scan_bottle(current_db, current_lang)
elif sec_key == "checker":
    render_safety_checker(current_db, current_lang, current_demo)
elif sec_key == "schedule":
    render_daily_schedule(current_db, current_lang)
elif sec_key == "reports":
    render_caregiver_reports(current_db, current_lang, current_demo)
elif sec_key == "settings":
    render_settings_privacy(current_db, current_lang, current_demo)

st.divider()
st.caption(t("medical_disclaimer", current_lang))
st.caption(f"{drug_data.NLM_ATTRIBUTION} · {drug_data.OPENFDA_ATTRIBUTION}")
