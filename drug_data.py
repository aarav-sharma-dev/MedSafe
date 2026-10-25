"""Drug-name normalization (NLM RxNorm + local reference catalog),
anti-hallucination boilerplate filtering, FDA Look-Alike/Sound-Alike (LASA)
confusion guards, and supplementary drug-label retrieval (U.S. FDA openFDA).

Safety & design rules enforced here:
* RxNorm is used ONLY to identify and normalize medication names and active
  ingredients. Deprecated RxNav drug-interaction endpoints are never used.
* Pharmacy label boilerplate and OCR noise fragments (e.g. ``"arty"`` from
  ``"Quantity"`` or ``"Rilo"`` from ``"Refills"``) are blocked via exact and
  fuzzy boilerplate filtering before any local or RxNorm lookup.
* RxNorm ``/approximateTerm`` candidates must pass a strict character-similarity
  gate (>= 0.78) against the cleaned query token; low-similarity guesses such
  as ``"Rilo" -> "Rilonacept"`` are rejected outright.
* Matching is conservative: fuzzy/approximate matches, brand names,
  combination products, and multi-candidate results always set
  ``requires_confirmation=True`` and are never silently accepted as verified.
* FDA Look-Alike / Sound-Alike (LASA) drug pairs include Tall-Man Lettering
  and plain-English purpose descriptions so seniors can double-check similar
  medication names on their physical bottle.
"""

from __future__ import annotations

import difflib
import re
import time
from dataclasses import dataclass, field

import requests

import config
from dataset_import import normalize_name
from interactions import Ingredient

RXNORM_BASE = "https://rxnav.nlm.nih.gov/REST"
OPENFDA_LABEL = "https://api.fda.gov/drug/label.json"

NLM_ATTRIBUTION = (
    "This product uses publicly available data from the U.S. National Library "
    "of Medicine (NLM), National Institutes of Health, Department of Health "
    "and Human Services; NLM is not responsible for the product and does not "
    "endorse or recommend this or any other product."
)

OPENFDA_ATTRIBUTION = (
    "Source: U.S. Food and Drug Administration (openFDA Drug Labeling API). "
    "Do not rely on openFDA alone to make decisions regarding medical care."
)

# Simple in-process TTL cache so repeated UI reruns do not hammer public APIs.
_CACHE: dict[str, tuple[float, object]] = {}
_CACHE_TTL_SECONDS = 900.0
_LAST_REQUEST_TS = 0.0
_MIN_REQUEST_INTERVAL = 0.06  # < 16 req/sec, well under RxNorm's 20 req/sec limit


def clear_cache() -> None:
    _CACHE.clear()


def _cached_get_json(
    url: str,
    params: dict | None = None,
    timeout: float | None = None,
    session: requests.Session | None = None,
) -> tuple[dict | None, str | None]:
    """Perform a GET request with timeout, polite rate-limiting, and caching.
    Returns (json_dict, error_code)."""
    global _LAST_REQUEST_TS
    key = f"{url}?{sorted((params or {}).items())}"
    now = time.monotonic()
    hit = _CACHE.get(key)
    if hit and (now - hit[0]) < _CACHE_TTL_SECONDS:
        return hit[1], None  # type: ignore[return-value]

    elapsed = now - _LAST_REQUEST_TS
    if elapsed < _MIN_REQUEST_INTERVAL:
        time.sleep(_MIN_REQUEST_INTERVAL - elapsed)

    http = session or requests
    try:
        resp = http.get(url, params=params, timeout=timeout or config.HTTP_TIMEOUT)
        _LAST_REQUEST_TS = time.monotonic()
    except requests.Timeout:
        return None, "timeout"
    except requests.RequestException:
        return None, "network_error"

    if resp.status_code == 429:
        return None, "rate_limited"
    if resp.status_code == 404:
        return None, "not_found"
    if resp.status_code >= 400:
        return None, f"http_{resp.status_code}"

    try:
        data = resp.json()
    except ValueError:
        return None, "invalid_json"
    if not isinstance(data, dict):
        return None, "invalid_json"

    _CACHE[key] = (time.monotonic(), data)
    return data, None


# --- Pharmacy Boilerplate Shield & Fuzzy Noise Filter ----------------------

PHARMACY_BOILERPLATE_WORDS: frozenset[str] = frozenset(
    {
        "pharmacy", "rx", "qty", "quantity", "refill", "refills", "no", "dr", "md",
        "prescriber", "expiration", "exp", "date", "discard", "after", "ndc", "lot",
        "mfg", "take", "capsule", "capsules", "tablet", "tablets", "caplet", "caplets",
        "pill", "pills", "softgel", "softgels", "mouth", "oral", "daily", "twice",
        "three", "four", "once", "times", "time", "day", "days", "hour", "hours",
        "every", "with", "without", "food", "water", "milk", "meal", "meals",
        "morning", "evening", "night", "bedtime", "finish", "all", "medication",
        "medicine", "unless", "otherwise", "directed", "warning", "caution", "keep",
        "out", "reach", "children", "store", "room", "temperature", "federal", "law",
        "prohibits", "transfer", "any", "person", "other", "than", "patient", "whom",
        "prescribed", "main", "street", "st", "ave", "avenue", "road", "rd", "blvd",
        "boulevard", "lane", "ln", "drive", "court", "ct", "hometown", "call",
        "doctor", "pharmacist", "label", "bottle", "sample", "demo", "redacted",
        "phone", "address", "generic", "brand", "substituted", "compare", "active",
        "ingredient", "pain", "reliever", "fever", "reducer", "nsaid", "item",
        "market", "counter", "over", "community", "corner", "health", "center",
        "use", "inhale", "apply", "inject", "dissolve", "insert", "instill",
        "needed", "for", "and", "the", "from",
    }
)

# Short (<= 4 character) legitimate drug/brand/qualifier tokens allowed in queries
KNOWN_SHORT_DRUG_NAMES: frozenset[str] = frozenset(
    {"tums", "yaz", "iron", "zinc", "b12", "d3", "gaba", "pm", "am", "q10", "coq10"}
)

MIN_CANDIDATE_SIMILARITY: float = 0.78

# --- FDA Look-Alike / Sound-Alike (LASA) Confusion Registry ----------------

LASA_CONFUSION_PAIRS: dict[str, dict[str, str]] = {
    "amoxicillin": {
        "drug": "amoxicillin",
        "tall_man": "amoxiCILLIN",
        "purpose": "Antibiotic used to treat bacterial infections",
        "confused_with": "amoxapine",
        "confused_tall_man": "amoxAPINE",
        "confused_purpose": "Antidepressant medication",
        "warning": (
            "Look-Alike Name Check: Verify whether your bottle says **amoxiCILLIN** "
            "(an antibiotic for infections) or **amoxAPINE** (an antidepressant)."
        ),
    },
    "amoxapine": {
        "drug": "amoxapine",
        "tall_man": "amoxAPINE",
        "purpose": "Antidepressant medication",
        "confused_with": "amoxicillin",
        "confused_tall_man": "amoxiCILLIN",
        "confused_purpose": "Antibiotic used to treat bacterial infections",
        "warning": (
            "Look-Alike Name Check: Verify whether your bottle says **amoxAPINE** "
            "(an antidepressant) or **amoxiCILLIN** (an antibiotic for infections)."
        ),
    },
    "hydralazine": {
        "drug": "hydralazine",
        "tall_man": "hydrALAZINE",
        "purpose": "Blood pressure medication (vasodilator)",
        "confused_with": "hydroxyzine",
        "confused_tall_man": "hydrOXYzine",
        "confused_purpose": "Allergy, itching, or anxiety medication (antihistamine)",
        "warning": (
            "Look-Alike Name Check: **hydrALAZINE** (for blood pressure) and "
            "**hydrOXYzine** (for allergies/itching/anxiety) look very similar on labels. "
            "Please double-check the middle letters (`-ALAZINE` vs `-OXYzine`) on your bottle."
        ),
    },
    "hydroxyzine": {
        "drug": "hydroxyzine",
        "tall_man": "hydrOXYzine",
        "purpose": "Allergy, itching, or anxiety medication (antihistamine)",
        "confused_with": "hydralazine",
        "confused_tall_man": "hydrALAZINE",
        "confused_purpose": "Blood pressure medication (vasodilator)",
        "warning": (
            "Look-Alike Name Check: **hydrOXYzine** (for allergies/itching/anxiety) and "
            "**hydrALAZINE** (for blood pressure) look very similar on labels. "
            "Please double-check the middle letters (`-OXYzine` vs `-ALAZINE`) on your bottle."
        ),
    },
    "glipizide": {
        "drug": "glipizide",
        "tall_man": "glipiZIDE",
        "purpose": "Diabetes blood-sugar medication (sulfonylurea)",
        "confused_with": "glyburide",
        "confused_tall_man": "glyBURIDE",
        "confused_purpose": "Diabetes medication (carries higher low-blood-sugar risk in older adults)",
        "warning": (
            "Look-Alike Name Check: Verify whether your bottle says **glipiZIDE** "
            "or **glyBURIDE** (both treat diabetes, but they are different prescriptions)."
        ),
    },
    "glyburide": {
        "drug": "glyburide",
        "tall_man": "glyBURIDE",
        "purpose": "Diabetes medication (carries higher low-blood-sugar risk in older adults)",
        "confused_with": "glipizide",
        "confused_tall_man": "glipiZIDE",
        "confused_purpose": "Diabetes blood-sugar medication (sulfonylurea)",
        "warning": (
            "Look-Alike Name Check: Verify whether your bottle says **glyBURIDE** "
            "or **glipiZIDE** (both treat diabetes, but they are different prescriptions)."
        ),
    },
    "metformin": {
        "drug": "metformin",
        "tall_man": "metFORMIN",
        "purpose": "Diabetes blood-sugar medication",
        "confused_with": "metronidazole",
        "confused_tall_man": "metRONIDAZOLE",
        "confused_purpose": "Antibiotic used to treat infections",
        "warning": (
            "Look-Alike Name Check: Verify whether your bottle says **metFORMIN** "
            "(for diabetes) or **metRONIDAZOLE** (an antibiotic)."
        ),
    },
    "metronidazole": {
        "drug": "metronidazole",
        "tall_man": "metRONIDAZOLE",
        "purpose": "Antibiotic used to treat infections",
        "confused_with": "metformin",
        "confused_tall_man": "metFORMIN",
        "confused_purpose": "Diabetes blood-sugar medication",
        "warning": (
            "Look-Alike Name Check: Verify whether your bottle says **metRONIDAZOLE** "
            "(an antibiotic) or **metFORMIN** (for diabetes)."
        ),
    },
    "prednisone": {
        "drug": "prednisone",
        "tall_man": "predniSONE",
        "purpose": "Oral corticosteroid for inflammation",
        "confused_with": "prednisolone",
        "confused_tall_man": "prednisoLONE",
        "confused_purpose": "Corticosteroid (different formulation)",
        "warning": (
            "Look-Alike Name Check: Verify whether your bottle says **predniSONE** "
            "or **prednisoLONE**."
        ),
    },
    "prednisolone": {
        "drug": "prednisolone",
        "tall_man": "prednisoLONE",
        "purpose": "Corticosteroid for inflammation",
        "confused_with": "prednisone",
        "confused_tall_man": "predniSONE",
        "confused_purpose": "Oral corticosteroid",
        "warning": (
            "Look-Alike Name Check: Verify whether your bottle says **prednisoLONE** "
            "or **predniSONE**."
        ),
    },
    "clonidine": {
        "drug": "clonidine",
        "tall_man": "clonIDINE",
        "purpose": "Blood pressure medication",
        "confused_with": "clonazepam",
        "confused_tall_man": "clonAZEPAM",
        "confused_purpose": "Anxiety or seizure medication (benzodiazepine)",
        "warning": (
            "Look-Alike Name Check: **clonIDINE** (for blood pressure) and "
            "**clonAZEPAM** (for anxiety/seizures) start with the same letters. "
            "Please verify the ending (`-IDINE` vs `-AZEPAM`) on your bottle."
        ),
    },
    "clonazepam": {
        "drug": "clonazepam",
        "tall_man": "clonAZEPAM",
        "purpose": "Anxiety or seizure medication (benzodiazepine)",
        "confused_with": "clonidine",
        "confused_tall_man": "clonIDINE",
        "confused_purpose": "Blood pressure medication",
        "warning": (
            "Look-Alike Name Check: **clonAZEPAM** (for anxiety/seizures) and "
            "**clonIDINE** (for blood pressure) start with the same letters. "
            "Please verify the ending (`-AZEPAM` vs `-IDINE`) on your bottle."
        ),
    },
    "celecoxib": {
        "drug": "celecoxib",
        "tall_man": "celeCOXIB (Celebrex)",
        "purpose": "Arthritis & pain reliever (NSAID)",
        "confused_with": "citalopram",
        "confused_tall_man": "citaloPRAM (Celexa)",
        "confused_purpose": "Antidepressant medication",
        "warning": (
            "Look-Alike Name Check: Verify whether your bottle says **celeCOXIB / Celebrex** "
            "(for arthritis pain) or **citaloPRAM / Celexa** (an antidepressant)."
        ),
    },
    "citalopram": {
        "drug": "citalopram",
        "tall_man": "citaloPRAM (Celexa)",
        "purpose": "Antidepressant medication",
        "confused_with": "celecoxib",
        "confused_tall_man": "celeCOXIB (Celebrex)",
        "confused_purpose": "Arthritis & pain reliever (NSAID)",
        "warning": (
            "Look-Alike Name Check: Verify whether your bottle says **citaloPRAM / Celexa** "
            "(an antidepressant) or **celeCOXIB / Celebrex** (for arthritis pain)."
        ),
    },
    "losartan": {
        "drug": "losartan",
        "tall_man": "loSARTAN",
        "purpose": "Blood pressure medication (ARB)",
        "confused_with": "valsartan",
        "confused_tall_man": "valSARTAN",
        "confused_purpose": "Blood pressure medication (ARB — different dosing)",
        "warning": (
            "Look-Alike Name Check: Verify whether your bottle says **loSARTAN** "
            "or **valSARTAN**."
        ),
    },
    "valsartan": {
        "drug": "valsartan",
        "tall_man": "valSARTAN",
        "purpose": "Blood pressure medication (ARB)",
        "confused_with": "losartan",
        "confused_tall_man": "loSARTAN",
        "confused_purpose": "Blood pressure medication (ARB — different dosing)",
        "warning": (
            "Look-Alike Name Check: Verify whether your bottle says **valSARTAN** "
            "or **loSARTAN**."
        ),
    },
    "bupropion": {
        "drug": "bupropion",
        "tall_man": "buPROPion",
        "purpose": "Mood or smoking-cessation medication",
        "confused_with": "buspirone",
        "confused_tall_man": "busPIRone",
        "confused_purpose": "Anxiety medication",
        "warning": (
            "Look-Alike Name Check: **buPROPion** and **busPIRone** look and sound "
            "very similar. Please verify the exact letters on your bottle."
        ),
    },
    "buspirone": {
        "drug": "buspirone",
        "tall_man": "busPIRone",
        "purpose": "Anxiety medication",
        "confused_with": "bupropion",
        "confused_tall_man": "buPROPion",
        "confused_purpose": "Mood or smoking-cessation medication",
        "warning": (
            "Look-Alike Name Check: **busPIRone** and **buPROPion** look and sound "
            "very similar. Please verify the exact letters on your bottle."
        ),
    },
}


def get_lasa_warning(drug_or_ingredient_name: str | None) -> dict[str, str] | None:
    """Return Look-Alike/Sound-Alike (LASA) Tall-Man verification metadata if the
    given medication or ingredient is in ``LASA_CONFUSION_PAIRS``."""
    if not drug_or_ingredient_name:
        return None
    norm = normalize_name(drug_or_ingredient_name)
    if norm in LASA_CONFUSION_PAIRS:
        return dict(LASA_CONFUSION_PAIRS[norm])
    for token in re.split(r"[\s+/()-]+", norm):
        if token in LASA_CONFUSION_PAIRS:
            return dict(LASA_CONFUSION_PAIRS[token])
    return None


# --- Local reference catalog (used offline & to enrich candidate cards) ----

@dataclass(frozen=True)
class DrugCandidate:
    display_name: str
    generic_name: str
    brand_name: str | None
    ingredients: tuple[Ingredient, ...]
    rxcui: str | None = None
    tty: str | None = None
    strength: str | None = None
    dose_form: str | None = None
    route: str | None = None
    category: str = "prescription"
    source: str = "local_reference"  # 'rxnorm' | 'local_reference'
    match_type: str = "exact"        # 'exact' | 'brand_or_alias' | 'approximate' | 'clinical_drug'
    note: str = ""
    confidence: float = 1.0
    lasa_warning: dict[str, str] | None = None

    @property
    def is_combination(self) -> bool:
        return len(self.ingredients) > 1

    @property
    def is_high_confidence(self) -> bool:
        return self.match_type in ("exact", "brand_or_alias") or self.confidence >= 0.85

    @property
    def summary_label(self) -> str:
        parts = [self.display_name]
        if self.brand_name and self.brand_name.lower() not in self.display_name.lower():
            parts.append(f"Brand: {self.brand_name}")
        ing_str = " + ".join(i.name for i in self.ingredients)
        parts.append(f"Ingredient(s): {ing_str}")
        if self.strength:
            parts.append(self.strength)
        if self.dose_form:
            parts.append(self.dose_form)
        if self.rxcui:
            parts.append(f"RxCUI {self.rxcui}")
        return " · ".join(parts)


@dataclass
class NormalizationResult:
    query: str
    parsed_name: str
    extracted_strength: str | None
    extracted_form: str | None
    candidates: list[DrugCandidate] = field(default_factory=list)
    exact_match: bool = False
    requires_confirmation: bool = True
    auto_select_candidate: bool = False
    api_status: str = "ok"  # 'ok' | 'offline_fallback' | 'no_match' | 'invalid_query' | 'error'
    error_message: str | None = None
    uncertainty_reasons: list[str] = field(default_factory=list)
    lasa_warnings: list[dict[str, str]] = field(default_factory=list)


# Documented local catalog of common medications, antibiotics, cardiovascular,
# diabetes, thyroid, GI, respiratory, pain, and combination products with RxCUIs.
LOCAL_CATALOG: list[dict] = [
    # --- Antibiotics & Anti-infectives ---
    {
        "generic": "amoxicillin",
        "brands": ["Amoxil", "Moxatag"],
        "rxcui": "723",
        "strengths": ["250 mg", "500 mg", "875 mg"],
        "dose_form": "Oral Capsule",
        "route": "Oral",
        "category": "prescription",
        "ingredients": [("amoxicillin", "723")],
    },
    {
        "generic": "amoxicillin / clavulanate",
        "brands": ["Augmentin"],
        "rxcui": "214199",
        "strengths": ["500-125 mg", "875-125 mg"],
        "dose_form": "Oral Tablet",
        "route": "Oral",
        "category": "prescription",
        "ingredients": [("amoxicillin", "723"), ("clavulanate", "48203")],
    },
    {
        "generic": "azithromycin",
        "brands": ["Zithromax", "Z-Pak"],
        "rxcui": "18631",
        "strengths": ["250 mg", "500 mg"],
        "dose_form": "Oral Tablet",
        "route": "Oral",
        "category": "prescription",
        "ingredients": [("azithromycin", "18631")],
    },
    {
        "generic": "cephalexin",
        "brands": ["Keflex"],
        "rxcui": "2231",
        "strengths": ["250 mg", "500 mg"],
        "dose_form": "Oral Capsule",
        "route": "Oral",
        "category": "prescription",
        "ingredients": [("cephalexin", "2231")],
    },
    {
        "generic": "doxycycline",
        "brands": ["Vibramycin", "Doryx"],
        "rxcui": "3640",
        "strengths": ["50 mg", "100 mg"],
        "dose_form": "Oral Capsule",
        "route": "Oral",
        "category": "prescription",
        "ingredients": [("doxycycline", "3640")],
    },
    {
        "generic": "ciprofloxacin",
        "brands": ["Cipro"],
        "rxcui": "2551",
        "strengths": ["250 mg", "500 mg", "750 mg"],
        "dose_form": "Oral Tablet",
        "route": "Oral",
        "category": "prescription",
        "ingredients": [("ciprofloxacin", "2551")],
    },
    {
        "generic": "clarithromycin",
        "brands": ["Biaxin"],
        "rxcui": "21212",
        "strengths": ["250 mg", "500 mg"],
        "dose_form": "Oral Tablet",
        "route": "Oral",
        "category": "prescription",
        "ingredients": [("clarithromycin", "21212")],
    },
    {
        "generic": "metronidazole",
        "brands": ["Flagyl"],
        "rxcui": "6922",
        "strengths": ["250 mg", "500 mg"],
        "dose_form": "Oral Tablet",
        "route": "Oral",
        "category": "prescription",
        "ingredients": [("metronidazole", "6922")],
    },
    {
        "generic": "fluconazole",
        "brands": ["Diflucan"],
        "rxcui": "4450",
        "strengths": ["100 mg", "150 mg", "200 mg"],
        "dose_form": "Oral Tablet",
        "route": "Oral",
        "category": "prescription",
        "ingredients": [("fluconazole", "4450")],
    },
    # --- Cardiovascular, Blood Pressure, Cholesterol & Anticoagulants ---
    {
        "generic": "lisinopril",
        "brands": ["Prinivil", "Zestril", "Qbrelis"],
        "rxcui": "29046",
        "strengths": ["2.5 mg", "5 mg", "10 mg", "20 mg", "40 mg"],
        "dose_form": "Oral Tablet",
        "route": "Oral",
        "category": "prescription",
        "ingredients": [("lisinopril", "29046")],
    },
    {
        "generic": "amlodipine",
        "brands": ["Norvasc"],
        "rxcui": "17767",
        "strengths": ["2.5 mg", "5 mg", "10 mg"],
        "dose_form": "Oral Tablet",
        "route": "Oral",
        "category": "prescription",
        "ingredients": [("amlodipine", "17767")],
    },
    {
        "generic": "losartan",
        "brands": ["Cozaar"],
        "rxcui": "52175",
        "strengths": ["25 mg", "50 mg", "100 mg"],
        "dose_form": "Oral Tablet",
        "route": "Oral",
        "category": "prescription",
        "ingredients": [("losartan", "52175")],
    },
    {
        "generic": "valsartan",
        "brands": ["Diovan"],
        "rxcui": "69749",
        "strengths": ["40 mg", "80 mg", "160 mg", "320 mg"],
        "dose_form": "Oral Tablet",
        "route": "Oral",
        "category": "prescription",
        "ingredients": [("valsartan", "69749")],
    },
    {
        "generic": "metoprolol",
        "brands": ["Lopressor", "Toprol XL"],
        "rxcui": "6918",
        "strengths": ["25 mg", "50 mg", "100 mg"],
        "dose_form": "Oral Tablet",
        "route": "Oral",
        "category": "prescription",
        "ingredients": [("metoprolol", "6918")],
    },
    {
        "generic": "hydrochlorothiazide",
        "brands": ["Microzide"],
        "rxcui": "5487",
        "strengths": ["12.5 mg", "25 mg", "50 mg"],
        "dose_form": "Oral Tablet",
        "route": "Oral",
        "category": "prescription",
        "ingredients": [("hydrochlorothiazide", "5487")],
    },
    {
        "generic": "furosemide",
        "brands": ["Lasix"],
        "rxcui": "4603",
        "strengths": ["20 mg", "40 mg", "80 mg"],
        "dose_form": "Oral Tablet",
        "route": "Oral",
        "category": "prescription",
        "ingredients": [("furosemide", "4603")],
    },
    {
        "generic": "spironolactone",
        "brands": ["Aldactone"],
        "rxcui": "9997",
        "strengths": ["25 mg", "50 mg", "100 mg"],
        "dose_form": "Oral Tablet",
        "route": "Oral",
        "category": "prescription",
        "ingredients": [("spironolactone", "9997")],
    },
    {
        "generic": "hydralazine",
        "brands": ["Apresoline"],
        "rxcui": "5470",
        "strengths": ["10 mg", "25 mg", "50 mg", "100 mg"],
        "dose_form": "Oral Tablet",
        "route": "Oral",
        "category": "prescription",
        "ingredients": [("hydralazine", "5470")],
    },
    {
        "generic": "clonidine",
        "brands": ["Catapres"],
        "rxcui": "2599",
        "strengths": ["0.1 mg", "0.2 mg", "0.3 mg"],
        "dose_form": "Oral Tablet",
        "route": "Oral",
        "category": "prescription",
        "ingredients": [("clonidine", "2599")],
    },
    {
        "generic": "atorvastatin",
        "brands": ["Lipitor"],
        "rxcui": "83367",
        "strengths": ["10 mg", "20 mg", "40 mg", "80 mg"],
        "dose_form": "Oral Tablet",
        "route": "Oral",
        "category": "prescription",
        "ingredients": [("atorvastatin", "83367")],
    },
    {
        "generic": "simvastatin",
        "brands": ["Zocor"],
        "rxcui": "36567",
        "strengths": ["10 mg", "20 mg", "40 mg"],
        "dose_form": "Oral Tablet",
        "route": "Oral",
        "category": "prescription",
        "ingredients": [("simvastatin", "36567")],
    },
    {
        "generic": "rosuvastatin",
        "brands": ["Crestor"],
        "rxcui": "301542",
        "strengths": ["5 mg", "10 mg", "20 mg", "40 mg"],
        "dose_form": "Oral Tablet",
        "route": "Oral",
        "category": "prescription",
        "ingredients": [("rosuvastatin", "301542")],
    },
    {
        "generic": "gemfibrozil",
        "brands": ["Lopid"],
        "rxcui": "4719",
        "strengths": ["600 mg"],
        "dose_form": "Oral Tablet",
        "route": "Oral",
        "category": "prescription",
        "ingredients": [("gemfibrozil", "4719")],
    },
    {
        "generic": "warfarin",
        "brands": ["Coumadin", "Jantoven"],
        "rxcui": "11289",
        "strengths": ["1 mg", "2 mg", "2.5 mg", "5 mg", "10 mg"],
        "dose_form": "Oral Tablet",
        "route": "Oral",
        "category": "prescription",
        "ingredients": [("warfarin", "11289")],
    },
    {
        "generic": "apixaban",
        "brands": ["Eliquis"],
        "rxcui": "1364430",
        "strengths": ["2.5 mg", "5 mg"],
        "dose_form": "Oral Tablet",
        "route": "Oral",
        "category": "prescription",
        "ingredients": [("apixaban", "1364430")],
    },
    {
        "generic": "clopidogrel",
        "brands": ["Plavix"],
        "rxcui": "32968",
        "strengths": ["75 mg"],
        "dose_form": "Oral Tablet",
        "route": "Oral",
        "category": "prescription",
        "ingredients": [("clopidogrel", "32968")],
    },
    {
        "generic": "amiodarone",
        "brands": ["Cordarone", "Pacerone"],
        "rxcui": "703",
        "strengths": ["200 mg", "400 mg"],
        "dose_form": "Oral Tablet",
        "route": "Oral",
        "category": "prescription",
        "ingredients": [("amiodarone", "703")],
    },
    {
        "generic": "verapamil",
        "brands": ["Calan", "Verelan"],
        "rxcui": "11170",
        "strengths": ["80 mg", "120 mg", "240 mg"],
        "dose_form": "Oral Tablet",
        "route": "Oral",
        "category": "prescription",
        "ingredients": [("verapamil", "11170")],
    },
    {
        "generic": "digoxin",
        "brands": ["Lanoxin"],
        "rxcui": "3407",
        "strengths": ["125 mcg", "250 mcg"],
        "dose_form": "Oral Tablet",
        "route": "Oral",
        "category": "prescription",
        "ingredients": [("digoxin", "3407")],
    },
    # --- Diabetes & Thyroid ---
    {
        "generic": "metformin",
        "brands": ["Glucophage"],
        "rxcui": "6809",
        "strengths": ["500 mg", "850 mg", "1000 mg"],
        "dose_form": "Oral Tablet",
        "route": "Oral",
        "category": "prescription",
        "ingredients": [("metformin", "6809")],
    },
    {
        "generic": "glipizide",
        "brands": ["Glucotrol", "Glucotrol XL"],
        "rxcui": "4821",
        "strengths": ["5 mg", "10 mg"],
        "dose_form": "Oral Tablet",
        "route": "Oral",
        "category": "prescription",
        "ingredients": [("glipizide", "4821")],
    },
    {
        "generic": "glyburide",
        "brands": ["DiaBeta", "Micronase"],
        "rxcui": "4815",
        "strengths": ["1.25 mg", "2.5 mg", "5 mg"],
        "dose_form": "Oral Tablet",
        "route": "Oral",
        "category": "prescription",
        "ingredients": [("glyburide", "4815")],
    },
    {
        "generic": "levothyroxine",
        "brands": ["Synthroid", "Levoxyl", "Unithroid", "Euthyrox"],
        "rxcui": "10582",
        "strengths": ["25 mcg", "50 mcg", "75 mcg", "100 mcg", "125 mcg"],
        "dose_form": "Oral Tablet",
        "route": "Oral",
        "category": "prescription",
        "ingredients": [("levothyroxine", "10582")],
    },
    # --- Pain, Anti-inflammatory, GI & Respiratory ---
    {
        "generic": "ibuprofen",
        "brands": ["Advil", "Motrin"],
        "rxcui": "5640",
        "strengths": ["200 mg", "400 mg", "600 mg", "800 mg"],
        "dose_form": "Oral Tablet",
        "route": "Oral",
        "category": "otc",
        "ingredients": [("ibuprofen", "5640")],
    },
    {
        "generic": "naproxen",
        "brands": ["Aleve", "Naprosyn"],
        "rxcui": "7258",
        "strengths": ["220 mg", "250 mg", "500 mg"],
        "dose_form": "Oral Tablet",
        "route": "Oral",
        "category": "otc",
        "ingredients": [("naproxen", "7258")],
    },
    {
        "generic": "celecoxib",
        "brands": ["Celebrex"],
        "rxcui": "140587",
        "strengths": ["100 mg", "200 mg"],
        "dose_form": "Oral Capsule",
        "route": "Oral",
        "category": "prescription",
        "ingredients": [("celecoxib", "140587")],
    },
    {
        "generic": "aspirin",
        "brands": ["Ecotrin", "Bayer"],
        "rxcui": "1191",
        "strengths": ["81 mg", "325 mg"],
        "dose_form": "Oral Tablet",
        "route": "Oral",
        "category": "otc",
        "ingredients": [("aspirin", "1191")],
    },
    {
        "generic": "acetaminophen",
        "brands": ["Tylenol"],
        "rxcui": "161",
        "strengths": ["325 mg", "500 mg", "650 mg"],
        "dose_form": "Oral Tablet",
        "route": "Oral",
        "category": "otc",
        "ingredients": [("acetaminophen", "161")],
    },
    {
        "generic": "prednisone",
        "brands": ["Rayos"],
        "rxcui": "8640",
        "strengths": ["5 mg", "10 mg", "20 mg"],
        "dose_form": "Oral Tablet",
        "route": "Oral",
        "category": "prescription",
        "ingredients": [("prednisone", "8640")],
    },
    {
        "generic": "prednisolone",
        "brands": ["Prelone", "Orapred"],
        "rxcui": "8638",
        "strengths": ["5 mg", "15 mg"],
        "dose_form": "Oral Tablet",
        "route": "Oral",
        "category": "prescription",
        "ingredients": [("prednisolone", "8638")],
    },
    {
        "generic": "omeprazole",
        "brands": ["Prilosec"],
        "rxcui": "7646",
        "strengths": ["20 mg", "40 mg"],
        "dose_form": "Delayed Release Oral Capsule",
        "route": "Oral",
        "category": "otc",
        "ingredients": [("omeprazole", "7646")],
    },
    {
        "generic": "pantoprazole",
        "brands": ["Protonix"],
        "rxcui": "40790",
        "strengths": ["20 mg", "40 mg"],
        "dose_form": "Delayed Release Oral Tablet",
        "route": "Oral",
        "category": "prescription",
        "ingredients": [("pantoprazole", "40790")],
    },
    {
        "generic": "albuterol",
        "brands": ["ProAir HFA", "Ventolin HFA"],
        "rxcui": "435",
        "strengths": ["90 mcg"],
        "dose_form": "Metered Dose Inhaler",
        "route": "Inhalation",
        "category": "prescription",
        "ingredients": [("albuterol", "435")],
    },
    # --- Neuro, Mood, Allergy & Sleep ---
    {
        "generic": "gabapentin",
        "brands": ["Neurontin"],
        "rxcui": "25480",
        "strengths": ["100 mg", "300 mg", "400 mg", "600 mg"],
        "dose_form": "Oral Capsule",
        "route": "Oral",
        "category": "prescription",
        "ingredients": [("gabapentin", "25480")],
    },
    {
        "generic": "sertraline",
        "brands": ["Zoloft"],
        "rxcui": "36437",
        "strengths": ["25 mg", "50 mg", "100 mg"],
        "dose_form": "Oral Tablet",
        "route": "Oral",
        "category": "prescription",
        "ingredients": [("sertraline", "36437")],
    },
    {
        "generic": "escitalopram",
        "brands": ["Lexapro"],
        "rxcui": "321988",
        "strengths": ["5 mg", "10 mg", "20 mg"],
        "dose_form": "Oral Tablet",
        "route": "Oral",
        "category": "prescription",
        "ingredients": [("escitalopram", "321988")],
    },
    {
        "generic": "citalopram",
        "brands": ["Celexa"],
        "rxcui": "2556",
        "strengths": ["10 mg", "20 mg", "40 mg"],
        "dose_form": "Oral Tablet",
        "route": "Oral",
        "category": "prescription",
        "ingredients": [("citalopram", "2556")],
    },
    {
        "generic": "duloxetine",
        "brands": ["Cymbalta"],
        "rxcui": "72625",
        "strengths": ["20 mg", "30 mg", "60 mg"],
        "dose_form": "Delayed Release Oral Capsule",
        "route": "Oral",
        "category": "prescription",
        "ingredients": [("duloxetine", "72625")],
    },
    {
        "generic": "bupropion",
        "brands": ["Wellbutrin XL", "Zyban"],
        "rxcui": "42347",
        "strengths": ["150 mg", "300 mg"],
        "dose_form": "Extended Release Oral Tablet",
        "route": "Oral",
        "category": "prescription",
        "ingredients": [("bupropion", "42347")],
    },
    {
        "generic": "buspirone",
        "brands": ["BuSpar"],
        "rxcui": "1827",
        "strengths": ["5 mg", "10 mg", "15 mg"],
        "dose_form": "Oral Tablet",
        "route": "Oral",
        "category": "prescription",
        "ingredients": [("buspirone", "1827")],
    },
    {
        "generic": "amoxapine",
        "brands": ["Asendin"],
        "rxcui": "722",
        "strengths": ["25 mg", "50 mg", "100 mg"],
        "dose_form": "Oral Tablet",
        "route": "Oral",
        "category": "prescription",
        "ingredients": [("amoxapine", "722")],
    },
    {
        "generic": "hydroxyzine",
        "brands": ["Atarax", "Vistaril"],
        "rxcui": "5553",
        "strengths": ["10 mg", "25 mg", "50 mg"],
        "dose_form": "Oral Tablet",
        "route": "Oral",
        "category": "prescription",
        "ingredients": [("hydroxyzine", "5553")],
    },
    {
        "generic": "clonazepam",
        "brands": ["Klonopin"],
        "rxcui": "2598",
        "strengths": ["0.5 mg", "1 mg", "2 mg"],
        "dose_form": "Oral Tablet",
        "route": "Oral",
        "category": "prescription",
        "ingredients": [("clonazepam", "2598")],
    },
    {
        "generic": "alprazolam",
        "brands": ["Xanax"],
        "rxcui": "596",
        "strengths": ["0.25 mg", "0.5 mg", "1 mg"],
        "dose_form": "Oral Tablet",
        "route": "Oral",
        "category": "prescription",
        "ingredients": [("alprazolam", "596")],
    },
    {
        "generic": "tramadol",
        "brands": ["Ultram"],
        "rxcui": "10689",
        "strengths": ["50 mg"],
        "dose_form": "Oral Tablet",
        "route": "Oral",
        "category": "prescription",
        "ingredients": [("tramadol", "10689")],
    },
    {
        "generic": "oxycodone",
        "brands": ["OxyContin", "Roxicodone"],
        "rxcui": "7804",
        "strengths": ["5 mg", "10 mg", "15 mg"],
        "dose_form": "Oral Tablet",
        "route": "Oral",
        "category": "prescription",
        "ingredients": [("oxycodone", "7804")],
    },
    {
        "generic": "diphenhydramine",
        "brands": ["Benadryl"],
        "rxcui": "3498",
        "strengths": ["25 mg", "50 mg"],
        "dose_form": "Oral Capsule",
        "route": "Oral",
        "category": "otc",
        "ingredients": [("diphenhydramine", "3498")],
    },
    {
        "generic": "cetirizine",
        "brands": ["Zyrtec"],
        "rxcui": "20610",
        "strengths": ["5 mg", "10 mg"],
        "dose_form": "Oral Tablet",
        "route": "Oral",
        "category": "otc",
        "ingredients": [("cetirizine", "20610")],
    },
    {
        "generic": "loratadine",
        "brands": ["Claritin"],
        "rxcui": "28889",
        "strengths": ["10 mg"],
        "dose_form": "Oral Tablet",
        "route": "Oral",
        "category": "otc",
        "ingredients": [("loratadine", "28889")],
    },
    # --- Electrolytes, Vitamins & Supplements ---
    {
        "generic": "potassium chloride",
        "brands": ["Klor-Con", "K-Tab"],
        "rxcui": "8591",
        "strengths": ["10 mEq", "20 mEq"],
        "dose_form": "Extended Release Oral Tablet",
        "route": "Oral",
        "category": "prescription",
        "ingredients": [("potassium chloride", "8591")],
    },
    {
        "generic": "calcium carbonate",
        "brands": ["Tums", "Caltrate"],
        "rxcui": "1901",
        "strengths": ["500 mg", "600 mg", "1000 mg"],
        "dose_form": "Chewable Tablet",
        "route": "Oral",
        "category": "supplement",
        "ingredients": [("calcium carbonate", "1901")],
    },
    {
        "generic": "vitamin d3",
        "brands": ["Vitamin D3", "Cholecalciferol"],
        "rxcui": "2418",
        "strengths": ["1000 units", "2000 units", "5000 units"],
        "dose_form": "Oral Capsule",
        "route": "Oral",
        "category": "supplement",
        "ingredients": [("cholecalciferol", "2418")],
    },
    {
        "generic": "melatonin",
        "brands": ["Melatonin"],
        "rxcui": "6711",
        "strengths": ["1 mg", "3 mg", "5 mg", "10 mg"],
        "dose_form": "Oral Tablet",
        "route": "Oral",
        "category": "supplement",
        "ingredients": [("melatonin", "6711")],
    },
    # --- Combination products (multiple active ingredients) ---
    {
        "generic": "lisinopril / hydrochlorothiazide",
        "brands": ["Zestoretic", "Prinzide"],
        "rxcui": "214354",
        "strengths": ["10-12.5 mg", "20-12.5 mg", "20-25 mg"],
        "dose_form": "Oral Tablet",
        "route": "Oral",
        "category": "prescription",
        "ingredients": [("lisinopril", "29046"), ("hydrochlorothiazide", "5487")],
    },
    {
        "generic": "losartan / hydrochlorothiazide",
        "brands": ["Hyzaar"],
        "rxcui": "214555",
        "strengths": ["50-12.5 mg", "100-25 mg"],
        "dose_form": "Oral Tablet",
        "route": "Oral",
        "category": "prescription",
        "ingredients": [("losartan", "52175"), ("hydrochlorothiazide", "5487")],
    },
    {
        "generic": "ibuprofen / diphenhydramine",
        "brands": ["Advil PM", "Motrin PM"],
        "rxcui": "686375",
        "strengths": ["200-38 mg"],
        "dose_form": "Oral Tablet",
        "route": "Oral",
        "category": "otc",
        "ingredients": [("ibuprofen", "5640"), ("diphenhydramine", "3498")],
    },
    {
        "generic": "naproxen / diphenhydramine",
        "brands": ["Aleve PM"],
        "rxcui": "1596452",
        "strengths": ["220-25 mg"],
        "dose_form": "Oral Tablet",
        "route": "Oral",
        "category": "otc",
        "ingredients": [("naproxen", "7258"), ("diphenhydramine", "3498")],
    },
    {
        "generic": "oxycodone / acetaminophen",
        "brands": ["Percocet"],
        "rxcui": "214182",
        "strengths": ["5-325 mg", "10-325 mg"],
        "dose_form": "Oral Tablet",
        "route": "Oral",
        "category": "prescription",
        "ingredients": [("oxycodone", "7804"), ("acetaminophen", "161")],
    },
    {
        "generic": "hydrocodone / acetaminophen",
        "brands": ["Norco", "Vicodin", "Lortab"],
        "rxcui": "214184",
        "strengths": ["5-325 mg", "7.5-325 mg", "10-325 mg"],
        "dose_form": "Oral Tablet",
        "route": "Oral",
        "category": "prescription",
        "ingredients": [("hydrocodone", "5489"), ("acetaminophen", "161")],
    },
    {
        "generic": "hydrocodone / ibuprofen",
        "brands": ["Vicoprofen"],
        "rxcui": "214549",
        "strengths": ["7.5-200 mg"],
        "dose_form": "Oral Tablet",
        "route": "Oral",
        "category": "prescription",
        "ingredients": [("hydrocodone", "5489"), ("ibuprofen", "5640")],
    },
]

_KNOWN_CATALOG_NAMES: frozenset[str] = frozenset(
    {normalize_name(e["generic"]) for e in LOCAL_CATALOG}
    | {normalize_name(b) for e in LOCAL_CATALOG for b in e.get("brands", [])}
    | set(KNOWN_SHORT_DRUG_NAMES)
)

_STRENGTH_RE = re.compile(
    r"\b(\d+(?:\.\d+)?(?:\s*[-/]\s*\d+(?:\.\d+)?)?\s*(?:mg|mcg|g|ml|meq|units|unit|iu|%))\b",
    re.IGNORECASE,
)

# Plural-first ordered form keywords so 'Capsules' and 'Tablets' are matched completely
_FORM_KEYWORDS: dict[str, str] = {
    "capsules": "Oral Capsule",
    "capsule": "Oral Capsule",
    "capsu1es": "Oral Capsule",
    "capsu1e": "Oral Capsule",
    "capsuies": "Oral Capsule",
    "capsuie": "Oral Capsule",
    "caps": "Oral Capsule",
    "cap": "Oral Capsule",
    "softgels": "Oral Capsule",
    "softgel": "Oral Capsule",
    "tablets": "Oral Tablet",
    "tablet": "Oral Tablet",
    "tab1ets": "Oral Tablet",
    "tab1et": "Oral Tablet",
    "tabiets": "Oral Tablet",
    "tabiet": "Oral Tablet",
    "tabs": "Oral Tablet",
    "tab": "Oral Tablet",
    "caplets": "Oral Tablet",
    "caplet": "Oral Tablet",
    "chewable": "Chewable Tablet",
    "suspensions": "Oral Suspension",
    "suspension": "Oral Suspension",
    "solutions": "Oral Solution",
    "solution": "Oral Solution",
    "liquid": "Oral Solution",
    "inhaler": "Metered Dose Inhaler",
    "spray": "Nasal Spray",
    "drops": "Drops",
    "cream": "Topical Cream",
    "ointment": "Topical Ointment",
    "patch": "Transdermal Patch",
}

_SALT_SUFFIXES = (
    " hydrochloride",
    " hcl",
    " sodium",
    " calcium",
    " potassium",
    " tartrate",
    " succinate",
    " besylate",
    " bisulfate",
    " dihydrate",
    " monohydrate",
)


def _ocr_il_skeleton(word: str) -> str:
    """Normalize common small-font OCR confusions (`1`->`l`, `0`->`o`, `rn`->`m`,
    and `i`/`l` runs) for tokens >= 6 chars."""
    s = (word or "").lower().strip()
    s = s.replace("0", "o").replace("1", "l").replace("rn", "m").replace("vv", "w")
    s = re.sub(r"[il|]+", "l", s)
    return s


def denoise_ocr_drug_token(token: str) -> str:
    """De-noise a single >= 6-char OCR word by correcting common glyph swaps
    (`1`->`l`/`i`, `0`->`o`, `rn`->`m`, `i`<->`l`) when it closely matches a
    known medication in `LOCAL_CATALOG` and is not in `PHARMACY_BOILERPLATE_WORDS`."""
    raw = re.sub(r"[^a-zA-Z0-9-]", "", (token or "").strip())
    low = raw.lower()
    if len(low) < 6:
        return token

    # Check direct character-swap normalization first (0->o, 1->l/i, rn->m)
    swapped = low.replace("0", "o").replace("1", "l").replace("rn", "m")
    if swapped in _KNOWN_CATALOG_NAMES:
        return swapped
    swapped_i = low.replace("0", "o").replace("1", "i").replace("rn", "m")
    if swapped_i in _KNOWN_CATALOG_NAMES:
        return swapped_i

    # Check if this token is a boilerplate word before trying lexicon matching
    if low in PHARMACY_BOILERPLATE_WORDS or swapped in PHARMACY_BOILERPLATE_WORDS:
        return token
    for bp in PHARMACY_BOILERPLATE_WORDS:
        if len(bp) >= 4 and difflib.SequenceMatcher(None, low, bp).ratio() >= 0.68:
            return token

    # Check i/l/1/rn skeleton and SequenceMatcher against known catalog drug names >= 6 chars
    skel = _ocr_il_skeleton(low)
    best_name: str | None = None
    best_score = 0.0
    for cat_name in _KNOWN_CATALOG_NAMES:
        if len(cat_name) < 6 or " " in cat_name:
            continue
        if _ocr_il_skeleton(cat_name) == skel:
            return cat_name
        sim = max(
            difflib.SequenceMatcher(None, low, cat_name).ratio(),
            difflib.SequenceMatcher(None, swapped, cat_name).ratio(),
        )
        if sim > best_score:
            best_score = sim
            best_name = cat_name

    if best_name and best_score >= 0.82:
        return best_name
    return swapped if swapped.isalpha() else token


def is_boilerplate_or_noise_token(token: str) -> bool:
    """Return True if ``token`` is a pharmacy label boilerplate word, a garbled
    fuzzy corruption of a boilerplate word (similarity >= 0.68, e.g. ``'arty'``
    from ``'quantity'`` or ``'rilo'`` from ``'refills'``), or a short (<= 4 char)
    fragment that is not a known short medication/brand name."""
    w = re.sub(r"[^a-z0-9]", "", (token or "").lower())
    if not w:
        return True
    if w in _KNOWN_CATALOG_NAMES:
        return False
    if len(w) >= 6 and denoise_ocr_drug_token(w) in _KNOWN_CATALOG_NAMES:
        return False
    if w.isdigit():
        return True
    if w in PHARMACY_BOILERPLATE_WORDS:
        return True
    if len(w) <= 4 and w not in KNOWN_SHORT_DRUG_NAMES:
        return True
    for bp in PHARMACY_BOILERPLATE_WORDS:
        if len(bp) >= 4 and difflib.SequenceMatcher(None, w, bp).ratio() >= 0.68:
            return True
    return False


def parse_medication_query(raw_text: str) -> tuple[str, str | None, str | None]:
    """Extract (base_drug_name, strength, dose_form) from a string like
    'Amoxicillin 500 mg Capsules' or 'LISINOPRIL 10MG ORAL TAB'."""
    text = (raw_text or "").strip()
    if not text:
        return "", None, None

    strength_match = _STRENGTH_RE.search(text)
    strength = None
    if strength_match:
        s = strength_match.group(1)
        strength = re.sub(r"\s+", " ", s).strip()
        strength = (
            re.sub(r"(?i)\bmg\b", "mg", strength)
            .replace("MCG", "mcg")
            .replace("Mcg", "mcg")
            .replace("MEQ", "mEq")
            .replace("meq", "mEq")
            .replace("UNITS", "units")
            .replace("Units", "units")
        )
        strength = re.sub(r"(\d)(mg|mcg|g|ml|mEq|units|unit|iu|%)", r"\1 \2", strength)

    found_form = None
    for kw, label in _FORM_KEYWORDS.items():
        if re.search(rf"\b{re.escape(kw)}\b", text, re.IGNORECASE):
            found_form = label
            break

    # Remove strength, form words, and common bottle noise to isolate drug name
    cleaned = _STRENGTH_RE.sub(" ", text)
    for kw in _FORM_KEYWORDS:
        cleaned = re.sub(rf"\b{re.escape(kw)}\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(
        r"\b(oral|delayed|extended|release|er|xl|sr|dr|rx|take|daily|qty|quantity|refill|refills)\b",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"[^a-zA-Z0-9+/ -]", " ", cleaned)

    # Filter out boilerplate and OCR noise tokens while preserving +, / separators
    raw_tokens = cleaned.split()
    kept_tokens: list[str] = []
    for tok in raw_tokens:
        if tok in ("+", "/"):
            if kept_tokens and kept_tokens[-1] not in ("+", "/"):
                kept_tokens.append(tok)
            continue
        if not is_boilerplate_or_noise_token(tok):
            kept_tokens.append(tok)

    while kept_tokens and kept_tokens[-1] in ("+", "/"):
        kept_tokens.pop()

    base = normalize_name(" ".join(kept_tokens))
    for suffix in _SALT_SUFFIXES:
        if base.endswith(suffix) and base != "potassium chloride":
            base = base[: -len(suffix)].strip()
    return base, strength, found_form


def _compute_candidate_similarity(query_base: str, cand: DrugCandidate | str) -> float:
    """Compute highest character similarity (0.0..1.0) between ``query_base``
    and the candidate's generic name, display name, or brand names."""
    q = normalize_name(query_base)
    if not q:
        return 0.0
    if isinstance(cand, str):
        targets = [normalize_name(cand)]
    else:
        targets = [normalize_name(cand.generic_name), normalize_name(cand.display_name)]
        for ing in cand.ingredients:
            targets.append(normalize_name(ing.name))
        if cand.brand_name:
            for b in cand.brand_name.split(","):
                targets.append(normalize_name(b))
    best = 0.0
    for t_str in targets:
        if not t_str:
            continue
        if q == t_str:
            return 1.0
        sim = difflib.SequenceMatcher(None, q, t_str).ratio()
        if sim > best:
            best = sim
        for part in t_str.split():
            p_sim = difflib.SequenceMatcher(None, q, part).ratio()
            if p_sim > best:
                best = p_sim
    return best


def _search_local_catalog(
    base_name: str,
    raw_query: str,
    strength: str | None,
    dose_form: str | None,
) -> list[DrugCandidate]:
    """Find exact, brand, combination, and close spelling/OCR candidates from the
    documented local catalog."""
    q_norm = normalize_name(raw_query)
    if not base_name:
        return []
    candidates: list[DrugCandidate] = []
    seen_keys: set[str] = set()

    def _add_entry(
        entry: dict,
        match_type: str,
        matched_brand: str | None = None,
        note: str = "",
        confidence: float = 1.0,
    ) -> None:
        key = entry["generic"]
        if key in seen_keys:
            return
        seen_keys.add(key)
        chosen_strength = strength or (entry["strengths"][0] if entry.get("strengths") else None)
        chosen_form = dose_form or entry.get("dose_form")
        brand = matched_brand or (", ".join(entry["brands"]) if entry.get("brands") else None)
        display = (
            f"{matched_brand} ({entry['generic'].title()})"
            if matched_brand
            else entry["generic"].title()
        )
        lasa = get_lasa_warning(entry["generic"])
        candidates.append(
            DrugCandidate(
                display_name=display,
                generic_name=entry["generic"],
                brand_name=brand,
                ingredients=tuple(Ingredient(n, rx) for n, rx in entry["ingredients"]),
                rxcui=entry.get("rxcui"),
                tty="MIN" if len(entry["ingredients"]) > 1 else "IN",
                strength=chosen_strength,
                dose_form=chosen_form,
                route=entry.get("route", "Oral"),
                category=entry.get("category", "prescription"),
                source="local_reference",
                match_type=match_type,
                note=note,
                confidence=confidence,
                lasa_warning=lasa,
            )
        )

    for entry in LOCAL_CATALOG:
        gen = normalize_name(entry["generic"])
        brands_lower = {normalize_name(b): b for b in entry.get("brands", [])}
        # 1. Exact generic match
        if base_name == gen or q_norm == gen:
            _add_entry(
                entry,
                "exact",
                note="Exact generic ingredient match.",
                confidence=1.0,
            )
        # 2. Exact brand match (including multi-word brands like "Advil PM")
        elif q_norm in brands_lower or base_name in brands_lower:
            brand_label = brands_lower.get(q_norm) or brands_lower.get(base_name)
            is_combo = len(entry["ingredients"]) > 1
            _add_entry(
                entry,
                "brand_or_alias",
                matched_brand=brand_label,
                note=(
                    f"Combination brand product containing {' + '.join(n for n, _ in entry['ingredients'])}. Please confirm."
                    if is_combo
                    else f"Brand name for {entry['generic']}. Please confirm."
                ),
                confidence=0.95,
            )
        # 3. Combination query like "lisinopril + hydrochlorothiazide"
        elif any(sep in base_name for sep in ("+", "/")):
            parts = {normalize_name(p) for p in re.split(r"[+/]", base_name) if normalize_name(p)}
            ing_set = {normalize_name(n) for n, _ in entry["ingredients"]}
            if parts and parts == ing_set:
                _add_entry(
                    entry,
                    "brand_or_alias",
                    note="Combination medication with multiple active ingredients.",
                    confidence=0.95,
                )

    # 4. Prefix / substring matches when disambiguating related brands (e.g. "Advil" vs "Advil PM")
    has_exact_generic = any(c.match_type == "exact" for c in candidates)
    if len(base_name) >= 5:
        for entry in LOCAL_CATALOG:
            gen = normalize_name(entry["generic"])
            if not has_exact_generic and gen.startswith(base_name) and gen != base_name:
                sim = difflib.SequenceMatcher(None, base_name, gen).ratio()
                if sim >= 0.78:
                    _add_entry(
                        entry,
                        "approximate",
                        note="Partial name match — please confirm the exact medication.",
                        confidence=sim,
                    )
            for b_low, b_orig in {normalize_name(b): b for b in entry.get("brands", [])}.items():
                if b_low.startswith(base_name) and b_low != base_name:
                    _add_entry(
                        entry,
                        "approximate",
                        matched_brand=b_orig,
                        note=f"Possible brand match ({b_orig}) — please confirm.",
                        confidence=0.86,
                    )

    # 5. Conservative fuzzy / OCR character-confusion suggestions (>= 0.78 cutoff, never auto-confirmed!)
    if not candidates and len(base_name) >= 5:
        denoised_base = denoise_ocr_drug_token(base_name)
        base_skel = _ocr_il_skeleton(base_name)
        all_names: dict[str, tuple[dict, str | None]] = {}
        for entry in LOCAL_CATALOG:
            all_names[normalize_name(entry["generic"])] = (entry, None)
            for b in entry.get("brands", []):
                all_names[normalize_name(b)] = (entry, b)

        # First check if OCR de-noising or i/l/1/rn skeleton matches a catalog entry
        for match_key, (entry, b_orig) in all_names.items():
            if len(match_key) >= 6 and (
                match_key == denoised_base or _ocr_il_skeleton(match_key) == base_skel
            ):
                sim = max(
                    0.88,
                    difflib.SequenceMatcher(None, base_name, match_key).ratio(),
                )
                _add_entry(
                    entry,
                    "approximate",
                    matched_brand=b_orig,
                    note=f"Matched '{raw_query.strip()}' after correcting common OCR character confusion — please confirm.",
                    confidence=sim,
                )

        close = difflib.get_close_matches(base_name, list(all_names.keys()), n=3, cutoff=0.78)
        for match_key in close:
            entry, b_orig = all_names[match_key]
            sim = difflib.SequenceMatcher(None, base_name, match_key).ratio()
            _add_entry(
                entry,
                "approximate",
                matched_brand=b_orig,
                note=f"Spelling suggestion for '{raw_query.strip()}' — requires your confirmation.",
                confidence=sim,
            )

    return candidates


def search_catalog_by_prefix(prefix: str, limit: int = 15) -> list[DrugCandidate]:
    """Senior-friendly quick letter-picker helper: return `DrugCandidate` objects
    from `LOCAL_CATALOG` matching a 1-3+ letter prefix on generic or brand name."""
    p = normalize_name(prefix)
    matched_entries: list[dict] = []
    if not p:
        matched_entries = list(LOCAL_CATALOG[:limit])
    else:
        for entry in LOCAL_CATALOG:
            gen = normalize_name(entry["generic"])
            brands = [normalize_name(b) for b in entry.get("brands", [])]
            if gen.startswith(p) or any(b.startswith(p) for b in brands) or p in gen:
                matched_entries.append(entry)
                if len(matched_entries) >= limit:
                    break

    results: list[DrugCandidate] = []
    for entry in matched_entries:
        brand = ", ".join(entry["brands"]) if entry.get("brands") else None
        lasa = get_lasa_warning(entry["generic"])
        results.append(
            DrugCandidate(
                display_name=entry["generic"].title(),
                generic_name=entry["generic"],
                brand_name=brand,
                ingredients=tuple(Ingredient(n, rx) for n, rx in entry["ingredients"]),
                rxcui=entry.get("rxcui"),
                tty="MIN" if len(entry["ingredients"]) > 1 else "IN",
                strength=entry["strengths"][0] if entry.get("strengths") else None,
                dose_form=entry.get("dose_form"),
                route=entry.get("route", "Oral"),
                category=entry.get("category", "prescription"),
                source="local_reference",
                match_type="exact",
                note="Selected from Quick Letter & Common Medicine Picker.",
                confidence=1.0,
                lasa_warning=lasa,
            )
        )
    return results


def _fetch_rxnorm_related(
    rxcui: str,
    fallback_name: str,
    strength: str | None,
    dose_form: str | None,
    match_type: str,
    session: requests.Session | None = None,
) -> DrugCandidate | None:
    """Resolve an RxCUI's active ingredients (IN), brand names (BN), and dose form (DF)."""
    props_json, err = _cached_get_json(f"{RXNORM_BASE}/rxcui/{rxcui}/properties.json", session=session)
    if err or not props_json or "properties" not in props_json:
        return None
    props = props_json["properties"]
    concept_name = props.get("name") or fallback_name
    tty = props.get("tty") or ""

    rel_json, _ = _cached_get_json(
        f"{RXNORM_BASE}/rxcui/{rxcui}/related.json",
        params={"tty": "IN+MIN+BN+DF"},
        session=session,
    )
    ingredients: list[Ingredient] = []
    brands: list[str] = []
    forms: list[str] = []
    if rel_json:
        for grp in rel_json.get("relatedGroup", {}).get("conceptGroup", []) or []:
            g_tty = grp.get("tty")
            for cp in grp.get("conceptProperties", []) or []:
                cp_name = (cp.get("name") or "").strip()
                cp_rxcui = (cp.get("rxcui") or "").strip() or None
                if not cp_name:
                    continue
                if g_tty == "IN":
                    ingredients.append(Ingredient(normalize_name(cp_name), cp_rxcui))
                elif g_tty == "BN":
                    brands.append(cp_name)
                elif g_tty == "DF":
                    forms.append(cp_name)

    if not ingredients:
        if tty in ("IN", "PIN"):
            ingredients.append(Ingredient(normalize_name(concept_name), rxcui))
        else:
            parsed_base, _, _ = parse_medication_query(concept_name)
            if parsed_base:
                ingredients.append(Ingredient(parsed_base, rxcui))

    if not ingredients:
        return None

    _, parsed_str, parsed_form = parse_medication_query(concept_name)
    final_strength = strength or parsed_str
    final_form = dose_form or (forms[0] if forms else parsed_form)
    generic_label = " / ".join(i.name for i in ingredients)
    brand_label = ", ".join(brands[:2]) if brands else None
    lasa = get_lasa_warning(generic_label)

    return DrugCandidate(
        display_name=concept_name.title() if tty in ("IN", "PIN", "BN") else concept_name,
        generic_name=generic_label,
        brand_name=brand_label,
        ingredients=tuple(ingredients),
        rxcui=rxcui,
        tty=tty,
        strength=final_strength,
        dose_form=final_form,
        route="Oral" if final_form and "oral" in final_form.lower() else None,
        category="prescription",
        source="rxnorm",
        match_type=match_type,
        note=(
            "Standardized via NLM RxNorm."
            if match_type == "exact"
            else "Candidate from NLM RxNorm — please review and confirm."
        ),
        confidence=1.0 if match_type == "exact" else 0.8,
        lasa_warning=lasa,
    )


def resolve_drug_candidates(
    raw_query: str,
    *,
    from_ocr: bool = False,
    use_network: bool = True,
    session: requests.Session | None = None,
) -> NormalizationResult:
    """Resolve a user-entered or OCR-extracted medication string into a list of
    distinguishable candidates with conservative confirmation flags."""
    query = (raw_query or "").strip()
    base_name, strength, dose_form = parse_medication_query(query)
    if not query or not base_name or len(base_name) < 2:
        return NormalizationResult(
            query=query,
            parsed_name=base_name,
            extracted_strength=strength,
            extracted_form=dose_form,
            candidates=[],
            exact_match=False,
            requires_confirmation=True,
            auto_select_candidate=False,
            api_status="invalid_query",
            error_message="Please enter a recognizable medication name (non-drug label words were filtered).",
            uncertainty_reasons=["Medication name is missing, too short, or consisted only of label boilerplate."],
        )

    local_candidates = _search_local_catalog(base_name, query, strength, dose_form)
    rxnorm_candidates: list[DrugCandidate] = []
    api_status = "ok"
    api_error: str | None = None

    if use_network:
        # 1. Exact / normalized search on RxNorm
        exact_json, err = _cached_get_json(
            f"{RXNORM_BASE}/rxcui.json",
            params={"name": base_name, "search": 2},
            session=session,
        )
        if err in ("timeout", "network_error", "rate_limited") or (err and err.startswith("http_")):
            api_status = "offline_fallback" if local_candidates else "error"
            api_error = (
                "RxNorm lookup service is currently unreachable; showing local reference matches."
                if local_candidates
                else "RxNorm lookup service could not be reached. You can still save the medicine manually, "
                     "or confirm it from the local reference list."
            )
        else:
            rx_ids = (exact_json or {}).get("idGroup", {}).get("rxnormId") or []
            for rxcui in rx_ids[:3]:
                cand = _fetch_rxnorm_related(
                    str(rxcui), base_name, strength, dose_form, "exact", session=session
                )
                if cand:
                    rxnorm_candidates.append(cand)

            # 2. Approximate candidate lookup ONLY when base_name is >= 5 chars,
            # and strictly gated by >= 0.78 character similarity so "Rilo" never matches "Rilonacept"!
            if not rxnorm_candidates and len(base_name) >= 5:
                approx_json, approx_err = _cached_get_json(
                    f"{RXNORM_BASE}/approximateTerm.json",
                    params={"term": base_name, "maxEntries": 4},
                    session=session,
                )
                if not approx_err and approx_json:
                    seen_rxcuis: set[str] = set()
                    for item in approx_json.get("approximateGroup", {}).get("candidate", []) or []:
                        rxcui = str(item.get("rxcui") or "").strip()
                        if not rxcui or rxcui in seen_rxcuis:
                            continue
                        seen_rxcuis.add(rxcui)
                        cand = _fetch_rxnorm_related(
                            rxcui,
                            item.get("name") or base_name,
                            strength,
                            dose_form,
                            "approximate",
                            session=session,
                        )
                        if cand:
                            sim = _compute_candidate_similarity(base_name, cand)
                            if sim >= 0.78:
                                cand = DrugCandidate(
                                    display_name=cand.display_name,
                                    generic_name=cand.generic_name,
                                    brand_name=cand.brand_name,
                                    ingredients=cand.ingredients,
                                    rxcui=cand.rxcui,
                                    tty=cand.tty,
                                    strength=cand.strength,
                                    dose_form=cand.dose_form,
                                    route=cand.route,
                                    category=cand.category,
                                    source=cand.source,
                                    match_type="approximate",
                                    note=cand.note,
                                    confidence=sim,
                                    lasa_warning=cand.lasa_warning,
                                )
                                rxnorm_candidates.append(cand)
                        if len(rxnorm_candidates) >= 3:
                            break
    else:
        api_status = "offline_fallback"

    # Merge candidates without losing local brand/combination context
    merged: list[DrugCandidate] = []
    seen_ing_keys: set[tuple[str, ...]] = set()

    rx_by_ings = {tuple(sorted(i.name for i in c.ingredients)): c for c in rxnorm_candidates}

    for loc in local_candidates:
        ing_key = tuple(sorted(i.name for i in loc.ingredients))
        rx_match = rx_by_ings.get(ing_key)
        if rx_match:
            loc = DrugCandidate(
                display_name=loc.display_name,
                generic_name=loc.generic_name,
                brand_name=loc.brand_name or rx_match.brand_name,
                ingredients=loc.ingredients,
                rxcui=rx_match.rxcui or loc.rxcui,
                tty=rx_match.tty or loc.tty,
                strength=loc.strength or rx_match.strength,
                dose_form=loc.dose_form or rx_match.dose_form,
                route=loc.route or rx_match.route,
                category=loc.category,
                source="rxnorm",
                match_type=loc.match_type,
                note=loc.note,
                confidence=max(loc.confidence, rx_match.confidence),
                lasa_warning=loc.lasa_warning or rx_match.lasa_warning,
            )
        merged.append(loc)
        seen_ing_keys.add(ing_key)

    for rx in rxnorm_candidates:
        ing_key = tuple(sorted(i.name for i in rx.ingredients))
        if ing_key not in seen_ing_keys:
            merged.append(rx)
            seen_ing_keys.add(ing_key)

    if not merged and api_status == "ok":
        api_status = "no_match"

    lasa_list: list[dict[str, str]] = []
    seen_lasa: set[str] = set()
    for c in merged:
        if c.lasa_warning and c.lasa_warning["drug"] not in seen_lasa:
            seen_lasa.add(c.lasa_warning["drug"])
            lasa_list.append(c.lasa_warning)

    reasons: list[str] = []
    if from_ocr:
        reasons.append("Scanned from a bottle image — OCR text always requires your confirmation.")
    if not merged:
        reasons.append(f"No standardized medication match was found for '{query}'.")
    elif len(merged) > 1:
        reasons.append("Multiple possible medication matches were found — please select the right one.")
    elif merged[0].match_type != "exact":
        reasons.append(merged[0].note or "Matched via brand name or spelling suggestion — please confirm.")
    elif merged[0].is_combination:
        reasons.append(
            "Combination product with multiple active ingredients ("
            + " + ".join(i.name for i in merged[0].ingredients)
            + ")."
        )
    for lw in lasa_list:
        reasons.append(lw["warning"])

    is_exact = (
        len(merged) == 1
        and merged[0].match_type == "exact"
        and not merged[0].is_combination
        and not from_ocr
    )
    requires_conf = not is_exact or bool(reasons)
    auto_select = bool(merged and merged[0].is_high_confidence)

    return NormalizationResult(
        query=query,
        parsed_name=base_name,
        extracted_strength=strength,
        extracted_form=dose_form,
        candidates=merged,
        exact_match=is_exact,
        requires_confirmation=requires_conf,
        auto_select_candidate=auto_select,
        api_status=api_status,
        error_message=api_error,
        uncertainty_reasons=reasons,
        lasa_warnings=lasa_list,
    )


def normalize_drug_name(
    raw_text: str,
    *,
    use_network: bool = True,
    session: requests.Session | None = None,
) -> str | None:
    """Compatibility helper: return the top normalized generic ingredient name
    only when a single unambiguous match exists; otherwise None."""
    res = resolve_drug_candidates(raw_text, use_network=use_network, session=session)
    if not res.candidates:
        return None
    if len(res.candidates) == 1 and res.candidates[0].match_type in ("exact", "brand_or_alias"):
        return res.candidates[0].generic_name
    return None


# --- openFDA supplementary label context -----------------------------------

def _format_fda_date(raw_date: str | None) -> str | None:
    """'20240515' -> '2024-05-15'."""
    if not raw_date or len(raw_date) < 8 or not raw_date[:8].isdigit():
        return None
    return f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}"


def get_label_info(
    drug_name: str,
    *,
    session: requests.Session | None = None,
) -> dict:
    """Fetch supplementary official FDA label sections from openFDA."""
    clean = normalize_name(drug_name)
    if not clean:
        return {}

    search_expr = (
        f'openfda.generic_name:"{clean}" OR openfda.brand_name:"{clean}" '
        f'OR openfda.substance_name:"{clean}"'
    )
    data, err = _cached_get_json(
        OPENFDA_LABEL,
        params={"search": search_expr, "limit": 1},
        session=session,
    )
    if err or not data:
        return {}

    results = data.get("results") or []
    if not results or not isinstance(results[0], dict):
        return {}

    label = results[0]
    out: dict[str, object] = {}
    for field_name in (
        "purpose",
        "indications_and_usage",
        "warnings",
        "warnings_and_cautions",
        "drug_interactions",
        "ask_doctor_or_pharmacist",
    ):
        value = label.get(field_name)
        if isinstance(value, list) and value and isinstance(value[0], str):
            text = " ".join(value[0].split())
            if text:
                out[field_name] = text[:1500]

    if not out:
        return {}

    openfda_meta = label.get("openfda") or {}
    set_id = label.get("set_id") or (
        openfda_meta.get("spl_set_id", [None])[0]
        if isinstance(openfda_meta.get("spl_set_id"), list)
        else None
    )
    eff_date = _format_fda_date(label.get("effective_time"))
    generic_list = openfda_meta.get("generic_name") or []
    brand_list = openfda_meta.get("brand_name") or []

    out["matched_generic"] = generic_list[0] if generic_list else clean
    out["matched_brand"] = brand_list[0] if brand_list else None
    out["effective_date"] = eff_date or "Date not listed on record"
    out["set_id"] = set_id
    out["label_url"] = (
        f"https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={set_id}"
        if set_id
        else "https://open.fda.gov/apis/drug/label/"
    )
    out["source"] = "U.S. FDA openFDA Drug Labeling API"
    out["disclaimer"] = (
        "Official FDA product labeling excerpt (supplementary context only — "
        "not a complete pairwise interaction check). " + OPENFDA_ATTRIBUTION
    )
    return out
