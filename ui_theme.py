"""Design system, accessible stylesheet, and reusable UI card helpers for MedSafe.

Supports 3 senior-accessible appearance modes:
* ``light`` ("☀️ Light Mode — Daylight"): Warm daylight surface (#F4F7FB / #FFFFFF),
  deep navy headings (#142D4C), crisp dark slate text (#0F172A), high-visibility
  input borders (#64748B) and readable placeholders (#5B6B7F).
* ``dark`` ("🌙 Dark Mode — Low Glare"): Soothing slate night surface (#0B132B / #162238),
  crisp off-white text (#F8FAFC), sky-teal headings (#5EEAD4), dark input boxes
  (#0F192A) with bright text (#F8FAFC) and readable silver placeholders (#94A3B8).
* ``high_contrast`` ("👁️ High Contrast — WCAG AAA Low Vision"): Maximum-legibility
  pitch-black surface (#000000 / #070B12), pure white text (#FFFFFF), high-visibility
  yellow headings and borders (#FFD60A), and bold 2.5px outlines for seniors with
  low vision or glare sensitivity.

Never uses green or teal to imply that a missing interaction record means a
medication combination is safe. Every severity and status badge includes
explicit text and shape/symbol labels, never color alone.
"""

from __future__ import annotations

import html
from pathlib import Path

import streamlit as st

import config
from interactions import CheckStatus, PairResult
from medications import MedicationRecord
from translations import (
    category_label,
    check_status_label,
    identity_status_label,
    severity_label,
    t,
)

FONT_SCALE_PX = {
    "standard": 18,
    "large": 20,
    "xlarge": 22,
}

THEME_MODES: dict[str, str] = {
    "light": "☀️ Light Mode (Daylight)",
    "dark": "🌙 Dark Mode (Low Glare)",
    "high_contrast": "👁️ High Contrast (AAA Low Vision)",
}

THEME_DESCRIPTIONS: dict[str, str] = {
    "light": "Warm daylight background with crisp dark text and clear input borders.",
    "dark": "Low-glare dark slate background with bright text for evening or comfortable reading.",
    "high_contrast": (
        "WCAG AAA Low-Vision Mode: Pitch-black background, pure white text, high-visibility "
        "yellow headings, and bold 2.5 px borders for maximum legibility."
    ),
}

_PALETTES: dict[str, dict[str, str]] = {
    "light": {
        "bg": "#F6F8FB",
        "surface": "#FFFFFF",
        "surface_alt": "#EEF3F9",
        "sidebar_bg": "#FFFFFF",
        "heading": "#17324D",
        "text": "#182433",
        "text_muted": "#475569",
        "border": "#CBD5E1",
        "border_strong": "#64748B",
        "border_width": "1.5px",
        "accent": "#0F8B8D",
        "accent_hover": "#17324D",
        "accent_soft": "#E6F6F6",
        "accent_text": "#095C5E",
        "input_bg": "#FFFFFF",
        "input_text": "#182433",
        "input_border": "#64748B",
        "placeholder": "#566579",
        "primary_btn_bg": "#0F8B8D",
        "primary_btn_text": "#FFFFFF",
        "primary_btn_border": "#0C6E70",
        "primary_btn_hover_bg": "#17324D",
        "primary_btn_hover_text": "#FFFFFF",
        "secondary_btn_bg": "#FFFFFF",
        "secondary_btn_text": "#17324D",
        "secondary_btn_border": "#17324D",
        "secondary_btn_hover_bg": "#E6F6F6",
        "amber": "#9A5B00",
        "amber_bg": "#FFF6E5",
        "red": "#B42332",
        "red_bg": "#FDF2F3",
        "neutral_badge_bg": "#E2E8F0",
        "neutral_badge_text": "#182433",
        "neutral_badge_border": "#64748B",
        "shadow": "0 2px 8px rgba(15, 23, 42, 0.06)",
    },
    "dark": {
        "bg": "#0B132B",
        "surface": "#162238",
        "surface_alt": "#1E2D47",
        "sidebar_bg": "#101A2E",
        "heading": "#5EEAD4",
        "text": "#F8FAFC",
        "text_muted": "#CBD5E1",
        "border": "#334155",
        "border_strong": "#64748B",
        "border_width": "1.5px",
        "accent": "#14B8A6",
        "accent_hover": "#2DD4BF",
        "accent_soft": "#133B43",
        "accent_text": "#5EEAD4",
        "input_bg": "#0F172A",
        "input_text": "#F8FAFC",
        "input_border": "#64748B",
        "placeholder": "#94A3B8",
        "primary_btn_bg": "#0D9488",
        "primary_btn_text": "#FFFFFF",
        "primary_btn_border": "#2DD4BF",
        "primary_btn_hover_bg": "#14B8A6",
        "primary_btn_hover_text": "#042F2E",
        "secondary_btn_bg": "#1E293B",
        "secondary_btn_text": "#F8FAFC",
        "secondary_btn_border": "#64748B",
        "secondary_btn_hover_bg": "#334155",
        "amber": "#FBBF24",
        "amber_bg": "#3B280C",
        "red": "#FB7185",
        "red_bg": "#3F1621",
        "neutral_badge_bg": "#1E293B",
        "neutral_badge_text": "#F1F5F9",
        "neutral_badge_border": "#94A3B8",
        "shadow": "0 4px 12px rgba(0, 0, 0, 0.35)",
    },
    "high_contrast": {
        "bg": "#000000",
        "surface": "#070B12",
        "surface_alt": "#111827",
        "sidebar_bg": "#000000",
        "heading": "#FFD60A",
        "text": "#FFFFFF",
        "text_muted": "#E2E8F0",
        "border": "#FFFFFF",
        "border_strong": "#FFD60A",
        "border_width": "2.5px",
        "accent": "#00F5D4",
        "accent_hover": "#FFD60A",
        "accent_soft": "#002B29",
        "accent_text": "#00F5D4",
        "input_bg": "#000000",
        "input_text": "#FFFFFF",
        "input_border": "#FFD60A",
        "placeholder": "#CBD5E1",
        "primary_btn_bg": "#FFD60A",
        "primary_btn_text": "#000000",
        "primary_btn_border": "#FFFFFF",
        "primary_btn_hover_bg": "#00F5D4",
        "primary_btn_hover_text": "#000000",
        "secondary_btn_bg": "#000000",
        "secondary_btn_text": "#FFFFFF",
        "secondary_btn_border": "#FFFFFF",
        "secondary_btn_hover_bg": "#1E293B",
        "amber": "#FFD60A",
        "amber_bg": "#2B2100",
        "red": "#FF6B6B",
        "red_bg": "#330008",
        "neutral_badge_bg": "#000000",
        "neutral_badge_text": "#FFFFFF",
        "neutral_badge_border": "#FFFFFF",
        "shadow": "none",
    },
}


def resolve_theme_mode(theme_mode: str | None = None, *, high_contrast: bool = False) -> str:
    if high_contrast and not theme_mode:
        return "high_contrast"
    clean = (theme_mode or "light").strip().lower()
    if clean in _PALETTES:
        return clean
    return "light"


def inject_theme_css(
    *,
    font_size: str = "standard",
    theme_mode: str | None = None,
    high_contrast: bool = False,
) -> None:
    """Apply MedSafe's scoped design tokens, typography, input visibility fixes,
    and 48x48px senior-friendly touch targets."""
    base_px = FONT_SCALE_PX.get(font_size, 18)
    mode = resolve_theme_mode(theme_mode, high_contrast=high_contrast)
    p = _PALETTES[mode]

    st.markdown(
        f"""
        <style>
        :root {{
            --ms-bg: {p["bg"]};
            --ms-surface: {p["surface"]};
            --ms-surface-alt: {p["surface_alt"]};
            --ms-sidebar-bg: {p["sidebar_bg"]};
            --ms-heading: {p["heading"]};
            --ms-text: {p["text"]};
            --ms-text-muted: {p["text_muted"]};
            --ms-border: {p["border"]};
            --ms-border-strong: {p["border_strong"]};
            --ms-border-width: {p["border_width"]};
            --ms-accent: {p["accent"]};
            --ms-accent-hover: {p["accent_hover"]};
            --ms-accent-soft: {p["accent_soft"]};
            --ms-accent-text: {p["accent_text"]};
            --ms-input-bg: {p["input_bg"]};
            --ms-input-text: {p["input_text"]};
            --ms-input-border: {p["input_border"]};
            --ms-placeholder: {p["placeholder"]};
            --ms-primary-btn-bg: {p["primary_btn_bg"]};
            --ms-primary-btn-text: {p["primary_btn_text"]};
            --ms-primary-btn-border: {p["primary_btn_border"]};
            --ms-primary-btn-hover-bg: {p["primary_btn_hover_bg"]};
            --ms-primary-btn-hover-text: {p["primary_btn_hover_text"]};
            --ms-secondary-btn-bg: {p["secondary_btn_bg"]};
            --ms-secondary-btn-text: {p["secondary_btn_text"]};
            --ms-secondary-btn-border: {p["secondary_btn_border"]};
            --ms-secondary-btn-hover-bg: {p["secondary_btn_hover_bg"]};
            --ms-amber: {p["amber"]};
            --ms-amber-bg: {p["amber_bg"]};
            --ms-red: {p["red"]};
            --ms-red-bg: {p["red_bg"]};
            --ms-neutral-badge-bg: {p["neutral_badge_bg"]};
            --ms-neutral-badge-text: {p["neutral_badge_text"]};
            --ms-neutral-badge-border: {p["neutral_badge_border"]};
            --ms-shadow: {p["shadow"]};
            --ms-base-size: {base_px}px;
        }}

        /* Main app background and typography */
        .stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"] {{
            background-color: var(--ms-bg) !important;
            color: var(--ms-text) !important;
            font-family: "Segoe UI", Inter, -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
            font-size: var(--ms-base-size) !important;
            line-height: 1.6 !important;
        }}

        header[data-testid="stHeader"] {{
            background-color: var(--ms-bg) !important;
            color: var(--ms-text) !important;
        }}

        /* General text elements (excluding buttons so button text color is preserved) */
        .stMarkdown, .stMarkdown p, .stMarkdown li, .stMarkdown span,
        [data-testid="stText"], [data-testid="stCaptionContainer"] p {{
            font-size: var(--ms-base-size) !important;
            line-height: 1.6 !important;
            color: var(--ms-text) !important;
        }}

        [data-testid="stCaptionContainer"] p, .stCaption {{
            color: var(--ms-text-muted) !important;
            font-size: calc(var(--ms-base-size) * 0.9) !important;
        }}

        h1, h2, h3, h4, h5, h6,
        .stMarkdown h1, .stMarkdown h2, .stMarkdown h3, .stMarkdown h4 {{
            color: var(--ms-heading) !important;
            font-weight: 700 !important;
            letter-spacing: -0.01em;
        }}

        /* Sidebar styling */
        section[data-testid="stSidebar"],
        section[data-testid="stSidebar"] > div {{
            background-color: var(--ms-sidebar-bg) !important;
            color: var(--ms-text) !important;
            border-right: var(--ms-border-width) solid var(--ms-border) !important;
        }}

        /* Widget labels, radio options, and checkboxes */
        label,
        [data-testid="stWidgetLabel"] p,
        [data-testid="stWidgetLabel"] span,
        .stRadio label,
        .stRadio div[role="radiogroup"] label p,
        .stRadio div[role="radiogroup"] label span,
        .stCheckbox label p,
        .stCheckbox label span {{
            color: var(--ms-text) !important;
            font-size: var(--ms-base-size) !important;
            font-weight: 600 !important;
            line-height: 1.5 !important;
        }}

        /* =====================================================================
           TEXT INPUTS, TEXTAREAS, DATE/TIME INPUTS & PLACEHOLDERS (HIGH VISIBILITY)
           ===================================================================== */
        div[data-baseweb="input"],
        div[data-baseweb="base-input"],
        div[data-baseweb="textarea"],
        .stTextInput > div > div,
        .stTextArea > div > div,
        .stDateInput > div > div,
        .stTimeInput > div > div,
        .stNumberInput > div > div {{
            background-color: var(--ms-input-bg) !important;
            color: var(--ms-input-text) !important;
            border: var(--ms-border-width) solid var(--ms-input-border) !important;
            border-radius: 10px !important;
            min-height: 48px !important;
        }}

        div[data-baseweb="input"]:focus-within,
        div[data-baseweb="textarea"]:focus-within,
        .stTextInput > div > div:focus-within,
        .stTextArea > div > div:focus-within {{
            border-color: var(--ms-accent) !important;
            box-shadow: 0 0 0 3px var(--ms-accent-soft) !important;
        }}

        .stTextInput input,
        .stTextArea textarea,
        .stDateInput input,
        .stTimeInput input,
        .stNumberInput input,
        div[data-baseweb="input"] input,
        div[data-baseweb="base-input"] input,
        div[data-baseweb="textarea"] textarea {{
            background-color: var(--ms-input-bg) !important;
            color: var(--ms-input-text) !important;
            -webkit-text-fill-color: var(--ms-input-text) !important;
            caret-color: var(--ms-accent) !important;
            font-size: var(--ms-base-size) !important;
            font-weight: 500 !important;
            line-height: 1.5 !important;
            padding: 10px 14px !important;
            opacity: 1 !important;
        }}

        /* Visible Placeholders across all browsers */
        .stTextInput input::placeholder,
        .stTextArea textarea::placeholder,
        div[data-baseweb="input"] input::placeholder,
        div[data-baseweb="textarea"] textarea::placeholder,
        input::-webkit-input-placeholder,
        textarea::-webkit-input-placeholder,
        input::-moz-placeholder,
        textarea::-moz-placeholder {{
            color: var(--ms-placeholder) !important;
            -webkit-text-fill-color: var(--ms-placeholder) !important;
            opacity: 1 !important;
            font-weight: 400 !important;
        }}

        /* Disabled text inputs / textareas (e.g. OCR extracted text box) */
        .stTextInput input:disabled,
        .stTextArea textarea:disabled,
        div[data-baseweb="textarea"] textarea[disabled] {{
            background-color: var(--ms-surface-alt) !important;
            color: var(--ms-text) !important;
            -webkit-text-fill-color: var(--ms-text) !important;
            opacity: 1 !important;
            cursor: default !important;
        }}

        /* =====================================================================
           SELECTBOXES & DROPDOWN MENUS
           ===================================================================== */
        .stSelectbox div[data-baseweb="select"] > div {{
            background-color: var(--ms-input-bg) !important;
            color: var(--ms-input-text) !important;
            border: var(--ms-border-width) solid var(--ms-input-border) !important;
            border-radius: 10px !important;
            min-height: 48px !important;
        }}

        .stSelectbox div[data-baseweb="select"] span,
        .stSelectbox div[data-baseweb="select"] div,
        .stSelectbox div[data-baseweb="select"] input {{
            color: var(--ms-input-text) !important;
            -webkit-text-fill-color: var(--ms-input-text) !important;
            font-size: var(--ms-base-size) !important;
            font-weight: 500 !important;
        }}

        .stSelectbox svg {{
            fill: var(--ms-input-text) !important;
        }}

        /* Dropdown popover menu */
        div[data-baseweb="popover"],
        div[data-baseweb="popover"] > div,
        ul[data-baseweb="menu"],
        div[role="listbox"] {{
            background-color: var(--ms-surface) !important;
            color: var(--ms-text) !important;
            border: var(--ms-border-width) solid var(--ms-border-strong) !important;
            border-radius: 10px !important;
        }}

        li[role="option"],
        li[role="option"] span,
        li[role="option"] div {{
            background-color: transparent !important;
            color: var(--ms-text) !important;
            font-size: var(--ms-base-size) !important;
            padding-top: 6px !important;
            padding-bottom: 6px !important;
        }}

        li[role="option"]:hover,
        li[role="option"][aria-selected="true"] {{
            background-color: var(--ms-accent-soft) !important;
            color: var(--ms-heading) !important;
            font-weight: 700 !important;
        }}

        /* =====================================================================
           CONTAINERS, EXPANDERS, TABS, FILE UPLOADER & CODE BLOCKS
           ===================================================================== */
        [data-testid="stVerticalBlockBorderWrapper"] {{
            background-color: var(--ms-surface) !important;
            border: var(--ms-border-width) solid var(--ms-border) !important;
            border-radius: 14px !important;
            padding: 18px !important;
            box-shadow: var(--ms-shadow);
        }}

        [data-testid="stExpander"],
        details {{
            background-color: var(--ms-surface) !important;
            border: var(--ms-border-width) solid var(--ms-border) !important;
            border-radius: 12px !important;
            overflow: hidden;
        }}

        [data-testid="stExpander"] summary,
        [data-testid="stExpander"] summary p,
        [data-testid="stExpander"] summary span,
        details > summary {{
            background-color: var(--ms-surface-alt) !important;
            color: var(--ms-heading) !important;
            font-weight: 700 !important;
            font-size: calc(var(--ms-base-size) * 1.03) !important;
            padding: 12px 16px !important;
        }}

        [data-testid="stFileUploader"] section {{
            background-color: var(--ms-surface-alt) !important;
            border: 2px dashed var(--ms-border-strong) !important;
            border-radius: 12px !important;
            color: var(--ms-text) !important;
        }}

        .stTabs [data-baseweb="tab-list"] {{
            gap: 8px;
            border-bottom: 2px solid var(--ms-border);
        }}

        .stTabs [data-baseweb="tab"] {{
            min-height: 48px !important;
            padding: 10px 18px !important;
            background-color: var(--ms-surface-alt) !important;
            color: var(--ms-text) !important;
            border-radius: 10px 10px 0 0 !important;
            font-weight: 600 !important;
        }}

        .stTabs [aria-selected="true"] {{
            background-color: var(--ms-primary-btn-bg) !important;
            color: var(--ms-primary-btn-text) !important;
        }}

        .stTabs [aria-selected="true"] p,
        .stTabs [aria-selected="true"] span {{
            color: var(--ms-primary-btn-text) !important;
        }}

        /* =====================================================================
           SENIOR-ACCESSIBLE BUTTONS (>= 48x48px TOUCH TARGETS & CLEAR CONTRAST)
           ===================================================================== */
        .stButton > button,
        .stDownloadButton > button,
        .stFormSubmitButton > button {{
            min-height: 48px !important;
            padding: 0.6rem 1.2rem !important;
            border-radius: 10px !important;
            font-size: var(--ms-base-size) !important;
            font-weight: 700 !important;
            cursor: pointer !important;
            transition: background-color 0.14s ease, border-color 0.14s ease, box-shadow 0.14s ease;
        }}

        /* Primary action buttons */
        .stButton > button[kind="primary"],
        .stFormSubmitButton > button[kind="primary"],
        button[data-testid="stBaseButton-primary"],
        button[data-testid="baseButton-primary"] {{
            background-color: var(--ms-primary-btn-bg) !important;
            border: 2px solid var(--ms-primary-btn-border) !important;
            color: var(--ms-primary-btn-text) !important;
        }}

        .stButton > button[kind="primary"] *,
        .stFormSubmitButton > button[kind="primary"] *,
        button[data-testid="stBaseButton-primary"] *,
        button[data-testid="baseButton-primary"] * {{
            color: var(--ms-primary-btn-text) !important;
            font-weight: 700 !important;
        }}

        .stButton > button[kind="primary"]:hover,
        .stFormSubmitButton > button[kind="primary"]:hover,
        button[data-testid="stBaseButton-primary"]:hover,
        button[data-testid="baseButton-primary"]:hover {{
            background-color: var(--ms-primary-btn-hover-bg) !important;
            border-color: var(--ms-primary-btn-hover-bg) !important;
            color: var(--ms-primary-btn-hover-text) !important;
        }}

        .stButton > button[kind="primary"]:hover *,
        .stFormSubmitButton > button[kind="primary"]:hover *,
        button[data-testid="stBaseButton-primary"]:hover *,
        button[data-testid="baseButton-primary"]:hover * {{
            color: var(--ms-primary-btn-hover-text) !important;
        }}

        /* Secondary action buttons, secondary form submit buttons & download buttons */
        .stButton > button:not([kind="primary"]),
        .stFormSubmitButton > button:not([kind="primary"]),
        .stButton > button[kind="secondary"],
        .stFormSubmitButton > button[kind="secondary"],
        .stDownloadButton > button,
        button[data-testid="stBaseButton-secondary"],
        button[data-testid="stBaseButton-secondaryFormSubmit"],
        button[data-testid="baseButton-secondary"] {{
            background-color: var(--ms-secondary-btn-bg) !important;
            border: 2px solid var(--ms-secondary-btn-border) !important;
            color: var(--ms-secondary-btn-text) !important;
        }}

        .stButton > button:not([kind="primary"]) *,
        .stFormSubmitButton > button:not([kind="primary"]) *,
        .stButton > button[kind="secondary"] *,
        .stFormSubmitButton > button[kind="secondary"] *,
        .stDownloadButton > button *,
        button[data-testid="stBaseButton-secondary"] *,
        button[data-testid="stBaseButton-secondaryFormSubmit"] *,
        button[data-testid="baseButton-secondary"] * {{
            color: var(--ms-secondary-btn-text) !important;
            font-weight: 700 !important;
        }}

        .stButton > button:not([kind="primary"]):hover,
        .stFormSubmitButton > button:not([kind="primary"]):hover,
        .stButton > button[kind="secondary"]:hover,
        .stFormSubmitButton > button[kind="secondary"]:hover,
        .stDownloadButton > button:hover,
        button[data-testid="stBaseButton-secondary"]:hover,
        button[data-testid="stBaseButton-secondaryFormSubmit"]:hover,
        button[data-testid="baseButton-secondary"]:hover {{
            background-color: var(--ms-secondary-btn-hover-bg) !important;
            border-color: var(--ms-accent) !important;
            color: var(--ms-secondary-btn-text) !important;
        }}

        /* Streamlit Alerts (st.info, st.warning, st.error, st.success) — explicit high contrast */
        [data-testid="stAlert"],
        div[role="alert"] {{
            background-color: var(--ms-surface-alt) !important;
            color: var(--ms-text) !important;
            border: var(--ms-border-width) solid var(--ms-border-strong) !important;
            border-radius: 10px !important;
        }}

        [data-testid="stAlert"] p,
        [data-testid="stAlert"] span,
        [data-testid="stAlert"] li,
        div[role="alert"] p,
        div[role="alert"] span {{
            color: var(--ms-text) !important;
            font-weight: 500 !important;
        }}

        /* Keyboard Focus Ring */
        button:focus-visible,
        input:focus-visible,
        textarea:focus-visible,
        select:focus-visible,
        [tabindex]:focus-visible {{
            outline: 3px solid var(--ms-accent) !important;
            outline-offset: 2px !important;
        }}

        /* =====================================================================
           MEDSAFE CUSTOM CARDS & BADGES (100% THEME-AWARE)
           ===================================================================== */
        .ms-header-card {{
            background: var(--ms-surface);
            border: var(--ms-border-width) solid var(--ms-border);
            border-radius: 14px;
            padding: 18px 22px;
            margin-bottom: 14px;
            box-shadow: var(--ms-shadow);
        }}

        .ms-demo-banner {{
            background: var(--ms-amber-bg);
            border: 2px solid var(--ms-amber);
            border-radius: 12px;
            padding: 14px 18px;
            margin-bottom: 16px;
            color: var(--ms-text);
        }}

        .ms-card {{
            background: var(--ms-surface);
            border: var(--ms-border-width) solid var(--ms-border);
            border-radius: 12px;
            padding: 18px 20px;
            margin-bottom: 14px;
            box-shadow: var(--ms-shadow);
            color: var(--ms-text);
        }}

        .ms-card-title {{
            font-size: 1.22em;
            font-weight: 700;
            color: var(--ms-heading);
        }}

        .ms-card-subtitle {{
            color: var(--ms-text-muted);
            font-weight: 600;
        }}

        .ms-card-major {{
            border-left: 7px solid var(--ms-red);
            background: var(--ms-surface);
        }}

        .ms-card-moderate {{
            border-left: 7px solid var(--ms-amber);
            background: var(--ms-surface);
        }}

        .ms-card-minor {{
            border-left: 7px solid var(--ms-heading);
            background: var(--ms-surface);
        }}

        .ms-card-neutral {{
            border-left: 7px solid var(--ms-border-strong);
            background: var(--ms-surface);
        }}

        .ms-stat-box {{
            background: var(--ms-surface);
            border: var(--ms-border-width) solid var(--ms-border);
            border-top: 5px solid var(--ms-accent);
            border-radius: 12px;
            padding: 15px 16px;
            height: 100%;
            box-shadow: var(--ms-shadow);
        }}

        .ms-stat-value {{
            font-size: calc(var(--ms-base-size) * 1.55);
            font-weight: 800;
            color: var(--ms-heading);
            line-height: 1.2;
        }}

        .ms-stat-label {{
            font-size: calc(var(--ms-base-size) * 0.94);
            color: var(--ms-text);
            font-weight: 700;
            margin-top: 6px;
        }}

        .ms-stat-sublabel {{
            font-size: calc(var(--ms-base-size) * 0.84);
            color: var(--ms-text-muted);
            margin-top: 4px;
        }}

        /* Accessible badges with shape + text */
        .ms-badge {{
            display: inline-block;
            padding: 4px 12px;
            border-radius: 999px;
            font-size: calc(var(--ms-base-size) * 0.85);
            font-weight: 700;
            margin-right: 8px;
            margin-bottom: 4px;
            border: 1.5px solid transparent;
        }}

        .ms-badge-major {{
            background: var(--ms-red-bg);
            color: var(--ms-red);
            border-color: var(--ms-red);
        }}

        .ms-badge-moderate {{
            background: var(--ms-amber-bg);
            color: var(--ms-amber);
            border-color: var(--ms-amber);
        }}

        .ms-badge-minor, .ms-badge-neutral {{
            background: var(--ms-neutral-badge-bg);
            color: var(--ms-neutral-badge-text);
            border-color: var(--ms-neutral-badge-border);
        }}

        .ms-badge-teal {{
            background: var(--ms-accent-soft);
            color: var(--ms-accent-text);
            border-color: var(--ms-accent);
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _inline_logo_svg(theme_mode: str = "light") -> str:
    logo_path: Path = config.ASSETS_DIR / "logo.svg"
    if logo_path.exists():
        svg = logo_path.read_text(encoding="utf-8")
        if theme_mode == "dark":
            svg = svg.replace("#17324D", "#F8FAFC").replace("#566579", "#CBD5E1")
        elif theme_mode == "high_contrast":
            svg = (
                svg.replace("#17324D", "#FFD60A")
                .replace("#0F8B8D", "#00F5D4")
                .replace("#566579", "#FFFFFF")
            )
        return svg
    return "<strong>MedSafe</strong>"


def render_app_header(
    section_title: str,
    *,
    language: str = "English",
    is_demo: bool = False,
    theme_mode: str = "light",
) -> None:
    """Render the consistent top branding header with section title, local-first
    privacy indicator, and obvious DEMO indicator when sample data is active."""
    svg = _inline_logo_svg(theme_mode)
    sec_escaped = html.escape(section_title)
    privacy_text = html.escape(t("privacy_badge_local", language))
    demo_pill = (
        f'<span class="ms-badge ms-badge-moderate" role="status">'
        f'[DEMO] {html.escape(t("demo_badge", language))}</span>'
        if is_demo
        else '<span class="ms-badge ms-badge-teal" role="status">[PERSONAL] Local Profile</span>'
    )
    st.markdown(
        f"""
        <div class="ms-header-card" role="banner">
            <div style="display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:12px;">
                <div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap;">
                    <div style="width:210px;max-width:100%;">{svg}</div>
                    <div style="border-left:2px solid var(--ms-border);padding-left:14px;">
                        <div class="ms-card-title">{sec_escaped}</div>
                        <div class="ms-card-subtitle" style="font-size:0.9em;">&#128274; {privacy_text}</div>
                    </div>
                </div>
                <div>{demo_pill}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if is_demo:
        st.markdown(
            f"""
            <div class="ms-demo-banner" role="region" aria-label="Demonstration mode notice">
                <strong>[DEMO] {html.escape(t("demo_badge", language))}:</strong>
                {html.escape(t("demo_banner_text", language))}
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_stat_card(value: str | int, label: str, sublabel: str = "") -> None:
    val_esc = html.escape(str(value))
    lbl_esc = html.escape(label)
    sub_html = (
        f'<div class="ms-stat-sublabel">{html.escape(sublabel)}</div>'
        if sublabel
        else ""
    )
    st.markdown(
        f"""
        <div class="ms-stat-box">
            <div class="ms-stat-value">{val_esc}</div>
            <div class="ms-stat-label">{lbl_esc}</div>
            {sub_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def severity_badge_html(severity_level: str, severity_raw: str | None, language: str = "English") -> str:
    lvl = (severity_level or "unspecified").lower()
    css_cls = {
        "major": "ms-badge-major",
        "moderate": "ms-badge-moderate",
        "minor": "ms-badge-minor",
        "unspecified": "ms-badge-neutral",
    }.get(lvl, "ms-badge-neutral")
    symbol = {
        "major": "[!]",
        "moderate": "[▲]",
        "minor": "[•]",
        "unspecified": "[?]",
    }.get(lvl, "[?]")
    label = severity_label(lvl, language)
    if severity_raw and severity_raw.lower() != lvl:
        label = f"{label} (raw: {severity_raw})"
    return f'<span class="ms-badge {css_cls}">{html.escape(symbol)} {html.escape(label)}</span>'


def status_badge_html(status: CheckStatus, language: str = "English") -> str:
    label = check_status_label(status.value, language)
    if status == CheckStatus.MATCH_FOUND:
        cls, sym = "ms-badge-major", "[RECORD FOUND]"
    elif status == CheckStatus.NO_MATCHING_RECORD:
        # Neutral slate/navy — NEVER green "SAFE"
        cls, sym = "ms-badge-neutral", "[NO RECORD IN DATASET]"
    else:
        cls, sym = "ms-badge-moderate", "[INCOMPLETE CHECK]"
    return f'<span class="ms-badge {cls}">{html.escape(sym)} {html.escape(label)}</span>'


def render_medication_card_header(med: MedicationRecord, language: str = "English") -> None:
    """Render a clean, high-contrast summary header for one medication."""
    id_badge_cls = {
        "confirmed": "ms-badge-teal",
        "needs_review": "ms-badge-moderate",
        "unidentified": "ms-badge-major",
    }.get(med.identity_status, "ms-badge-neutral")
    id_symbol = {
        "confirmed": "[✓]",
        "needs_review": "[▲]",
        "unidentified": "[!]",
    }.get(med.identity_status, "[?]")
    id_text = identity_status_label(med.identity_status, language)
    cat_text = category_label(med.category, language)
    src_badge = (
        '<span class="ms-badge ms-badge-moderate">[DEMO] Demo sample</span>'
        if med.entry_source == "demo"
        else f'<span class="ms-badge ms-badge-neutral">Source: {html.escape(med.entry_source)}</span>'
    )
    active_badge = (
        ""
        if med.active
        else '<span class="ms-badge ms-badge-neutral">[INACTIVE] Past / paused medicine</span>'
    )

    meta_parts = [p for p in (med.strength, med.dose_form, med.route) if p]
    meta_line = " · ".join(meta_parts) if meta_parts else "Strength / form not recorded"
    ings = " + ".join(i.name for i in med.ingredients) if med.ingredients else "Not yet identified"
    rxcui_part = f" (RxCUI: {med.rxcui})" if med.rxcui else ""
    sched_line = (
        ", ".join(s.display_time for s in med.schedule)
        if med.schedule
        else "No reminder time set"
    )
    instr_line = med.instructions or "No directions entered"

    st.markdown(
        f"""
        <div class="ms-card">
            <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:8px;">
                <div>
                    <span class="ms-card-title">
                        {html.escape(med.display_name)}
                    </span>
                    <span class="ms-card-subtitle" style="margin-left:8px;">
                        {html.escape(meta_line)}
                    </span>
                </div>
                <div>
                    <span class="ms-badge {id_badge_cls}">{html.escape(id_symbol)} {html.escape(id_text)}</span>
                    <span class="ms-badge ms-badge-neutral">{html.escape(cat_text)}</span>
                    {src_badge}
                    {active_badge}
                </div>
            </div>
            <div style="margin-top:8px;color:var(--ms-text);">
                <strong>Active ingredient(s):</strong> {html.escape(ings)}{html.escape(rxcui_part)}
                &nbsp;|&nbsp; <strong>Schedule:</strong> {html.escape(sched_line)}
            </div>
            <div style="margin-top:4px;color:var(--ms-text-muted);">
                <strong>User-entered directions:</strong> {html.escape(instr_line)}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def pair_card_border_class(pair: PairResult) -> str:
    if pair.status == CheckStatus.MATCH_FOUND:
        sev = pair.top_severity or "unspecified"
        if sev == "major":
            return "ms-card-major"
        if sev == "moderate":
            return "ms-card-moderate"
        return "ms-card-minor"
    if pair.status == CheckStatus.NO_MATCHING_RECORD:
        return "ms-card-neutral"
    return "ms-card-moderate"


def render_lasa_warning_card(lasa: dict[str, str]) -> None:
    """Render an FDA / ISMP Look-Alike / Sound-Alike (LASA) confusion guard card
    with Tall-Man Lettering so seniors can double-check similar-looking drug names."""
    tall_man = html.escape(lasa.get("tall_man", ""))
    purpose = html.escape(lasa.get("purpose", ""))
    confused_tm = html.escape(lasa.get("confused_tall_man", ""))
    confused_purpose = html.escape(lasa.get("confused_purpose", ""))
    st.markdown(
        f"""
        <div class="ms-card ms-card-moderate" role="region" aria-label="Look-alike medication name safety check">
            <div style="margin-bottom:6px;">
                <span class="ms-badge ms-badge-moderate">[▲] Look-Alike Name Double-Check (FDA / ISMP Tall-Man Lettering)</span>
            </div>
            <div style="color:var(--ms-text);line-height:1.6;">
                Please double-check the spelling on your bottle label:<br/>
                &bull; <strong><code>{tall_man}</code></strong> — {purpose}<br/>
                &bull; Do not confuse with <strong><code>{confused_tm}</code></strong> — {confused_purpose}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

