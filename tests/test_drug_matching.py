"""Automated tests for conservative drug-name normalization, anti-hallucination
boilerplate shield, LASA Tall-Man Lettering guard, and openFDA lookup."""

from __future__ import annotations

import requests

import drug_data


class _FailingSession:
    """Simulated requests.Session that raises a timeout on every call."""

    def get(self, *args, **kwargs):
        raise requests.Timeout("simulated timeout")


class _MockResponse:
    def __init__(self, status_code: int, payload: object):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _MockSession:
    def __init__(self, response: _MockResponse):
        self._response = response

    def get(self, *args, **kwargs):
        return self._response


def test_exact_generic_match_offline() -> None:
    drug_data.clear_cache()
    res = drug_data.resolve_drug_candidates("Lisinopril 10 mg", use_network=False)
    assert res.candidates
    top = res.candidates[0]
    assert top.generic_name == "lisinopril"
    assert top.strength == "10 mg"
    assert top.rxcui == "29046"
    assert res.exact_match is True


def test_antibiotic_catalog_and_plural_dosage_forms() -> None:
    drug_data.clear_cache()
    res = drug_data.resolve_drug_candidates("Amoxicillin 500 mg Capsules", use_network=False)
    assert res.candidates
    top = res.candidates[0]
    assert top.generic_name == "amoxicillin"
    assert top.strength == "500 mg"
    assert top.dose_form == "Oral Capsule"
    assert res.exact_match is True


def test_lasa_confusion_guard_tall_man_lettering() -> None:
    """Regression test 5: Verify that resolving hydralazine or amoxicillin
    returns the expected FDA/ISMP LASA confusion warning with Tall-Man Lettering."""
    drug_data.clear_cache()

    hydra_res = drug_data.resolve_drug_candidates("Hydralazine 25 mg", use_network=False)
    assert hydra_res.candidates
    hydra_lasa = hydra_res.candidates[0].lasa_warning
    assert hydra_lasa is not None
    assert hydra_lasa["confused_with"] == "hydroxyzine"
    assert hydra_lasa["tall_man"] == "hydrALAZINE"
    assert hydra_lasa["confused_tall_man"] == "hydrOXYzine"
    assert "blood pressure" in hydra_lasa["purpose"].lower()

    amox_res = drug_data.resolve_drug_candidates("Amoxicillin 500 mg", use_network=False)
    assert amox_res.candidates
    amox_lasa = amox_res.candidates[0].lasa_warning
    assert amox_lasa is not None
    assert amox_lasa["confused_with"] == "amoxapine"
    assert amox_lasa["tall_man"] == "amoxiCILLIN"
    assert amox_lasa["confused_tall_man"] == "amoxAPINE"
    assert "antibiotic" in amox_lasa["purpose"].lower()


def test_rxnorm_similarity_gate_blocks_rilonacept_hallucination() -> None:
    """Verify that even if RxNorm /approximateTerm were to return 'Rilonacept'
    for a garbled or short query, our >= 0.78 similarity gate and boilerplate
    shield reject it completely."""
    drug_data.clear_cache()
    assert drug_data.is_boilerplate_or_noise_token("Rilo") is True
    assert drug_data.is_boilerplate_or_noise_token("arty") is True
    assert drug_data.is_boilerplate_or_noise_token("Refills") is True
    assert drug_data.is_boilerplate_or_noise_token("Amoxicillin") is False

    # Similarity between 'rilo' and 'rilonacept' is ~0.57 < 0.78
    sim = drug_data._compute_candidate_similarity("rilo", "Rilonacept")
    assert sim < drug_data.MIN_CANDIDATE_SIMILARITY


def test_brand_and_combination_require_confirmation() -> None:
    drug_data.clear_cache()
    advil_pm = drug_data.resolve_drug_candidates("Advil PM", use_network=False)
    assert advil_pm.candidates
    cand = advil_pm.candidates[0]
    assert cand.is_combination is True
    assert {i.name for i in cand.ingredients} == {"ibuprofen", "diphenhydramine"}
    assert advil_pm.requires_confirmation is True

    zestoretic = drug_data.resolve_drug_candidates("Zestoretic", use_network=False)
    assert zestoretic.candidates
    assert {i.name for i in zestoretic.candidates[0].ingredients} == {
        "lisinopril",
        "hydrochlorothiazide",
    }
    assert zestoretic.requires_confirmation is True


def test_fuzzy_match_is_never_auto_confirmed() -> None:
    drug_data.clear_cache()
    res = drug_data.resolve_drug_candidates("lisinoprl", use_network=False)
    assert res.candidates
    assert res.candidates[0].generic_name == "lisinopril"
    assert res.candidates[0].match_type == "approximate"
    assert res.exact_match is False
    assert res.requires_confirmation is True
    # Compatibility helper must return None for fuzzy matches so callers never
    # silently substitute a misspelled name without confirmation.
    assert drug_data.normalize_drug_name("lisinoprl", use_network=False) is None


def test_unknown_and_invalid_queries() -> None:
    drug_data.clear_cache()
    unk = drug_data.resolve_drug_candidates("completely_unknown_drug_999", use_network=False)
    assert unk.candidates == []
    assert unk.exact_match is False
    assert unk.requires_confirmation is True

    short = drug_data.resolve_drug_candidates("x", use_network=False)
    assert short.api_status == "invalid_query"
    assert short.candidates == []


def test_network_timeout_falls_back_gracefully() -> None:
    drug_data.clear_cache()
    res = drug_data.resolve_drug_candidates(
        "Metformin 500 mg",
        use_network=True,
        session=_FailingSession(),  # type: ignore[arg-type]
    )
    assert res.api_status == "offline_fallback"
    assert res.candidates
    assert res.candidates[0].generic_name == "metformin"


def test_openfda_label_parsing_and_error_handling() -> None:
    drug_data.clear_cache()
    payload = {
        "results": [
            {
                "effective_time": "20250412",
                "set_id": "abc-123-def",
                "drug_interactions": ["NSAIDs may diminish the antihypertensive effect."],
                "warnings": ["Monitor renal function."],
                "openfda": {
                    "generic_name": ["LISINOPRIL"],
                    "brand_name": ["PRINIVIL"],
                },
            }
        ]
    }
    info = drug_data.get_label_info(
        "lisinopril",
        session=_MockSession(_MockResponse(200, payload)),  # type: ignore[arg-type]
    )
    assert info["effective_date"] == "2025-04-12"
    assert "abc-123-def" in info["label_url"]
    assert "NSAIDs" in info["drug_interactions"]
    assert "openFDA" in info["disclaimer"]

    # Network failure or 404 returns empty dict cleanly
    drug_data.clear_cache()
    empty = drug_data.get_label_info(
        "lisinopril",
        session=_FailingSession(),  # type: ignore[arg-type]
    )
    assert empty == {}
