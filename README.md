# MedSafe 💊

A medication safety companion for seniors — scans pill bottles, checks for unsafe drug combinations against a verified database, and explains warnings in plain language (with translation).

Built for the Congressional App Challenge.

## How it works

```
Pill bottle photo ──► OCR (pytesseract) ──► RxNorm API (clean up the name)
                                                    │
My medicine list (SQLite) ──► interaction DB (DDInter/seed CSV) ── decides IF drugs interact
                                                    │
                                     Gemini AI ── only EXPLAINS confirmed
                                                  interactions in plain words
```

**Responsible AI design:** the database decides *whether* two drugs interact; the AI only *explains* it. The AI is never trusted with the safety decision, so a hallucination can't create or hide a warning.

## Setup

```bash
pip install streamlit requests pillow pytesseract
python -m streamlit run app.py
```

Optional (each unlocks a feature, app works without them):

1. **AI explanations & translation** — free key from https://aistudio.google.com then `export GEMINI_API_KEY=your_key`. Without it, a built-in template explanation is used.
2. **Camera scanning** — install the Tesseract engine (`brew install tesseract` on Mac, `apt install tesseract-ocr` on Linux, installer on Windows). Without it, type drug names manually.
3. **Full interaction database** — the app ships with 25 well-known interaction pairs (`data/interactions_seed.csv`). For real coverage, download the free DDInter 2.0 dataset (ddinter2.scbdd.com), convert to the same 4 columns (`drug_a,drug_b,severity,mechanism`), replace the CSV, and run `python interactions.py` to reload.

## Files

| File | What it does |
|---|---|
| `app.py` | Streamlit UI — three tabs: add medicine, safety check, reminders |
| `interactions.py` | SQLite interaction database + medication list (the source of truth) |
| `drug_data.py` | Free government APIs: RxNorm (name cleanup) + openFDA (label text) |
| `ai_explain.py` | Gemini AI: plain-language explanations, translation, OCR cleanup |
| `data/interactions_seed.csv` | Starter interaction data — swap in DDInter 2.0 |

## Quick demo (no internet needed)

```bash
python interactions.py    # loads DB, prints the lisinopril + ibuprofen warning
python ai_explain.py      # prints a plain-language explanation
```

In the app: add `lisinopril` and `metformin`, then in Safety check type `ibuprofen` ("about to buy a pain reliever") → red warning appears.

## Contest checklist

- [ ] Test with 2–3 real seniors (grandparent, neighbor) and note their feedback — judges love real users
- [ ] Record the 1-minute demo video: problem → grandma scans bottle → warning in Hindi → caregiver angle
- [ ] Story: why you built it (a real family moment beats any feature)
- [ ] Mention the responsible-AI design (database decides, AI explains)
- [ ] Submit at congressionalappchallenge.us before early November

## Ideas to grow it

- Caregiver text alerts for missed doses (Twilio free trial)
- Food interactions (grapefruit + statins)
- Voice input ("I'm about to take Advil, is that okay?")
- Pill identification by photo (NLM RxImage)

---
*Not medical advice. Always consult a doctor or pharmacist.*
