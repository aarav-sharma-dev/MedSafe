"""Medication bottle scanning: Pre-scan image quality diagnostics, Multi-Pass
Ensemble OCR (preserving shaded pink/yellow pharmacy highlight boxes),
clinical-safe PII redaction, anchor-based anti-hallucination drug parsing,
and demo sample label generation.

Safety rules enforced here:
* A bottle image is never proof of a medication's identity. Every OCR scan
  produces an unconfirmed proposal (`identity_status="needs_review"` or
  `"unidentified"`) that requires explicit human review before saving.
* Personal details visible on a bottle label (prescription numbers, dates of
  birth, phone numbers, patient/address headers) are redacted in-place and
  never saved or transmitted, while clinical lines (strengths, dosage forms,
  and directions) are strictly protected from accidental redaction.
* Unreadable or garbled directions are left blank rather than guessed.
* Pharmacy boilerplate fragments (e.g. 'arty: 30, Rilo:' from 'Quantity: 30,
  Refills: 0') are blocked by exact + fuzzy boilerplate shielding so they can
  never hallucinate a random drug candidate.
"""

from __future__ import annotations

import io
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from PIL import (
    Image,
    ImageChops,
    ImageDraw,
    ImageEnhance,
    ImageFilter,
    ImageFont,
    ImageOps,
    ImageStat,
)

import config
import drug_data
from dataset_import import normalize_name

STANDARD_TESSERACT_PATHS = (
    "/opt/homebrew/bin/tesseract",
    "/usr/local/bin/tesseract",
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
)

MIN_OCR_WIDTH = 1200
MAX_IMAGE_DIMENSION = 2200


@dataclass
class OcrEngineStatus:
    available: bool
    executable_path: str | None
    version: str | None
    message: str


@dataclass
class ImageQualityReport:
    """Pre-scan diagnostics for senior photography issues (blur, darkness, glare)."""

    width: int
    height: int
    mean_brightness: float
    contrast_std: float
    edge_sharpness: float
    glare_ratio: float
    is_blurry: bool = False
    too_dark: bool = False
    too_bright: bool = False
    low_contrast: bool = False
    has_glare: bool = False
    coaching_tips: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (
            self.is_blurry
            or self.too_dark
            or self.too_bright
            or self.low_contrast
            or self.has_glare
        )


def detect_tesseract() -> OcrEngineStatus:
    """Locate the Tesseract executable via PATH or standard OS install paths."""
    try:
        import pytesseract
    except ImportError:
        return OcrEngineStatus(
            available=False,
            executable_path=None,
            version=None,
            message=(
                "The Python package `pytesseract` is not installed. Run "
                "`pip install pytesseract` or enter medication details manually."
            ),
        )

    exe = shutil.which("tesseract")
    if not exe:
        for candidate in STANDARD_TESSERACT_PATHS:
            if Path(candidate).is_file():
                exe = candidate
                break

    if exe:
        pytesseract.pytesseract.tesseract_cmd = exe

    try:
        ver = str(pytesseract.get_tesseract_version())
        return OcrEngineStatus(
            available=True,
            executable_path=exe or "tesseract",
            version=ver,
            message=f"Tesseract OCR {ver} ready ({exe or 'system PATH'}).",
        )
    except Exception:
        return OcrEngineStatus(
            available=False,
            executable_path=None,
            version=None,
            message=(
                "The Tesseract OCR engine executable was not found on this machine. "
                "Install it (Windows: UB-Mannheim Tesseract installer to "
                r"`C:\Program Files\Tesseract-OCR\tesseract.exe`; macOS: `brew install tesseract`; "
                "Ubuntu/Debian: `sudo apt install tesseract-ocr`) or enter medicines manually."
            ),
        )


# --- 1. Pre-Scan Image Quality Diagnostics ---------------------------------

def analyze_image_quality(image: Image.Image) -> ImageQualityReport:
    """Analyze a bottle image for blur/tremor, poor lighting, low contrast,
    and specular glare, returning senior-friendly coaching tips."""
    img = ImageOps.exif_transpose(image)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    w, h = img.size
    gray = ImageOps.grayscale(img)
    stat = ImageStat.Stat(gray)
    mean_b = float(stat.mean[0]) if stat.mean else 128.0
    std_c = float(stat.stddev[0]) if stat.stddev else 0.0

    edges = gray.filter(ImageFilter.FIND_EDGES)
    edge_stat = ImageStat.Stat(edges)
    edge_sharpness = float(edge_stat.stddev[0]) if edge_stat.stddev else 0.0

    # Central label region for specular glare analysis
    cx0, cy0 = int(w * 0.15), int(h * 0.15)
    cx1, cy1 = max(cx0 + 1, int(w * 0.85)), max(cy0 + 1, int(h * 0.85))
    center_crop = gray.crop((cx0, cy0, cx1, cy1))
    hist = center_crop.histogram()
    total_center_px = max(1, sum(hist))
    bright_px = sum(hist[251:256])
    glare_ratio = float(bright_px) / float(total_center_px)

    too_dark = mean_b < 45.0
    too_bright = mean_b > 235.0
    low_contrast = std_c < 22.0
    is_blurry = edge_sharpness < 12.0
    # Flag glare when bright pixels wash out contrast or overexpose the central label
    has_glare = bool(
        too_bright or (glare_ratio > 0.45 and std_c < 32.0 and edge_sharpness < 22.0)
    )

    tips: list[str] = []
    if is_blurry:
        tips.append(
            "This photo looks a bit blurry or has slight camera movement. "
            "Tip: Rest your elbows on a table, hold the bottle about 6–8 inches from the camera, "
            "or use the Quick Letter & Common Medicine Picker below."
        )
    if too_dark:
        tips.append(
            "This photo looks quite dark. "
            "Tip: Hold the bottle near a table lamp or window so the print is brightly lit, "
            "or use the Quick Letter & Common Medicine Picker below."
        )
    if too_bright or has_glare:
        tips.append(
            "This photo has bright glare or washout on the bottle label. "
            "Tip: Turn off direct camera flash and tilt the bottle slightly under indoor light, "
            "or use the Quick Letter & Common Medicine Picker below."
        )
    if low_contrast and not (too_dark or too_bright):
        tips.append(
            "The label print has low contrast against the bottle background. "
            "Tip: Move the bottle into steady light or use the Quick Letter & Common Medicine Picker below."
        )

    return ImageQualityReport(
        width=w,
        height=h,
        mean_brightness=round(mean_b, 2),
        contrast_std=round(std_c, 2),
        edge_sharpness=round(edge_sharpness, 2),
        glare_ratio=round(glare_ratio, 3),
        is_blurry=is_blurry,
        too_dark=too_dark,
        too_bright=too_bright,
        low_contrast=low_contrast,
        has_glare=has_glare,
        coaching_tips=tips,
    )


# --- 2. Multi-Pass Ensemble OCR Preprocessing ------------------------------

def _has_gemini_key() -> bool:
    """Safe wrapper around config.has_gemini_key() that can never raise AttributeError."""
    fn = getattr(config, "has_gemini_key", None)
    if callable(fn):
        return bool(fn())
    key_fn = getattr(config, "gemini_api_key", None)
    if callable(key_fn):
        return bool(key_fn())
    return bool(os.environ.get("GEMINI_API_KEY", "").strip())


def _get_gemini_model() -> str:
    """Safe wrapper around config.gemini_model() / DEFAULT_GEMINI_MODEL."""
    fn = getattr(config, "gemini_model", None)
    if callable(fn):
        return str(fn())
    return str(getattr(config, "GEMINI_MODEL", getattr(config, "DEFAULT_GEMINI_MODEL", "gemini-3.8-flash")))


def _normalize_image_dimensions(
    image: Image.Image,
    *,
    min_width: int = 1600,
    max_dim: int = 2800,
) -> Image.Image:
    """Apply EXIF orientation transpose, upscale small images proportionally up
    to `min_width` (1600px+) with LANCZOS so 10-12px bottle fonts become crisp
    35-45px glyphs, and cap oversized dimensions at `max_dim`."""
    img = ImageOps.exif_transpose(image)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    w, h = img.size
    if w < min_width:
        scale = max(2.0, float(min_width) / float(max(1, w)))
        img = img.resize(
            (max(1, int(round(w * scale))), max(1, int(round(h * scale)))),
            Image.Resampling.LANCZOS,
        )
        w, h = img.size

    if max(w, h) > max_dim:
        scale = float(max_dim) / float(max(w, h))
        img = img.resize(
            (max(1, int(round(w * scale))), max(1, int(round(h * scale)))),
            Image.Resampling.LANCZOS,
        )
    return img


def preprocess_label_image(
    image: Image.Image,
    *,
    apply_threshold: bool = False,
    threshold_value: int = 168,
) -> Image.Image:
    """Pass A (Shaded-Box & Highlight Preserving Pass):
    Correct EXIF orientation, upscale small photos, convert to grayscale, apply
    gentle autocontrast (cutoff=1) and UnsharpMask(radius=1.8, percent=160, threshold=3).
    Never applies destructive binary thresholding unless explicitly requested."""
    img = _normalize_image_dimensions(image)
    gray = ImageOps.grayscale(img)
    gray = ImageOps.autocontrast(gray, cutoff=1)
    gray = gray.filter(ImageFilter.UnsharpMask(radius=1.8, percent=160, threshold=3))

    if apply_threshold:
        gray = gray.point(lambda px: 255 if px >= threshold_value else 0, mode="L")
    return gray


def preprocess_blurry_pass(image: Image.Image) -> Image.Image:
    """Pass B (Blurry / Low-Contrast Senior Photo Pass):
    Stronger unsharp masking + contrast stretch for out-of-focus or curved labels."""
    img = _normalize_image_dimensions(image)
    gray = ImageOps.grayscale(img)
    gray = ImageOps.autocontrast(gray, cutoff=2)
    gray = gray.filter(ImageFilter.UnsharpMask(radius=2.6, percent=220, threshold=2))
    gray = ImageEnhance.Contrast(gray).enhance(1.55)
    return gray


def preprocess_color_highlight_pass(
    image: Image.Image,
    *,
    min_width: int = 1600,
) -> Image.Image:
    """Pass C (Color-Channel Max Pass for Pink/Yellow Highlight Boxes & Red Borders):
    Pharmacy labels frequently surround directions and the drug name ('Amoxicillin
    500 mg Capsules') with a red/pink rectangle border and shaded pink/yellow fills.
    In the per-pixel maximum of the Red and Green channels (`ImageChops.lighter(r, g)`),
    red border lines, pink fills, and yellow fills all have high intensity (>= 180),
    whereas black/charcoal printed text stays dark (< 95). Stretching `[0..185] -> [0..255]`
    completely erases red box borders and pink/yellow highlights into pure white while
    making the dark printed text razor-sharp."""
    img = _normalize_image_dimensions(image, min_width=min_width)
    rgb = img.convert("RGB")
    r, g, _b = rgb.split()
    rg_max = ImageChops.lighter(r, g)
    out = ImageOps.autocontrast(rg_max, cutoff=1)
    # Bleach red/pink box borders and shaded fills (>= 180 in max(R,G)) cleanly into white (255)
    out = out.point(lambda px: 255 if px >= 182 else int(px * 255 // 182), mode="L")
    out = out.filter(ImageFilter.UnsharpMask(radius=1.8, percent=180, threshold=2))
    return out


def preprocess_cropped_label_pass(image: Image.Image) -> Image.Image:
    """Pass D (Auto-Cropped Central Label Region + 3x-4x Upscale Pass):
    Full-bottle photos have large side margins, a bottle cap at the top, and
    pills at the bottom, leaving the label text small. Cropping to the central
    label region and upscaling to >= 1800px wide before erasing red/pink/yellow
    boxes makes 10px boxed bottle text cleanly readable by Tesseract."""
    img = ImageOps.exif_transpose(image)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    w, h = img.size
    if h > w * 1.15:
        # Portrait full-bottle photo: trim cap (top 14%), bottom pills (bottom 14%), and side margins (8%)
        box = (
            max(0, int(w * 0.08)),
            max(0, int(h * 0.14)),
            min(w, max(1, int(w * 0.92))),
            min(h, max(1, int(h * 0.86))),
        )
    else:
        # Landscape / pre-cropped label: keep full horizontal text margins (only trim 1% border artifact)
        box = (
            max(0, int(w * 0.01)),
            max(0, int(h * 0.02)),
            min(w, max(1, int(w * 0.99))),
            min(h, max(1, int(h * 0.98))),
        )
    cropped = img.crop(box)
    return preprocess_color_highlight_pass(cropped, min_width=1800)


# --- 3. Clinical-Safe PII Redaction ----------------------------------------

_CLINICAL_UNIT_RE = re.compile(
    r"(?i)\b\d+(?:\.\d+)?\s*(?:mg|mcg|g|ml|meq|units|%)\b"
)

_CLINICAL_PROTECTION_WORDS = frozenset({
    # Dosage units & forms
    "mg", "mcg", "ml", "meq", "units",
    "tablet", "tablets", "capsule", "capsules", "cap", "caps", "tab", "tabs",
    "pill", "pills", "liquid", "solution", "suspension", "cream", "ointment",
    "patch", "inhaler", "spray", "drops", "lozenge", "syrup", "suppository",
    # Direction keywords
    "take", "mouth", "daily", "twice", "three", "times", "every", "hours",
    "morning", "evening", "bedtime", "food", "water", "meals", "needed",
    "inhale", "apply", "inject", "dissolve", "swallow", "days",
})

# Span-level PII patterns safe to apply anywhere (explicitly labeled identifiers)
_UNIVERSAL_PII_PATTERNS: list[tuple[re.Pattern, str]] = [
    (
        re.compile(r"(?i)\b(?:rx\s*(?:#|no\.?|num(?:ber)?)?\s*[:#-]?\s*)\d[\d-]{3,}\b"),
        "[RX# REDACTED]",
    ),
    (
        re.compile(r"(?i)\b(?:patient|pt)\s*(?:name)?\s*:\s*[^\n\r]+"),
        "PATIENT: [REDACTED]",
    ),
    (
        re.compile(r"(?i)\b(?:dob|date of birth|birth\s*date)\s*[:#-]?\s*[\d/\-.]+"),
        "DOB: [REDACTED]",
    ),
    (
        re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b"),
        "[PHONE REDACTED]",
    ),
]

# Address pattern is ONLY applied on lines that do NOT contain protected clinical words,
# and only matches single-line street addresses (using `[ \t]` instead of `\s` so it can
# NEVER cross newline boundaries and swallow adjacent lines!).
_SINGLE_LINE_ADDRESS_RE = re.compile(
    r"(?i)\b\d{1,5}[ \t]+[A-Za-z0-9.][A-Za-z0-9. \t]{1,28}[ \t]+"
    r"(?:street|st|avenue|ave|road|rd|boulevard|blvd|lane|ln|drive|dr|way|court|ct)\b[^\n\r]*"
)


def _is_protected_clinical_line(line: str) -> bool:
    """Return True if a line contains dosage units, dosage forms, or direction
    keywords, or a known medication name in our catalog."""
    if _CLINICAL_UNIT_RE.search(line):
        return True
    tokens = {w.lower() for w in re.findall(r"[A-Za-z]+", line)}
    if tokens & _CLINICAL_PROTECTION_WORDS:
        return True
    return False


def redact_label_pii(raw_text: str) -> tuple[str, int]:
    """Strip personal identifiers (Rx numbers, patient names, DOB, phone,
    street addresses) in-place from OCR text while strictly protecting clinical
    lines (medication names, strengths, dosage forms, and directions)."""
    if not raw_text:
        return "", 0

    redacted_lines: list[str] = []
    total_count = 0

    for raw_line in raw_text.splitlines():
        line = raw_line
        for pattern, replacement in _UNIVERSAL_PII_PATTERNS:
            line, n = pattern.subn(replacement, line)
            total_count += n

        # Only apply street-address redaction if this line is NOT a protected clinical line
        if not _is_protected_clinical_line(line):
            line, n_addr = _SINGLE_LINE_ADDRESS_RE.subn("[ADDRESS REDACTED]", line)
            total_count += n_addr

        redacted_lines.append(line)

    return "\n".join(redacted_lines), total_count


# --- 4. Anti-Hallucination Drug Extraction & Boilerplate Shield ------------

_INSTRUCTION_START_RE = re.compile(
    r"(?i)^\s*(?:t?ake|use|inhale|apply|inject|dissolve|swallow|instill|insert|give|chew)\b"
)

_DIRECTION_CONTINUATION_RE = re.compile(
    r"(?i)\b(?:daily|day|days|time|times|twice|once|three|four|every|hour|hours|"
    r"morning|evening|night|bedtime|mouth|food|water|meal|meals|needed|directed|until)\b"
)

_METADATA_LINE_RE = re.compile(
    r"(?i)\b(?:qty|quantity|refill|refills|expiration|exp\s*date|ndc|lot|mfg|"
    r"discard\s+after|keep\s+out|demo\s+sample\s+label|not\s+a\s+real\s+prescription|"
    r"\[rx#\s*redacted\]|\[address\s*redacted\]|\[phone\s*redacted\]|patient:\s*\[redacted\])\b"
)

_FORM_OR_SALT_RE = re.compile(
    r"(?i)\b(?:tablet|tablets|tab1et|tab1ets|tabiet|tabiets|tab|tabs|"
    r"capsule|capsules|capsu1e|capsu1es|capsuie|capsuies|cap|caps|oral|solution|"
    r"suspension|cream|ointment|patch|inhaler|spray|drops|lozenge|syrup|"
    r"hcl|hydrochloride|sodium|potassium|tartrate|succinate|besylate|maleate|"
    r"calcium|sulfate|acetate|phosphate|citrate|fumarate|mesylate|nitrate|"
    r"er|xr|sr|dr|ec)\b"
)


@dataclass
class OcrExtractionResult:
    raw_text: str
    redacted_text: str
    pii_redacted_count: int
    proposed_name: str
    proposed_generic: str | None
    proposed_brand: str | None
    proposed_strength: str | None
    proposed_form: str | None
    proposed_instructions: str | None
    candidates: list[drug_data.DrugCandidate] = field(default_factory=list)
    normalization: drug_data.NormalizationResult | None = None
    uncertainty_notes: list[str] = field(default_factory=list)
    identity_status: str = "needs_review"  # never 'confirmed' until user reviews
    engine_used: str = "tesseract"
    image_quality: ImageQualityReport | None = None
    lasa_warnings: list[dict[str, str]] = field(default_factory=list)


def _is_legible_direction_line(clean: str) -> bool:
    alpha = sum(c.isalpha() or c.isdigit() or c.isspace() for c in clean)
    return len(clean) >= 6 and (alpha / max(1, len(clean))) >= 0.85


def _extract_directions(lines: list[str]) -> tuple[str | None, bool]:
    """Pull a legible directions block, joining wrapped continuation lines such as:
      'TAKE 1 CAPSULE BY MOUTH'
      'THREE TIMES DAILY FOR 10 DAYS'
    -> 'TAKE 1 CAPSULE BY MOUTH THREE TIMES DAILY FOR 10 DAYS'.
    Returns (instructions, was_unreadable_candidate)."""
    best_instructions: str | None = None
    was_garbled = False

    for idx, line in enumerate(lines):
        clean = " ".join(line.strip().split())
        if _INSTRUCTION_START_RE.match(clean):
            if re.match(r"^(?:AKE|ake)\b", clean):
                clean = ("T" if clean[0].isupper() else "t") + clean
            if not _is_legible_direction_line(clean) or len(clean) < 10:
                was_garbled = True
                continue

            parts = [clean]
            # Look ahead up to 2 immediately following lines for wrapped directions
            for next_idx in range(idx + 1, min(len(lines), idx + 3)):
                nxt = " ".join(lines[next_idx].strip().split())
                if not nxt or not _is_legible_direction_line(nxt):
                    break
                # Stop if the next line is a medication-strength line, metadata line, or new instruction
                if drug_data._STRENGTH_RE.search(nxt) or _METADATA_LINE_RE.search(nxt):
                    break
                if _INSTRUCTION_START_RE.match(nxt):
                    break
                # Stop if the next line contains a known medication name in our catalog
                nxt_words = [
                    drug_data.denoise_ocr_drug_token(w)
                    for w in re.findall(r"[A-Za-z0-9]{5,}", nxt)
                    if not drug_data.is_boilerplate_or_noise_token(w)
                ]
                if any(w.lower() in drug_data._KNOWN_CATALOG_NAMES for w in nxt_words):
                    break
                if _DIRECTION_CONTINUATION_RE.search(nxt):
                    # Avoid duplicating text if already present in `clean`
                    if nxt.lower() not in " ".join(parts).lower():
                        parts.append(nxt)
                else:
                    break

            joined = " ".join(parts)
            if best_instructions is None or len(joined) > len(best_instructions):
                best_instructions = joined

    if best_instructions:
        return best_instructions, False
    return None, was_garbled


def _score_label_line(line: str) -> int:
    """Compute an anchor-based score for how likely `line` is the primary
    medication identity line on a pharmacy bottle."""
    clean = " ".join(line.strip().split())
    if not clean:
        return -100

    score = 0
    has_strength = bool(drug_data._STRENGTH_RE.search(clean))
    has_form_or_salt = bool(_FORM_OR_SALT_RE.search(clean))
    is_instruction = bool(_INSTRUCTION_START_RE.match(clean))
    is_metadata = bool(_METADATA_LINE_RE.search(clean))

    if has_strength:
        score += 50
    if has_form_or_salt:
        score += 35

    if is_instruction:
        score -= 40
    if is_metadata and not has_strength:
        score -= 45

    # Inspect alphanumeric tokens on this line (with OCR character-confusion de-noising)
    raw_words = re.findall(r"[A-Za-z0-9]{3,}", clean)
    meaningful_words: list[str] = []
    for w in raw_words:
        if w.isdigit():
            continue
        denoised = drug_data.denoise_ocr_drug_token(w) if len(w) >= 6 else w
        if not drug_data.is_boilerplate_or_noise_token(denoised):
            meaningful_words.append(denoised)

    if not meaningful_words:
        score -= 60
    else:
        # Bonus if any token (or OCR-denoised token) on the line matches our local catalog
        for w in meaningful_words:
            hits = drug_data._search_local_catalog(w.lower(), w, None, None)
            if any(h.match_type in ("exact", "brand_or_alias") for h in hits):
                score += 40
                break
            if any(h.confidence >= 0.82 for h in hits):
                score += 30
                break

    return score


def _extract_drug_prefix_before_strength(line: str) -> str:
    """Extract the clean drug name tokens appearing before the dosage strength
    on an anchor line (e.g. 'Amoxicillin 500 mg Capsules' -> 'Amoxicillin',
    or 'Amoxici11in 500 mg Capsules' -> 'amoxicillin')."""
    m = drug_data._STRENGTH_RE.search(line)
    prefix = line[: m.start()].strip() if m else line.strip()
    base, _, _ = drug_data.parse_medication_query(prefix)
    words: list[str] = []
    for w in re.findall(r"[A-Za-z0-9/-]+", base):
        denoised = drug_data.denoise_ocr_drug_token(w) if len(w) >= 6 else w
        if not drug_data.is_boilerplate_or_noise_token(denoised):
            words.append(denoised)
    return " ".join(words).strip()


def parse_label_text(
    raw_text: str,
    *,
    use_network: bool = True,
    engine_used: str = "tesseract",
    image_quality: ImageQualityReport | None = None,
) -> OcrExtractionResult:
    """Parse OCR text into a conservative, unconfirmed medication proposal."""
    redacted, pii_count = redact_label_pii(raw_text or "")
    lines = [ln.strip() for ln in redacted.splitlines() if ln.strip()]

    if not lines:
        notes = [
            "No readable text was found on the image. Please retake the photo in "
            "bright light or use the Quick Letter & Common Medicine Picker below."
        ]
        if image_quality and image_quality.coaching_tips:
            notes.extend(image_quality.coaching_tips)
        return OcrExtractionResult(
            raw_text="",
            redacted_text="",
            pii_redacted_count=0,
            proposed_name="",
            proposed_generic=None,
            proposed_brand=None,
            proposed_strength=None,
            proposed_form=None,
            proposed_instructions=None,
            candidates=[],
            normalization=None,
            uncertainty_notes=notes,
            identity_status="unidentified",
            engine_used=engine_used,
            image_quality=image_quality,
            lasa_warnings=[],
        )

    instructions, garbled_dir = _extract_directions(lines)

    # First scan all non-metadata lines for strength & dosage form in case `--psm 11`
    # separated the drug name and `"500 mg Capsules"` onto adjacent lines.
    fallback_strength: str | None = None
    fallback_form: str | None = None
    for ln in lines:
        if _METADATA_LINE_RE.search(ln) or _INSTRUCTION_START_RE.match(ln):
            continue
        _b, s_val, f_val = drug_data.parse_medication_query(ln)
        if s_val and not fallback_strength:
            fallback_strength = s_val
        if f_val and not fallback_form:
            fallback_form = f_val

    # Score every line using anchor-based rules
    scored_lines: list[tuple[int, int, str]] = []
    for idx, ln in enumerate(lines):
        sc = _score_label_line(ln)
        scored_lines.append((sc, -idx, ln))

    scored_lines.sort(reverse=True)

    found_candidates: list[drug_data.DrugCandidate] = []
    seen_generics: set[str] = set()
    best_line = ""
    extracted_strength: str | None = None
    extracted_form: str | None = None

    for score, _neg_idx, ln in scored_lines:
        # Never extract drug candidates from lines scored as boilerplate/instructions/noise (< 0)
        if score < 0:
            continue

        base, str_val, form_val = drug_data.parse_medication_query(ln)
        if str_val and not extracted_strength:
            extracted_strength = str_val
        if form_val and not extracted_form:
            extracted_form = form_val

        anchor_query = _extract_drug_prefix_before_strength(ln)
        if not anchor_query and not base:
            continue

        query_to_use = anchor_query or base
        eff_strength = str_val or extracted_strength or fallback_strength
        eff_form = form_val or extracted_form or fallback_form

        # Check full anchor query and individual non-boilerplate tokens against local catalog
        line_hits = list(
            drug_data._search_local_catalog(
                query_to_use.lower(),
                ln,
                eff_strength,
                eff_form,
            )
        )
        raw_tokens = re.findall(r"[A-Za-z0-9]{3,}", ln)
        for raw_w in raw_tokens:
            if raw_w.isdigit():
                continue
            w = drug_data.denoise_ocr_drug_token(raw_w) if len(raw_w) >= 6 else raw_w
            if drug_data.is_boilerplate_or_noise_token(w):
                continue
            for w_hit in drug_data._search_local_catalog(
                w.lower(), w, eff_strength, eff_form
            ):
                if w_hit.match_type in ("exact", "brand_or_alias") or (
                    len(raw_w) >= 6 and w_hit.confidence >= 0.80
                ):
                    line_hits.append(w_hit)

        for h in line_hits:
            if not best_line:
                best_line = ln
            if h.generic_name not in seen_generics:
                seen_generics.add(h.generic_name)
                found_candidates.append(h)

        if not best_line and anchor_query:
            best_line = ln

    if not extracted_strength:
        extracted_strength = fallback_strength
    if not extracted_form:
        extracted_form = fallback_form

    norm_res: drug_data.NormalizationResult | None = None
    if best_line:
        primary_query = _extract_drug_prefix_before_strength(best_line)
        if primary_query:
            # Re-attach strength/form so resolve_drug_candidates preserves them
            full_q_parts = [primary_query]
            if extracted_strength:
                full_q_parts.append(extracted_strength)
            if extracted_form:
                full_q_parts.append(extracted_form)
            norm_res = drug_data.resolve_drug_candidates(
                " ".join(full_q_parts),
                from_ocr=True,
                use_network=use_network,
            )
            for c in norm_res.candidates:
                if c.generic_name not in seen_generics:
                    seen_generics.add(c.generic_name)
                    found_candidates.append(c)

            if not extracted_strength:
                extracted_strength = norm_res.extracted_strength
            if not extracted_form:
                extracted_form = norm_res.extracted_form

    uncertainty: list[str] = [
        "Scanned from a bottle image — please review and confirm every field before saving."
    ]
    if image_quality and image_quality.coaching_tips:
        uncertainty.extend(image_quality.coaching_tips)
    if pii_count > 0:
        uncertainty.append(
            f"Redacted {pii_count} personal identifier(s) (such as Rx number, patient name, or phone) "
            "so they are not stored."
        )
    if not extracted_strength:
        uncertainty.append("Medication strength was not clearly detected on the label — please enter it if known.")
    if not extracted_form:
        uncertainty.append("Dosage form (e.g., Oral Tablet, Oral Capsule) was not detected — please verify.")
    if garbled_dir:
        uncertainty.append("Dosage directions on the label looked unclear and were left blank for safety.")
    elif not instructions:
        uncertainty.append("Directions were not detected on the label — please copy them from your bottle.")

    if len(found_candidates) > 1:
        uncertainty.append(
            f"Multiple possible medications were detected ({', '.join(c.display_name for c in found_candidates)}). "
            "Please select the exact medicine on your bottle."
        )
    elif not found_candidates:
        uncertainty.append(
            "Could not match the scanned text to a standardized medication name. "
            "Please use the Quick Letter & Common Medicine Picker below or type the medication name manually."
        )

    # Collect FDA Look-Alike / Sound-Alike (LASA) warnings for any matched candidate
    lasa_list: list[dict[str, str]] = []
    seen_lasa: set[str] = set()
    for c in found_candidates:
        w = c.lasa_warning or drug_data.get_lasa_warning(c.generic_name)
        if w and w["drug"] not in seen_lasa:
            seen_lasa.add(w["drug"])
            lasa_list.append(w)

    top = found_candidates[0] if found_candidates else None
    # Never pre-fill random OCR garbage if no candidate matched!
    proposed_name = top.display_name if top else ""
    id_status = "needs_review" if top else "unidentified"

    return OcrExtractionResult(
        raw_text=raw_text,
        redacted_text=redacted,
        pii_redacted_count=pii_count,
        proposed_name=proposed_name,
        proposed_generic=top.generic_name if top else None,
        proposed_brand=top.brand_name if top else None,
        proposed_strength=extracted_strength,
        proposed_form=extracted_form or (top.dose_form if top else None),
        proposed_instructions=instructions,
        candidates=found_candidates,
        normalization=norm_res,
        uncertainty_notes=uncertainty,
        identity_status=id_status,
        engine_used=engine_used,
        image_quality=image_quality,
        lasa_warnings=lasa_list,
    )


def _merge_multipass_lines(pass_texts: list[str]) -> str:
    """Merge unique, legible lines across multiple OCR passes while preserving
    reading order and prioritizing lines with clinical anchors."""
    merged_lines: list[str] = []
    seen_norm: list[str] = []

    for text in pass_texts:
        if not text:
            continue
        for raw_ln in text.splitlines():
            clean = " ".join(raw_ln.strip().split())
            if len(clean) < 3:
                continue
            # Check alphanumeric legibility ratio
            alnum_space = sum(c.isalnum() or c.isspace() or c in ":/.,()-+#%" for c in clean)
            if (alnum_space / max(1, len(clean))) < 0.72:
                continue
            norm_key = re.sub(r"[^a-z0-9]+", "", clean.lower())
            if len(norm_key) < 2:
                continue

            # Deduplicate near-identical lines across passes, keeping the fuller or higher-scoring one
            duplicate_idx = None
            for idx, existing_norm in enumerate(seen_norm):
                if norm_key == existing_norm or (
                    len(norm_key) >= 6
                    and len(existing_norm) >= 6
                    and (norm_key in existing_norm or existing_norm in norm_key)
                ):
                    duplicate_idx = idx
                    break

            if duplicate_idx is not None:
                existing_line = merged_lines[duplicate_idx]
                existing_norm_key = seen_norm[duplicate_idx]
                # Never overwrite a fuller line with a clipped substring of it
                if norm_key in existing_norm_key and len(norm_key) < len(existing_norm_key):
                    continue
                if len(norm_key) > len(existing_norm_key) or (
                    _score_label_line(clean) > _score_label_line(existing_line)
                ):
                    merged_lines[duplicate_idx] = clean
                    seen_norm[duplicate_idx] = norm_key
            else:
                merged_lines.append(clean)
                seen_norm.append(norm_key)

    return "\n".join(merged_lines)


def transcribe_label_with_gemini_vision(image: Image.Image) -> str | None:
    """Optional, strictly-gated Gemini Vision transcription fallback.
    Only invoked when `GEMINI_API_KEY` is configured and local Tesseract is
    unavailable or fails to find a medication candidate on a complex bottle.
    Returns raw transcribed label lines (never treated as confirmed identity)."""
    if not _has_gemini_key():
        return None
    try:
        from google import genai

        api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not api_key:
            return None
        client = genai.Client(api_key=api_key)
        prompt = (
            "Transcribe ONLY the exact printed medication name, strength, dosage form, "
            "and directions visible on this pharmacy label, one line per item. "
            "Do NOT include patient names, Rx numbers, phone numbers, or street addresses. "
            "Do NOT guess or invent any text that is not clearly visible."
        )
        response = client.models.generate_content(
            model=_get_gemini_model(),
            contents=[prompt, image],
        )
        text = getattr(response, "text", None)
        if text and text.strip():
            return text.strip()
    except Exception:
        return None
    return None


def scan_label_image(
    image: Image.Image | bytes | Path,
    *,
    use_network: bool = True,
) -> tuple[OcrExtractionResult, Image.Image, OcrEngineStatus]:
    """Run Pre-Scan Quality Diagnostics + Multi-Pass Ensemble OCR on a pill
    bottle image, then parse into an unconfirmed `OcrExtractionResult`."""
    if isinstance(image, (str, Path)):
        pil_img = Image.open(image)
    elif isinstance(image, (bytes, bytearray)):
        pil_img = Image.open(io.BytesIO(image))
    else:
        pil_img = image

    pil_img = ImageOps.exif_transpose(pil_img)
    quality = analyze_image_quality(pil_img)

    pass_a_img = preprocess_label_image(pil_img, apply_threshold=False)
    pass_c_img = preprocess_color_highlight_pass(pil_img)
    pass_crop_img = preprocess_cropped_label_pass(pil_img)

    status = detect_tesseract()
    if not status.available:
        # Optional Gemini Vision fallback if configured and network allowed
        if use_network and _has_gemini_key():
            vision_text = transcribe_label_with_gemini_vision(pil_img)
            if vision_text:
                parsed = parse_label_text(
                    vision_text,
                    use_network=use_network,
                    engine_used="gemini_vision_fallback",
                    image_quality=quality,
                )
                return parsed, pass_c_img, status

        notes = [status.message]
        if quality.coaching_tips:
            notes.extend(quality.coaching_tips)
        res = OcrExtractionResult(
            raw_text="",
            redacted_text="",
            pii_redacted_count=0,
            proposed_name="",
            proposed_generic=None,
            proposed_brand=None,
            proposed_strength=None,
            proposed_form=None,
            proposed_instructions=None,
            candidates=[],
            normalization=None,
            uncertainty_notes=notes,
            identity_status="unidentified",
            engine_used="unavailable",
            image_quality=quality,
        )
        return res, pass_a_img, status

    import pytesseract

    pass_outputs: list[str] = []
    display_processed = pass_c_img

    try:
        # Pass C (Color-Channel Max pass — erases red/pink box borders & pink/yellow highlight fills):
        # Always run both --psm 6 (uniform block) and --psm 11 (sparse text inside bordered boxes)
        for psm_cfg in ("--oem 3 --psm 6", "--oem 3 --psm 11"):
            text_c = pytesseract.image_to_string(pass_c_img, config=psm_cfg)
            if text_c and text_c.strip():
                pass_outputs.append(text_c)

        # Pass D (Auto-Cropped Central Label Region upscaled to >= 1800px wide):
        for psm_cfg in ("--oem 3 --psm 6", "--oem 3 --psm 11"):
            text_crop = pytesseract.image_to_string(pass_crop_img, config=psm_cfg)
            if text_crop and text_crop.strip():
                pass_outputs.append(text_crop)

        # Pass A (Standard grayscale autocontrast + unsharp pass)
        text_a = pytesseract.image_to_string(pass_a_img, config="--oem 3 --psm 6")
        if text_a and text_a.strip():
            pass_outputs.append(text_a)

        merged_prelim = _merge_multipass_lines(pass_outputs)
        prelim = parse_label_text(
            merged_prelim,
            use_network=False,
            engine_used="tesseract_multipass",
            image_quality=quality,
        )

        # Pass B (Strong unsharp + contrast stretch for blurry/curved labels if still missing fields)
        if not prelim.candidates or not prelim.proposed_strength or not prelim.proposed_instructions:
            pass_b_img = preprocess_blurry_pass(pil_img)
            for psm_cfg in ("--oem 3 --psm 4", "--oem 3 --psm 11"):
                text_b = pytesseract.image_to_string(pass_b_img, config=psm_cfg)
                if text_b and text_b.strip():
                    pass_outputs.append(text_b)

    except Exception as exc:
        res = OcrExtractionResult(
            raw_text="",
            redacted_text="",
            pii_redacted_count=0,
            proposed_name="",
            proposed_generic=None,
            proposed_brand=None,
            proposed_strength=None,
            proposed_form=None,
            proposed_instructions=None,
            candidates=[],
            normalization=None,
            uncertainty_notes=[
                f"OCR engine could not read the image ({type(exc).__name__}). "
                "Please use the Quick Letter & Common Medicine Picker or enter details manually."
            ],
            identity_status="unidentified",
            engine_used="error",
            image_quality=quality,
        )
        return res, pass_a_img, status

    merged_text = _merge_multipass_lines(pass_outputs)
    engine_tag = "tesseract_multipass"

    parsed = parse_label_text(
        merged_text,
        use_network=use_network,
        engine_used=engine_tag,
        image_quality=quality,
    )

    # Optional strictly-gated Gemini Vision fallback if local OCR found 0 candidates
    if not parsed.candidates and use_network and _has_gemini_key():
        vision_text = transcribe_label_with_gemini_vision(pil_img)
        if vision_text:
            combined = _merge_multipass_lines([merged_text, vision_text])
            parsed = parse_label_text(
                combined,
                use_network=use_network,
                engine_used="tesseract+gemini_vision_fallback",
                image_quality=quality,
            )

    return parsed, display_processed, status


# --- Demo Sample Prescription Label Generator ------------------------------

SAMPLE_LABELS: list[dict[str, str]] = [
    {
        "id": "lisinopril",
        "filename": "sample_label_lisinopril.png",
        "title": "Sample 1: Lisinopril 10 mg Oral Tablet (Prescription)",
        "pharmacy": "COMMUNITY CORNER PHARMACY  (555) 234-5678",
        "rx_line": "RX# 8492014   PATIENT: DEMO USER",
        "drug_line": "LISINOPRIL 10 MG TABLET",
        "brand_line": "Generic for: PRINIVIL / ZESTRIL",
        "directions": "Take 1 tablet by mouth every morning",
        "footer": "QTY: 30 TABLETS   REFILLS: 2   DR. PATEL",
        "fallback_text": (
            "DEMO SAMPLE LABEL — NOT A REAL PRESCRIPTION\n"
            "COMMUNITY CORNER PHARMACY (555) 234-5678\n"
            "RX# 8492014 PATIENT: DEMO USER\n"
            "LISINOPRIL 10 MG TABLET\n"
            "Generic for: PRINIVIL / ZESTRIL\n"
            "Take 1 tablet by mouth every morning\n"
            "QTY: 30 TABLETS REFILLS: 2"
        ),
    },
    {
        "id": "ibuprofen",
        "filename": "sample_label_ibuprofen.png",
        "title": "Sample 2: Ibuprofen 200 mg Tablet (OTC Pain Reliever)",
        "pharmacy": "DEMO HEALTH MARKET — OVER-THE-COUNTER",
        "rx_line": "ITEM# OTC-200   FOR DEMONSTRATION ONLY",
        "drug_line": "IBUPROFEN 200 MG ORAL TABLET",
        "brand_line": "Compare to active ingredient in ADVIL",
        "directions": "Take 1 tablet every 6 to 8 hours with food as needed",
        "footer": "PAIN RELIEVER / FEVER REDUCER (NSAID) — 50 TABLETS",
        "fallback_text": (
            "DEMO SAMPLE LABEL — NOT A REAL PRESCRIPTION\n"
            "DEMO HEALTH MARKET — OVER-THE-COUNTER\n"
            "IBUPROFEN 200 MG ORAL TABLET\n"
            "Compare to active ingredient in ADVIL\n"
            "Take 1 tablet every 6 to 8 hours with food as needed\n"
            "PAIN RELIEVER / FEVER REDUCER (NSAID)"
        ),
    },
    {
        "id": "metformin",
        "filename": "sample_label_metformin.png",
        "title": "Sample 3: Metformin 500 mg Oral Tablet (Prescription)",
        "pharmacy": "COMMUNITY CORNER PHARMACY  (555) 234-5678",
        "rx_line": "RX# 8492099   PATIENT: DEMO USER",
        "drug_line": "METFORMIN 500 MG ORAL TABLET",
        "brand_line": "Generic for: GLUCOPHAGE",
        "directions": "Take 1 tablet by mouth twice daily with meals",
        "footer": "QTY: 60 TABLETS   REFILLS: 3   DR. PATEL",
        "fallback_text": (
            "DEMO SAMPLE LABEL — NOT A REAL PRESCRIPTION\n"
            "COMMUNITY CORNER PHARMACY (555) 234-5678\n"
            "RX# 8492099 PATIENT: DEMO USER\n"
            "METFORMIN 500 MG ORAL TABLET\n"
            "Generic for: GLUCOPHAGE\n"
            "Take 1 tablet by mouth twice daily with meals\n"
            "QTY: 60 TABLETS REFILLS: 3"
        ),
    },
]


def _load_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = (
        ["arialbd.ttf", "segoeuib.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"]
        if bold
        else ["arial.ttf", "segoeui.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"]
    )
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def ensure_sample_labels(assets_dir: Path | None = None) -> list[Path]:
    """Generate the 3 high-contrast DEMO SAMPLE LABEL PNG images in `assets/`."""
    target_dir = Path(assets_dir or config.ASSETS_DIR)
    target_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []

    font_banner = _load_font(20, bold=True)
    font_small = _load_font(18, bold=False)
    font_drug = _load_font(34, bold=True)
    font_dir = _load_font(24, bold=True)

    for spec in SAMPLE_LABELS:
        out_path = target_dir / spec["filename"]
        paths.append(out_path)
        if out_path.exists():
            continue

        img = Image.new("RGB", (820, 420), color=(255, 255, 255))
        draw = ImageDraw.Draw(img)

        # Outer border
        draw.rectangle([8, 8, 811, 411], outline=(23, 50, 77), width=3)
        # Top DEMO banner
        draw.rectangle([11, 11, 808, 54], fill=(234, 247, 246))
        draw.text(
            (28, 20),
            "DEMO SAMPLE LABEL - NOT A REAL PRESCRIPTION",
            fill=(23, 50, 77),
            font=font_banner,
        )

        draw.text((28, 70), spec["pharmacy"], fill=(60, 72, 88), font=font_small)
        draw.text((28, 102), spec["rx_line"], fill=(60, 72, 88), font=font_small)
        draw.line([(28, 136), (790, 136)], fill=(200, 210, 220), width=2)

        # Prominent drug name + strength
        draw.text((28, 154), spec["drug_line"], fill=(0, 0, 0), font=font_drug)
        draw.text((28, 204), spec["brand_line"], fill=(40, 52, 68), font=font_small)

        # Directions box
        draw.rectangle([24, 246, 792, 314], outline=(180, 192, 206), width=2)
        draw.text((38, 266), spec["directions"], fill=(0, 0, 0), font=font_dir)

        draw.text((28, 344), spec["footer"], fill=(60, 72, 88), font=font_small)
        img.save(out_path, format="PNG")

    return paths


def ensure_logo_svg(assets_dir: Path | None = None) -> Path:
    """Create the clean healthcare shield + checkmark SVG logo in `assets/logo.svg`."""
    target_dir = Path(assets_dir or config.ASSETS_DIR)
    target_dir.mkdir(parents=True, exist_ok=True)
    logo_path = target_dir / "logo.svg"
    svg = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 56" role="img" aria-label="MedSafe logo">
  <defs>
    <linearGradient id="msShield" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#17324D"/>
      <stop offset="100%" stop-color="#0F8B8D"/>
    </linearGradient>
  </defs>
  <path d="M28 4 L48 11 V26 C48 39 39.5 48.2 28 52 C16.5 48.2 8 39 8 26 V11 Z" fill="url(#msShield)"/>
  <path d="M28 13 V25 M22 19 H34" stroke="#EAF7F6" stroke-width="3.2" stroke-linecap="round"/>
  <path d="M19 33 L25.5 39 L37.5 27" fill="none" stroke="#FFFFFF" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"/>
  <text x="60" y="34" font-family="Segoe UI, Inter, system-ui, -apple-system, sans-serif" font-size="26" font-weight="700" fill="#17324D">Med</text>
  <text x="115" y="34" font-family="Segoe UI, Inter, system-ui, -apple-system, sans-serif" font-size="26" font-weight="700" fill="#0F8B8D">Safe</text>
  <text x="61" y="48" font-family="Segoe UI, Inter, system-ui, -apple-system, sans-serif" font-size="10.5" font-weight="600" fill="#566579" letter-spacing="0.4">MEDICATION SAFETY COMPANION</text>
</svg>
"""
    logo_path.write_text(svg, encoding="utf-8")
    return logo_path


if __name__ == "__main__":
    ensure_logo_svg()
    paths = ensure_sample_labels()
    eng = detect_tesseract()
    print("Tesseract:", eng)
    for p in paths:
        res, _, _ = scan_label_image(p, use_network=False)
        print(
            p.name,
            "-> proposed:",
            res.proposed_name,
            "| strength:",
            res.proposed_strength,
            "| form:",
            res.proposed_form,
            "| dir:",
            res.proposed_instructions,
            "| status:",
            res.identity_status,
            "| pii_redacted:",
            res.pii_redacted_count,
        )
        _ = normalize_name
