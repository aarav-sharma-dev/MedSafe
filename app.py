"""MedSafe - a medication safety companion for seniors.

Run with:  streamlit run app.py
"""

import streamlit as st

import ai_explain
import alerts
import drug_data
import interactions

# Optional OCR: app still works without tesseract installed.
# Note: the pytesseract package is only a wrapper - the Tesseract ENGINE
# must also be installed (Mac: brew install tesseract).
try:
    from PIL import Image
    import pytesseract

    pytesseract.get_tesseract_version()  # raises if the engine is missing
    OCR_AVAILABLE = True
except Exception:
    OCR_AVAILABLE = False

# Optional text-to-speech: app still works without gTTS installed
try:
    from io import BytesIO

    from gtts import gTTS

    TTS_AVAILABLE = True
except ImportError:
    TTS_AVAILABLE = False

TTS_LANG = {"English": "en", "Hindi": "hi", "Spanish": "es", "Mandarin": "zh-CN"}


def read_aloud(text: str, language: str):
    """Return MP3 bytes of the text, or None if TTS is unavailable/offline."""
    if not TTS_AVAILABLE:
        return None
    try:
        buf = BytesIO()
        gTTS(text=text, lang=TTS_LANG.get(language, "en")).write_to_fp(buf)
        return buf.getvalue()
    except Exception:
        return None

st.set_page_config(page_title="MedSafe", page_icon="💊", layout="centered")
interactions.init_db()

SEVERITY_STYLE = {
    "major": ("🔴", "Serious interaction"),
    "moderate": ("🟠", "Moderate interaction"),
    "minor": ("🟡", "Mild interaction"),
}

st.title("💊 MedSafe")
st.caption("Checks your medicines for unsafe combinations and explains them in plain words.")

tab_scan, tab_check, tab_remind = st.tabs(["📷 Add medicine", "⚠️ Safety check", "⏰ Today's medicines"])


# ---------- Tab 1: add a medicine (scan or type) ----------
with tab_scan:
    st.subheader("Add a medicine")

    drug_name = None
    if OCR_AVAILABLE:
        photo = st.camera_input("Point the camera at the pill bottle label") or st.file_uploader(
            "...or upload a photo of the label", type=["png", "jpg", "jpeg"]
        )
        if photo:
            with st.spinner("Reading the label..."):
                try:
                    text = pytesseract.image_to_string(Image.open(photo))
                except Exception:
                    text = ""
                    st.error(
                        "Couldn't read the photo - the Tesseract engine may not be "
                        "installed (Mac: `brew install tesseract`). Type the name below."
                    )
                if text:
                    st.text_area("Text found on label", text, height=100)
                    guess = ai_explain.clean_ocr_to_drug_name(text)
                    if guess:
                        drug_name = drug_data.normalize_drug_name(guess) or guess
                        st.success(f"Found: **{drug_name.title()}**")
                    else:
                        st.warning("Couldn't find a drug name - type it below.")
    else:
        st.info(
            "Camera scanning is off because the Tesseract OCR engine isn't installed "
            "(Mac: `brew install tesseract`, then restart the app). You can type the name instead."
        )

    typed = st.text_input("Medicine name", placeholder="e.g. lisinopril")
    dose = st.text_input("Dose (optional)", placeholder="e.g. 10 mg")
    time_of_day = st.selectbox("When is it taken?", ["8:00 am", "12:30 pm", "6:00 pm", "8:00 pm", "bedtime"])

    if st.button("Add to my medicines", type="primary"):
        name = (typed or drug_name or "").strip().lower()
        if not name:
            st.error("Enter or scan a medicine name first.")
        else:
            clean = drug_data.normalize_drug_name(name) or name
            interactions.add_med(clean, dose, time_of_day)
            st.success(f"Added {clean.title()}. Check the Safety check tab!")

    meds = interactions.list_meds()
    if meds:
        st.write("**My medicines:** " + ", ".join(m["name"].title() for m in meds))


# ---------- Tab 2: interaction check ----------
with tab_check:
    st.subheader("Safety check")
    meds = interactions.list_meds()
    med_names = [m["name"] for m in meds]

    extra = st.text_input(
        "Also check something new (e.g. before buying a pain reliever)",
        placeholder="e.g. ibuprofen",
    )
    check_names = med_names + ([extra.strip().lower()] if extra.strip() else [])

    language = st.selectbox("Explain in", ["English", "Hindi", "Spanish", "Mandarin"])

    if not check_names:
        st.info("Add a medicine first to run a safety check.")
    elif st.button("Run safety check", type="primary"):
        found = interactions.check_list(check_names) if len(check_names) > 1 else []
        food_hits = interactions.check_foods(check_names)
        if not found and len(check_names) > 1:
            st.success("✅ No known interactions found among your medicines.")
            st.caption(
                "Checked against the local interaction database. "
                "Always confirm new medicines with your pharmacist."
            )
        for hit in found:
            icon, label = SEVERITY_STYLE.get(hit["severity"], ("⚪", "Interaction"))
            with st.container(border=True):
                st.markdown(f"### {icon} {label}")
                st.markdown(f"**{hit['drug_a'].title()} + {hit['drug_b'].title()}**")
                with st.spinner("Writing a plain-language explanation..."):
                    explanation = ai_explain.explain(hit, language)
                st.write(explanation)
                audio = read_aloud(explanation, language)
                if audio:
                    st.audio(audio, format="audio/mp3")
                elif not TTS_AVAILABLE:
                    st.caption("Install gTTS (`pip install gTTS`) to enable read-aloud.")
                with st.expander("What the FDA label says"):
                    label_text = None
                    for drug in (hit["drug_a"], hit["drug_b"]):
                        info = drug_data.get_label_info(drug)
                        label_text = (
                            info.get("drug_interactions")
                            or info.get("ask_doctor_or_pharmacist")
                            or info.get("warnings")
                        )
                        if label_text:
                            st.caption(f"From the FDA label for {drug.title()}:")
                            break
                    st.write(
                        label_text
                        or "No label text found on openFDA for these drugs "
                        "(or you're offline)."
                    )

        if food_hits:
            st.markdown("#### 🍊 Food and drink to watch")
            for row in food_hits:
                icon, _ = SEVERITY_STYLE.get(row["severity"], ("⚪", ""))
                with st.container(border=True):
                    st.markdown(
                        f"{icon} **{row['drug'].title()} + {row['food'].title()}** "
                        f"({row['severity']})"
                    )
                    with st.spinner("Explaining..."):
                        food_text = ai_explain.explain_food(row, language)
                    st.write(food_text)
                    audio = read_aloud(food_text, language)
                    if audio:
                        st.audio(audio, format="audio/mp3")
        elif check_names:
            st.caption("No food or drink warnings for these medicines.")


# ---------- Tab 3: reminders ----------


@st.fragment(run_every=60)
def overdue_banner():
    """Re-checks every minute while the app is open. Shows overdue doses
    and, after the grace period, emails the caregiver (once per med per day)."""
    late = alerts.overdue_meds(interactions.list_meds())
    if not late:
        return
    names = ", ".join(
        f"{m['name'].title()} ({alerts.format_lateness(m['minutes_overdue'])})"
        for m in late
    )
    st.error(f"⏰ Overdue: {names} — please take them or mark them taken.")
    for m in late:
        if m["minutes_overdue"] >= alerts.GRACE_MINUTES and not m.get("alerted_today"):
            if alerts.send_caregiver_email(m):
                interactions.mark_alerted(m["name"])
                st.warning(f"Caregiver notified about {m['name'].title()}.")
            elif not alerts.caregiver_configured():
                st.caption(
                    "Caregiver email not set up - see alerts.py for the three "
                    "environment variables to enable it."
                )
                break


with tab_remind:
    st.subheader("Today's medicines")
    overdue_banner()
    meds = interactions.list_meds()
    if not meds:
        st.info("No medicines yet - add one in the first tab.")
    else:
        taken = sum(m["taken_today"] for m in meds)
        st.caption(f"{taken} of {len(meds)} taken today")
        st.progress(taken / len(meds))
        for m in meds:
            col1, col2, col3 = st.columns([3, 2, 2])
            status = "✅" if m["taken_today"] else "⏰"
            col1.markdown(f"{status} **{m['name'].title()}** {m['dose']}")
            col2.caption(m["time_of_day"])
            if not m["taken_today"]:
                if col3.button("Mark taken", key=f"take_{m['name']}"):
                    interactions.mark_taken(m["name"])
                    st.rerun()
            else:
                if col3.button("Undo", key=f"undo_{m['name']}"):
                    interactions.mark_taken(m["name"], False)
                    st.rerun()
        if st.button("Start a new day (reset)"):
            interactions.reset_day()
            st.rerun()

st.divider()
st.caption(
    "MedSafe is a student project for the Congressional App Challenge. "
    "It is not medical advice - always consult a doctor or pharmacist."
)
