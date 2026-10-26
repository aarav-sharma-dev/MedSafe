"""Plain-language explanation layer for already-confirmed interaction records.

Responsible-AI rules enforced here:
1. The database (interactions.py), never the AI, decides whether an
   interaction record exists and what its severity is.
2. Only the minimum non-personal fields of a confirmed record (`drug_a`,
   `drug_b`, `severity`, `mechanism`, `management`, `language`) are ever
   sent to the optional Gemini API. Patient names, notes, prescribers,
   schedules, and bottle images are never transmitted.
3. Gemini is called via the current Interactions API (`v1beta/interactions`,
   model `gemini-3.8-flash`, `store=False`) with a strict JSON schema:
   `explanation`, `why_it_matters`, `what_to_do_next`, `limitations`.
4. Every AI response is validated before display. Malformed JSON, extra/missing
   fields, HTML tags, prescriptive dosing advice, severity contradictions, or
   invented clinical mechanisms when the source had none are rejected and
   replaced with the deterministic built-in template.
5. AI is never used to guess a drug identity from garbled OCR text.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
import requests

import config
from interactions import FoodFinding, InteractionRecord, PairResult
from translations import normalize_language

REQUIRED_FIELDS = ("explanation", "why_it_matters", "what_to_do_next", "limitations")

EXPLANATION_JSON_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "explanation": {"type": "string"},
        "why_it_matters": {"type": "string"},
        "what_to_do_next": {"type": "string"},
        "limitations": {"type": "string"},
    },
    "required": list(REQUIRED_FIELDS),
    "additionalProperties": False,
}

_HTML_TAG_RE = re.compile(r"<\s*/?\s*[a-zA-Z][^>]*>")

# Phrases that prescribe changing treatment or falsely claim safety.
_FORBIDDEN_PATTERNS = [
    re.compile(r"(?i)\b(stop\s+taking|discontinue\s+taking|stop\s+your\s+medication)\b"),
    re.compile(r"(?i)\b(change\s+your\s+dose|adjust\s+your\s+dose|reduce\s+your\s+dose|increase\s+your\s+dose|double\s+your\s+dose|skip\s+your\s+dose)\b"),
    re.compile(r"(?i)\b(switch\s+to\s+another\s+drug|take\s+acetaminophen\s+instead|take\s+tylenol\s+instead)\b"),
    re.compile(r"(?i)\b(completely\s+safe|100%\s+safe|guaranteed\s+safe|no\s+risk\s+at\s+all|totally\s+harmless)\b"),
]

# Specific clinical mechanisms that must NOT appear in AI output unless they
# were already present in the source record's mechanism/management text.
_CLINICAL_CLAIMS = (
    "cyp3a4",
    "cyp2c9",
    "cyp2c19",
    "cyp2d6",
    "rhabdomyolysis",
    "hyperkalemia",
    "serotonin syndrome",
    "lactic acidosis",
    "qt prolongation",
    "torsades",
    "anaphylaxis",
    "clinical trial",
    "randomized study",
    "meta-analysis",
    "pubmed",
)


@dataclass
class ExplanationResult:
    explanation: str
    why_it_matters: str
    what_to_do_next: str
    limitations: str
    source: str  # 'template' | 'ai'
    language: str
    original_english: dict[str, str]
    fallback_reason: str | None = None

    def as_text(self) -> str:
        return (
            f"{self.explanation} {self.why_it_matters} "
            f"{self.what_to_do_next} ({self.limitations})"
        )


def _normalize_input_record(item: InteractionRecord | PairResult | FoodFinding | dict) -> dict[str, str]:
    """Extract ONLY the safe, non-personal interaction fields."""
    if isinstance(item, PairResult):
        rec = item.records[0] if item.records else None
        return {
            "drug_a": item.med_a.display_name,
            "drug_b": item.med_b.display_name,
            "kind": "drug_drug",
            "severity_level": (rec.severity_level if rec else (item.top_severity or "unspecified")).lower(),
            "severity_raw": (rec.severity_raw if rec and rec.severity_raw else "unspecified"),
            "mechanism": (rec.mechanism or "").strip() if rec else "",
            "management": (rec.management or "").strip() if rec else "",
            "dataset_name": rec.dataset_name if rec else "loaded interaction dataset",
        }
    if isinstance(item, InteractionRecord):
        return {
            "drug_a": item.ingredient_a.title(),
            "drug_b": item.ingredient_b.title(),
            "kind": "drug_drug",
            "severity_level": (item.severity_level or "unspecified").lower(),
            "severity_raw": item.severity_raw or item.severity_level or "unspecified",
            "mechanism": (item.mechanism or "").strip(),
            "management": (item.management or "").strip(),
            "dataset_name": item.dataset_name or "loaded interaction dataset",
        }
    if isinstance(item, FoodFinding):
        return {
            "drug_a": item.medicine,
            "drug_b": item.food,
            "kind": "drug_food",
            "severity_level": (item.severity_level or "unspecified").lower(),
            "severity_raw": item.severity_raw or item.severity_level or "unspecified",
            "mechanism": (item.mechanism or "").strip(),
            "management": "",
            "dataset_name": item.dataset_name or "loaded food interaction dataset",
        }

    # Dict input
    is_food = "food" in item and "drug_a" not in item
    drug_a = str(item.get("drug_a") or item.get("drug") or item.get("ingredient_a") or "Medicine A").strip()
    drug_b = str(item.get("drug_b") or item.get("food") or item.get("ingredient_b") or "Medicine B").strip()
    sev_raw = str(item.get("severity_raw") or item.get("severity") or item.get("severity_level") or "unspecified").strip()
    sev_lvl = str(item.get("severity_level") or item.get("severity") or "unspecified").strip().lower()
    if sev_lvl not in ("major", "moderate", "minor", "unspecified"):
        sev_lvl = "unspecified"
    return {
        "drug_a": drug_a,
        "drug_b": drug_b,
        "kind": "drug_food" if is_food else str(item.get("kind") or "drug_drug"),
        "severity_level": sev_lvl,
        "severity_raw": sev_raw,
        "mechanism": str(item.get("mechanism") or "").strip(),
        "management": str(item.get("management") or "").strip(),
        "dataset_name": str(item.get("dataset_name") or "loaded interaction dataset").strip(),
    }


def build_template_fields(info: dict[str, str], language: str = "English") -> dict[str, str]:
    """Deterministic, source-grounded explanation in English, Hindi, or Spanish."""
    lang = normalize_language(language)
    a = info["drug_a"].title()
    b = info["drug_b"].title()
    sev_lvl = info["severity_level"]
    sev_raw = info["severity_raw"]
    mech = info["mechanism"]
    mgmt = info["management"]
    dataset = info["dataset_name"]
    is_food = info.get("kind") == "drug_food"

    if lang == "Hindi":
        sev_word = {
            "major": "गंभीर (Major)",
            "moderate": "मध्यम (Moderate)",
            "minor": "हल्का (Minor)",
            "unspecified": f"अनिर्दिष्ट ({sev_raw})",
        }.get(sev_lvl, sev_raw)
        if is_food:
            explanation = (
                f"{dataset} में {a} (दवा) और {b} (खान-पान) के बीच एक {sev_word} स्तर का "
                f"रिकॉर्ड दर्ज है।"
            )
        else:
            explanation = (
                f"{dataset} में {a} और {b} के बीच एक {sev_word} स्तर का इंटरैक्शन रिकॉर्ड दर्ज है।"
            )
        if mech:
            why = f"स्रोत में दर्ज विवरण: {mech}"
        else:
            why = "लोड किए गए डेटासेट में इस रिकॉर्ड के लिए विस्तृत कारण (mechanism) दर्ज नहीं है।"
        if mgmt:
            next_step = (
                f"स्रोत नोट: {mgmt} कृपया अपने डॉक्टर या फार्मासिस्ट से पूछें कि आपके लिए इसका क्या "
                f"अर्थ है। बिना डॉक्टरी सलाह के कोई भी निर्धारित दवा बंद न करें और न ही खुराक बदलें।"
            )
        else:
            next_step = (
                "कृपया अपने फार्मासिस्ट या डॉक्टर से बात करें कि आपकी स्थिति में इसका क्या अर्थ है। "
                "अपने डॉक्टर या फार्मासिस्ट से पूछे बिना किसी भी निर्धारित दवा को बंद न करें।"
            )
        limitations = (
            f"यह जानकारी केवल {dataset} के रिकॉर्ड पर आधारित है और व्यक्तिगत चिकित्सीय सलाह नहीं है।"
        )
        return {
            "explanation": explanation,
            "why_it_matters": why,
            "what_to_do_next": next_step,
            "limitations": limitations,
        }

    if lang == "Spanish":
        sev_word = {
            "major": "grave / mayor (Major)",
            "moderate": "moderada (Moderate)",
            "minor": "leve / menor (Minor)",
            "unspecified": f"no especificada ({sev_raw})",
        }.get(sev_lvl, sev_raw)
        if is_food:
            explanation = (
                f"La base de datos ({dataset}) registra una precaución {sev_word} entre "
                f"el medicamento {a} y el alimento o bebida {b}."
            )
        else:
            explanation = (
                f"La base de datos ({dataset}) registra una interacción {sev_word} entre {a} y {b}."
            )
        if mech:
            why = f"Descripción registrada por la fuente: {mech}"
        else:
            why = "La base de datos de origen no incluye una descripción detallada del mecanismo para este par."
        if mgmt:
            next_step = (
                f"Nota de la fuente: {mgmt} Consulte a su farmacéutico o médico qué significa "
                f"esto en su caso. No suspenda ni cambie la dosis de un medicamento recetado por su cuenta."
            )
        else:
            next_step = (
                "Consulte a su farmacéutico o médico para entender qué significa este registro "
                "para su situación. No deje de tomar un medicamento recetado por su cuenta."
            )
        limitations = (
            f"Basado únicamente en el registro de {dataset}. No sustituye la revisión de un profesional de la salud."
        )
        return {
            "explanation": explanation,
            "why_it_matters": why,
            "what_to_do_next": next_step,
            "limitations": limitations,
        }

    if lang == "Chinese":
        sev_word = {
            "major": "严重 (Major)",
            "moderate": "中度 (Moderate)",
            "minor": "轻度 (Minor)",
            "unspecified": f"未指定 ({sev_raw})",
        }.get(sev_lvl, sev_raw)
        explanation = (
            f"在已加载的数据库（{dataset}）中，{a} 与 {b} 之间有一条{sev_word}级别的相互作用记录。"
        )
        why = f"来源记录说明：{mech}" if mech else "来源数据库记录了该配对，但未提供详细的机制说明。"
        next_step = (
            f"来源建议：{mgmt} 请咨询您的药剂师或医生了解这对您的具体情况意味着什么。未经医嘱请勿擅自停用处方药或更改剂量。"
            if mgmt
            else "请咨询您的药剂师或医生了解该记录对您的情况意味着什么。未经专业指导请勿擅自停药或更改剂量。"
        )
        limitations = f"严格基于 {dataset} 数据库记录，不能替代针对您个人健康状况的专业医疗评估。"
        return {
            "explanation": explanation,
            "why_it_matters": why,
            "what_to_do_next": next_step,
            "limitations": limitations,
        }

    if lang == "Tagalog":
        sev_word = {
            "major": "malubha / Major",
            "moderate": "katamtaman / Moderate",
            "minor": "bahagya / Minor",
            "unspecified": f"hindi tinukoy ({sev_raw})",
        }.get(sev_lvl, sev_raw)
        explanation = (
            f"Ang naka-load na database ({dataset}) ay may {sev_word} na tala ng interaksyon sa pagitan ng {a} at {b}."
        )
        why = f"Ayon sa pinagmulan: {mech}" if mech else "Walang detalyadong paliwanag ng mekanismo sa database."
        next_step = (
            f"Paalala mula sa database: {mgmt} Makipag-ugnayan sa iyong parmasyutiko o doktor. Huwag ihinto o baguhin ang dosis nang mag-isa."
            if mgmt
            else "Makipag-ugnayan sa iyong parmasyutiko o doktor upang malaman ang ibig sabihin nito para sa iyo. Huwag basta ihinto ang iniresetang gamot."
        )
        limitations = f"Batay lamang sa {dataset}. Hindi ito pamalit sa payo ng doktor o parmasyutiko."
        return {
            "explanation": explanation,
            "why_it_matters": why,
            "what_to_do_next": next_step,
            "limitations": limitations,
        }

    if lang == "Vietnamese":
        sev_word = {
            "major": "nghiêm trọng (Major)",
            "moderate": "trung bình (Moderate)",
            "minor": "nhẹ (Minor)",
            "unspecified": f"chưa phân loại ({sev_raw})",
        }.get(sev_lvl, sev_raw)
        explanation = (
            f"Cơ sở dữ liệu ({dataset}) ghi nhận một tương tác mức độ {sev_word} giữa {a} và {b}."
        )
        why = f"Thông tin từ nguồn dữ liệu: {mech}" if mech else "Cơ sở dữ liệu không cung cấp mô tả cơ chế chi tiết cho cặp này."
        next_step = (
            f"Ghi chú từ nguồn: {mgmt} Hãy hỏi dược sĩ hoặc bác sĩ của quý vị. Tuyệt đối không tự ý ngưng thuốc kê đơn hoặc đổi liều."
            if mgmt
            else "Hãy liên hệ dược sĩ hoặc bác sĩ để hiểu rõ ý nghĩa của bản ghi này đối với tình trạng của quý vị. Không tự ý ngưng thuốc kê đơn."
        )
        limitations = f"Chỉ dựa trên bản ghi trong {dataset}, không thay thế tư vấn y khoa cá nhân."
        return {
            "explanation": explanation,
            "why_it_matters": why,
            "what_to_do_next": next_step,
            "limitations": limitations,
        }

    if lang == "French":
        sev_word = {
            "major": "majeure / grave (Major)",
            "moderate": "modérée (Moderate)",
            "minor": "mineure / légère (Minor)",
            "unspecified": f"non spécifiée ({sev_raw})",
        }.get(sev_lvl, sev_raw)
        explanation = (
            f"La base de données chargée ({dataset}) indique une interaction {sev_word} entre {a} et {b}."
        )
        why = f"Description de la source : {mech}" if mech else "La base de données source ne fournit pas de mécanisme détaillé."
        next_step = (
            f"Note de la source : {mgmt} Consultez votre pharmacien ou médecin. N'arrêtez jamais un médicament prescrit sans avis médical."
            if mgmt
            else "Consultez votre pharmacien ou médecin pour savoir ce que cela signifie dans votre situation. Ne modifiez pas votre dose vous-même."
        )
        limitations = f"Fondé uniquement sur {dataset}. Ne remplace pas une évaluation médicale personnalisée."
        return {
            "explanation": explanation,
            "why_it_matters": why,
            "what_to_do_next": next_step,
            "limitations": limitations,
        }

    # Default: English
    sev_word = {
        "major": "serious (major)",
        "moderate": "moderate",
        "minor": "mild (minor)",
        "unspecified": f"unspecified ({sev_raw})",
    }.get(sev_lvl, sev_raw)
    if is_food:
        explanation = (
            f"The loaded dataset ({dataset}) lists a {sev_word} interaction record between "
            f"the medicine {a} and the food or drink {b}."
        )
    else:
        explanation = (
            f"The loaded dataset ({dataset}) lists a {sev_word} interaction record between "
            f"{a} and {b}."
        )
    if mech:
        why = f"What the source reports: {mech}"
    else:
        why = (
            "The source dataset records this interaction pair but does not supply a "
            "detailed mechanism description."
        )
    if mgmt:
        next_step = (
            f"Source note: {mgmt} Please contact your pharmacist or prescriber to discuss "
            f"what this means for your situation. Do not stop taking a prescribed medicine "
            f"or adjust your dose on your own."
        )
    else:
        next_step = (
            "Contact your pharmacist or prescriber to understand what this record means for "
            "your situation. Do not stop taking a prescribed medicine or change your dose "
            "without professional guidance."
        )
    limitations = (
        f"Grounded strictly in {dataset}. This summary does not account for your full medical "
        f"history, lab values, or unlisted medications."
    )
    return {
        "explanation": explanation,
        "why_it_matters": why,
        "what_to_do_next": next_step,
        "limitations": limitations,
    }


def validate_ai_payload(
    payload: object,
    source_info: dict[str, str],
) -> tuple[bool, str | None]:
    """Validate structured AI explanation output against safety rules.
    Returns (is_valid, rejection_reason)."""
    if not isinstance(payload, dict):
        return False, "not_a_dict"
    if set(payload.keys()) != set(REQUIRED_FIELDS):
        return False, "invalid_fields"

    combined_parts: list[str] = []
    for k in REQUIRED_FIELDS:
        val = payload.get(k)
        if not isinstance(val, str):
            return False, f"non_string_{k}"
        clean = val.strip()
        if len(clean) < 8 or len(clean) > 1200:
            return False, f"length_out_of_range_{k}"
        if _HTML_TAG_RE.search(clean):
            return False, "contains_html"
        combined_parts.append(clean)

    combined = " ".join(combined_parts)
    low = combined.lower()

    for pat in _FORBIDDEN_PATTERNS:
        if pat.search(combined):
            return False, "forbidden_prescriptive_or_safety_claim"

    # Check severity consistency
    sev = source_info.get("severity_level", "unspecified")
    if sev == "major" and re.search(r"(?i)\b(minor\s+interaction|mild\s+concern|harmless)\b", combined):
        return False, "severity_downgrade"
    if sev == "unspecified" and re.search(
        r"(?i)\b(classified\s+as\s+major|classified\s+as\s+minor|major\s+severity|minor\s+severity)\b",
        combined,
    ):
        return False, "invented_severity"

    # Reject invented clinical terms that were not in the source record
    source_blob = (
        f"{source_info.get('mechanism', '')} {source_info.get('management', '')}"
    ).lower()
    for term in _CLINICAL_CLAIMS:
        if term in low and term not in source_blob:
            return False, f"unsupported_clinical_claim:{term}"

    return True, None


def _build_prompt(info: dict[str, str], language: str) -> str:
    pair_desc = (
        f"Medicine: {info['drug_a'].title()}\nFood or Drink: {info['drug_b'].title()}"
        if info.get("kind") == "drug_food"
        else f"Medicine A: {info['drug_a'].title()}\nMedicine B: {info['drug_b'].title()}"
    )
    mech = info["mechanism"] or "Not provided by the source dataset."
    mgmt = info["management"] or "Not provided by the source dataset."
    return (
        "You are rewriting a confirmed medication interaction record into warm, clear, "
        "plain language suitable for a senior adult.\n\n"
        f"{pair_desc}\n"
        f"Source dataset: {info['dataset_name']}\n"
        f"Source recorded severity: {info['severity_raw']} (normalized: {info['severity_level']})\n"
        f"Source recorded mechanism: {mech}\n"
        f"Source recorded management note: {mgmt}\n"
        f"Target display language: {language}\n\n"
        "Strict safety rules:\n"
        "1. Use ONLY the facts provided above. If the mechanism or management note says "
        "'Not provided by the source dataset', explicitly state that the source dataset "
        "does not provide that detail.\n"
        "2. Do NOT change or downgrade the recorded severity.\n"
        "3. Do NOT tell the user to stop taking a medicine, change a dose, skip a dose, "
        "or switch to another drug.\n"
        "4. Encourage talking with a pharmacist or prescriber.\n"
        "5. Return valid JSON with exactly the four string fields: "
        "explanation, why_it_matters, what_to_do_next, limitations."
    )


def _extract_interaction_text(resp_json: dict) -> str | None:
    """Extract output text from a Gemini Interactions API JSON response
    (or legacy candidates response if mocked in tests)."""
    if not isinstance(resp_json, dict):
        return None
    if isinstance(resp_json.get("output_text"), str) and resp_json["output_text"].strip():
        return resp_json["output_text"].strip()
    steps = resp_json.get("steps")
    if isinstance(steps, list):
        texts: list[str] = []
        for step in reversed(steps):
            if isinstance(step, dict) and step.get("type") == "model_output":
                for part in step.get("content") or []:
                    if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str):
                        texts.append(part["text"])
                if texts:
                    return "\n".join(texts).strip()
    candidates = resp_json.get("candidates")
    if isinstance(candidates, list) and candidates:
        try:
            return candidates[0]["content"]["parts"][0]["text"].strip()
        except (KeyError, IndexError, TypeError):
            return None
    return None


def explain_structured(
    interaction: InteractionRecord | PairResult | FoodFinding | dict,
    language: str = "English",
    *,
    session: requests.Session | None = None,
) -> ExplanationResult:
    """Return a validated, structured plain-language explanation of a confirmed
    interaction record, falling back to deterministic templates whenever Gemini
    is unconfigured, unreachable, or returns an unvalidated payload."""
    lang = normalize_language(language)
    info = _normalize_input_record(interaction)
    english_template = build_template_fields(info, "English")
    localized_template = build_template_fields(info, lang)

    api_key = config.gemini_api_key()
    if not api_key:
        return ExplanationResult(
            **localized_template,
            source="template",
            language=lang,
            original_english=english_template,
            fallback_reason="no_api_key",
        )

    prompt = _build_prompt(info, lang)
    http = session or requests
    models_to_try = (
        config.gemini_model_chain()
        if hasattr(config, "gemini_model_chain")
        else [config.gemini_model()]
    )
    body = {
        "model": config.gemini_model(),
        "input": prompt,
        "store": False,
        "system_instruction": (
            "You are a safety-first healthcare plain-language translator. Never invent "
            "medical facts, mechanisms, severities, or dosing advice."
        ),
        "response_format": {
            "type": "text",
            "mime_type": "application/json",
            "schema": EXPLANATION_JSON_SCHEMA,
        },
    }
    try:
        # Auth via header, not ?key= query param: the Interactions API expects
        # x-goog-api-key, and keys never belong in URLs (they end up in logs).
        raw_text = None
        for model_name in models_to_try:
            body["model"] = model_name
            resp = http.post(
                config.GEMINI_ENDPOINT,
                headers={"x-goog-api-key": api_key},
                json=body,
                timeout=config.AI_TIMEOUT,
            )
            if resp.status_code in (429, 403, 404, 500, 503) and model_name != models_to_try[-1]:
                continue  # quota-limited or unknown model: try the fallback
            resp.raise_for_status()
            raw_text = _extract_interaction_text(resp.json())
            break
        if not raw_text:
            raise ValueError("empty_model_output")
        parsed = json.loads(raw_text)
    except Exception:
        return ExplanationResult(
            **localized_template,
            source="template",
            language=lang,
            original_english=english_template,
            fallback_reason="api_or_parse_error",
        )

    valid, reason = validate_ai_payload(parsed, info)
    if not valid:
        return ExplanationResult(
            **localized_template,
            source="template",
            language=lang,
            original_english=english_template,
            fallback_reason=reason,
        )

    return ExplanationResult(
        explanation=parsed["explanation"].strip(),
        why_it_matters=parsed["why_it_matters"].strip(),
        what_to_do_next=parsed["what_to_do_next"].strip(),
        limitations=parsed["limitations"].strip(),
        source="ai",
        language=lang,
        original_english=english_template,
        fallback_reason=None,
    )


def explain_food_structured(
    row: FoodFinding | dict,
    language: str = "English",
    *,
    session: requests.Session | None = None,
) -> ExplanationResult:
    if isinstance(row, dict) and "kind" not in row:
        row = {**row, "kind": "drug_food"}
    return explain_structured(row, language=language, session=session)


def explain(interaction: InteractionRecord | PairResult | dict, language: str = "English") -> str:
    """Plain-language string summary of a confirmed interaction."""
    return explain_structured(interaction, language=language).as_text()


def explain_food(row: FoodFinding | dict, language: str = "English") -> str:
    """Plain-language string summary of a confirmed drug-food interaction."""
    return explain_food_structured(row, language=language).as_text()


if __name__ == "__main__":
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    demo = {
        "drug_a": "lisinopril",
        "drug_b": "ibuprofen",
        "severity": "major",
        "mechanism": (
            "NSAIDs like ibuprofen reduce the blood-pressure-lowering "
            "effect of ACE inhibitors and together can strain the kidneys."
        ),
    }
    for lg in ("English", "Hindi", "Spanish"):
        res = explain_structured(demo, lg)
        print(f"[{lg} | source={res.source}] {res.explanation}")
