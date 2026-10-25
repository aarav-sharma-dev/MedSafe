"""Algorithmic FDA & ISMP Tall Man Lettering engine for Look-Alike, Sound-Alike (LASA) drugs.

Clinical rationale:
* Look-Alike, Sound-Alike (LASA) medication names are a leading cause of
  prescribing, dispensing, and self-administration errors in older adults.
* Endorsed by the U.S. Food and Drug Administration (FDA Name Differentiation
  Project), the Institute for Safe Medication Practices (ISMP), The Joint
  Commission, and the World Health Organization, Tall Man Lettering uses mixed
  case and bold uppercase segments (e.g., ``hydrALAZINE`` vs. ``hydrOXYzine``)
  to disrupt word-shape familiarity and draw the eye to the distinguishing
  syllables.
* Standard software pipelines often destroy Tall Man safety markers via
  ``.lower()``, ``.title()``, or CSS ``text-transform: capitalize``. This module
  provides:
  1. A curated registry of FDA Table 1 and ISMP Table 2 LASA drug groups.
  2. The deterministic Mid-Tall Man & CD3 comparator algorithm for dynamically
     deriving mixed-case strings across any confusable drug pair while keeping
     mid-word ``'i'`` lowercase so it cannot be mistaken for ``'l'``.
  3. An HTML formatter (:func:`render_tall_man_html`) that renders uppercase
     distinguishing segments in ``font-weight: 700`` with ``text-transform: none``.
"""

from __future__ import annotations

import html
import re


# Curated dictionary of FDA Table 1 and ISMP Table 2 Look-Alike, Sound-Alike
# (LASA) confusable drug pairs and trios.
LASA_CONFUSION_PAIRS: dict[str, dict[str, str]] = {
    # --- Antibiotics vs. Antidepressants ---
    "amoxicillin": {
        "drug": "amoxicillin",
        "tall_man": "amoxiCILLIN",
        "purpose": "Antibiotic used to treat bacterial infections",
        "confused_with": "amoxapine",
        "confused_tall_man": "amoxAPINE",
        "confused_purpose": "Antidepressant medication",
        "group": "amoxiCILLIN vs. amoxAPINE",
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
        "group": "amoxiCILLIN vs. amoxAPINE",
        "warning": (
            "Look-Alike Name Check: Verify whether your bottle says **amoxAPINE** "
            "(an antidepressant) or **amoxiCILLIN** (an antibiotic for infections)."
        ),
    },
    # --- Hydralazine vs. Hydrochlorothiazide vs. Hydroxyzine (FDA Table 1 Trio) ---
    "hydralazine": {
        "drug": "hydralazine",
        "tall_man": "hydrALAZINE",
        "purpose": "Blood pressure medication (vasodilator)",
        "confused_with": "hydroxyzine",
        "confused_tall_man": "hydrOXYzine",
        "confused_purpose": "Allergy, itching, or anxiety medication (antihistamine)",
        "group": "hydrALAZINE vs. hydroCHLOROthiazide vs. hydrOXYzine",
        "warning": (
            "Look-Alike Name Check: **hydrALAZINE** (for blood pressure), "
            "**hydroCHLOROthiazide** (water pill), and **hydrOXYzine** (for allergies/anxiety) "
            "look very similar on labels. Please check the middle letters on your bottle."
        ),
    },
    "hydroxyzine": {
        "drug": "hydroxyzine",
        "tall_man": "hydrOXYzine",
        "purpose": "Allergy, itching, or anxiety medication (antihistamine)",
        "confused_with": "hydralazine",
        "confused_tall_man": "hydrALAZINE",
        "confused_purpose": "Blood pressure medication (vasodilator)",
        "group": "hydrALAZINE vs. hydroCHLOROthiazide vs. hydrOXYzine",
        "warning": (
            "Look-Alike Name Check: **hydrOXYzine** (for allergies/itching/anxiety) and "
            "**hydrALAZINE** (for blood pressure) look very similar on labels. "
            "Please double-check the middle letters (`-OXYzine` vs `-ALAZINE`) on your bottle."
        ),
    },
    "hydrochlorothiazide": {
        "drug": "hydrochlorothiazide",
        "tall_man": "hydroCHLOROthiazide",
        "purpose": "Blood pressure & fluid retention water pill (thiazide diuretic)",
        "confused_with": "hydralazine",
        "confused_tall_man": "hydrALAZINE",
        "confused_purpose": "Blood pressure vasodilator (different dosing & mechanism)",
        "group": "hydrALAZINE vs. hydroCHLOROthiazide vs. hydrOXYzine",
        "warning": (
            "Look-Alike Name Check: Verify whether your bottle says **hydroCHLOROthiazide** "
            "(water pill), **hydrALAZINE** (vasodilator), or **hydrOXYzine** (antihistamine)."
        ),
    },
    # --- Trazodone vs. Tramadol (ISMP High-Alert Pair) ---
    "trazodone": {
        "drug": "trazodone",
        "tall_man": "traZODone",
        "purpose": "Sleep & mood medication (antidepressant)",
        "confused_with": "tramadol",
        "confused_tall_man": "traMADol",
        "confused_purpose": "Opioid pain reliever",
        "group": "traZODone vs. traMADol",
        "warning": (
            "Look-Alike Name Check: **traZODone** (for sleep/mood) and **traMADol** "
            "(an opioid pain medication) share the same prefix. Verify `-ZODone` vs `-MADol`."
        ),
    },
    "tramadol": {
        "drug": "tramadol",
        "tall_man": "traMADol",
        "purpose": "Opioid pain reliever",
        "confused_with": "trazodone",
        "confused_tall_man": "traZODone",
        "confused_purpose": "Sleep & mood medication (antidepressant)",
        "group": "traZODone vs. traMADol",
        "warning": (
            "Look-Alike Name Check: **traMADol** (an opioid pain reliever) and **traZODone** "
            "(for sleep/mood) share the same prefix. Verify `-MADol` vs `-ZODone`."
        ),
    },
    # --- Bupropion vs. Buspirone (FDA Table 1) ---
    "bupropion": {
        "drug": "bupropion",
        "tall_man": "buPROPion",
        "purpose": "Mood or smoking-cessation medication",
        "confused_with": "buspirone",
        "confused_tall_man": "busPIRone",
        "confused_purpose": "Anxiety medication",
        "group": "buPROPion vs. busPIRone",
        "warning": (
            "Look-Alike Name Check: **buPROPion** and **busPIRone** look and sound "
            "very similar. Please verify the exact middle letters on your bottle."
        ),
    },
    "buspirone": {
        "drug": "buspirone",
        "tall_man": "busPIRone",
        "purpose": "Anxiety medication",
        "confused_with": "bupropion",
        "confused_tall_man": "buPROPion",
        "confused_purpose": "Mood or smoking-cessation medication",
        "group": "buPROPion vs. busPIRone",
        "warning": (
            "Look-Alike Name Check: **busPIRone** and **buPROPion** look and sound "
            "very similar. Please verify the exact middle letters on your bottle."
        ),
    },
    # --- Metformin vs. Metronidazole (ISMP Table 2) ---
    "metformin": {
        "drug": "metformin",
        "tall_man": "metFORMIN",
        "purpose": "Diabetes blood-sugar medication",
        "confused_with": "metronidazole",
        "confused_tall_man": "metroNIDAZOLE",
        "confused_purpose": "Antibiotic used to treat infections",
        "group": "metFORMIN vs. metroNIDAZOLE",
        "warning": (
            "Look-Alike Name Check: Verify whether your bottle says **metFORMIN** "
            "(for diabetes) or **metroNIDAZOLE** (an antibiotic)."
        ),
    },
    "metronidazole": {
        "drug": "metronidazole",
        "tall_man": "metroNIDAZOLE",
        "purpose": "Antibiotic used to treat infections",
        "confused_with": "metformin",
        "confused_tall_man": "metFORMIN",
        "confused_purpose": "Diabetes blood-sugar medication",
        "group": "metFORMIN vs. metroNIDAZOLE",
        "warning": (
            "Look-Alike Name Check: Verify whether your bottle says **metroNIDAZOLE** "
            "(an antibiotic) or **metFORMIN** (for diabetes)."
        ),
    },
    # --- Benzodiazepine & Clonidine Group (ALPRAZolam / LORazepam / clonazePAM / clonIDINE) ---
    "alprazolam": {
        "drug": "alprazolam",
        "tall_man": "ALPRAZolam",
        "purpose": "Anxiety & panic medication (benzodiazepine)",
        "confused_with": "lorazepam",
        "confused_tall_man": "LORazepam",
        "confused_purpose": "Anxiety & sedation medication (different potency benzodiazepine)",
        "group": "ALPRAZolam vs. LORazepam vs. clonazePAM",
        "warning": (
            "Look-Alike Name Check: Verify whether your bottle says **ALPRAZolam**, "
            "**LORazepam**, or **clonazePAM** — these have very different milligram strengths."
        ),
    },
    "lorazepam": {
        "drug": "lorazepam",
        "tall_man": "LORazepam",
        "purpose": "Anxiety & sedation medication (benzodiazepine)",
        "confused_with": "alprazolam",
        "confused_tall_man": "ALPRAZolam",
        "confused_purpose": "Anxiety & panic medication (different potency benzodiazepine)",
        "group": "ALPRAZolam vs. LORazepam vs. clonazePAM",
        "warning": (
            "Look-Alike Name Check: Verify whether your bottle says **LORazepam**, "
            "**ALPRAZolam**, or **clonazePAM**."
        ),
    },
    "clonidine": {
        "drug": "clonidine",
        "tall_man": "clonIDINE",
        "purpose": "Blood pressure medication",
        "confused_with": "clonazepam",
        "confused_tall_man": "clonazePAM",
        "confused_purpose": "Anxiety or seizure medication (benzodiazepine)",
        "group": "clonIDINE vs. clonazePAM (ALPRAZolam / LORazepam)",
        "warning": (
            "Look-Alike Name Check: **clonIDINE** (for blood pressure) and "
            "**clonazePAM** (for anxiety/seizures) start with the same letters. "
            "Please verify the ending (`-IDINE` vs `-azePAM`) on your bottle."
        ),
    },
    "clonazepam": {
        "drug": "clonazepam",
        "tall_man": "clonazePAM",
        "purpose": "Anxiety or seizure medication (benzodiazepine)",
        "confused_with": "clonidine",
        "confused_tall_man": "clonIDINE",
        "confused_purpose": "Blood pressure medication",
        "group": "ALPRAZolam vs. LORazepam vs. clonazePAM vs. clonIDINE",
        "warning": (
            "Look-Alike Name Check: **clonazePAM** (for anxiety/seizures) can be confused "
            "with **clonIDINE** (blood pressure) or **LORazepam** / **ALPRAZolam**."
        ),
    },
    # --- Amlodipine vs. Amiloride (ISMP Table 2) ---
    "amlodipine": {
        "drug": "amlodipine",
        "tall_man": "amLODIPine",
        "purpose": "Blood pressure medication (calcium channel blocker)",
        "confused_with": "amiloride",
        "confused_tall_man": "aMILoride",
        "confused_purpose": "Potassium-sparing water pill (diuretic)",
        "group": "amLODIPine vs. aMILoride",
        "warning": (
            "Look-Alike Name Check: Verify whether your bottle says **amLODIPine** "
            "(calcium channel blocker) or **aMILoride** (potassium-sparing diuretic)."
        ),
    },
    "amiloride": {
        "drug": "amiloride",
        "tall_man": "aMILoride",
        "purpose": "Potassium-sparing water pill (diuretic)",
        "confused_with": "amlodipine",
        "confused_tall_man": "amLODIPine",
        "confused_purpose": "Blood pressure medication (calcium channel blocker)",
        "group": "amLODIPine vs. aMILoride",
        "warning": (
            "Look-Alike Name Check: Verify whether your bottle says **aMILoride** "
            "(potassium-sparing diuretic) or **amLODIPine** (calcium channel blocker)."
        ),
    },
    # --- Carbamazepine vs. Oxcarbazepine (ISMP Table 2) ---
    "carbamazepine": {
        "drug": "carbamazepine",
        "tall_man": "carBAMazepine",
        "purpose": "Seizure & nerve-pain medication (anticonvulsant)",
        "confused_with": "oxcarbazepine",
        "confused_tall_man": "OXcarbazepine",
        "confused_purpose": "Related anticonvulsant with different milligram dosing",
        "group": "carBAMazepine vs. OXcarbazepine",
        "warning": (
            "Look-Alike Name Check: Verify whether your bottle says **carBAMazepine** "
            "or **OXcarbazepine** — their milligram doses are not interchangeable."
        ),
    },
    "oxcarbazepine": {
        "drug": "oxcarbazepine",
        "tall_man": "OXcarbazepine",
        "purpose": "Seizure medication (anticonvulsant)",
        "confused_with": "carbamazepine",
        "confused_tall_man": "carBAMazepine",
        "confused_purpose": "Seizure & nerve-pain medication with different dosing",
        "group": "carBAMazepine vs. OXcarbazepine",
        "warning": (
            "Look-Alike Name Check: Verify whether your bottle says **OXcarbazepine** "
            "or **carBAMazepine** — their milligram doses are not interchangeable."
        ),
    },
    # --- CeleBREX (celecoxib) vs. CeleXA (citalopram) ---
    "celecoxib": {
        "drug": "celecoxib",
        "tall_man": "celeCOXIB (CeleBREX)",
        "purpose": "Arthritis & pain reliever (NSAID)",
        "confused_with": "citalopram",
        "confused_tall_man": "citaloPRAM (CeleXA)",
        "confused_purpose": "Antidepressant medication (SSRI)",
        "group": "CeleBREX vs. CeleXA",
        "warning": (
            "Look-Alike Name Check: Verify whether your bottle says **celeCOXIB / CeleBREX** "
            "(for arthritis pain) or **citaloPRAM / CeleXA** (an antidepressant)."
        ),
    },
    "celebrex": {
        "drug": "celebrex",
        "tall_man": "CeleBREX",
        "purpose": "Arthritis & pain reliever (celecoxib)",
        "confused_with": "celexa",
        "confused_tall_man": "CeleXA",
        "confused_purpose": "Antidepressant medication (citalopram)",
        "group": "CeleBREX vs. CeleXA",
        "warning": (
            "Look-Alike Name Check: Verify whether your bottle says **CeleBREX** "
            "(for arthritis pain) or **CeleXA** (an antidepressant)."
        ),
    },
    "citalopram": {
        "drug": "citalopram",
        "tall_man": "citaloPRAM (CeleXA)",
        "purpose": "Antidepressant medication (SSRI)",
        "confused_with": "celecoxib",
        "confused_tall_man": "celeCOXIB (CeleBREX)",
        "confused_purpose": "Arthritis & pain reliever (NSAID)",
        "group": "CeleBREX vs. CeleXA",
        "warning": (
            "Look-Alike Name Check: Verify whether your bottle says **citaloPRAM / CeleXA** "
            "(an antidepressant) or **celeCOXIB / CeleBREX** (for arthritis pain)."
        ),
    },
    "celexa": {
        "drug": "celexa",
        "tall_man": "CeleXA",
        "purpose": "Antidepressant medication (citalopram)",
        "confused_with": "celebrex",
        "confused_tall_man": "CeleBREX",
        "confused_purpose": "Arthritis & pain reliever (celecoxib)",
        "group": "CeleBREX vs. CeleXA",
        "warning": (
            "Look-Alike Name Check: Verify whether your bottle says **CeleXA** "
            "(an antidepressant) or **CeleBREX** (for arthritis pain)."
        ),
    },
    # --- Insulin High-Alert Pairs: HumaLOG vs. HumuLIN, NovoLOG vs. NovoLIN ---
    "humalog": {
        "drug": "humalog",
        "tall_man": "HumaLOG",
        "purpose": "Rapid-acting mealtime insulin (insulin lispro)",
        "confused_with": "humulin",
        "confused_tall_man": "HumuLIN",
        "confused_purpose": "Regular or intermediate-acting human insulin",
        "group": "HumaLOG vs. HumuLIN",
        "warning": (
            "High-Alert Insulin Check: Verify whether your pen/vial says **HumaLOG** "
            "(rapid-acting mealtime insulin) or **HumuLIN** (human insulin)."
        ),
    },
    "humulin": {
        "drug": "humulin",
        "tall_man": "HumuLIN",
        "purpose": "Regular or intermediate-acting human insulin",
        "confused_with": "humalog",
        "confused_tall_man": "HumaLOG",
        "confused_purpose": "Rapid-acting mealtime insulin (insulin lispro)",
        "group": "HumaLOG vs. HumuLIN",
        "warning": (
            "High-Alert Insulin Check: Verify whether your pen/vial says **HumuLIN** "
            "(human insulin) or **HumaLOG** (rapid-acting mealtime insulin)."
        ),
    },
    "novolog": {
        "drug": "novolog",
        "tall_man": "NovoLOG",
        "purpose": "Rapid-acting mealtime insulin (insulin aspart)",
        "confused_with": "novolin",
        "confused_tall_man": "NovoLIN",
        "confused_purpose": "Regular or intermediate-acting human insulin",
        "group": "NovoLOG vs. NovoLIN",
        "warning": (
            "High-Alert Insulin Check: Verify whether your pen/vial says **NovoLOG** "
            "(rapid-acting mealtime insulin) or **NovoLIN** (human insulin)."
        ),
    },
    "novolin": {
        "drug": "novolin",
        "tall_man": "NovoLIN",
        "purpose": "Regular or intermediate-acting human insulin",
        "confused_with": "novolog",
        "confused_tall_man": "NovoLOG",
        "confused_purpose": "Rapid-acting mealtime insulin (insulin aspart)",
        "group": "NovoLOG vs. NovoLIN",
        "warning": (
            "High-Alert Insulin Check: Verify whether your pen/vial says **NovoLIN** "
            "(human insulin) or **NovoLOG** (rapid-acting mealtime insulin)."
        ),
    },
    # --- PriLOSEC (omeprazole) vs. PROzac (fluoxetine) ---
    "prilosec": {
        "drug": "prilosec",
        "tall_man": "PriLOSEC",
        "purpose": "Stomach acid reducer (omeprazole)",
        "confused_with": "prozac",
        "confused_tall_man": "PROzac",
        "confused_purpose": "Antidepressant medication (fluoxetine)",
        "group": "PriLOSEC vs. PROzac",
        "warning": (
            "Look-Alike Brand Check: Verify whether your bottle says **PriLOSEC** "
            "(for heartburn/acid reflux) or **PROzac** (for mood/depression)."
        ),
    },
    "prozac": {
        "drug": "prozac",
        "tall_man": "PROzac",
        "purpose": "Antidepressant medication (fluoxetine)",
        "confused_with": "prilosec",
        "confused_tall_man": "PriLOSEC",
        "confused_purpose": "Stomach acid reducer (omeprazole)",
        "group": "PriLOSEC vs. PROzac",
        "warning": (
            "Look-Alike Brand Check: Verify whether your bottle says **PROzac** "
            "(for mood/depression) or **PriLOSEC** (for heartburn/acid reflux)."
        ),
    },
    # --- Opioid High-Alert Trio: oxyCODONE vs. HYDROCODONE vs. oxyMORphone ---
    "oxycodone": {
        "drug": "oxycodone",
        "tall_man": "oxyCODONE",
        "purpose": "Opioid pain medication",
        "confused_with": "oxyMORphone",
        "confused_tall_man": "oxyMORphone / HYDROCODONE",
        "confused_purpose": "Higher-potency opioid pain medication (not interchangeable)",
        "group": "oxyCODONE vs. HYDROCODONE vs. oxyMORphone",
        "warning": (
            "High-Alert Opioid Check: Verify whether your bottle says **oxyCODONE**, "
            "**HYDROCODONE**, or **oxyMORphone** — these opioids have very different strengths."
        ),
    },
    "hydrocodone": {
        "drug": "hydrocodone",
        "tall_man": "HYDROCODONE",
        "purpose": "Opioid pain & cough medication",
        "confused_with": "oxycodone",
        "confused_tall_man": "oxyCODONE",
        "confused_purpose": "Opioid pain medication (higher milligram potency)",
        "group": "oxyCODONE vs. HYDROCODONE vs. oxyMORphone",
        "warning": (
            "High-Alert Opioid Check: Verify whether your bottle says **HYDROCODONE**, "
            "**oxyCODONE**, or **oxyMORphone**."
        ),
    },
    "oxymorphone": {
        "drug": "oxymorphone",
        "tall_man": "oxyMORphone",
        "purpose": "Potent opioid pain medication",
        "confused_with": "oxycodone",
        "confused_tall_man": "oxyCODONE",
        "confused_purpose": "Opioid pain medication (different potency)",
        "group": "oxyCODONE vs. HYDROCODONE vs. oxyMORphone",
        "warning": (
            "High-Alert Opioid Check: Verify whether your bottle says **oxyMORphone** "
            "or **oxyCODONE** — milligram doses are NOT equivalent."
        ),
    },
    # --- Pyridostigmine vs. Physostigmine (ISMP Practitioner Survey 91%) ---
    "pyridostigmine": {
        "drug": "pyridostigmine",
        "tall_man": "pyRIDostigmine",
        "purpose": "Muscle-strength medication for myasthenia gravis",
        "confused_with": "physostigmine",
        "confused_tall_man": "PHYSostigmine",
        "confused_purpose": "Emergency anticholinergic toxicity antidote",
        "group": "pyRIDostigmine vs. PHYSostigmine",
        "warning": (
            "Look-Alike Name Check: Verify whether your bottle says **pyRIDostigmine** "
            "or **PHYSostigmine**."
        ),
    },
    "physostigmine": {
        "drug": "physostigmine",
        "tall_man": "PHYSostigmine",
        "purpose": "Anticholinergic toxicity antidote",
        "confused_with": "pyridostigmine",
        "confused_tall_man": "pyRIDostigmine",
        "confused_purpose": "Myasthenia gravis medication",
        "group": "pyRIDostigmine vs. PHYSostigmine",
        "warning": (
            "Look-Alike Name Check: Verify whether your bottle says **PHYSostigmine** "
            "or **pyRIDostigmine**."
        ),
    },
    # --- Cyclophosphamide vs. Cyclosporine vs. Cycloserine (FDA/ISMP Trio) ---
    "cyclophosphamide": {
        "drug": "cyclophosphamide",
        "tall_man": "cycloPHOSphamide",
        "purpose": "Chemotherapy & autoimmune immunosuppressant",
        "confused_with": "cyclosporine",
        "confused_tall_man": "cycloSPORINE / cycloSERINE",
        "confused_purpose": "Transplant immunosuppressant or tuberculosis antibiotic",
        "group": "cycloPHOSphamide vs. cycloSPORINE vs. cycloSERINE",
        "warning": (
            "Look-Alike Name Check: Verify whether your bottle says **cycloPHOSphamide**, "
            "**cycloSPORINE**, or **cycloSERINE**."
        ),
    },
    "cyclosporine": {
        "drug": "cyclosporine",
        "tall_man": "cycloSPORINE",
        "purpose": "Transplant & autoimmune immunosuppressant",
        "confused_with": "cyclophosphamide",
        "confused_tall_man": "cycloPHOSphamide / cycloSERINE",
        "confused_purpose": "Chemotherapy medication or tuberculosis antibiotic",
        "group": "cycloPHOSphamide vs. cycloSPORINE vs. cycloSERINE",
        "warning": (
            "Look-Alike Name Check: Verify whether your bottle says **cycloSPORINE**, "
            "**cycloPHOSphamide**, or **cycloSERINE**."
        ),
    },
    "cycloserine": {
        "drug": "cycloserine",
        "tall_man": "cycloSERINE",
        "purpose": "Antibiotic used for drug-resistant tuberculosis",
        "confused_with": "cyclosporine",
        "confused_tall_man": "cycloSPORINE / cycloPHOSphamide",
        "confused_purpose": "Immunosuppressant or chemotherapy medication",
        "group": "cycloPHOSphamide vs. cycloSPORINE vs. cycloSERINE",
        "warning": (
            "Look-Alike Name Check: Verify whether your bottle says **cycloSERINE**, "
            "**cycloSPORINE**, or **cycloPHOSphamide**."
        ),
    },
    # --- Droperidol vs. Dronabinol (ISMP Table 2) ---
    "droperidol": {
        "drug": "droperidol",
        "tall_man": "droPERidol",
        "purpose": "Anti-nausea & sedative medication",
        "confused_with": "dronabinol",
        "confused_tall_man": "droNABinol",
        "confused_purpose": "Appetite & anti-nausea cannabinoid capsule",
        "group": "droPERidol vs. droNABinol",
        "warning": (
            "Look-Alike Name Check: Verify whether your bottle says **droPERidol** "
            "or **droNABinol**."
        ),
    },
    "dronabinol": {
        "drug": "dronabinol",
        "tall_man": "droNABinol",
        "purpose": "Appetite & anti-nausea cannabinoid capsule",
        "confused_with": "droperidol",
        "confused_tall_man": "droPERidol",
        "confused_purpose": "Anti-nausea & sedative medication",
        "group": "droPERidol vs. droNABinol",
        "warning": (
            "Look-Alike Name Check: Verify whether your bottle says **droNABinol** "
            "or **droPERidol**."
        ),
    },
    # --- Dexamethasone vs. Dexmedetomidine (ISMP Table 2) ---
    "dexamethasone": {
        "drug": "dexamethasone",
        "tall_man": "dexAMETHasone",
        "purpose": "Corticosteroid for inflammation & swelling",
        "confused_with": "dexmedetomidine",
        "confused_tall_man": "dexmedeTOMIDine",
        "confused_purpose": "Hospital sedative medication",
        "group": "dexAMETHasone vs. dexmedeTOMIDine",
        "warning": (
            "Look-Alike Name Check: Verify whether your bottle says **dexAMETHasone** "
            "or **dexmedeTOMIDine**."
        ),
    },
    "dexmedetomidine": {
        "drug": "dexmedetomidine",
        "tall_man": "dexmedeTOMIDine",
        "purpose": "Sedative medication",
        "confused_with": "dexamethasone",
        "confused_tall_man": "dexAMETHasone",
        "confused_purpose": "Corticosteroid for inflammation",
        "group": "dexAMETHasone vs. dexmedeTOMIDine",
        "warning": (
            "Look-Alike Name Check: Verify whether your bottle says **dexmedeTOMIDine** "
            "or **dexAMETHasone**."
        ),
    },
    # --- Additional Common Senior LASA Pairs (Glipizide/Glyburide, Prednisone/Prednisolone, Losartan/Valsartan) ---
    "glipizide": {
        "drug": "glipizide",
        "tall_man": "glipiZIDE",
        "purpose": "Diabetes blood-sugar medication (sulfonylurea)",
        "confused_with": "glyburide",
        "confused_tall_man": "glyBURIDE",
        "confused_purpose": "Diabetes medication (carries higher low-blood-sugar risk in older adults)",
        "group": "glipiZIDE vs. glyBURIDE",
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
        "group": "glipiZIDE vs. glyBURIDE",
        "warning": (
            "Look-Alike Name Check: Verify whether your bottle says **glyBURIDE** "
            "or **glipiZIDE** (both treat diabetes, but they are different prescriptions)."
        ),
    },
    "prednisone": {
        "drug": "prednisone",
        "tall_man": "predniSONE",
        "purpose": "Oral corticosteroid for inflammation",
        "confused_with": "prednisolone",
        "confused_tall_man": "prednisoLONE",
        "confused_purpose": "Corticosteroid (different formulation)",
        "group": "predniSONE vs. prednisoLONE",
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
        "group": "predniSONE vs. prednisoLONE",
        "warning": (
            "Look-Alike Name Check: Verify whether your bottle says **prednisoLONE** "
            "or **predniSONE**."
        ),
    },
    "losartan": {
        "drug": "losartan",
        "tall_man": "loSARTAN",
        "purpose": "Blood pressure medication (ARB)",
        "confused_with": "valsartan",
        "confused_tall_man": "valSARTAN",
        "confused_purpose": "Blood pressure medication (ARB — different dosing)",
        "group": "loSARTAN vs. valSARTAN",
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
        "group": "loSARTAN vs. valSARTAN",
        "warning": (
            "Look-Alike Name Check: Verify whether your bottle says **valSARTAN** "
            "or **loSARTAN**."
        ),
    },
}


def _uppercase_preserving_midword_i(segment: str, *, is_word_start: bool = False) -> str:
    """Capitalize ``segment`` for Tall Man Lettering while keeping the letter
    ``'i'`` lowercase whenever it sits inside a word (so ``'I'`` is never
    mistaken for lowercase ``'l'`` in sans-serif clinical displays)."""
    out: list[str] = []
    for idx, ch in enumerate(segment):
        if ch.lower() == "i" and not (is_word_start and idx == 0):
            out.append("i")
        else:
            out.append(ch.upper())
    return "".join(out)


def compute_tall_man_pair(
    drug_a: str,
    drug_b: str,
    *,
    cd3_limit: bool = True,
) -> tuple[str, str]:
    """Algorithmically derive Tall Man Lettering for two confusable drug names
    using the deterministic 3-step Mid-Tall Man / CD3 convention:

    1. **Left-to-right shared prefix**: Leave shared leading letters in lowercase
       until encountering differing characters between ``drug_a`` and ``drug_b``.
    2. **Right-to-left shared suffix**: Starting from the final character, return
       two or more shared trailing letters back to lowercase (if fewer than two
       trailing letters are shared, the tail stays part of the distinguishing block).
    3. **Central distinguishing capitalization (CD3 rule + mid-word 'i' guard)**:
       Capitalize the distinguishing central characters (capped at 3 characters
       when ``cd3_limit=True`` to prevent over-capitalization from diluting visual
       novelty), and never capitalize ``'i'`` inside a mid-word segment.
    """
    a = (drug_a or "").strip().lower()
    b = (drug_b or "").strip().lower()
    if not a or not b or a == b:
        return a, b

    # Step 1: Shared prefix length from the left
    prefix_len = 0
    min_len = min(len(a), len(b))
    while prefix_len < min_len and a[prefix_len] == b[prefix_len]:
        prefix_len += 1

    # Step 2: Shared suffix length from the right (without overlapping the prefix)
    suffix_len = 0
    while (
        suffix_len < (min_len - prefix_len)
        and a[len(a) - 1 - suffix_len] == b[len(b) - 1 - suffix_len]
    ):
        suffix_len += 1

    # Under the Mid-Tall Man convention, only return >= 2 shared trailing letters
    # to lowercase; a single shared final letter remains capitalized with the tail.
    if suffix_len < 2:
        suffix_len = 0

    def _format_one(word: str) -> str:
        end_idx = len(word) - suffix_len if suffix_len > 0 else len(word)
        prefix = word[:prefix_len]
        middle = word[prefix_len:end_idx]
        suffix = word[end_idx:]

        if not middle:
            # One word is a prefix of the other: highlight the last 3 letters
            cut = max(0, len(word) - 3)
            return word[:cut] + _uppercase_preserving_midword_i(
                word[cut:], is_word_start=(cut == 0)
            )

        if cd3_limit and len(middle) > 3:
            cap_part = _uppercase_preserving_midword_i(
                middle[:3], is_word_start=(prefix_len == 0)
            )
            rest_mid = middle[3:]
            return f"{prefix}{cap_part}{rest_mid}{suffix}"

        cap_mid = _uppercase_preserving_midword_i(
            middle, is_word_start=(prefix_len == 0)
        )
        return f"{prefix}{cap_mid}{suffix}"

    return _format_one(a), _format_one(b)


def get_lasa_entry(drug_or_brand: str | None) -> dict[str, str] | None:
    """Look up a drug or brand name in ``LASA_CONFUSION_PAIRS`` (case-insensitive)."""
    if not drug_or_brand:
        return None
    clean = re.sub(r"[^a-z0-9+/\s()-]", " ", str(drug_or_brand).lower()).strip()
    if clean in LASA_CONFUSION_PAIRS:
        return dict(LASA_CONFUSION_PAIRS[clean])
    for token in re.split(r"[\s+/()-]+", clean):
        if token in LASA_CONFUSION_PAIRS:
            return dict(LASA_CONFUSION_PAIRS[token])
    return None


def get_tall_man_display_name(
    drug_name: str | None,
    *,
    confused_with: str | None = None,
) -> str:
    """Return the official FDA/ISMP Tall Man string for ``drug_name`` if it is in
    our LASA registry, or dynamically compute it via :func:`compute_tall_man_pair`
    when ``confused_with`` is provided."""
    if not drug_name:
        return ""
    entry = get_lasa_entry(drug_name)
    if entry:
        return entry["tall_man"]
    if confused_with:
        tm_a, _ = compute_tall_man_pair(drug_name, confused_with, cd3_limit=True)
        return tm_a
    return drug_name


# Matches consecutive uppercase distinguishing blocks (2+ uppercase letters,
# optionally containing a mid-word lowercase 'i' surrounded by uppercase letters,
# e.g. 'AMETH', 'OXY', 'ALAZINE', 'RID', 'PIR').
_TALL_MAN_SEGMENT_RE = re.compile(r"[A-Z]+(?:i[A-Z]+)*")


def render_tall_man_html(tall_man_text: str | None) -> str:
    """Render a Tall Man string as safe HTML with ``<strong class=\"ms-tall-man-upper\">``
    around the uppercase distinguishing syllable(s) so ``font-weight: 700`` and
    ``text-transform: none`` are preserved across every UI card and alert."""
    if not tall_man_text:
        return ""
    text = str(tall_man_text)
    # Only treat as mixed-case Tall Man if the string contains both lowercase and uppercase
    has_lower = any(c.islower() for c in text)
    has_upper = any(c.isupper() for c in text)
    if not (has_lower and has_upper):
        return f'<span class="ms-tall-man-name">{html.escape(text)}</span>'

    parts: list[str] = []
    last = 0
    for match in _TALL_MAN_SEGMENT_RE.finditer(text):
        seg = match.group(0)
        # Single leading capital letter (standard Title Case) is not a Tall Man segment
        if len(seg) < 2:
            continue
        if match.start() > last:
            parts.append(html.escape(text[last : match.start()]))
        parts.append(f'<strong class="ms-tall-man-upper">{html.escape(seg)}</strong>')
        last = match.end()
    if last < len(text):
        parts.append(html.escape(text[last:]))

    return f'<span class="ms-tall-man-name">{"".join(parts)}</span>'

