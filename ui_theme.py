"""Clinical-grade design system, human-factors stylesheet, and NHS/Apple Health
UI components for MedSafe.

Engineered against clinical human-factors standards:
* **Typography**: Braille Institute's ``Atkinson Hyperlegible`` fixed at >= 19px
  (1.1875rem, line-height 1.6) for medication names, dosages, schedules, and
  clinical warnings to eliminate ``0``/``O`` and ``1``/``l``/``I`` character
  recognition errors; ``Plus Jakarta Sans`` (600 semi-bold) for structural
  headers; ``JetBrains Mono`` (``tabular-nums``) for RxCUI, NDC, and lot codes.
* **Strict Anti-Vibecoding Geometry**: Zero purple/indigo gradients, zero neon
  glows, and strictly 2 border-radius tokens (``6px`` for inner inputs/badges/
  buttons and ``10px`` for structural cards) with ``cubic-bezier(0.22, 1, 0.36, 1)``
  transitions and subtle ``2px`` max hover lift.
* **Clinical Palette**: Stark white ``#FFFFFF`` primary surface, near-black
  ``#111111`` primary text, soft slate ``#575B5F`` secondary labels, single
  clinical blue ``#1A73E8`` accent, semantic warning red ``#D93025``, caution
  amber ``#FA903E``, and verified identity green ``#23AE48`` on ``#E6FAEB``.
* **Safety Invariant**: Never uses green to imply that a missing interaction
  record means a medication combination is "safe". Every severity and status
  badge includes explicit text and shape/symbol labels, never color alone.
"""

from __future__ import annotations

import html
from pathlib import Path
from typing import Iterable

import streamlit as st


def html_markdown(block: str) -> None:
    """Render an HTML fragment via st.markdown with indentation stripped.

    Markdown treats lines indented by 4+ spaces as code blocks, so indented
    triple-quoted HTML can render as raw source. Stripping per-line leading
    whitespace (harmless for HTML) prevents that entire bug class.
    """
    cleaned = "\n".join(l.strip() for l in block.splitlines() if l.strip())
    st.markdown(cleaned, unsafe_allow_html=True)


import config
from interactions import CheckReport, CheckStatus, PairResult
from medications import MedicationRecord
from tall_man_lettering import get_tall_man_display_name, render_tall_man_html
from translations import (
    category_label,
    check_status_label,
    identity_status_label,
    severity_label,
    t,
)

# Minimum 19px (1.1875rem) clinical body typography standard
FONT_SCALE_PX = {
    "standard": 19,
    "large": 21,
    "xlarge": 24,
}

THEME_MODES: dict[str, str] = {
    "light": "☀️ Light",
    "dark": "🌙 Dark",
    "high_contrast": "👁️ High contrast",
}

THEME_DESCRIPTIONS: dict[str, str] = {
    "light": "Bright background with dark text — best for daytime.",
    "dark": "Dark background with light text — easier on the eyes at night.",
    "high_contrast": "Black background, white text, extra-bold outlines — best for low vision.",
}

_PALETTES: dict[str, dict[str, str]] = {
    "light": {
        "bg": "#F8FAFC",
        "surface": "#FFFFFF",
        "surface_alt": "#F1F5F9",
        "sidebar_bg": "#FFFFFF",
        "heading": "#111111",
        "text": "#111111",
        "text_muted": "#575B5F",
        "border": "#D0D7DE",
        "border_strong": "#575B5F",
        "border_width": "1.5px",
        "accent": "#1A73E8",
        "accent_hover": "#1557B0",
        "accent_soft": "#E8F0FE",
        "accent_text": "#1557B0",
        "input_bg": "#FFFFFF",
        "input_text": "#111111",
        "input_border": "#575B5F",
        "placeholder": "#575B5F",
        "primary_btn_bg": "#1A73E8",
        "primary_btn_text": "#FFFFFF",
        "primary_btn_border": "#1557B0",
        "primary_btn_hover_bg": "#1557B0",
        "primary_btn_hover_text": "#FFFFFF",
        "secondary_btn_bg": "#FFFFFF",
        "secondary_btn_text": "#111111",
        "secondary_btn_border": "#575B5F",
        "secondary_btn_hover_bg": "#E8F0FE",
        "amber": "#8A3B00",
        "amber_border": "#FA903E",
        "amber_bg": "#FEF3E8",
        "red": "#D93025",
        "red_bg": "#FCE8E6",
        "safe_green": "#23AE48",
        "safe_green_text": "#136528",
        "safe_green_bg": "#E6FAEB",
        "neutral_badge_bg": "#EEF2F6",
        "neutral_badge_text": "#111111",
        "neutral_badge_border": "#575B5F",
        "shadow": "0 1px 3px rgba(17, 17, 17, 0.06)",
    },
    "dark": {
        "bg": "#111111",
        "surface": "#1A1D21",
        "surface_alt": "#24292F",
        "sidebar_bg": "#16191D",
        "heading": "#FFFFFF",
        "text": "#F8FAFC",
        "text_muted": "#B0B7C3",
        "border": "#374151",
        "border_strong": "#8B949E",
        "border_width": "1.5px",
        "accent": "#4C9AFF",
        "accent_hover": "#66B2FF",
        "accent_soft": "#172B4D",
        "accent_text": "#85B8FF",
        "input_bg": "#111111",
        "input_text": "#FFFFFF",
        "input_border": "#8B949E",
        "placeholder": "#9CA3AF",
        "primary_btn_bg": "#1A73E8",
        "primary_btn_text": "#FFFFFF",
        "primary_btn_border": "#4C9AFF",
        "primary_btn_hover_bg": "#4C9AFF",
        "primary_btn_hover_text": "#111111",
        "secondary_btn_bg": "#24292F",
        "secondary_btn_text": "#FFFFFF",
        "secondary_btn_border": "#8B949E",
        "secondary_btn_hover_bg": "#374151",
        "amber": "#FDBA74",
        "amber_border": "#FA903E",
        "amber_bg": "#3B230E",
        "red": "#F87171",
        "red_bg": "#3F1515",
        "safe_green": "#23AE48",
        "safe_green_text": "#86EFAC",
        "safe_green_bg": "#0F2E1A",
        "neutral_badge_bg": "#24292F",
        "neutral_badge_text": "#F8FAFC",
        "neutral_badge_border": "#8B949E",
        "shadow": "0 2px 6px rgba(0, 0, 0, 0.35)",
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
        "accent": "#4CC9F0",
        "accent_hover": "#FFD60A",
        "accent_soft": "#001D3D",
        "accent_text": "#4CC9F0",
        "input_bg": "#000000",
        "input_text": "#FFFFFF",
        "input_border": "#FFD60A",
        "placeholder": "#CBD5E1",
        "primary_btn_bg": "#FFD60A",
        "primary_btn_text": "#000000",
        "primary_btn_border": "#FFFFFF",
        "primary_btn_hover_bg": "#4CC9F0",
        "primary_btn_hover_text": "#000000",
        "secondary_btn_bg": "#000000",
        "secondary_btn_text": "#FFFFFF",
        "secondary_btn_border": "#FFFFFF",
        "secondary_btn_hover_bg": "#1E293B",
        "amber": "#FFD60A",
        "amber_border": "#FFD60A",
        "amber_bg": "#2B2100",
        "red": "#FF6B6B",
        "red_bg": "#330008",
        "safe_green": "#4ADE80",
        "safe_green_text": "#4ADE80",
        "safe_green_bg": "#002B11",
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
    """Apply MedSafe's clinical human-factors stylesheet:
    * Atkinson Hyperlegible (>= 19px, line-height 1.6) + Plus Jakarta Sans (600)
      + JetBrains Mono (tabular-nums).
    * Strictly 2 border-radius tokens (6px for inner inputs/badges/buttons,
      10px for structural cards).
    * Cubic-bezier(0.22, 1, 0.36, 1) micro-interactions with max 2px hover lift.
    * Generous 24px-28px internal card padding and >= 48x48px touch targets.
    """
    base_px = FONT_SCALE_PX.get(font_size, 19)
    mode = resolve_theme_mode(theme_mode, high_contrast=high_contrast)
    p = _PALETTES[mode]

    html_markdown(f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible:ital,wght@0,400;0,700;1,400;1,700&family=JetBrains+Mono:wght@400;600&family=Plus+Jakarta+Sans:wght@500;600;700&display=swap');

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
            --ms-amber-border: {p["amber_border"]};
            --ms-amber-bg: {p["amber_bg"]};
            --ms-red: {p["red"]};
            --ms-red-bg: {p["red_bg"]};
            --ms-safe-green: {p["safe_green"]};
            --ms-safe-green-text: {p["safe_green_text"]};
            --ms-safe-green-bg: {p["safe_green_bg"]};
            --ms-neutral-badge-bg: {p["neutral_badge_bg"]};
            --ms-neutral-badge-text: {p["neutral_badge_text"]};
            --ms-neutral-badge-border: {p["neutral_badge_border"]};
            --ms-shadow: {p["shadow"]};
            --ms-base-size: {base_px}px;
            --ms-radius-sm: 6px;
            --ms-radius-lg: 10px;
            --ms-ease: cubic-bezier(0.22, 1, 0.36, 1);
            --ms-font-clinical: "Atkinson Hyperlegible", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            --ms-font-heading: "Plus Jakarta Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            --ms-font-mono: "JetBrains Mono", Consolas, "Courier New", monospace;
        }}

        /* Main app background and Atkinson Hyperlegible clinical body typography */
        .stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"] {{
            background-color: var(--ms-bg) !important;
            color: var(--ms-text) !important;
            font-family: var(--ms-font-clinical) !important;
            font-size: var(--ms-base-size) !important;
            font-weight: 400 !important;
            line-height: 1.6 !important;
        }}

        header[data-testid="stHeader"] {{
            background-color: var(--ms-bg) !important;
            color: var(--ms-text) !important;
        }}

        /* General text elements (excluding buttons so button text color is preserved) */
        .stMarkdown, .stMarkdown p, .stMarkdown li, .stMarkdown span,
        [data-testid="stText"], [data-testid="stCaptionContainer"] p {{
            font-family: var(--ms-font-clinical) !important;
            font-size: var(--ms-base-size) !important;
            line-height: 1.6 !important;
            color: var(--ms-text) !important;
        }}

        [data-testid="stCaptionContainer"] p, .stCaption {{
            color: var(--ms-text-muted) !important;
            font-size: calc(var(--ms-base-size) * 0.92) !important;
        }}

        /* Structural navigation & section headers: Plus Jakarta Sans 600 semi-bold */
        h1, h2, h3, h4, h5, h6,
        .stMarkdown h1, .stMarkdown h2, .stMarkdown h3, .stMarkdown h4 {{
            font-family: var(--ms-font-heading) !important;
            color: var(--ms-heading) !important;
            font-weight: 600 !important;
            letter-spacing: -0.015em;
            line-height: 1.35 !important;
        }}

        /* Monospace identifiers (RxCUI, NDC, lot numbers) with tabular-nums */
        code, .ms-mono-code {{
            font-family: var(--ms-font-mono) !important;
            font-variant-numeric: tabular-nums !important;
            text-transform: none !important;
            font-size: 0.94em;
        }}

        /* Tall Man Lettering preservation: never flatten casing or truncate */
        .ms-tall-man-name {{
            font-family: var(--ms-font-clinical) !important;
            text-transform: none !important;
            white-space: normal !important;
            overflow: visible !important;
            text-overflow: clip !important;
            letter-spacing: 0.01em;
        }}

        .ms-tall-man-upper {{
            font-weight: 700 !important;
            text-transform: none !important;
            text-decoration: underline;
            text-decoration-thickness: 1.5px;
            text-underline-offset: 3px;
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
            font-family: var(--ms-font-clinical) !important;
            color: var(--ms-text) !important;
            font-size: var(--ms-base-size) !important;
            font-weight: 600 !important;
            line-height: 1.5 !important;
            text-transform: none !important;
        }}

        /* =====================================================================
           TEXT INPUTS, TEXTAREAS, DATE/TIME INPUTS & PLACEHOLDERS (6px RADIUS)
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
            border-radius: var(--ms-radius-sm) !important;
            min-height: 48px !important;
            transition: border-color 0.18s var(--ms-ease), box-shadow 0.18s var(--ms-ease);
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
            font-family: var(--ms-font-clinical) !important;
            background-color: var(--ms-input-bg) !important;
            color: var(--ms-input-text) !important;
            -webkit-text-fill-color: var(--ms-input-text) !important;
            caret-color: var(--ms-accent) !important;
            font-size: var(--ms-base-size) !important;
            font-weight: 400 !important;
            line-height: 1.5 !important;
            padding: 10px 14px !important;
            opacity: 1 !important;
            text-transform: none !important;
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
           SELECTBOXES & DROPDOWN MENUS (PRESERVING TALL MAN CASE)
           ===================================================================== */
        .stSelectbox div[data-baseweb="select"] > div {{
            background-color: var(--ms-input-bg) !important;
            color: var(--ms-input-text) !important;
            border: var(--ms-border-width) solid var(--ms-input-border) !important;
            border-radius: var(--ms-radius-sm) !important;
            min-height: 48px !important;
        }}

        .stSelectbox div[data-baseweb="select"] span,
        .stSelectbox div[data-baseweb="select"] div,
        .stSelectbox div[data-baseweb="select"] input {{
            font-family: var(--ms-font-clinical) !important;
            color: var(--ms-input-text) !important;
            -webkit-text-fill-color: var(--ms-input-text) !important;
            font-size: var(--ms-base-size) !important;
            font-weight: 400 !important;
            text-transform: none !important;
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
            border-radius: var(--ms-radius-lg) !important;
        }}

        li[role="option"],
        li[role="option"] span,
        li[role="option"] div {{
            font-family: var(--ms-font-clinical) !important;
            background-color: transparent !important;
            color: var(--ms-text) !important;
            font-size: var(--ms-base-size) !important;
            padding-top: 6px !important;
            padding-bottom: 6px !important;
            text-transform: none !important;
        }}

        li[role="option"]:hover,
        li[role="option"][aria-selected="true"] {{
            background-color: var(--ms-accent-soft) !important;
            color: var(--ms-heading) !important;
            font-weight: 700 !important;
        }}

        /* =====================================================================
           CONTAINERS, EXPANDERS, TABS & FILE UPLOADER (10px CARD RADIUS, 24px PAD)
           ===================================================================== */
        [data-testid="stVerticalBlockBorderWrapper"] {{
            background-color: var(--ms-surface) !important;
            border: var(--ms-border-width) solid var(--ms-border) !important;
            border-radius: var(--ms-radius-lg) !important;
            padding: 24px 28px !important;
            box-shadow: var(--ms-shadow);
        }}

        [data-testid="stExpander"],
        details {{
            background-color: var(--ms-surface) !important;
            border: var(--ms-border-width) solid var(--ms-border) !important;
            border-radius: var(--ms-radius-lg) !important;
            overflow: hidden;
        }}

        [data-testid="stExpander"] summary,
        [data-testid="stExpander"] summary p,
        [data-testid="stExpander"] summary span,
        details > summary {{
            font-family: var(--ms-font-heading) !important;
            background-color: var(--ms-surface-alt) !important;
            color: var(--ms-heading) !important;
            font-weight: 600 !important;
            font-size: calc(var(--ms-base-size) * 1.02) !important;
            padding: 14px 20px !important;
        }}

        [data-testid="stFileUploader"] section {{
            background-color: var(--ms-surface-alt) !important;
            border: 2px dashed var(--ms-border-strong) !important;
            border-radius: var(--ms-radius-lg) !important;
            padding: 24px !important;
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
            border-radius: var(--ms-radius-sm) !important;
            font-family: var(--ms-font-heading) !important;
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
           APPLE HEALTH CLEAR-SPACE & CLINICAL BUTTONS (6px RADIUS, 2px MAX LIFT)
           ===================================================================== */
        .stButton,
        .stDownloadButton,
        .stFormSubmitButton {{
            margin-top: 6px !important;
            margin-bottom: 6px !important;
        }}

        .stButton > button,
        .stDownloadButton > button,
        .stFormSubmitButton > button {{
            min-height: 48px !important;
            padding: 0.65rem 1.25rem !important;
            border-radius: var(--ms-radius-sm) !important;
            font-family: var(--ms-font-heading) !important;
            font-size: var(--ms-base-size) !important;
            font-weight: 600 !important;
            cursor: pointer !important;
            text-transform: none !important;
            transition: background-color 0.18s var(--ms-ease),
                        border-color 0.18s var(--ms-ease),
                        transform 0.18s var(--ms-ease),
                        box-shadow 0.18s var(--ms-ease);
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
            font-weight: 600 !important;
        }}

        .stButton > button[kind="primary"]:hover,
        .stFormSubmitButton > button[kind="primary"]:hover,
        button[data-testid="stBaseButton-primary"]:hover,
        button[data-testid="baseButton-primary"]:hover {{
            background-color: var(--ms-primary-btn-hover-bg) !important;
            border-color: var(--ms-primary-btn-hover-bg) !important;
            color: var(--ms-primary-btn-hover-text) !important;
            transform: translateY(-2px);
        }}

        .stButton > button[kind="primary"]:hover *,
        .stFormSubmitButton > button[kind="primary"]:hover *,
        button[data-testid="stBaseButton-primary"]:hover *,
        button[data-testid="baseButton-primary"]:hover * {{
            color: var(--ms-primary-btn-hover-text) !important;
        }}

        /* Secondary action buttons */
        .stButton > button:not([kind="primary"]),
        .stFormSubmitButton > button:not([kind="primary"]),
        .stButton > button[kind="secondary"],
        .stFormSubmitButton > button[kind="secondary"],
        .stDownloadButton > button,
        button[data-testid="stBaseButton-secondary"],
        button[data-testid="stBaseButton-secondaryFormSubmit"],
        button[data-testid="baseButton-secondary"] {{
            background-color: var(--ms-secondary-btn-bg) !important;
            border: 1.5px solid var(--ms-secondary-btn-border) !important;
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
            font-weight: 600 !important;
        }}

        .stButton > button:not([kind="primary"]):hover,
        .stFormSubmitButton > button:not([kind="primary"]):hover,
        .stButton > button[kind="secondary"]):hover,
        .stFormSubmitButton > button[kind="secondary"]:hover,
        .stDownloadButton > button:hover,
        button[data-testid="stBaseButton-secondary"]:hover,
        button[data-testid="stBaseButton-secondaryFormSubmit"]:hover,
        button[data-testid="baseButton-secondary"]:hover {{
            background-color: var(--ms-secondary-btn-hover-bg) !important;
            border-color: var(--ms-accent) !important;
            color: var(--ms-secondary-btn-text) !important;
            transform: translateY(-2px);
        }}

        /* Streamlit Alerts — explicit high contrast */
        [data-testid="stAlert"],
        div[role="alert"] {{
            background-color: var(--ms-surface-alt) !important;
            color: var(--ms-text) !important;
            border: var(--ms-border-width) solid var(--ms-border-strong) !important;
            border-radius: var(--ms-radius-lg) !important;
        }}

        [data-testid="stAlert"] p,
        [data-testid="stAlert"] span,
        [data-testid="stAlert"] li,
        div[role="alert"] p,
        div[role="alert"] span {{
            color: var(--ms-text) !important;
            font-weight: 400 !important;
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
           NHS DIGITAL PRIMARY CARDS, SECONDARY CARDS & WARNING CALLOUTS
           ===================================================================== */
        .ms-header-card {{
            background: var(--ms-surface);
            border: var(--ms-border-width) solid var(--ms-border);
            border-radius: var(--ms-radius-lg);
            padding: 24px 28px;
            margin-bottom: 18px;
            box-shadow: var(--ms-shadow);
        }}

        .ms-demo-banner {{
            background: var(--ms-amber-bg);
            border: 1.5px solid var(--ms-amber-border);
            border-left: 4px solid var(--ms-amber-border);
            border-radius: var(--ms-radius-lg);
            padding: 16px 22px;
            margin-bottom: 18px;
            color: var(--ms-text);
        }}

        /* NHS Primary Card (Active Daily Regimens & Immediate Dosing Controls) */
        .ms-card, .ms-primary-card {{
            background: var(--ms-surface);
            border: var(--ms-border-width) solid var(--ms-border);
            border-radius: var(--ms-radius-lg);
            padding: 24px 28px;
            margin-bottom: 16px;
            box-shadow: var(--ms-shadow);
            color: var(--ms-text);
            transition: border-color 0.18s var(--ms-ease), transform 0.18s var(--ms-ease);
        }}

        /* NHS Secondary Card (Historical Logs, Recalls, Shortages, Metadata) */
        .ms-secondary-card {{
            background: var(--ms-surface-alt);
            border: 1px solid var(--ms-border);
            border-radius: var(--ms-radius-lg);
            padding: 22px 26px;
            margin-bottom: 14px;
            color: var(--ms-text);
        }}

        .ms-card-title {{
            font-family: var(--ms-font-heading);
            font-size: 1.2em;
            font-weight: 600;
            color: var(--ms-heading);
        }}

        .ms-card-subtitle {{
            color: var(--ms-text-muted);
            font-weight: 400;
        }}

        /* NHS Warning Callout (4px solid semantic left border + SPL evidence drawer) */
        .ms-nhs-callout {{
            background: var(--ms-surface);
            border: 1px solid var(--ms-border);
            border-left: 4px solid var(--ms-red);
            border-radius: var(--ms-radius-lg);
            padding: 24px 28px;
            margin-bottom: 16px;
            box-shadow: var(--ms-shadow);
            color: var(--ms-text);
        }}

        .ms-nhs-callout-amber {{
            border-left: 4px solid var(--ms-amber-border);
        }}

        .ms-nhs-callout-blue {{
            border-left: 4px solid var(--ms-accent);
        }}

        .ms-card-major {{
            border-left: 4px solid var(--ms-red);
            background: var(--ms-surface);
        }}

        .ms-card-moderate {{
            border-left: 4px solid var(--ms-amber-border);
            background: var(--ms-surface);
        }}

        .ms-card-minor {{
            border-left: 4px solid var(--ms-accent);
            background: var(--ms-surface);
        }}

        .ms-card-neutral {{
            border-left: 4px solid var(--ms-border-strong);
            background: var(--ms-surface);
        }}

        .ms-stat-box {{
            background: var(--ms-surface);
            border: var(--ms-border-width) solid var(--ms-border);
            border-top: 4px solid var(--ms-accent);
            border-radius: var(--ms-radius-lg);
            padding: 22px 24px;
            height: 100%;
            box-shadow: var(--ms-shadow);
        }}

        .ms-stat-value {{
            font-family: var(--ms-font-heading);
            font-variant-numeric: tabular-nums;
            font-size: calc(var(--ms-base-size) * 1.55);
            font-weight: 700;
            color: var(--ms-heading);
            line-height: 1.2;
        }}

        .ms-stat-label {{
            font-family: var(--ms-font-heading);
            font-size: calc(var(--ms-base-size) * 0.96);
            color: var(--ms-text);
            font-weight: 600;
            margin-top: 6px;
        }}

        .ms-stat-sublabel {{
            font-size: calc(var(--ms-base-size) * 0.86);
            color: var(--ms-text-muted);
            margin-top: 4px;
        }}

        /* Accessible badges with 6px radius + shape + text */
        .ms-badge {{
            display: inline-block;
            padding: 4px 10px;
            border-radius: var(--ms-radius-sm);
            font-family: var(--ms-font-heading);
            font-size: calc(var(--ms-base-size) * 0.82);
            font-weight: 600;
            margin-right: 8px;
            margin-bottom: 4px;
            border: 1.5px solid transparent;
            text-transform: none !important;
        }}

        .ms-badge-major {{
            background: var(--ms-red-bg);
            color: var(--ms-red);
            border-color: var(--ms-red);
            font-weight: 700;
        }}

        .ms-badge-moderate {{
            background: var(--ms-amber-bg);
            color: var(--ms-amber);
            border-color: var(--ms-amber-border);
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

        .ms-badge-verified {{
            background: var(--ms-safe-green-bg);
            color: var(--ms-safe-green-text);
            border-color: var(--ms-safe-green);
        }}

        /* Expandable FDA SPL Evidence Drawer inside NHS Warning Callouts */
        details.ms-spl-drawer {{
            margin-top: 12px;
            background: var(--ms-surface-alt) !important;
            border: 1px solid var(--ms-border) !important;
            border-radius: var(--ms-radius-sm) !important;
            padding: 0 !important;
        }}

        details.ms-spl-drawer > summary {{
            cursor: pointer;
            padding: 10px 14px !important;
            font-size: calc(var(--ms-base-size) * 0.92) !important;
            font-weight: 600 !important;
            color: var(--ms-accent-text) !important;
            background: var(--ms-surface-alt) !important;
        }}

        .ms-spl-drawer-body {{
            padding: 14px 18px;
            border-top: 1px solid var(--ms-border);
            font-size: calc(var(--ms-base-size) * 0.94);
            line-height: 1.6;
            color: var(--ms-text);
        }}

        /* Interactive Polypharmacy Matrix Table */
        .ms-matrix-table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 10px;
            margin-bottom: 16px;
            background: var(--ms-surface);
            border: 1px solid var(--ms-border);
            border-radius: var(--ms-radius-lg);
            overflow: hidden;
        }}

        .ms-matrix-table th,
        .ms-matrix-table td {{
            border: 1px solid var(--ms-border);
            padding: 12px 14px;
            text-align: left;
            vertical-align: top;
            font-size: calc(var(--ms-base-size) * 0.92);
        }}

        .ms-matrix-table th {{
            background: var(--ms-surface-alt);
            font-family: var(--ms-font-heading);
            font-weight: 600;
            color: var(--ms-heading);
        }}

        /* Skeleton Shimmer Loader */
        @keyframes ms-shimmer {{
            0% {{ background-position: -400px 0; }}
            100% {{ background-position: 400px 0; }}
        }}

        .ms-skeleton-line {{
            height: 18px;
            margin-bottom: 10px;
            border-radius: var(--ms-radius-sm);
            background: var(--ms-surface-alt);
            background-image: linear-gradient(
                90deg,
                var(--ms-surface-alt) 0px,
                var(--ms-border) 80px,
                var(--ms-surface-alt) 160px
            );
            background-size: 600px 100%;
            animation: ms-shimmer 1.4s infinite linear;
        }}

        /* Clinical Governance & Apple Health Privacy Footer */
        .ms-clinical-footer {{
            background: var(--ms-surface-alt);
            border: 1px solid var(--ms-border);
            border-radius: var(--ms-radius-lg);
            padding: 24px 28px;
            margin-top: 28px;
            color: var(--ms-text-muted);
            font-size: calc(var(--ms-base-size) * 0.88);
            line-height: 1.6;
        }}

        /* --- Bug-fix overrides (keep LAST so they win the cascade) -------- */

        /* 1. Material Symbols icons: broad font-family !important rules above
           would otherwise break icon ligatures into raw text like
           "keyboard_double_arrow_right". Always restore the icon font. */
        [data-testid="stIconMaterial"],
        [data-testid="stExpanderToggleIcon"],
        .stApp span[data-testid="stIconMaterial"],
        .stMarkdown span[data-testid="stIconMaterial"],
        .stApp [data-testid="stExpanderToggleIcon"],
        button span[data-testid="stIconMaterial"],
        summary span[data-testid="stIconMaterial"],
        [data-testid="stExpander"] summary span[data-testid="stIconMaterial"],
        span[translate="no"].material-symbols-rounded,
        .material-symbols-rounded, .material-symbols-outlined {{
            font-family: "Material Symbols Rounded", "Material Symbols Outlined" !important;
            font-weight: normal !important;
            letter-spacing: normal !important;
            text-transform: none !important;
            white-space: nowrap !important;
            overflow: visible !important;
        }}

        /* 2. Selectbox/dropdowns: BaseWeb renders the open menu in a portal
           outside .stApp, so theme it explicitly or dark/high-contrast modes
           show same-on-same text. */
        [data-baseweb="select"] > div,
        [data-baseweb="select"] input {{
            background-color: var(--ms-surface) !important;
            color: var(--ms-text) !important;
        }}
        [data-baseweb="select"] div[value],
        [data-baseweb="select"] span {{
            color: var(--ms-text) !important;
        }}
        [data-baseweb="popover"] [role="listbox"],
        ul[data-testid="stSelectboxVirtualDropdown"] {{
            background-color: var(--ms-surface) !important;
            border: var(--ms-border-width) solid var(--ms-border) !important;
        }}
        /* Options render in a body-level portal with no popover ancestor,
           so these selectors must work without one. */
        [role="listbox"] {{
            background-color: var(--ms-surface) !important;
            border: var(--ms-border-width) solid var(--ms-border) !important;
        }}
        [role="option"], [role="option"] div, [role="option"] span,
        [data-baseweb="menu"] li, [data-baseweb="menu"] li * {{
            background-color: transparent !important;
            color: var(--ms-text) !important;
        }}
        [role="option"][aria-selected="true"],
        [role="option"][aria-selected="true"] div,
        [role="option"]:hover, [role="option"]:hover div {{
            background-color: var(--ms-surface-alt) !important;
            color: var(--ms-heading) !important;
        }}

        /* 3. Buttons: never truncate labels - wrap onto extra lines instead. */
        .stButton button, [data-testid="stBaseButton-primary"],
        [data-testid="stBaseButton-secondary"] {{
            white-space: normal !important;
            height: auto !important;
            min-height: 52px;
        }}
        .stButton button p, .stButton button div {{
            white-space: normal !important;
            overflow: visible !important;
            text-overflow: clip !important;
        }}
        </style>
        """)


def _inline_logo_svg(theme_mode: str = "light") -> str:
    logo_path: Path = config.ASSETS_DIR / "logo.svg"
    if logo_path.exists():
        svg = logo_path.read_text(encoding="utf-8")
        if theme_mode == "dark":
            svg = svg.replace("#17324D", "#FFFFFF").replace("#0F8B8D", "#4C9AFF").replace("#566579", "#B0B7C3")
        elif theme_mode == "high_contrast":
            svg = (
                svg.replace("#17324D", "#FFD60A")
                .replace("#0F8B8D", "#4CC9F0")
                .replace("#566579", "#FFFFFF")
            )
        else:
            svg = svg.replace("#17324D", "#111111").replace("#0F8B8D", "#1A73E8").replace("#566579", "#575B5F")
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
    Apple Health-style privacy indicator, and obvious DEMO indicator when sample data is active."""
    svg = _inline_logo_svg(theme_mode)
    sec_escaped = html.escape(section_title)
    # Header stays minimal for seniors: logo + current section. The demo pill
    # appears only in demo mode; privacy details live under More -> Settings.
    demo_pill = (
        f'<span class="ms-badge ms-badge-moderate" role="status">'
        f'[DEMO] {html.escape(t("demo_badge", language))}</span>'
        if is_demo
        else ""
    )
    html_markdown(f"""
        <div class="ms-header-card" role="banner">
            <div style="display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:14px;">
                <div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap;">
                    <div style="width:210px;max-width:100%;">{svg}</div>
                    <div style="border-left:2px solid var(--ms-border);padding-left:16px;">
                        <div class="ms-card-title">{sec_escaped}</div>
                    </div>
                </div>
                <div>{demo_pill}</div>
            </div>
        </div>
        """)
    if is_demo:
        html_markdown(f"""
            <div class="ms-demo-banner" role="region" aria-label="Demonstration mode notice">
                <strong>[DEMO] {html.escape(t("demo_badge", language))}:</strong>
                {html.escape(t("demo_banner_text", language))}
            </div>
            """)


def render_stat_card(value: str | int, label: str, sublabel: str = "") -> None:
    val_esc = html.escape(str(value))
    lbl_esc = html.escape(label)
    sub_html = (
        f'<div class="ms-stat-sublabel">{html.escape(sublabel)}</div>'
        if sublabel
        else ""
    )
    html_markdown(f"""
        <div class="ms-stat-box">
            <div class="ms-stat-value">{val_esc}</div>
            <div class="ms-stat-label">{lbl_esc}</div>
            {sub_html}
        </div>
        """)


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
        # Neutral slate — NEVER green "SAFE"
        cls, sym = "ms-badge-neutral", "[NO RECORD IN DATASET]"
    else:
        cls, sym = "ms-badge-moderate", "[INCOMPLETE CHECK]"
    return f'<span class="ms-badge {cls}">{html.escape(sym)} {html.escape(label)}</span>'


def render_medication_card_header(med: MedicationRecord, language: str = "English") -> None:
    """Render an NHS Digital Primary Card summary header for one medication,
    preserving FDA/ISMP Tall Man Lettering on confusable generic names and
    tabular-nums monospace formatting for RxCUI codes."""
    id_badge_cls = {
        "confirmed": "ms-badge-verified",
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

    # Check if this medication or its primary generic has an FDA/ISMP Tall Man form
    tall_man_str = get_tall_man_display_name(med.generic_name or med.display_name)
    if tall_man_str and tall_man_str != (med.generic_name or med.display_name):
        title_html = (
            f"{html.escape(med.display_name)} "
            f'<span style="font-size:0.88em;color:var(--ms-text-muted);">'
            f'(Tall Man: {render_tall_man_html(tall_man_str)})</span>'
        )
    else:
        title_html = html.escape(med.display_name)

    meta_parts = [p for p in (med.strength, med.dose_form, med.route) if p]
    meta_line = " · ".join(meta_parts) if meta_parts else "Strength / form not recorded"
    ings_html_parts: list[str] = []
    for ing in med.ingredients:
        tm_ing = get_tall_man_display_name(ing.name)
        if tm_ing != ing.name:
            ings_html_parts.append(render_tall_man_html(tm_ing))
        else:
            ings_html_parts.append(html.escape(ing.name))
    ings_html = " + ".join(ings_html_parts) if ings_html_parts else "Not yet identified"

    rxcui_html = (
        f' <span class="ms-mono-code">(RxCUI: {html.escape(str(med.rxcui))})</span>'
        if med.rxcui
        else ""
    )
    sched_line = (
        ", ".join(s.display_time for s in med.schedule)
        if med.schedule
        else "No reminder time set"
    )
    instr_line = med.instructions or "No directions entered"

    html_markdown(f"""
        <div class="ms-primary-card">
            <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:10px;">
                <div>
                    <span class="ms-card-title">{title_html}</span>
                    <span class="ms-card-subtitle" style="margin-left:10px;">
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
            <div style="margin-top:10px;color:var(--ms-text);">
                <strong>Active ingredient(s):</strong> {ings_html}{rxcui_html}
                &nbsp;|&nbsp; <strong>Schedule:</strong> {html.escape(sched_line)}
            </div>
            <div style="margin-top:6px;color:var(--ms-text-muted);">
                <strong>User-entered directions:</strong> {html.escape(instr_line)}
            </div>
        </div>
        """)


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


def render_nhs_warning_callout(
    title: str,
    guidance_html: str,
    *,
    category: str = "BOXED WARNING",
    severity: str = "major",
    spl_section_title: str | None = None,
    spl_text: str | None = None,
    source_label: str | None = None,
) -> None:
    """Render an NHS Digital Service Manual Warning Callout featuring:
    * A 4px solid semantic left border (``#D93025`` red or ``#FA903E`` amber).
    * An explicit severity header badge (``BOXED WARNING``, ``CONTRAINDICATION``,
      ``LASA ALERT``, ``ACTIVE RECALL``, or ``DRUG SHORTAGE``).
    * Plain-language patient guidance.
    * An optional expandable clinical evidence drawer displaying the exact FDA
      Structured Product Labeling (SPL) section text.
    """
    sev = (severity or "major").lower()
    if sev == "major":
        callout_cls = "ms-nhs-callout"
        badge_cls = "ms-badge-major"
        sym = "[!]"
    elif sev == "moderate":
        callout_cls = "ms-nhs-callout ms-nhs-callout-amber"
        badge_cls = "ms-badge-moderate"
        sym = "[▲]"
    else:
        callout_cls = "ms-nhs-callout ms-nhs-callout-blue"
        badge_cls = "ms-badge-teal"
        sym = "[i]"

    drawer_html = ""
    if spl_text:
        sec_hdr = html.escape(spl_section_title or "Official FDA Structured Product Labeling (SPL) Excerpt")
        src_part = (
            f'<div style="margin-top:8px;font-size:0.88em;color:var(--ms-text-muted);">'
            f'Source: {html.escape(source_label)}</div>'
            if source_label
            else ""
        )
        drawer_html = (
            f'<details class="ms-spl-drawer">'
            f"<summary>{sec_hdr}</summary>"
            f'<div class="ms-spl-drawer-body">{html.escape(spl_text)}{src_part}</div>'
            f"</details>"
        )

    html_markdown(f"""
        <div class="{callout_cls}" role="region" aria-label="{html.escape(category)}: {html.escape(title)}">
            <div style="margin-bottom:8px;">
                <span class="ms-badge {badge_cls}">{html.escape(sym)} {html.escape(category)}</span>
                <strong style="font-family:var(--ms-font-heading);font-weight:600;color:var(--ms-heading);">
                    {html.escape(title)}
                </strong>
            </div>
            <div style="color:var(--ms-text);line-height:1.6;">
                {guidance_html}
            </div>
            {drawer_html}
        </div>
        """)


def render_lasa_warning_card(lasa: dict[str, str]) -> None:
    """Render an NHS-style FDA / ISMP Look-Alike / Sound-Alike (LASA) Warning Callout
    with bolded Tall Man Lettering segments so seniors can double-check similar-looking
    drug names without any CSS case flattening."""
    tall_man_html = render_tall_man_html(lasa.get("tall_man", ""))
    purpose = html.escape(lasa.get("purpose", ""))
    confused_tm_html = render_tall_man_html(lasa.get("confused_tall_man", ""))
    confused_purpose = html.escape(lasa.get("confused_purpose", ""))
    group_label = lasa.get("group") or f"{lasa.get('tall_man', '')} vs. {lasa.get('confused_tall_man', '')}"

    guidance = (
        "Please double-check the exact middle/ending letters on your bottle label:<br/>"
        f"&bull; {tall_man_html} — {purpose}<br/>"
        f"&bull; Do not confuse with {confused_tm_html} — {confused_purpose}"
    )
    render_nhs_warning_callout(
        f"Look-Alike Name Double-Check ({group_label})",
        guidance,
        category="LASA ALERT",
        severity="moderate",
        spl_section_title="Why FDA & ISMP Tall Man Lettering is shown",
        spl_text=(
            "The U.S. Food and Drug Administration (FDA Name Differentiation Project) and "
            "the Institute for Safe Medication Practices (ISMP) highlight distinguishing "
            "letters in bold uppercase so look-alike and sound-alike medicine names are "
            "not mixed up on pharmacy labels."
        ),
    )


def render_polypharmacy_matrix(
    meds: list[MedicationRecord],
    report: CheckReport,
    *,
    language: str = "English",
) -> None:
    """Render an Interactive Polypharmacy Pairwise Interaction Matrix table
    evaluating all pairwise combinations across a patient's medication list."""
    if len(meds) < 2:
        return

    pair_lookup: dict[tuple[str, str], PairResult] = {}
    for res in report.results:
        k1 = (res.med_a.display_name, res.med_b.display_name)
        k2 = (res.med_b.display_name, res.med_a.display_name)
        pair_lookup[k1] = res
        pair_lookup[k2] = res

    header_cells = ["<th>Medication</th>"]
    for m in meds:
        tm = get_tall_man_display_name(m.generic_name or m.display_name)
        col_html = render_tall_man_html(tm) if tm != (m.generic_name or m.display_name) else html.escape(m.display_name)
        header_cells.append(f"<th>{col_html}</th>")

    body_rows: list[str] = []
    for i, med_row in enumerate(meds):
        tm_row = get_tall_man_display_name(med_row.generic_name or med_row.display_name)
        row_label = (
            render_tall_man_html(tm_row)
            if tm_row != (med_row.generic_name or med_row.display_name)
            else html.escape(med_row.display_name)
        )
        cells = [f"<th>{row_label}</th>"]
        for j, med_col in enumerate(meds):
            if i == j:
                cells.append('<td style="color:var(--ms-text-muted);">&mdash;</td>')
                continue
            pr = pair_lookup.get((med_row.display_name, med_col.display_name))
            if not pr:
                cells.append('<td><span class="ms-badge ms-badge-neutral">[?] Not checked</span></td>')
            elif pr.status == CheckStatus.MATCH_FOUND:
                cells.append(f"<td>{severity_badge_html(pr.top_severity or 'unspecified', None, language)}</td>")
            elif pr.status == CheckStatus.NO_MATCHING_RECORD:
                cells.append('<td><span class="ms-badge ms-badge-neutral">[NO RECORD] None in dataset</span></td>')
            else:
                cells.append('<td><span class="ms-badge ms-badge-moderate">[▲] Confirm identity</span></td>')
        body_rows.append(f"<tr>{''.join(cells)}</tr>")

    html_markdown(f"""
        <div style="overflow-x:auto;">
            <table class="ms-matrix-table" aria-label="Polypharmacy Pairwise Interaction Matrix">
                <thead><tr>{''.join(header_cells)}</tr></thead>
                <tbody>{''.join(body_rows)}</tbody>
            </table>
        </div>
        """)


def render_skeleton_loader(lines: int = 3, label: str = "Loading clinical safety data...") -> None:
    """Render an accessible skeleton shimmer placeholder for asynchronous clinical views."""
    bars = "".join(
        f'<div class="ms-skeleton-line" style="width:{92 - (i * 12) % 35}%;"></div>'
        for i in range(max(1, lines))
    )
    html_markdown(f"""
        <div class="ms-secondary-card" role="status" aria-live="polite" aria-label="{html.escape(label)}">
            <div style="font-weight:600;margin-bottom:10px;color:var(--ms-text-muted);">
                {html.escape(label)}
            </div>
            {bars}
        </div>
        """)


def render_clinical_metadata_footer(
    *,
    data_sources: Iterable[str] | None = None,
    limitations: Iterable[str] | None = None,
    fda_disclaimer: str | None = None,
) -> None:
    """Render the transparent clinical governance footer disclosing ``data_sources``,
    scope ``limitations``, the mandatory FDA disclaimer, and the Apple Health-style
    privacy notice that health data belongs to the user."""
    sources_list = list(
        data_sources
        or [
            "MedSafe Local SQLite Interaction Dataset (medsafe-starter / imported DDInter CSVs)",
            "U.S. National Library of Medicine RxNorm REST API (rxnav.nlm.nih.gov/REST)",
            "U.S. FDA openFDA REST APIs (Drug Labeling, FAERS Adverse Events, Enforcement Recalls, Drug Shortages)",
        ]
    )
    lims_list = list(
        limitations
        or [
            "'No interaction record found in dataset' means no matching entry was found in the loaded table — it does NOT guarantee a combination is safe.",
            "FAERS adverse event counts reflect reporting volume and prescription frequency, not proven causation.",
            "Drug recalls are lot-specific; always verify lot numbers with your pharmacist before stopping any prescription.",
        ]
    )
    disc = fda_disclaimer or (
        "Do not rely on openFDA or MedSafe alone to make decisions regarding medical care. "
        "Always speak to your physician or pharmacist before starting, stopping, or changing any medication."
    )

    src_items = "".join(f"<li>{html.escape(s)}</li>" for s in sources_list)
    lim_items = "".join(f"<li>{html.escape(l)}</li>" for l in lims_list)

    # Senior-first footer: one quiet line everywhere; the full governance
    # details live inside an expander so they never dominate a page.
    with st.expander("ℹ️ Data sources, limitations & privacy"):
        html_markdown(f"""
            <div class="ms-clinical-footer" role="contentinfo" aria-label="Clinical data sources, limitations, and privacy notice">
                <div style="margin-bottom:8px;">
                    <strong>Data sources:</strong>
                    <ul style="margin:4px 0 8px 20px;">{src_items}</ul>
                </div>
                <div style="margin-bottom:8px;">
                    <strong>Limitations:</strong>
                    <ul style="margin:4px 0 8px 20px;">{lim_items}</ul>
                </div>
                <div style="margin-bottom:6px;color:var(--ms-text);">
                    <strong>Disclaimer:</strong> {html.escape(disc)}
                </div>
                <div>
                    <strong>Privacy:</strong> Your medication list, schedule, and dose history are stored
                    only on this device and are never transmitted or sold.
                </div>
            </div>
            """)
