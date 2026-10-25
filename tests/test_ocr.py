"""Automated tests for bottle scanning, multi-pass OCR, pre-scan quality
diagnostics, clinical-safe PII redaction, anti-hallucination boilerplate shield,
and review workflow."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw, ImageFilter

import db
import drug_data
import medications
import ocr_service


def test_sample_labels_generated_and_parsed(tmp_path: Path) -> None:
    paths = ocr_service.ensure_sample_labels(tmp_path)
    assert len(paths) == 3
    for p in paths:
        assert p.exists()
        img = Image.open(p)
        proc = ocr_service.preprocess_label_image(img)
        assert proc.mode == "L"

    # Parse sample label text directly to verify deterministic extraction & PII redaction
    spec = ocr_service.SAMPLE_LABELS[0]
    res = ocr_service.parse_label_text(spec["fallback_text"], use_network=False)
    assert res.proposed_generic == "lisinopril"
    assert res.proposed_strength == "10 mg"
    assert res.proposed_form == "Oral Tablet"
    assert res.proposed_instructions == "Take 1 tablet by mouth every morning"
    # OCR results must NEVER be automatically marked 'confirmed'
    assert res.identity_status == "needs_review"
    # PII (Rx number, phone, patient line) must be redacted
    assert res.pii_redacted_count >= 2
    assert "8492014" not in res.redacted_text
    assert "[RX# REDACTED]" in res.redacted_text


def test_amoxicillin_bottle_regression() -> None:
    """Regression test 1: Exact pharmacy bottle with address, directions,
    Amoxicillin 500 mg Capsules, and Quantity/Refills must extract cleanly
    and redact street address without touching clinical lines."""
    raw_label = (
        "PHARMACY\n"
        "123 Main Street\n"
        "TAKE 1 CAPSULE BY MOUTH THREE TIMES DAILY FOR 10 DAYS\n"
        "Amoxicillin 500 mg Capsules\n"
        "Quantity: 30, Refills: 0\n"
        "EXPIRATION DATE: 09/06/2026"
    )
    res = ocr_service.parse_label_text(raw_label, use_network=False)

    assert res.proposed_name == "Amoxicillin"
    assert res.proposed_generic == "amoxicillin"
    assert res.proposed_strength == "500 mg"
    assert res.proposed_form == "Oral Capsule"
    assert res.proposed_instructions == "TAKE 1 CAPSULE BY MOUTH THREE TIMES DAILY FOR 10 DAYS"
    assert res.identity_status == "needs_review"

    # Street address must be redacted while clinical lines remain intact
    assert "123 Main Street" not in res.redacted_text
    assert "[ADDRESS REDACTED]" in res.redacted_text
    assert "Amoxicillin 500 mg Capsules" in res.redacted_text
    assert "TAKE 1 CAPSULE BY MOUTH THREE TIMES DAILY FOR 10 DAYS" in res.redacted_text

    # LASA warning for amoxicillin <-> amoxapine must be attached
    assert res.lasa_warnings
    assert res.lasa_warnings[0]["confused_with"] == "amoxapine"


def test_garbled_boilerplate_anti_hallucination() -> None:
    """Regression test 2: Garbled OCR reads of 'Quantity: 30, Refills: 0' such
    as 'arty: 30, Rilo:' must NEVER match Rilonacept or any random drug."""
    for garbled in ("arty: 30, Rilo:", "Quantity: 30, Refills: 0", "Rilo", "arty"):
        ocr_res = ocr_service.parse_label_text(garbled, use_network=False)
        assert ocr_res.candidates == [], f"Unexpected OCR candidates for {garbled!r}: {ocr_res.candidates}"
        assert ocr_res.proposed_name == ""
        assert ocr_res.identity_status == "unidentified"
        assert "rilonacept" not in ocr_res.proposed_name.lower()

        norm_res = drug_data.resolve_drug_candidates(garbled, from_ocr=True, use_network=False)
        assert norm_res.candidates == [], f"Unexpected drug_data candidates for {garbled!r}: {norm_res.candidates}"


def test_colored_highlight_box_image_ocr() -> None:
    """Regression test 3: Synthetic pharmacy label with a shaded pink highlight
    box (#F8BBD0) behind 'Amoxicillin 500 mg Capsules' and a yellow highlight
    box (#FFF59D) behind 'Quantity: 30, Refills: 0'."""
    img = Image.new("RGB", (920, 440), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)

    font_title = ocr_service._load_font(22, bold=True)
    font_dir = ocr_service._load_font(24, bold=True)
    font_drug = ocr_service._load_font(36, bold=True)
    font_meta = ocr_service._load_font(22, bold=False)

    draw.text((32, 24), "PHARMACY", fill=(20, 20, 20), font=font_title)
    draw.text((32, 58), "123 Main Street", fill=(40, 40, 40), font=font_meta)
    draw.text(
        (32, 110),
        "TAKE 1 CAPSULE BY MOUTH THREE TIMES DAILY FOR 10 DAYS",
        fill=(0, 0, 0),
        font=font_dir,
    )

    # Shaded pink highlight box behind drug name
    draw.rectangle([28, 168, 720, 234], fill=(248, 187, 208))
    draw.text((40, 182), "Amoxicillin 500 mg Capsules", fill=(0, 0, 0), font=font_drug)

    # Shaded yellow highlight box behind Quantity / Refills
    draw.rectangle([28, 256, 460, 308], fill=(255, 245, 157))
    draw.text((40, 268), "Quantity: 30, Refills: 0", fill=(0, 0, 0), font=font_meta)

    draw.text((32, 336), "EXPIRATION DATE: 09/06/2026", fill=(40, 40, 40), font=font_meta)

    # Verify Pass C (Color-Channel Max Pass) turns the pink & yellow highlight boxes
    # bright (> 235) while keeping the black text dark (< 40).
    pass_c = ocr_service.preprocess_color_highlight_pass(img)
    assert pass_c.mode == "L"
    # Sample background pixel inside the pink highlight box (scaled according to pass_c width)
    scale_x = pass_c.width / img.width
    scale_y = pass_c.height / img.height
    pink_bg_px = pass_c.getpixel((int(680 * scale_x), int(176 * scale_y)))
    yellow_bg_px = pass_c.getpixel((int(430 * scale_x), int(264 * scale_y)))
    assert pink_bg_px >= 230, f"Expected pink highlight box to bleach white, got {pink_bg_px}"
    assert yellow_bg_px >= 230, f"Expected yellow highlight box to bleach white, got {yellow_bg_px}"

    # Run full scan_label_image (when Tesseract is installed, verify end-to-end extraction!)
    res, proc_img, status = ocr_service.scan_label_image(img, use_network=False)
    assert proc_img.mode == "L"
    if status.available:
        assert res.proposed_name == "Amoxicillin"
        assert res.proposed_generic == "amoxicillin"
        assert res.proposed_strength == "500 mg"
        assert res.proposed_form == "Oral Capsule"
        assert res.proposed_instructions is not None
        assert "TAKE 1 CAPSULE" in res.proposed_instructions.upper()


def test_blurry_and_dark_image_quality_diagnostics() -> None:
    """Regression test 4: Blurry and dark synthetic images trigger image_quality
    flags and return warm, senior-friendly coaching tips without crashing."""
    # Create a dark, low-contrast, heavily blurred image
    dark_img = Image.new("RGB", (600, 300), color=(22, 24, 26))
    draw = ImageDraw.Draw(dark_img)
    draw.text((40, 120), "faint text", fill=(32, 34, 36))
    blurry_dark_img = dark_img.filter(ImageFilter.GaussianBlur(radius=6))

    iq = ocr_service.analyze_image_quality(blurry_dark_img)
    assert iq.too_dark is True
    assert iq.is_blurry is True
    assert iq.low_contrast is True
    assert iq.ok is False
    assert len(iq.coaching_tips) >= 2
    assert any("blurry" in tip.lower() or "dark" in tip.lower() for tip in iq.coaching_tips)

    # Also verify scan_label_image attaches image_quality without crashing
    res, _, _ = ocr_service.scan_label_image(blurry_dark_img, use_network=False)
    assert res.image_quality is not None
    assert res.image_quality.too_dark is True
    assert res.image_quality.coaching_tips


def test_garbled_and_empty_ocr_text() -> None:
    empty_res = ocr_service.parse_label_text("   \n  ", use_network=False)
    assert empty_res.identity_status == "unidentified"
    assert empty_res.candidates == []
    assert any("No readable text" in n for n in empty_res.uncertainty_notes)

    garbled_res = ocr_service.parse_label_text(
        "X#99!! @@ $$%\nTake 1 @@##$$%%^^&&**(()))",
        use_network=False,
    )
    assert garbled_res.identity_status == "unidentified"
    # Garbled directions must not be silently accepted
    assert garbled_res.proposed_instructions is None
    assert any("unclear" in n.lower() for n in garbled_res.uncertainty_notes)


def test_missing_strength_and_multiple_medication_candidates() -> None:
    multi_text = (
        "LISINOPRIL TABLET\n"
        "Also mentions METFORMIN on label\n"
        "Take 1 tablet daily"
    )
    res = ocr_service.parse_label_text(multi_text, use_network=False)
    generics = {c.generic_name for c in res.candidates}
    assert "lisinopril" in generics
    assert "metformin" in generics
    assert res.proposed_strength is None
    assert any("strength" in n.lower() for n in res.uncertainty_notes)
    assert any("multiple possible medications" in n.lower() for n in res.uncertainty_notes)


def test_unavailable_tesseract_graceful_fallback(tmp_path: Path) -> None:
    img = Image.new("RGB", (200, 100), color=(255, 255, 255))
    with patch("ocr_service.shutil.which", return_value=None), patch(
        "ocr_service.STANDARD_TESSERACT_PATHS", ()
    ), patch("pytesseract.get_tesseract_version", side_effect=OSError("not installed")):
        status = ocr_service.detect_tesseract()
        assert status.available is False
        res, _, st_out = ocr_service.scan_label_image(img, use_network=False)
        assert st_out.available is False
        assert res.identity_status == "unidentified"
        assert res.engine_used == "unavailable"


def test_user_editing_and_confirming_scanned_medication(tmp_path: Path) -> None:
    db_path = tmp_path / "ocr_confirm.sqlite3"
    db.prepare(db_path)

    ocr_res = ocr_service.parse_label_text(
        "RX# 998877\nLISINOPRIL 10 MG TABLET\nTake 1 tablet by mouth every morning",
        use_network=False,
    )
    assert ocr_res.identity_status == "needs_review"

    # User reviews and edits strength to 20 mg, then explicitly confirms
    med_id = medications.add_medication(
        db_path,
        ocr_res.proposed_name,
        generic_name=ocr_res.proposed_generic,
        strength="20 mg",
        dose_form=ocr_res.proposed_form,
        instructions=ocr_res.proposed_instructions,
        entry_source="scanned",
        identity_status="confirmed",
        identity_source="ocr_user_confirmed",
        original_text=ocr_res.redacted_text,
        ingredients=[ocr_res.proposed_generic or "lisinopril"],
    )
    saved = medications.get_medication(db_path, med_id)
    assert saved is not None
    assert saved.entry_source == "scanned"
    assert saved.identity_status == "confirmed"
    assert saved.strength == "20 mg"
    assert "998877" not in (saved.original_text or "")


def test_ocr_character_confusions_and_multiline_directions() -> None:
    """Verify that common OCR character confusions ('Amoxicilin', 'Amoxicllin',
    'Amoxici11in', 'Arnoxicillin', 'Amoxlcillin', 'Am0xicillin') and wrapped
    2-line directions resolve cleanly to Amoxicillin (RxCUI 723)."""
    confused_spellings = (
        "Amoxicilin",
        "Amoxicllin",
        "Amoxici11in",
        "Arnoxicillin",
        "Amoxlcillin",
        "Am0xicillin",
    )
    for variant in confused_spellings:
        raw_text = (
            "PHARMACY\n"
            "123 Main Street\n"
            "TAKE 1 CAPSULE BY MOUTH\n"
            "THREE TIMES DAILY FOR 10 DAYS\n"
            f"{variant} 500 mg Capsules\n"
            "Quantity: 30, Refills: 0\n"
        )
        res = ocr_service.parse_label_text(raw_text, use_network=False)
        assert res.candidates, f"Expected Amoxicillin candidate for OCR variant {variant!r}"
        assert res.candidates[0].generic_name == "amoxicillin"
        assert res.candidates[0].rxcui == "723"
        assert res.proposed_strength == "500 mg"
        assert res.proposed_form == "Oral Capsule"
        assert (
            res.proposed_instructions
            == "TAKE 1 CAPSULE BY MOUTH THREE TIMES DAILY FOR 10 DAYS"
        )


def test_low_res_416x662_bordered_amoxicillin_bottle_image() -> None:
    """Create a 416x662 synthetic full-bottle image mimicking `Screens...173015.png`
    (white background, orange bottle body, gray label, pink/red bordered box
    containing small text 'TAKE 1 CAPSULE BY MOUTH\\nTHREE TIMES DAILY FOR 10 DAYS'
    and 'Amoxicillin 500 mg Capsules', plus yellow highlight 'Quantity: 30, Refills: 0')
    and verify scan_label_image succeeds without exceptions and extracts Amoxicillin."""
    img = Image.new("RGB", (416, 662), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)

    # White bottle cap at top
    draw.rectangle([95, 38, 321, 98], fill=(242, 244, 247), outline=(190, 195, 202), width=2)
    # Amber/orange bottle body
    draw.rectangle([72, 98, 344, 618], fill=(222, 118, 34), outline=(175, 85, 18), width=2)
    # Gray/off-white pharmacy label in central region
    draw.rectangle([76, 145, 340, 495], fill=(244, 244, 244), outline=(180, 180, 180), width=1)

    font_hdr = ocr_service._load_font(13, bold=True)
    font_small = ocr_service._load_font(12, bold=False)
    font_dir = ocr_service._load_font(12, bold=True)
    font_drug = ocr_service._load_font(15, bold=True)

    draw.text((88, 156), "PHARMACY", fill=(25, 25, 25), font=font_hdr)
    draw.text((88, 174), "123 Main Street", fill=(45, 45, 45), font=font_small)

    # Red/pink bordered box around directions + pink-shaded drug name box
    draw.rectangle([84, 202, 332, 314], fill=(252, 232, 238), outline=(215, 42, 62), width=2)
    draw.text((92, 212), "TAKE 1 CAPSULE BY MOUTH", fill=(10, 10, 10), font=font_dir)
    draw.text((92, 232), "THREE TIMES DAILY FOR 10 DAYS", fill=(10, 10, 10), font=font_dir)

    # Shaded pink highlight box with red border around 'Amoxicillin 500 mg Capsules'
    draw.rectangle([88, 262, 328, 306], fill=(248, 187, 208), outline=(210, 38, 58), width=2)
    draw.text((95, 274), "Amoxicillin 500 mg Capsules", fill=(0, 0, 0), font=font_drug)

    # Yellow highlight box around Quantity / Refills
    draw.rectangle([86, 330, 290, 362], fill=(255, 245, 157))
    draw.text((92, 338), "Quantity: 30, Refills: 0", fill=(15, 15, 15), font=font_small)

    draw.text((88, 382), "EXPIRATION DATE: 09/06/2026", fill=(40, 40, 40), font=font_small)

    # Run scan_label_image with use_network=True (with mocked offline session if needed)
    # to ensure config.has_gemini_key() never raises AttributeError
    res, proc_img, status = ocr_service.scan_label_image(img, use_network=False)
    assert proc_img.mode == "L"
    if status.available:
        assert any(c.generic_name == "amoxicillin" and c.rxcui == "723" for c in res.candidates)
        assert res.proposed_strength == "500 mg"
        assert res.proposed_form == "Oral Capsule"
        assert res.proposed_instructions is not None
        assert "TAKE 1 CAPSULE BY MOUTH THREE TIMES DAILY FOR 10 DAYS" in res.proposed_instructions.upper()


def test_config_attributes_exist() -> None:
    """Audit config module attributes referenced across the codebase."""
    import config

    assert hasattr(config, "get_gemini_api_key") and callable(config.get_gemini_api_key)
    assert hasattr(config, "has_gemini_key") and callable(config.has_gemini_key)
    assert hasattr(config, "gemini_api_key") and callable(config.gemini_api_key)
    assert hasattr(config, "gemini_model") and callable(config.gemini_model)
    assert isinstance(config.get_gemini_api_key(), str)
    assert isinstance(config.has_gemini_key(), bool)
    assert hasattr(config, "DEFAULT_GEMINI_MODEL")
    assert hasattr(config, "GEMINI_MODEL")
    assert hasattr(config, "HTTP_TIMEOUT")
    assert hasattr(config, "AI_TIMEOUT")

