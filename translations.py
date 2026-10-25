"""Multilingual translation system for MedSafe.

Supported languages (7):
* English
* Spanish (Español)
* Hindi (हिन्दी)
* Chinese (中文 - 简体)
* Tagalog (Filipino)
* Vietnamese (Tiếng Việt)
* French (Français)

Design rules enforced here:
* Every UI section, navigation item, button, empty state, validation message,
  interaction status, severity label, and safety disclaimer has a stable key.
* Medication names, active ingredients, and standardized identifiers (RxCUI,
  dataset record IDs) are preserved as-is so clinical identifiers are never
  mistranslated.
"""

from __future__ import annotations

SUPPORTED_LANGUAGES: dict[str, str] = {
    "English": "English",
    "Spanish": "Español (Spanish)",
    "Hindi": "हिन्दी (Hindi)",
    "Chinese": "中文 (Chinese)",
    "Tagalog": "Tagalog (Filipino)",
    "Vietnamese": "Tiếng Việt (Vietnamese)",
    "French": "Français (French)",
}

TTS_LANG_CODES: dict[str, str] = {
    "English": "en",
    "Spanish": "es",
    "Hindi": "hi",
    "Chinese": "zh-CN",
    "Tagalog": "tl",
    "Vietnamese": "vi",
    "French": "fr",
}

TRANSLATIONS: dict[str, dict[str, str]] = {
    "English": {
        # Header & Global Banners
        "app_tagline": "Medication safety and daily routine companion",
        "privacy_badge_local": "Local-first prototype: your medication list is stored in SQLite on this device.",
        "demo_badge": "DEMO MODE — FICTIONAL SAMPLE DATA",
        "demo_banner_text": (
            "Demonstration Mode is active. You are viewing fictional sample medications "
            "(Lisinopril, Metformin, Atorvastatin, and an unconfirmed herbal supplement) "
            "to explore MedSafe safely. Switch to Personal Mode in the sidebar or Settings anytime."
        ),
        "medical_disclaimer": (
            "Educational Prototype Disclaimer: MedSafe is a student project for the "
            "Congressional App Challenge. It is not clinically validated, diagnostic, or "
            "a substitute for professional medical or pharmacist advice. Never stop, start, "
            "or change a prescribed medication without consulting your prescriber or pharmacist."
        ),

        # Navigation
        "nav_title": "Navigation",
        "nav_overview": "Overview",
        "nav_medicines": "My Medicines",
        "nav_scan": "Scan a Bottle",
        "nav_checker": "Safety Checker",
        "nav_schedule": "Daily Schedule",
        "nav_reports": "Caregiver & Reports",
        "nav_settings": "Settings & Privacy",

        # Onboarding
        "onboarding_title": "How MedSafe works (5 quick steps)",
        "onboarding_step_1": "1. Add medicines by typing a name or scanning a pill bottle label.",
        "onboarding_step_2": "2. Review and confirm each medicine's active ingredient, strength, and form.",
        "onboarding_step_3": "3. Check your list against the loaded interaction dataset.",
        "onboarding_step_4": "4. Understand what the result means — and what the dataset does not cover.",
        "onboarding_step_5": "5. Organize your daily schedule and print a clear summary for your pharmacist or doctor.",

        # Overview
        "overview_heading": "Your medication overview",
        "overview_subtitle": (
            "Review your active medicines, check available interaction records, "
            "and organize your daily medication routine."
        ),
        "stat_active_meds": "Active medicines",
        "stat_needs_confirmation": "Needs identity confirmation",
        "stat_unresolved_checks": "Unresolved checks / limitations",
        "stat_today_schedule": "Today's scheduled doses",
        "stat_dataset_records": "Loaded interaction records",
        "quick_actions_title": "Primary actions",
        "btn_add_medicine": "Add a medicine",
        "btn_scan_bottle": "Scan a bottle",
        "btn_check_interaction": "Check an interaction",
        "btn_review_schedule": "Review today's schedule",
        "btn_prepare_summary": "Prepare a medication summary",
        "empty_meds_title": "No medicines in your list yet",
        "empty_meds_body": (
            "Start by adding your first prescription medicine, over-the-counter pain reliever, "
            "or supplement. You can type the name or scan a bottle label."
        ),
        "btn_add_first_med": "Add your first medicine",
        "recent_activity_title": "Recent activity & items needing attention",

        # My Medicines
        "meds_heading": "My Medicines",
        "meds_subtitle": (
            "Manage your active and past medicines, confirm standardized ingredients, "
            "and keep your prescribed directions organized."
        ),
        "cat_prescription": "Prescription medicine",
        "cat_otc": "Over-the-counter (OTC)",
        "cat_supplement": "Vitamin / supplement",
        "cat_herbal": "Herbal product",
        "cat_other": "Other",
        "id_confirmed": "Identity confirmed",
        "id_needs_review": "Needs identity confirmation",
        "id_unidentified": "Unidentified — cannot check interactions",
        "coverage_note_categories": (
            "Note on coverage: The loaded starter dataset primarily covers common "
            "prescription and over-the-counter drug pairs. Many supplements and herbal "
            "products are not represented in the dataset."
        ),
        "duplicate_warning_title": "Possible duplicate medicines or shared ingredients to review",
        "duplicate_warning_body": (
            "This is a review aid, not a clinical judgment. Please check with your pharmacist "
            "whether these entries are intended to be taken together:"
        ),

        # Scan a Bottle
        "scan_heading": "Scan a Medication Bottle",
        "scan_subtitle": (
            "Capture or upload a clear photo of a pill bottle label, or try a built-in "
            "demonstration label. Every scanned medicine requires your review before saving."
        ),
        "ocr_review_heading": "Review scanned label before saving",
        "ocr_uncertainty_banner": (
            "Human confirmation required: A photo of a bottle is not proof of identity. "
            "Please verify the medication name, active ingredient, strength, and directions "
            "against your physical bottle."
        ),

        # Safety Checker
        "checker_heading": "Safety Checker",
        "checker_subtitle": "Check a medicine against your current medication list.",
        "checker_mode_proposed": "A. Check a medicine I am considering adding",
        "checker_mode_full": "B. Review my current active medication list",
        "checker_run_btn": "Run interaction lookup",
        "incomplete_check_banner": (
            "Incomplete check: One or more medicines do not have a confirmed identity "
            "(or the interaction dataset is unavailable). Pairs involving those medicines "
            "could not be checked."
        ),

        # Interaction Statuses & Severities
        "status_MATCH_FOUND": "Interaction record found in loaded dataset",
        "status_NO_MATCHING_RECORD": "No matching record in loaded dataset (not proof of safety)",
        "status_IDENTITY_REQUIRES_CONFIRMATION": "Cannot check yet — medication identity needs confirmation",
        "status_UNABLE_TO_CHECK": "Unable to check — medication unidentified or lookup failed",
        "status_DATASET_UNAVAILABLE": "Unable to check — interaction dataset is unavailable",

        "severity_major": "Serious / Major (source classification)",
        "severity_moderate": "Moderate (source classification)",
        "severity_minor": "Minor / Mild (source classification)",
        "severity_unspecified": "Unspecified by source dataset",

        "no_record_explanation": (
            "No matching interaction record was found in the loaded dataset for this pair. "
            "Because the dataset is incomplete, this result does NOT confirm that these "
            "medicines are safe to take together. Ask a pharmacist or prescriber if you are unsure."
        ),
        "action_caution_match": (
            "An interaction record was found for these medicines. Contact your pharmacist "
            "or prescriber to understand what this means for your situation. Do not stop "
            "taking a prescribed medicine or change your dose without medical guidance."
        ),
        "action_caution_major": (
            "Prompt professional review recommended: The loaded dataset classifies this pair "
            "as a major interaction. Please speak with your pharmacist or prescriber before "
            "taking these medicines together. Do not stop a prescribed medicine on your own."
        ),
        "badge_source_template": "Built-in verified template (deterministic)",
        "badge_source_ai": "Plain-language rewrite by Gemini AI (from confirmed database record)",
        "show_original_english": "Show original English source record",

        # Daily Schedule
        "schedule_heading": "Daily Medication Schedule",
        "schedule_subtitle": (
            "Organize your daily routine and keep track of doses taken or skipped today."
        ),
        "schedule_honest_notice": (
            "In-app schedule notice: This checklist updates while MedSafe is open on your "
            "device. It does not send background push or SMS alerts when the browser is closed. "
            "You can download a calendar (.ics) file below to add reminders to your phone or computer."
        ),
        "missed_dose_warning": (
            "Missed or skipped dose note: Do not double your next dose to make up for a "
            "skipped dose. Check the instructions on your prescription label or ask your "
            "pharmacist what to do when a dose is missed."
        ),
        "dose_taken": "Marked taken",
        "dose_skipped": "Marked skipped",
        "dose_pending": "Not yet recorded",

        # Caregiver & Reports
        "reports_heading": "Caregiver & Pharmacist Reports",
        "reports_subtitle": (
            "Prepare a clear, honest summary of your medication list, interaction lookup "
            "results, and questions to bring to your pharmacist, doctor, or family caregiver."
        ),
        "caregiver_privacy_note": (
            "Privacy guarantee: MedSafe never automatically emails or transmits your "
            "medication list to anyone. Reports are generated locally on this screen so "
            "you can review them before downloading or printing."
        ),

        # Settings & Privacy
        "settings_heading": "Settings, Accessibility & Privacy",
        "settings_subtitle": (
            "Adjust theme mode (Light, Dark, High-Contrast), text size, language, "
            "demonstration mode, and local data controls."
        ),
    },

    "Hindi": {
        "app_tagline": "दवा सुरक्षा और दैनिक दिनचर्या सहायक",
        "privacy_badge_local": "लोकल-फ़र्स्ट प्रोटोटाइप: आपकी दवाओं की सूची इसी कंप्यूटर पर सुरक्षित रहती है।",
        "demo_badge": "डेमो मोड — काल्पनिक उदाहरण डेटा",
        "demo_banner_text": (
            "डेमो मोड चालू है। आप इस समय काल्पनिक उदाहरण दवाएं (Lisinopril, Metformin, "
            "Atorvastatin और एक हर्बल सप्लीमेंट) देख रहे हैं ताकि ऐप को आसानी से समझ सकें। "
            "अपनी असली सूची के लिए बाईं ओर या सेटिंग्स में पर्सनल मोड चुनें।"
        ),
        "medical_disclaimer": (
            "महत्वपूर्ण सूचना: MedSafe Congressional App Challenge के लिए बनाया गया एक शैक्षिक "
            "प्रोटोटाइप है। यह डॉक्टर या फार्मासिस्ट की सलाह का विकल्प नहीं है। अपने डॉक्टर या "
            "फार्मासिस्ट से पूछे बिना किसी भी निर्धारित दवा को बंद न करें और न ही उसकी खुराक बदलें।"
        ),
        "nav_title": "मुख्य मेनू",
        "nav_overview": "सारांश (Overview)",
        "nav_medicines": "मेरी दवाएं",
        "nav_scan": "बोतल स्कैन करें",
        "nav_checker": "सुरक्षा जांच (Safety Checker)",
        "nav_schedule": "दैनिक समय-सारणी",
        "nav_reports": "केयरगिवर और रिपोर्ट",
        "nav_settings": "सेटिंग्स और गोपनीयता",
        "onboarding_title": "MedSafe कैसे काम करता है (5 आसान चरण)",
        "onboarding_step_1": "1. दवा का नाम टाइप करें या दवा की बोतल का लेबल स्कैन करें।",
        "onboarding_step_2": "2. सेव करने से पहले दवा के मुख्य घटक (ingredient) और ताकत (mg) की पुष्टि करें।",
        "onboarding_step_3": "3. उपलब्ध डेटाबेस में दवाओं के आपसी प्रभाव (interaction) की जांच करें।",
        "onboarding_step_4": "4. परिणाम और डेटाबेस की सीमाओं को सरल भाषा में समझें।",
        "onboarding_step_5": "5. अपनी दैनिक समय-सारणी बनाएं और डॉक्टर या फार्मासिस्ट के लिए सारांश तैयार करें।",
        "overview_heading": "आपकी दवाओं का सारांश",
        "overview_subtitle": (
            "अपनी सक्रिय दवाओं की समीक्षा करें, उपलब्ध इंटरैक्शन रिकॉर्ड जांचें और अपनी "
            "दैनिक दिनचर्या को व्यवस्थित रखें।"
        ),
        "stat_active_meds": "सक्रिय दवाएं",
        "stat_needs_confirmation": "पहचान की पुष्टि बाकी",
        "stat_unresolved_checks": "अधूरी जांच / सीमाएं",
        "stat_today_schedule": "आज की निर्धारित खुराक",
        "stat_dataset_records": "डेटाबेस में उपलब्ध रिकॉर्ड",
        "quick_actions_title": "प्रमुख कार्य",
        "btn_add_medicine": "दवा जोड़ें",
        "btn_scan_bottle": "बोतल स्कैन करें",
        "btn_check_interaction": "इंटरैक्शन जांचें",
        "btn_review_schedule": "आज की समय-सारणी देखें",
        "btn_prepare_summary": "सारांश रिपोर्ट बनाएं",
        "empty_meds_title": "आपकी सूची में अभी कोई दवा नहीं है",
        "empty_meds_body": "अपनी पहली दवा या सप्लीमेंट जोड़कर शुरुआत करें। आप नाम टाइप कर सकते हैं या लेबल स्कैन कर सकते हैं।",
        "btn_add_first_med": "पहली दवा जोड़ें",
        "recent_activity_title": "हाल की गतिविधि और ध्यान देने योग्य बातें",
        "meds_heading": "मेरी दवाएं",
        "meds_subtitle": "अपनी सक्रिय और पुरानी दवाओं को व्यवस्थित करें और उनके मानक घटकों की पुष्टि करें।",
        "cat_prescription": "डॉक्टर के पर्चे की दवा (Prescription)",
        "cat_otc": "बिना पर्चे की दवा (OTC)",
        "cat_supplement": "विटामिन / सप्लीमेंट",
        "cat_herbal": "हर्बल उत्पाद",
        "cat_other": "अन्य",
        "id_confirmed": "पहचान पुष्ट (Confirmed)",
        "id_needs_review": "पुष्टि आवश्यक (Needs Confirmation)",
        "id_unidentified": "अज्ञात — इंटरैक्शन जांच संभव नहीं",
        "coverage_note_categories": (
            "डेटासेट सीमा: लोड किए गए शुरुआती डेटासेट में मुख्य रूप से सामान्य एलोपैथिक दवाएं शामिल हैं। "
            "कई हर्बल उत्पाद और सप्लीमेंट इसमें शामिल नहीं हैं।"
        ),
        "duplicate_warning_title": "संभावित दोहराव या समान घटक वाली दवाएं",
        "duplicate_warning_body": "कृपया अपने फार्मासिस्ट से पूछें कि क्या ये दवाएं एक साथ ली जानी चाहिए:",
        "scan_heading": "दवा की बोतल स्कैन करें",
        "scan_subtitle": (
            "बोतल के लेबल की स्पष्ट फोटो अपलोड करें या डेमो लेबल आज़माएं। सेव करने से पहले आपकी "
            "पुष्टि आवश्यक है।"
        ),
        "ocr_review_heading": "सेव करने से पहले स्कैन किए गए विवरण की जांच करें",
        "ocr_uncertainty_banner": (
            "मानवीय पुष्टि आवश्यक: केवल फोटो से दवा की पक्की पहचान नहीं होती। कृपया अपनी असली "
            "बोतल से नाम, घटक और ताकत (mg) का मिलान करें।"
        ),
        "checker_heading": "सुरक्षा जांच (Safety Checker)",
        "checker_subtitle": "अपनी वर्तमान दवाओं के साथ किसी नई या मौजूदा दवा की जांच करें।",
        "checker_mode_proposed": "A. उस नई दवा की जांच करें जिसे मैं लेने की सोच रहा/रही हूं",
        "checker_mode_full": "B. मेरी वर्तमान सक्रिय दवाओं की आपस में जांच करें",
        "checker_run_btn": "इंटरैक्शन जांच चलाएं",
        "incomplete_check_banner": (
            "अधूरी जांच: एक या अधिक दवाओं की पहचान पुष्ट नहीं है (या डेटासेट उपलब्ध नहीं है)। "
            "उन दवाओं से जुड़े जोड़ों की पूरी जांच नहीं हो सकी।"
        ),
        "status_MATCH_FOUND": "डेटाबेस में इंटरैक्शन रिकॉर्ड मिला",
        "status_NO_MATCHING_RECORD": "डेटाबेस में कोई रिकॉर्ड नहीं मिला (सुरक्षित होने का प्रमाण नहीं)",
        "status_IDENTITY_REQUIRES_CONFIRMATION": "जांच रुकी — दवा की पहचान की पुष्टि आवश्यक है",
        "status_UNABLE_TO_CHECK": "जांच असंभव — दवा अज्ञात है या खोज विफल रही",
        "status_DATASET_UNAVAILABLE": "जांच असंभव — इंटरैक्शन डेटासेट उपलब्ध नहीं है",
        "severity_major": "गंभीर / Major (स्रोत वर्गीकरण)",
        "severity_moderate": "मध्यम / Moderate (स्रोत वर्गीकरण)",
        "severity_minor": "हल्का / Minor (स्रोत वर्गीकरण)",
        "severity_unspecified": "स्रोत डेटासेट में स्तर अनिर्दिष्ट",
        "no_record_explanation": (
            "लोड किए गए डेटासेट में इस जोड़ी के लिए कोई इंटरैक्शन रिकॉर्ड नहीं मिला। चूंकि यह डेटासेट "
            "अधूरा है, इसलिए इसका यह अर्थ नहीं है कि ये दवाएं एक साथ लेना पूरी तरह सुरक्षित है। "
            "संदेह होने पर कृपया अपने फार्मासिस्ट या डॉक्टर से पूछें।"
        ),
        "action_caution_match": (
            "इन दवाओं के लिए एक इंटरैक्शन रिकॉर्ड मिला है। कृपया अपने फार्मासिस्ट या डॉक्टर से समझें "
            "कि आपकी स्थिति में इसका क्या अर्थ है। बिना डॉक्टरी सलाह के कोई भी निर्धारित दवा बंद न करें।"
        ),
        "action_caution_major": (
            "तुरंत डॉक्टरी परामर्श की सलाह: डेटाबेस इसे एक गंभीर (Major) इंटरैक्शन मानता है। "
            "इन्हें एक साथ लेने से पहले अपने डॉक्टर या फार्मासिस्ट से अवश्य बात करें। अपने आप दवा बंद न करें।"
        ),
        "badge_source_template": "अंतर्निहित सत्यापित टेम्पलेट (Deterministic)",
        "badge_source_ai": "Gemini AI द्वारा सरल भाषा में अनुवाद (पुष्ट डेटाबेस रिकॉर्ड से)",
        "show_original_english": "मूल अंग्रेजी स्रोत रिकॉर्ड देखें",
        "schedule_heading": "दैनिक दवा समय-सारणी",
        "schedule_subtitle": "अपनी दैनिक दिनचर्या व्यवस्थित करें और आज ली गई खुराक दर्ज करें।",
        "schedule_honest_notice": (
            "समय-सारणी सूचना: यह सूची तब काम करती है जब MedSafe खुला हो। ब्राउज़र बंद होने पर यह "
            "अपने आप फोन अलर्ट या SMS नहीं भेजता। आप नीचे से कैलेंडर (.ics) फ़ाइल डाउनलोड कर सकते हैं।"
        ),
        "missed_dose_warning": (
            "छूटी हुई खुराक पर ध्यान दें: छूटी हुई खुराक की भरपाई के लिए अगली खुराक को दोगुना न करें। "
            "अपने पर्चे के निर्देश देखें या फार्मासिस्ट से पूछें।"
        ),
        "dose_taken": "ली गई (Taken)",
        "dose_skipped": "छूट गई (Skipped)",
        "dose_pending": "अभी दर्ज नहीं",
        "reports_heading": "केयरगिवर और फार्मासिस्ट रिपोर्ट",
        "reports_subtitle": (
            "अपने डॉक्टर, फार्मासिस्ट या परिवार के सदस्यों के लिए अपनी दवाओं और सवालों का स्पष्ट "
            "सारांश तैयार करें।"
        ),
        "caregiver_privacy_note": (
            "गोपनीयता की गारंटी: MedSafe कभी भी अपने आप किसी को ईमेल या संदेश नहीं भेजता। "
            "रिपोर्ट इसी स्क्रीन पर बनती है जिसे आप स्वयं देखकर डाउनलोड या प्रिंट कर सकते हैं।"
        ),
        "settings_heading": "सेटिंग्स, सुगम्यता और गोपनीयता",
        "settings_subtitle": "थीम (लाइट, डार्क, हाई-कॉन्ट्रास्ट), अक्षरों का आकार, भाषा और डेटा नियंत्रण बदलें।",
    },

    "Spanish": {
        "app_tagline": "Compañero de seguridad de medicamentos y rutina diaria",
        "privacy_badge_local": "Prototipo local: su lista de medicamentos se guarda en SQLite en este dispositivo.",
        "demo_badge": "MODO DEMO — DATOS DE EJEMPLO FICTICIOS",
        "demo_banner_text": (
            "El Modo de Demostración está activo. Está viendo medicamentos de ejemplo ficticios "
            "(Lisinopril, Metformin, Atorvastatin y un suplemento herbal sin confirmar). "
            "Cambie al Modo Personal en la barra lateral o en Ajustes cuando lo desee."
        ),
        "medical_disclaimer": (
            "Aviso de Prototipo Educativo: MedSafe es un proyecto estudiantil para el "
            "Congressional App Challenge. No está validado clínicamente ni sustituye el consejo "
            "de un médico o farmacéutico. Nunca deje de tomar, inicie ni cambie la dosis de un "
            "medicamento recetado sin consultar a su médico o farmacéutico."
        ),
        "nav_title": "Navegación",
        "nav_overview": "Resumen",
        "nav_medicines": "Mis Medicamentos",
        "nav_scan": "Escanear Frasco",
        "nav_checker": "Verificador de Seguridad",
        "nav_schedule": "Horario Diario",
        "nav_reports": "Cuidadores e Informes",
        "nav_settings": "Ajustes y Privacidad",
        "onboarding_title": "Cómo funciona MedSafe (5 pasos sencillos)",
        "onboarding_step_1": "1. Agregue medicamentos escribiendo el nombre o escaneando la etiqueta del frasco.",
        "onboarding_step_2": "2. Revise y confirme el ingrediente activo, la concentración y la forma farmacéutica.",
        "onboarding_step_3": "3. Compare su lista con la base de datos de interacciones cargada.",
        "onboarding_step_4": "4. Comprenda qué significa el resultado y qué no cubre la base de datos.",
        "onboarding_step_5": "5. Organice su horario diario e imprima un resumen claro para su farmacéutico o médico.",
        "overview_heading": "Resumen de sus medicamentos",
        "overview_subtitle": (
            "Revise sus medicamentos activos, consulte los registros de interacciones disponibles "
            "y organice su rutina diaria."
        ),
        "stat_active_meds": "Medicamentos activos",
        "stat_needs_confirmation": "Requieren confirmar identidad",
        "stat_unresolved_checks": "Revisiones pendientes / límites",
        "stat_today_schedule": "Dosis programadas hoy",
        "stat_dataset_records": "Registros en base de datos",
        "quick_actions_title": "Acciones principales",
        "btn_add_medicine": "Agregar medicamento",
        "btn_scan_bottle": "Escanear frasco",
        "btn_check_interaction": "Verificar interacción",
        "btn_review_schedule": "Ver horario de hoy",
        "btn_prepare_summary": "Preparar resumen",
        "empty_meds_title": "Aún no hay medicamentos en su lista",
        "empty_meds_body": (
            "Comience agregando su primer medicamento con receta, analgésico de venta libre "
            "o suplemento. Puede escribir el nombre o escanear una etiqueta."
        ),
        "btn_add_first_med": "Agregar mi primer medicamento",
        "recent_activity_title": "Actividad reciente y elementos que requieren atención",
        "meds_heading": "Mis Medicamentos",
        "meds_subtitle": (
            "Administre sus medicamentos activos y anteriores, confirme los ingredientes "
            "estandarizados y mantenga organizadas sus instrucciones."
        ),
        "cat_prescription": "Medicamento con receta",
        "cat_otc": "Venta libre (OTC)",
        "cat_supplement": "Vitamina / suplemento",
        "cat_herbal": "Producto herbal",
        "cat_other": "Otro",
        "id_confirmed": "Identidad confirmada",
        "id_needs_review": "Requiere confirmar identidad",
        "id_unidentified": "No identificado — no se puede verificar",
        "coverage_note_categories": (
            "Nota de cobertura: El conjunto de datos inicial cubre principalmente medicamentos "
            "comunes con receta y de venta libre. Muchos suplementos y productos herbales no "
            "están incluidos en la base de datos."
        ),
        "duplicate_warning_title": "Posibles medicamentos duplicados o ingredientes repetidos",
        "duplicate_warning_body": (
            "Esta es una ayuda de revisión, no un juicio clínico. Consulte con su farmacéutico "
            "si ambos medicamentos deben tomarse juntos:"
        ),
        "scan_heading": "Escanear un Frasco de Medicamento",
        "scan_subtitle": (
            "Tome o suba una foto clara de la etiqueta del frasco, o pruebe una etiqueta de "
            "demostración. Todo medicamento escaneado requiere su confirmación antes de guardarse."
        ),
        "ocr_review_heading": "Revise la etiqueta escaneada antes de guardar",
        "ocr_uncertainty_banner": (
            "Se requiere confirmación humana: Una foto no confirma por sí sola la identidad del "
            "medicamento. Verifique el nombre, ingrediente activo, concentración e instrucciones "
            "con su frasco físico."
        ),
        "checker_heading": "Verificador de Seguridad",
        "checker_subtitle": "Compare un medicamento con su lista actual de medicamentos.",
        "checker_mode_proposed": "A. Verificar un medicamento que estoy considerando agregar",
        "checker_mode_full": "B. Revisar mi lista actual de medicamentos activos",
        "checker_run_btn": "Ejecutar búsqueda de interacciones",
        "incomplete_check_banner": (
            "Revisión incompleta: Uno o más medicamentos no tienen una identidad confirmada "
            "(o la base de datos no está disponible). Los pares que incluyen esos medicamentos "
            "no pudieron verificarse."
        ),
        "status_MATCH_FOUND": "Registro de interacción encontrado en la base de datos",
        "status_NO_MATCHING_RECORD": "Sin registro coincidente en la base de datos (no prueba seguridad)",
        "status_IDENTITY_REQUIRES_CONFIRMATION": "Pendiente — se requiere confirmar la identidad del medicamento",
        "status_UNABLE_TO_CHECK": "No se pudo verificar — medicamento no identificado o fallo de consulta",
        "status_DATASET_UNAVAILABLE": "No se pudo verificar — la base de datos no está disponible",
        "severity_major": "Grave / Mayor (clasificación de la fuente)",
        "severity_moderate": "Moderada (clasificación de la fuente)",
        "severity_minor": "Leve / Menor (clasificación de la fuente)",
        "severity_unspecified": "No especificada por la base de datos de origen",
        "no_record_explanation": (
            "No se encontró ningún registro de interacción coincidente en la base de datos "
            "cargada para este par. Debido a que la base de datos es incompleta, este resultado "
            "NO confirma que sea seguro tomarlos juntos. Consulte a su farmacéutico o médico."
        ),
        "action_caution_match": (
            "Se encontró un registro de interacción para estos medicamentos. Comuníquese con su "
            "farmacéutico o médico para saber qué significa en su caso. No deje de tomar un "
            "medicamento recetado ni cambie su dosis por su cuenta."
        ),
        "action_caution_major": (
            "Se recomienda revisión profesional pronta: La base de datos clasifica este par como "
            "una interacción mayor. Hable con su farmacéutico o médico antes de tomar estos "
            "medicamentos juntos. No suspenda un medicamento recetado por su cuenta."
        ),
        "badge_source_template": "Plantilla verificada integrada (determinista)",
        "badge_source_ai": "Explicación en lenguaje sencillo por Gemini AI (basada en el registro confirmado)",
        "show_original_english": "Mostrar el registro original en inglés",
        "schedule_heading": "Horario Diario de Medicamentos",
        "schedule_subtitle": "Organice su rutina diaria y registre las dosis tomadas o saltadas hoy.",
        "schedule_honest_notice": (
            "Aviso sobre recordatorios: Esta lista funciona mientras MedSafe está abierto en su "
            "dispositivo. No envía alertas automáticas ni mensajes SMS cuando el navegador está "
            "cerrado. Puede descargar un archivo de calendario (.ics) abajo para su teléfono."
        ),
        "missed_dose_warning": (
            "Nota sobre dosis olvidadas: Nunca duplique la siguiente dosis para compensar una "
            "dosis olvidada. Revise las instrucciones de su receta o pregunte a su farmacéutico."
        ),
        "dose_taken": "Marcada como tomada",
        "dose_skipped": "Marcada como omitida",
        "dose_pending": "Aún sin registrar",
        "reports_heading": "Informes para Cuidadores y Farmacéuticos",
        "reports_subtitle": (
            "Prepare un resumen claro y honesto de sus medicamentos, resultados de búsqueda "
            "de interacciones y preguntas para su farmacéutico, médico o familiar."
        ),
        "caregiver_privacy_note": (
            "Garantía de privacidad: MedSafe nunca envía ni comparte automáticamente su lista "
            "de medicamentos. Los informes se generan localmente para que usted los revise antes "
            "de descargarlos o imprimirlos."
        ),
        "settings_heading": "Ajustes, Accesibilidad y Privacidad",
        "settings_subtitle": (
            "Ajuste el tema (Claro, Oscuro, Alto Contraste), tamaño de letra, idioma, "
            "modo de demostración y control de sus datos locales."
        ),
    },

    "Chinese": {
        "app_tagline": "用药安全与日常服药管理助手",
        "privacy_badge_local": "本地优先原型：您的药物清单保存在本设备的 SQLite 数据库中。",
        "demo_badge": "演示模式 — 虚构示例数据",
        "demo_banner_text": (
            "演示模式已启用。您当前查看的是虚构的示例药物（Lisinopril、Metformin、Atorvastatin "
            "以及一种待确认的草本补充剂），可安全体验全部功能。您可随时切换回个人模式。"
        ),
        "medical_disclaimer": (
            "教育原型声明：MedSafe 是 Congressional App Challenge 的学生参赛项目，未经临床验证，"
            "不能替代医生或药剂师的专业建议。未经医生或药剂师指导，请勿擅自停药、换药或更改剂量。"
        ),
        "nav_title": "导航菜单",
        "nav_overview": "总览 (Overview)",
        "nav_medicines": "我的药物",
        "nav_scan": "扫描药瓶",
        "nav_checker": "相互作用检查",
        "nav_schedule": "每日服药计划",
        "nav_reports": "家属与药师报告",
        "nav_settings": "设置与隐私",
        "onboarding_title": "MedSafe 使用指南（5 个简单步骤）",
        "onboarding_step_1": "1. 输入药名或扫描药瓶标签来添加药物。",
        "onboarding_step_2": "2. 保存前核对并确认每种药物的有效成分、剂量和剂型。",
        "onboarding_step_3": "3. 在已加载的相互作用数据库中比对您的药物清单。",
        "onboarding_step_4": "4. 用通俗语言了解结果含义以及数据库的覆盖局限。",
        "onboarding_step_5": "5. 安排每日服药时间，并为药剂师或医生打印清晰的汇总表。",
        "overview_heading": "您的用药总览",
        "overview_subtitle": "查看当前在用药物、检查数据库中的相互作用记录，并管理您的每日服药日常。",
        "stat_active_meds": "当前在用药物",
        "stat_needs_confirmation": "待确认药物身份",
        "stat_unresolved_checks": "待核实 / 数据库局限",
        "stat_today_schedule": "今日计划服药次数",
        "stat_dataset_records": "已加载数据库记录",
        "quick_actions_title": "常用操作",
        "btn_add_medicine": "添加药物",
        "btn_scan_bottle": "扫描药瓶",
        "btn_check_interaction": "检查相互作用",
        "btn_review_schedule": "查看今日服药表",
        "btn_prepare_summary": "生成用药汇总报告",
        "empty_meds_title": "您的清单中还没有药物",
        "empty_meds_body": "请先添加您的第一种处方药、非处方药或保健补充剂。您可以手动输入或扫描药瓶标签。",
        "btn_add_first_med": "添加第一种药物",
        "recent_activity_title": "近期记录与需要关注的事项",
        "meds_heading": "我的药物清单",
        "meds_subtitle": "管理在用与停用药物，确认标准化有效成分，并整理医嘱用法说明。",
        "cat_prescription": "处方药 (Prescription)",
        "cat_otc": "非处方药 (OTC)",
        "cat_supplement": "维生素 / 补充剂",
        "cat_herbal": "草本制品",
        "cat_other": "其他",
        "id_confirmed": "药物身份已确认",
        "id_needs_review": "需要人工确认成分",
        "id_unidentified": "未能识别 — 无法检查相互作用",
        "coverage_note_categories": (
            "覆盖范围说明：当前基础数据库主要涵盖常见处方药和非处方药配对，许多保健品与草本制品未包含在内。"
        ),
        "duplicate_warning_title": "可能存在重复药物或相同有效成分",
        "duplicate_warning_body": "以下药物可能含有相同成分或名称相近，请向药剂师确认是否应同时服用：",
        "scan_heading": "扫描药瓶标签",
        "scan_subtitle": "上传清晰的药瓶照片或体验内置示例标签。所有扫描结果在保存前均需人工核对。",
        "ocr_review_heading": "保存前请核对扫描信息",
        "ocr_uncertainty_banner": (
            "必须人工确认：药瓶照片本身不能保证识别完全准确，请对照实物药瓶核对药名、有效成分、剂量及用法。"
        ),
        "checker_heading": "用药安全检查器",
        "checker_subtitle": "将新药或现有药物与您的在用药物清单进行比对。",
        "checker_mode_proposed": "A. 检查我正考虑添加的新药物",
        "checker_mode_full": "B. 检查我当前所有在用药物的配对",
        "checker_run_btn": "运行相互作用查询",
        "incomplete_check_banner": (
            "检查未完全完成：一种或多种药物尚未确认有效成分（或数据库不可用），涉及这些药物的配对无法完成核查。"
        ),
        "status_MATCH_FOUND": "在已加载数据库中发现相互作用记录",
        "status_NO_MATCHING_RECORD": "已加载数据库中未见匹配记录（不代表绝对安全）",
        "status_IDENTITY_REQUIRES_CONFIRMATION": "暂无法检查 — 需先确认药物有效成分",
        "status_UNABLE_TO_CHECK": "无法检查 — 药物未识别或查询失败",
        "status_DATASET_UNAVAILABLE": "无法检查 — 相互作用数据库不可用",
        "severity_major": "严重 / Major（来源分级）",
        "severity_moderate": "中度 / Moderate（来源分级）",
        "severity_minor": "轻度 / Minor（来源分级）",
        "severity_unspecified": "来源数据库未指定级别",
        "no_record_explanation": (
            "在已加载的数据库中未找到这对药物的相互作用记录。由于数据库并不完整，该结果并不代表这两种药"
            "一起服用绝对安全。如有疑问，请咨询药剂师或医生。"
        ),
        "action_caution_match": (
            "数据库中有这两种药物的相互作用记录。请咨询药剂师或医生了解这对您的具体情况意味着什么。"
            "未经医嘱请勿擅自停用处方药或更改剂量。"
        ),
        "action_caution_major": (
            "建议尽快咨询专业人员：数据库将该配对归类为严重相互作用。请在同服前咨询您的药剂师或医生，"
            "切勿自行停用处方药。"
        ),
        "badge_source_template": "内置验证模板（确定性输出）",
        "badge_source_ai": "Gemini AI 通俗解读（基于已确认数据库记录）",
        "show_original_english": "查看英文原始数据库记录",
        "schedule_heading": "每日服药时间表",
        "schedule_subtitle": "安排每日服药时间，并记录今天已服或跳过的剂量。",
        "schedule_honest_notice": (
            "提醒说明：本清单在 MedSafe 打开时显示状态，关闭浏览器后不会发送后台推送或短信提醒。"
            "您可以在下方下载日历文件 (.ics) 导入手机或电脑日历。"
        ),
        "missed_dose_warning": (
            "漏服提示：切勿为了补服而将下一次剂量加倍。请查看药瓶说明或咨询药剂师。"
        ),
        "dose_taken": "已服用",
        "dose_skipped": "已跳过",
        "dose_pending": "尚未记录",
        "reports_heading": "家属与药剂师汇总报告",
        "reports_subtitle": "生成清晰的药物清单、相互作用核查结果及药师提问清单，方便就诊时携带打印。",
        "caregiver_privacy_note": (
            "隐私保障：MedSafe 绝不会自动向任何人发送邮件或上传您的药物清单。所有报告均在本地生成供您审阅下载。"
        ),
        "settings_heading": "设置、无障碍与隐私",
        "settings_subtitle": "调整外观模式（浅色、深色、高对比度）、字体大小、界面语言及本地数据控制。",
    },

    "Tagalog": {
        "app_tagline": "Kasama sa kaligtasan ng gamot at pang-araw-araw na iskedyul",
        "privacy_badge_local": "Local-first prototype: nakaimbak ang listahan ng iyong gamot sa SQLite sa device na ito.",
        "demo_badge": "DEMO MODE — HALIMBAWANG DATOS LAMANG",
        "demo_banner_text": (
            "Aktibo ang Demonstration Mode. Tinitingnan mo ang mga halimbawang gamot "
            "(Lisinopril, Metformin, Atorvastatin, at isang herbal supplement) upang ligtas na "
            "masubukan ang MedSafe. Maaaring lumipat sa Personal Mode anumang oras."
        ),
        "medical_disclaimer": (
            "Paunawa: Ang MedSafe ay isang proyekto para sa Congressional App Challenge at hindi "
            "pamalit sa payo ng doktor o parmasyutiko. Huwag ihinto o baguhin ang dosis ng "
            "iniresetang gamot nang hindi kumukunsulta sa iyong doktor o parmasyutiko."
        ),
        "nav_title": "Menu",
        "nav_overview": "Pangkalahatang-ideya",
        "nav_medicines": "Aking mga Gamot",
        "nav_scan": "I-scan ang Bote",
        "nav_checker": "Safety Checker",
        "nav_schedule": "Pang-araw-araw na Iskedyul",
        "nav_reports": "Ulat para sa Doktor / Pamilya",
        "nav_settings": "Settings at Privacy",
        "onboarding_title": "Paano gumagana ang MedSafe (5 hakbang)",
        "onboarding_step_1": "1. Magdagdag ng gamot sa pamamagitan ng pag-type o pag-scan ng bote.",
        "onboarding_step_2": "2. Suriin at kumpirmahin ang active ingredient, lakas (mg), at anyo ng gamot.",
        "onboarding_step_3": "3. Suriin ang iyong listahan laban sa naka-load na interaction database.",
        "onboarding_step_4": "4. Unawain ang ibig sabihin ng resulta at ang limitasyon ng dataset.",
        "onboarding_step_5": "5. Ayusin ang iyong iskedyul at mag-print ng malinaw na buod para sa parmasyutiko.",
        "overview_heading": "Pangkalahatang-ideya ng iyong mga gamot",
        "overview_subtitle": "Suriin ang iyong mga aktibong gamot, tingnan ang mga tala ng interaksyon, at ayusin ang iyong iskedyul.",
        "stat_active_meds": "Aktibong gamot",
        "stat_needs_confirmation": "Kailangang kumpirmahin",
        "stat_unresolved_checks": "Hindi pa tapos na pagsusuri",
        "stat_today_schedule": "Naka-iskedyul ngayong araw",
        "stat_dataset_records": "Naka-load na tala sa database",
        "quick_actions_title": "Mga pangunahing aksyon",
        "btn_add_medicine": "Magdagdag ng gamot",
        "btn_scan_bottle": "Mag-scan ng bote",
        "btn_check_interaction": "Suriin ang interaksyon",
        "btn_review_schedule": "Tingnan ang iskedyul ngayon",
        "btn_prepare_summary": "Maghanda ng ulat",
        "empty_meds_title": "Wala pang gamot sa iyong listahan",
        "empty_meds_body": "Magsimula sa pagdaragdag ng iyong unang gamot o supplement sa pamamagitan ng pag-type o pag-scan.",
        "btn_add_first_med": "Idagdag ang unang gamot",
        "recent_activity_title": "Kamakailang aktibidad at mga dapat pansinin",
        "meds_heading": "Aking mga Gamot",
        "meds_subtitle": "Pamahalaan ang iyong mga aktibo at dating gamot at kumpirmahin ang mga sangkap nito.",
        "cat_prescription": "Gamot na may reseta",
        "cat_otc": "Over-the-counter (OTC)",
        "cat_supplement": "Bitamina / supplement",
        "cat_herbal": "Herbal na produkto",
        "cat_other": "Iba pa",
        "id_confirmed": "Kumpirmado ang pagkakakilanlan",
        "id_needs_review": "Kailangang kumpirmahin",
        "id_unidentified": "Hindi pa tukoy — hindi masuri ang interaksyon",
        "coverage_note_categories": (
            "Paalala sa saklaw: Ang starter dataset ay sumasaklaw lamang sa mga karaniwang gamot. "
            "Maraming supplement at herbal na produkto ang wala sa dataset na ito."
        ),
        "duplicate_warning_title": "Posibleng dobleng gamot o magkaparehong sangkap",
        "duplicate_warning_body": "Pakitanong sa iyong parmasyutiko kung dapat inumin nang sabay ang mga ito:",
        "scan_heading": "Mag-scan ng Bote ng Gamot",
        "scan_subtitle": "Mag-upload ng malinaw na larawan ng etiketa o subukan ang built-in na demo label.",
        "ocr_review_heading": "Suriin ang na-scan na etiketa bago i-save",
        "ocr_uncertainty_banner": (
            "Kailangan ng kumpirmasyon: Pakisuri ang pangalan, active ingredient, lakas, at direksyon "
            "laban sa iyong aktwal na bote ng gamot."
        ),
        "checker_heading": "Safety Checker",
        "checker_subtitle": "Ikumpara ang isang gamot sa iyong kasalukuyang listahan ng mga gamot.",
        "checker_mode_proposed": "A. Suriin ang isang gamot na balak kong idagdag",
        "checker_mode_full": "B. Suriin ang lahat ng aking kasalukuyang aktibong gamot",
        "checker_run_btn": "Patakbuhin ang pagsusuri",
        "incomplete_check_banner": (
            "Hindi kumpletong pagsusuri: May isa o higit pang gamot na hindi pa kumpirmado ang sangkap."
        ),
        "status_MATCH_FOUND": "May nahanap na tala ng interaksyon sa database",
        "status_NO_MATCHING_RECORD": "Walang nahanap na tala sa database (hindi patunay na ligtas)",
        "status_IDENTITY_REQUIRES_CONFIRMATION": "Hindi pa masuri — kailangang kumpirmahin ang gamot",
        "status_UNABLE_TO_CHECK": "Hindi masuri — hindi natukoy ang gamot",
        "status_DATASET_UNAVAILABLE": "Hindi masuri — hindi magamit ang database",
        "severity_major": "Malubha / Major (klasipikasyon ng pinagmulan)",
        "severity_moderate": "Katamtaman / Moderate (klasipikasyon ng pinagmulan)",
        "severity_minor": "Bahagya / Minor (klasipikasyon ng pinagmulan)",
        "severity_unspecified": "Hindi tinukoy sa database",
        "no_record_explanation": (
            "Walang nahanap na tala ng interaksyon sa naka-load na dataset para sa pares na ito. "
            "Dahil hindi kumpleto ang dataset, HINDI nito pinatutunayan na ligtas silang pagsabayin. "
            "Magtanong sa iyong parmasyutiko o doktor."
        ),
        "action_caution_match": (
            "May nahanap na tala ng interaksyon para sa mga gamot na ito. Makipag-ugnayan sa iyong "
            "parmasyutiko o doktor. Huwag basta ihinto ang iniresetang gamot."
        ),
        "action_caution_major": (
            "Inirerekomenda ang agarang pagkonsulta sa doktor o parmasyutiko: Itinuturing itong "
            "Major interaction sa dataset. Huwag ihinto ang iniresetang gamot nang mag-isa."
        ),
        "badge_source_template": "Built-in na beripikadong template (deterministic)",
        "badge_source_ai": "Paliwanag sa simpleng wika mula sa Gemini AI (batay sa database)",
        "show_original_english": "Ipakita ang orihinal na tala sa Ingles",
        "schedule_heading": "Pang-araw-araw na Iskedyul ng Gamot",
        "schedule_subtitle": "Ayusin ang iyong pang-araw-araw na iskedyul at itala ang nainom na gamot ngayong araw.",
        "schedule_honest_notice": (
            "Paalala: Gumagana ang listahang ito habang nakabukas ang MedSafe. Maaari kang "
            "mag-download ng calendar (.ics) file sa ibaba para sa paalala sa iyong telepono."
        ),
        "missed_dose_warning": (
            "Paalala sa nalaktawang dosis: Huwag doblehin ang susunod na dosis. Magtanong sa iyong parmasyutiko."
        ),
        "dose_taken": "Nainom na",
        "dose_skipped": "Nalaktawan",
        "dose_pending": "Hindi pa naitala",
        "reports_heading": "Ulat para sa Tagapag-alaga at Parmasyutiko",
        "reports_subtitle": "Maghanda ng malinaw na buod ng iyong mga gamot at mga tanong para sa iyong doktor o parmasyutiko.",
        "caregiver_privacy_note": (
            "Garantiya sa privacy: Hindi kailanman awtomatikong ipinapadala ng MedSafe ang iyong datos."
        ),
        "settings_heading": "Settings, Accessibility at Privacy",
        "settings_subtitle": "Baguhin ang tema (Light, Dark, High-Contrast), laki ng titik, wika, at lokal na datos.",
    },

    "Vietnamese": {
        "app_tagline": "Trợ lý an toàn thuốc và lịch uống thuốc hàng ngày",
        "privacy_badge_local": "Nguyên mẫu lưu trữ cục bộ: danh sách thuốc của quý vị được lưu trong SQLite trên thiết bị này.",
        "demo_badge": "CHẾ ĐỘ MINH HỌA — DỮ LIỆU MẪU GIẢ ĐỊNH",
        "demo_banner_text": (
            "Chế độ Minh họa đang bật. Quý vị đang xem các thuốc mẫu giả định (Lisinopril, "
            "Metformin, Atorvastatin và một thực phẩm thảo dược) để dùng thử MedSafe an toàn. "
            "Có thể chuyển sang Chế độ Cá nhân bất cứ lúc nào."
        ),
        "medical_disclaimer": (
            "Tuyên bố miễn trừ y tế: MedSafe là dự án học sinh cho Congressional App Challenge, "
            "không thay thế lời khuyên của bác sĩ hoặc dược sĩ. Tuyệt đối không tự ý ngưng thuốc "
            "hoặc đổi liều khi chưa hỏi ý kiến bác sĩ hoặc dược sĩ."
        ),
        "nav_title": "Điều hướng",
        "nav_overview": "Tổng quan",
        "nav_medicines": "Thuốc của tôi",
        "nav_scan": "Quét nhãn lọ thuốc",
        "nav_checker": "Kiểm tra tương tác",
        "nav_schedule": "Lịch uống hàng ngày",
        "nav_reports": "Báo cáo cho Dược sĩ / Người nhà",
        "nav_settings": "Cài đặt & Quyền riêng tư",
        "onboarding_title": "Cách MedSafe hoạt động (5 bước đơn giản)",
        "onboarding_step_1": "1. Thêm thuốc bằng cách nhập tên hoặc chụp/quét nhãn lọ thuốc.",
        "onboarding_step_2": "2. Kiểm tra và xác nhận hoạt chất, hàm lượng và dạng bào chế của từng thuốc.",
        "onboarding_step_3": "3. Đối chiếu danh sách thuốc với cơ sở dữ liệu tương tác đã nạp.",
        "onboarding_step_4": "4. Hiểu rõ ý nghĩa kết quả và những giới hạn của cơ sở dữ liệu.",
        "onboarding_step_5": "5. Sắp xếp lịch uống thuốc hàng ngày và in bản tóm tắt cho dược sĩ hoặc bác sĩ.",
        "overview_heading": "Tổng quan thuốc của quý vị",
        "overview_subtitle": "Xem lại các thuốc đang dùng, kiểm tra dữ liệu tương tác và quản lý lịch uống thuốc.",
        "stat_active_meds": "Thuốc đang dùng",
        "stat_needs_confirmation": "Cần xác nhận hoạt chất",
        "stat_unresolved_checks": "Kiểm tra chưa hoàn tất",
        "stat_today_schedule": "Liều uống hôm nay",
        "stat_dataset_records": "Bản ghi trong cơ sở dữ liệu",
        "quick_actions_title": "Thao tác chính",
        "btn_add_medicine": "Thêm thuốc mới",
        "btn_scan_bottle": "Quét lọ thuốc",
        "btn_check_interaction": "Kiểm tra tương tác",
        "btn_review_schedule": "Xem lịch hôm nay",
        "btn_prepare_summary": "Tạo bản tóm tắt",
        "empty_meds_title": "Chưa có thuốc nào trong danh sách",
        "empty_meds_body": "Hãy bắt đầu bằng cách thêm thuốc kê đơn, thuốc không kê đơn hoặc thực phẩm bổ sung đầu tiên.",
        "btn_add_first_med": "Thêm thuốc đầu tiên",
        "recent_activity_title": "Hoạt động gần đây & mục cần lưu ý",
        "meds_heading": "Thuốc của tôi",
        "meds_subtitle": "Quản lý thuốc đang dùng và đã ngưng, xác nhận hoạt chất chuẩn hóa và hướng dẫn sử dụng.",
        "cat_prescription": "Thuốc kê đơn",
        "cat_otc": "Thuốc không kê đơn (OTC)",
        "cat_supplement": "Vitamin / Thực phẩm bổ sung",
        "cat_herbal": "Thảo dược",
        "cat_other": "Khác",
        "id_confirmed": "Đã xác nhận hoạt chất",
        "id_needs_review": "Cần xác nhận lại",
        "id_unidentified": "Chưa nhận diện — không thể kiểm tra",
        "coverage_note_categories": (
            "Lưu ý phạm vi dữ liệu: Bộ dữ liệu mẫu chủ yếu bao gồm các thuốc phổ biến. Nhiều "
            "thực phẩm chức năng và thảo dược chưa có trong cơ sở dữ liệu này."
        ),
        "duplicate_warning_title": "Có thể trùng lặp thuốc hoặc trùng hoạt chất",
        "duplicate_warning_body": "Vui lòng hỏi dược sĩ xem các thuốc này có được dùng cùng nhau hay không:",
        "scan_heading": "Quét Nhãn Lọ Thuốc",
        "scan_subtitle": "Tải ảnh chụp rõ nét của nhãn lọ thuốc hoặc dùng thử nhãn mẫu tích hợp sẵn.",
        "ocr_review_heading": "Kiểm tra thông tin quét trước khi lưu",
        "ocr_uncertainty_banner": (
            "Bắt buộc xác nhận thủ công: Hãy đối chiếu tên thuốc, hoạt chất, hàm lượng và cách dùng "
            "với lọ thuốc thực tế của quý vị."
        ),
        "checker_heading": "Kiểm Tra An Toàn Thuốc",
        "checker_subtitle": "Đối chiếu một loại thuốc với danh sách thuốc hiện tại của quý vị.",
        "checker_mode_proposed": "A. Kiểm tra một loại thuốc tôi đang định dùng thêm",
        "checker_mode_full": "B. Kiểm tra toàn bộ danh sách thuốc đang dùng",
        "checker_run_btn": "Chạy tra cứu tương tác",
        "incomplete_check_banner": (
            "Kiểm tra chưa đầy đủ: Một hoặc nhiều thuốc chưa được xác nhận hoạt chất."
        ),
        "status_MATCH_FOUND": "Tìm thấy bản ghi tương tác trong cơ sở dữ liệu",
        "status_NO_MATCHING_RECORD": "Không có bản ghi trùng khớp trong dữ liệu (không chứng minh là an toàn)",
        "status_IDENTITY_REQUIRES_CONFIRMATION": "Chưa thể kiểm tra — cần xác nhận hoạt chất thuốc",
        "status_UNABLE_TO_CHECK": "Không thể kiểm tra — chưa nhận diện được thuốc",
        "status_DATASET_UNAVAILABLE": "Không thể kiểm tra — cơ sở dữ liệu không khả dụng",
        "severity_major": "Nghiêm trọng / Major (theo nguồn dữ liệu)",
        "severity_moderate": "Trung bình / Moderate (theo nguồn dữ liệu)",
        "severity_minor": "Nhẹ / Minor (theo nguồn dữ liệu)",
        "severity_unspecified": "Chưa phân loại mức độ trong dữ liệu nguồn",
        "no_record_explanation": (
            "Không tìm thấy bản ghi tương tác nào cho cặp thuốc này trong bộ dữ liệu hiện tại. "
            "Vì bộ dữ liệu chưa đầy đủ, kết quả này KHÔNG khẳng định hai thuốc dùng chung là an toàn. "
            "Hãy hỏi dược sĩ hoặc bác sĩ nếu quý vị chưa chắc chắn."
        ),
        "action_caution_match": (
            "Đã tìm thấy bản ghi tương tác cho các thuốc này. Hãy liên hệ dược sĩ hoặc bác sĩ để "
            "được tư vấn. Đừng tự ý ngưng thuốc kê đơn hoặc thay đổi liều lượng."
        ),
        "action_caution_major": (
            "Khuyến nghị hỏi ý kiến bác sĩ/dược sĩ sớm: Bộ dữ liệu phân loại đây là tương tác "
            "nghiêm trọng (Major). Không tự ý bỏ thuốc kê đơn."
        ),
        "badge_source_template": "Mẫu chuẩn tích hợp sẵn (Xác định)",
        "badge_source_ai": "Giải thích dễ hiểu bởi Gemini AI (dựa trên bản ghi cơ sở dữ liệu)",
        "show_original_english": "Xem bản ghi gốc bằng tiếng Anh",
        "schedule_heading": "Lịch Uống Thuốc Hàng Ngày",
        "schedule_subtitle": "Sắp xếp lịch uống thuốc trong ngày và đánh dấu các liều đã uống hoặc bỏ qua.",
        "schedule_honest_notice": (
            "Lưu ý: Bảng đánh dấu này hoạt động khi MedSafe đang mở. Quý vị có thể tải tệp lịch (.ics) "
            "bên dưới để thêm lời nhắc vào điện thoại."
        ),
        "missed_dose_warning": (
            "Lưu ý khi quên liều: Không tự ý uống gấp đôi liều tiếp theo để bù cho liều đã quên."
        ),
        "dose_taken": "Đã uống",
        "dose_skipped": "Đã bỏ qua",
        "dose_pending": "Chưa ghi nhận",
        "reports_heading": "Báo Cáo cho Người Chăm Sóc & Dược Sĩ",
        "reports_subtitle": "Tạo bản tóm tắt rõ ràng về danh sách thuốc và câu hỏi để mang đến gặp bác sĩ hoặc dược sĩ.",
        "caregiver_privacy_note": (
            "Cam kết quyền riêng tư: MedSafe không bao giờ tự động gửi email hay chia sẻ dữ liệu của quý vị."
        ),
        "settings_heading": "Cài Đặt, Trợ Năng & Quyền Riêng Tư",
        "settings_subtitle": "Điều chỉnh giao diện (Sáng, Tối, Tương phản cao), cỡ chữ, ngôn ngữ và dữ liệu cục bộ.",
    },

    "French": {
        "app_tagline": "Compagnon de sécurité des médicaments et de routine quotidienne",
        "privacy_badge_local": "Prototype local : votre liste de médicaments est stockée dans SQLite sur cet appareil.",
        "demo_badge": "MODE DÉMO — DONNÉES D'EXEMPLE FICTIVES",
        "demo_banner_text": (
            "Le mode démonstration est actif. Vous consultez des médicaments fictifs "
            "(Lisinopril, Metformin, Atorvastatin et un supplément à base de plantes) "
            "pour explorer MedSafe en toute sécurité. Passez au mode personnel à tout moment."
        ),
        "medical_disclaimer": (
            "Avis médical : MedSafe est un prototype éducatif créé pour le Congressional App Challenge. "
            "Il ne remplace pas l'avis d'un médecin ou d'un pharmacien. N'arrêtez et ne modifiez "
            "jamais un traitement prescrit sans consulter votre professionnel de santé."
        ),
        "nav_title": "Navigation",
        "nav_overview": "Aperçu",
        "nav_medicines": "Mes Médicaments",
        "nav_scan": "Scanner un Flacon",
        "nav_checker": "Vérificateur d'Interactions",
        "nav_schedule": "Horaire Quotidien",
        "nav_reports": "Aidants et Rapports",
        "nav_settings": "Paramètres et Confidentialité",
        "onboarding_title": "Comment fonctionne MedSafe (5 étapes simples)",
        "onboarding_step_1": "1. Ajoutez des médicaments en tapant leur nom ou en scannant l'étiquette du flacon.",
        "onboarding_step_2": "2. Vérifiez et confirmez le principe actif, le dosage et la forme de chaque médicament.",
        "onboarding_step_3": "3. Comparez votre liste avec la base de données d'interactions chargée.",
        "onboarding_step_4": "4. Comprenez la signification du résultat et les limites de la base de données.",
        "onboarding_step_5": "5. Organisez votre horaire quotidien et imprimez un résumé clair pour votre pharmacien.",
        "overview_heading": "Aperçu de vos médicaments",
        "overview_subtitle": "Consultez vos médicaments actifs, vérifiez les interactions enregistrées et gérez votre routine.",
        "stat_active_meds": "Médicaments actifs",
        "stat_needs_confirmation": "Identité à confirmer",
        "stat_unresolved_checks": "Vérifications incomplètes",
        "stat_today_schedule": "Doses prévues aujourd'hui",
        "stat_dataset_records": "Enregistrements chargés",
        "quick_actions_title": "Actions principales",
        "btn_add_medicine": "Ajouter un médicament",
        "btn_scan_bottle": "Scanner un flacon",
        "btn_check_interaction": "Vérifier une interaction",
        "btn_review_schedule": "Voir l'horaire du jour",
        "btn_prepare_summary": "Préparer un résumé",
        "empty_meds_title": "Aucun médicament dans votre liste",
        "empty_meds_body": "Commencez par ajouter votre premier médicament sur ordonnance, en vente libre ou supplément.",
        "btn_add_first_med": "Ajouter mon premier médicament",
        "recent_activity_title": "Activité récente et éléments à vérifier",
        "meds_heading": "Mes Médicaments",
        "meds_subtitle": "Gérez vos médicaments actifs et passés, et confirmez leurs principes actifs standardisés.",
        "cat_prescription": "Médicament sur ordonnance",
        "cat_otc": "Sans ordonnance (OTC)",
        "cat_supplement": "Vitamine / supplément",
        "cat_herbal": "Produit à base de plantes",
        "cat_other": "Autre",
        "id_confirmed": "Identité confirmée",
        "id_needs_review": "Confirmation requise",
        "id_unidentified": "Non identifié — vérification impossible",
        "coverage_note_categories": (
            "Note sur la couverture : Le jeu de données initial couvre principalement les médicaments "
            "courants. De nombreux suppléments et plantes n'y figurent pas."
        ),
        "duplicate_warning_title": "Médicaments en double ou principes actifs partagés possibles",
        "duplicate_warning_body": "Veuillez demander à votre pharmacien si ces médicaments doivent être pris ensemble :",
        "scan_heading": "Scanner un Flacon de Médicament",
        "scan_subtitle": "Importez une photo nette de l'étiquette ou testez une étiquette de démonstration intégrée.",
        "ocr_review_heading": "Vérifiez l'étiquette scannée avant d'enregistrer",
        "ocr_uncertainty_banner": (
            "Confirmation humaine requise : Vérifiez le nom, le principe actif, le dosage et les "
            "instructions avec votre flacon physique."
        ),
        "checker_heading": "Vérificateur de Sécurité",
        "checker_subtitle": "Comparez un médicament avec votre liste actuelle de médicaments.",
        "checker_mode_proposed": "A. Vérifier un médicament que j'envisage d'ajouter",
        "checker_mode_full": "B. Examiner ma liste actuelle de médicaments actifs",
        "checker_run_btn": "Lancer la recherche d'interactions",
        "incomplete_check_banner": (
            "Vérification incomplète : Un ou plusieurs médicaments n'ont pas d'identité confirmée."
        ),
        "status_MATCH_FOUND": "Interaction enregistrée trouvée dans la base de données",
        "status_NO_MATCHING_RECORD": "Aucun enregistrement trouvé dans la base (ne prouve pas la sécurité)",
        "status_IDENTITY_REQUIRES_CONFIRMATION": "Vérification en attente — identité du médicament à confirmer",
        "status_UNABLE_TO_CHECK": "Impossible de vérifier — médicament non identifié",
        "status_DATASET_UNAVAILABLE": "Impossible de vérifier — base de données indisponible",
        "severity_major": "Majeure / Grave (classification source)",
        "severity_moderate": "Modérée (classification source)",
        "severity_minor": "Mineure / Légère (classification source)",
        "severity_unspecified": "Non spécifiée par la source",
        "no_record_explanation": (
            "Aucune interaction correspondante n'a été trouvée dans le jeu de données chargé. "
            "Comme la base est incomplète, ce résultat NE confirme PAS que ces médicaments sont "
            "sans danger ensemble. Consultez votre pharmacien ou médecin."
        ),
        "action_caution_match": (
            "Une interaction a été trouvée pour ces médicaments. Contactez votre pharmacien ou "
            "médecin. N'arrêtez jamais un médicament prescrit sans avis médical."
        ),
        "action_caution_major": (
            "Avis professionnel rapide recommandé : La base de données classe cette paire comme "
            "une interaction majeure. Parlez-en à votre pharmacien ou médecin."
        ),
        "badge_source_template": "Modèle vérifié intégré (déterministe)",
        "badge_source_ai": "Explication simplifiée par Gemini AI (issue de l'enregistrement confirmé)",
        "show_original_english": "Afficher l'enregistrement original en anglais",
        "schedule_heading": "Horaire Quotidien des Médicaments",
        "schedule_subtitle": "Organisez votre routine quotidienne et notez les doses prises ou sautées aujourd'hui.",
        "schedule_honest_notice": (
            "Note : Cette liste fonctionne lorsque MedSafe est ouvert. Vous pouvez télécharger un "
            "fichier calendrier (.ics) ci-dessous pour ajouter des rappels sur votre téléphone."
        ),
        "missed_dose_warning": (
            "Note sur les doses oubliées : Ne doublez jamais la dose suivante pour compenser un oubli."
        ),
        "dose_taken": "Prise enregistrée",
        "dose_skipped": "Dose sautée",
        "dose_pending": "Non enregistrée",
        "reports_heading": "Rapports pour Aidants et Pharmaciens",
        "reports_subtitle": "Préparez un résumé clair de vos médicaments et des questions pour votre pharmacien ou médecin.",
        "caregiver_privacy_note": (
            "Garantie de confidentialité : MedSafe n'envoie jamais automatiquement votre liste à qui que ce soit."
        ),
        "settings_heading": "Paramètres, Accessibilité et Confidentialité",
        "settings_subtitle": "Ajustez le thème (Clair, Sombre, Contraste élevé), la taille du texte, la langue et vos données.",
    },
}


def normalize_language(language: str | None) -> str:
    if not language:
        return "English"
    clean = language.strip().lower()
    if clean in ("hindi", "hi", "हिन्दी", "हिन्दी (hindi)"):
        return "Hindi"
    if clean in ("spanish", "es", "español", "espanol", "español (spanish)"):
        return "Spanish"
    if clean in ("chinese", "zh", "zh-cn", "中文", "中文 (chinese)", "mandarin"):
        return "Chinese"
    if clean in ("tagalog", "tl", "filipino", "tagalog (filipino)"):
        return "Tagalog"
    if clean in ("vietnamese", "vi", "tiếng việt", "tiếng việt (vietnamese)"):
        return "Vietnamese"
    if clean in ("french", "fr", "français", "francais", "français (french)"):
        return "French"
    return "English"


def t(key: str, language: str = "English", **kwargs: object) -> str:
    """Look up a translated string by stable key, falling back to English."""
    lang = normalize_language(language)
    table = TRANSLATIONS.get(lang, TRANSLATIONS["English"])
    template = table.get(key) or TRANSLATIONS["English"].get(key) or key
    if kwargs:
        try:
            return template.format(**kwargs)
        except (KeyError, ValueError):
            return template
    return template


def category_label(category: str, language: str = "English") -> str:
    key = f"cat_{(category or 'other').strip().lower()}"
    return t(key, language)


def identity_status_label(status: str, language: str = "English") -> str:
    key = f"id_{(status or 'unidentified').strip().lower()}"
    return t(key, language)


def check_status_label(status: str, language: str = "English") -> str:
    return t(f"status_{status}", language)


def severity_label(severity_level: str, language: str = "English") -> str:
    return t(f"severity_{(severity_level or 'unspecified').strip().lower()}", language)
