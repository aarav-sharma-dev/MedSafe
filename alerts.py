"""Local in-app dose timing helpers (no automatic external transmission).

Privacy & safety note:
MedSafe is a local-first application and never automatically transmits
medication information by email or SMS. To share a medication or schedule
summary with a caregiver or pharmacist, use the Caregiver & Reports tab to
review and download a report explicitly.
"""

from __future__ import annotations

from datetime import datetime, time

GRACE_MINUTES = 60

TIME_MAP = {
    "morning": time(8, 0),
    "noon": time(12, 0),
    "afternoon": time(14, 0),
    "evening": time(18, 0),
    "bedtime": time(21, 0),
}


def parse_dose_time(label: str | None) -> time | None:
    """'8:00 am' or '08:00' -> time(8, 0). Returns None if unparseable."""
    raw = (label or "").strip().lower()
    if not raw:
        return None
    if raw in TIME_MAP:
        return TIME_MAP[raw]
    for fmt in ("%H:%M", "%I:%M %p", "%I %p"):
        try:
            return datetime.strptime(raw.upper(), fmt).time()
        except ValueError:
            continue
    return None


def minutes_overdue(med: dict, now: datetime | None = None) -> int:
    """How many minutes past its dose time this entry is (0 if not due yet,
    already recorded, or has no parseable time)."""
    if med.get("taken_today") or med.get("status") in ("taken", "skipped"):
        return 0
    due = parse_dose_time(med.get("time_of_day", ""))
    if due is None:
        return 0
    now = now or datetime.now()
    delta = (
        now - now.replace(hour=due.hour, minute=due.minute, second=0, microsecond=0)
    ).total_seconds() / 60
    return max(0, int(delta))


def overdue_meds(meds: list[dict], now: datetime | None = None) -> list[dict]:
    """Entries past their dose time today, annotated with minutes_overdue."""
    out = []
    for m in meds:
        late = minutes_overdue(m, now)
        if late > 0:
            item = dict(m)
            item["minutes_overdue"] = late
            out.append(item)
    out.sort(key=lambda m: -m["minutes_overdue"])
    return out


def format_lateness(minutes: int) -> str:
    """922 -> 'about 15 hours past scheduled time', 45 -> '45 min past scheduled time'."""
    if minutes < 60:
        return f"{minutes} min past scheduled time"
    hours = round((minutes / 60) * 2) / 2
    if hours == int(hours):
        hours = int(hours)
    unit = "hour" if hours == 1 else "hours"
    return f"about {hours} {unit} past scheduled time"
