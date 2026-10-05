"""Free government drug APIs: RxNorm (name lookup) and openFDA (label info).

Both are free, need no API key, and are public domain.
Every function fails gracefully (returns None / "") when offline.
"""

import requests

RXNORM_BASE = "https://rxnav.nlm.nih.gov/REST"
OPENFDA_LABEL = "https://api.fda.gov/drug/label.json"
TIMEOUT = 8


def normalize_drug_name(raw_text: str) -> "str | None":
    """Turn messy text (e.g. OCR output 'LISINOPRIl 10MG TAB') into a
    clean drug name using RxNorm's approximate-match search."""
    try:
        r = requests.get(
            f"{RXNORM_BASE}/approximateTerm.json",
            params={"term": raw_text, "maxEntries": 1},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        candidates = r.json().get("approximateGroup", {}).get("candidate", [])
        if not candidates:
            return None
        rxcui = candidates[0]["rxcui"]
        r2 = requests.get(f"{RXNORM_BASE}/rxcui/{rxcui}.json", timeout=TIMEOUT)
        r2.raise_for_status()
        names = r2.json().get("idGroup", {}).get("name")
        return names.lower() if names else None
    except Exception:
        return None


def get_label_info(drug_name: str) -> dict:
    """Fetch key sections of the FDA label from openFDA.

    Returns a dict with any of: purpose, warnings, drug_interactions.
    Empty dict when nothing is found or offline.
    """
    try:
        r = requests.get(
            OPENFDA_LABEL,
            params={
                "search": f'openfda.generic_name:"{drug_name}"',
                "limit": 1,
            },
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        results = r.json().get("results", [])
        if not results:
            return {}
        label = results[0]
        out = {}
        # Rx labels use 'drug_interactions'; OTC labels put the same info
        # under 'warnings' and 'ask_doctor_or_pharmacist'.
        for field in (
            "purpose",
            "indications_and_usage",
            "warnings",
            "drug_interactions",
            "ask_doctor_or_pharmacist",
        ):
            value = label.get(field)
            if value:
                out[field] = value[0][:1500]  # labels are long; trim for display
        return out
    except Exception:
        return {}


if __name__ == "__main__":
    print(normalize_drug_name("LISINOPRIl 10MG TAB"))
    info = get_label_info("lisinopril")
    print(list(info.keys()))
