"""Overdue-dose detection and caregiver email alerts.

Dose times come from the meds table ("8:00 am", "bedtime", ...).
A med is overdue when now > its time and it isn't marked taken.
After GRACE_MINUTES it escalates: one caregiver email per med per day.

Caregiver email setup (optional - everything else works without it):
    export MEDSAFE_SMTP_USER="yourgmail@gmail.com"
    export MEDSAFE_SMTP_PASS="an app password"   # google.com -> security -> app passwords
    export MEDSAFE_CAREGIVER_EMAIL="daughter@example.com"
"""

import os
import smtplib
from datetime import datetime, time
from email.message import EmailMessage

GRACE_MINUTES = 60

TIME_MAP = {"bedtime": time(21, 0)}


def parse_dose_time(label: str):
    """'8:00 am' -> time(8, 0). Returns None if unparseable."""
    label = (label or "").strip().lower()
    if label in TIME_MAP:
        return TIME_MAP[label]
    try:
        return datetime.strptime(label, "%I:%M %p").time()
    except ValueError:
        return None


def minutes_overdue(med: dict, now: datetime = None) -> int:
    """How many minutes past its dose time this med is (0 if not due yet,
    already taken, or has no parseable time)."""
    if med.get("taken_today"):
        return 0
    due = parse_dose_time(med.get("time_of_day", ""))
    if due is None:
        return 0
    now = now or datetime.now()
    delta = (now - now.replace(hour=due.hour, minute=due.minute,
                               second=0, microsecond=0)).total_seconds() / 60
    return max(0, int(delta))


def overdue_meds(meds: list, now: datetime = None) -> list:
    """Meds past their dose time, each annotated with minutes_overdue."""
    out = []
    for m in meds:
        late = minutes_overdue(m, now)
        if late > 0:
            m = dict(m)
            m["minutes_overdue"] = late
            out.append(m)
    out.sort(key=lambda m: -m["minutes_overdue"])
    return out


def format_lateness(minutes: int) -> str:
    """922 -> 'about 15 hours late', 90 -> 'about 1.5 hours late', 45 -> '45 min late'."""
    if minutes < 60:
        return f"{minutes} min late"
    hours = minutes / 60
    hours = round(hours * 2) / 2  # nearest half hour
    if hours == int(hours):
        hours = int(hours)
    unit = "hour" if hours == 1 else "hours"
    return f"about {hours} {unit} late"


def caregiver_configured() -> bool:
    return all(
        os.environ.get(k)
        for k in ("MEDSAFE_SMTP_USER", "MEDSAFE_SMTP_PASS", "MEDSAFE_CAREGIVER_EMAIL")
    )


def send_caregiver_email(med: dict) -> bool:
    """Email the caregiver about one missed dose. Returns True on success."""
    if not caregiver_configured():
        return False
    user = os.environ["MEDSAFE_SMTP_USER"]
    msg = EmailMessage()
    msg["Subject"] = f"MedSafe alert: {med['name'].title()} dose missed"
    msg["From"] = user
    msg["To"] = os.environ["MEDSAFE_CAREGIVER_EMAIL"]
    msg.set_content(
        f"The {med['time_of_day']} dose of {med['name'].title()} {med.get('dose', '')} "
        f"has not been marked as taken ({format_lateness(med.get('minutes_overdue', 0))}).\n\n"
        "You may want to check in.\n\n- MedSafe"
    )
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as s:
            s.login(user, os.environ["MEDSAFE_SMTP_PASS"])
            s.send_message(msg)
        return True
    except Exception:
        return False


if __name__ == "__main__":
    from datetime import datetime as dt

    fake_now = dt(2026, 9, 1, 9, 30)
    meds = [
        {"name": "lisinopril", "dose": "10 mg", "time_of_day": "8:00 am", "taken_today": 0},
        {"name": "metformin", "dose": "500 mg", "time_of_day": "12:30 pm", "taken_today": 0},
        {"name": "aspirin", "dose": "81 mg", "time_of_day": "8:00 am", "taken_today": 1},
    ]
    for m in overdue_meds(meds, fake_now):
        print(f"{m['name']}: {m['minutes_overdue']} min overdue")
    print("caregiver email configured:", caregiver_configured())
