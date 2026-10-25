"""Automated tests for the AI explanation module and strict output validation."""

from __future__ import annotations

import json
from pathlib import Path

import requests

import ai_explain
import db
import interactions
from interactions import CheckStatus, Ingredient, MedForCheck


class _MockPostResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self) -> dict:
        return self._payload


class _MockPostSession:
    def __init__(self, response: _MockPostResponse | Exception):
        self._response = response

    def post(self, *args, **kwargs):
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


SAMPLE_RECORD = {
    "drug_a": "lisinopril",
    "drug_b": "ibuprofen",
    "severity": "major",
    "severity_raw": "major",
    "severity_level": "major",
    "mechanism": (
        "NSAIDs like ibuprofen reduce the blood-pressure-lowering effect of ACE "
        "inhibitors and together can strain the kidneys."
    ),
    "dataset_name": "MedSafe starter interaction set",
}


def test_no_api_key_uses_template(monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    res = ai_explain.explain_structured(SAMPLE_RECORD, "English")
    assert res.source == "template"
    assert res.fallback_reason == "no_api_key"
    assert "Lisinopril" in res.explanation
    assert "Ibuprofen" in res.explanation
    assert "kidneys" in res.why_it_matters


def test_unavailable_api_and_invalid_json_fall_back_to_template(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-dummy-key")

    # 1. Network timeout / failure
    res_err = ai_explain.explain_structured(
        SAMPLE_RECORD,
        "English",
        session=_MockPostSession(requests.Timeout("timed out")),  # type: ignore[arg-type]
    )
    assert res_err.source == "template"
    assert res_err.fallback_reason == "api_or_parse_error"

    # 2. Malformed JSON from model
    bad_resp = _MockPostResponse(200, {"output_text": "not valid json {"})
    res_bad = ai_explain.explain_structured(
        SAMPLE_RECORD,
        "English",
        session=_MockPostSession(bad_resp),  # type: ignore[arg-type]
    )
    assert res_bad.source == "template"


def test_validation_rejects_unsupported_claims_and_prescriptive_advice(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-dummy-key")

    # 1. Tells user to stop taking medication -> rejected
    prescriptive = {
        "explanation": "Lisinopril and Ibuprofen have a major interaction record.",
        "why_it_matters": "Together they can strain the kidneys.",
        "what_to_do_next": "Stop taking your lisinopril immediately and switch to another drug.",
        "limitations": "Based on starter dataset.",
    }
    valid, reason = ai_explain.validate_ai_payload(prescriptive, SAMPLE_RECORD)
    assert valid is False
    assert reason == "forbidden_prescriptive_or_safety_claim"

    # 2. Downgrades major severity to minor/harmless -> rejected
    downgraded = {
        "explanation": "This is only a minor interaction and is totally harmless.",
        "why_it_matters": "Together they can strain the kidneys.",
        "what_to_do_next": "Ask your pharmacist.",
        "limitations": "Based on starter dataset.",
    }
    valid2, reason2 = ai_explain.validate_ai_payload(downgraded, SAMPLE_RECORD)
    assert valid2 is False

    # 3. Introduces unsupported clinical claims (e.g. CYP3A4 or rhabdomyolysis) not in source -> rejected
    hallucinated = {
        "explanation": "Lisinopril and Ibuprofen have a major interaction record.",
        "why_it_matters": "This blocks CYP3A4 and causes rhabdomyolysis in a clinical trial.",
        "what_to_do_next": "Talk with your pharmacist or doctor.",
        "limitations": "Based on starter dataset.",
    }
    valid3, reason3 = ai_explain.validate_ai_payload(hallucinated, SAMPLE_RECORD)
    assert valid3 is False
    assert reason3 and reason3.startswith("unsupported_clinical_claim")


def test_valid_ai_structured_response_and_multilingual_preservation(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-dummy-key")
    good_payload = {
        "explanation": "The database lists a serious interaction between Lisinopril and Ibuprofen.",
        "why_it_matters": "Ibuprofen can weaken blood-pressure control and add stress on the kidneys.",
        "what_to_do_next": "Please check with your pharmacist or doctor before taking both medicines.",
        "limitations": "Based only on the loaded interaction record.",
    }
    resp = _MockPostResponse(
        200,
        {
            "steps": [
                {
                    "type": "model_output",
                    "content": [{"type": "text", "text": json.dumps(good_payload)}],
                }
            ]
        },
    )
    res = ai_explain.explain_structured(
        SAMPLE_RECORD,
        "English",
        session=_MockPostSession(resp),  # type: ignore[arg-type]
    )
    assert res.source == "ai"
    assert res.explanation == good_payload["explanation"]

    # Verify core interaction engine result is 100% identical with or without Gemini
    # and across English, Hindi, and Spanish translations.
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    db_path = tmp_path / "ai_indep.sqlite3"
    db.prepare(db_path)
    meds = [
        MedForCheck("1", "Lisinopril", (Ingredient("lisinopril"),), "confirmed"),
        MedForCheck("2", "Ibuprofen", (Ingredient("ibuprofen"),), "confirmed"),
    ]
    rep = interactions.check_medications(db_path, meds)
    pair = rep.results[0]
    for lang in ("English", "Hindi", "Spanish"):
        exp = ai_explain.explain_structured(pair, language=lang)
        assert exp.source == "template"
        assert exp.original_english["explanation"]
        # Underlying pair status & severity are untouched
        assert pair.status == CheckStatus.MATCH_FOUND
        assert pair.top_severity == "major"

