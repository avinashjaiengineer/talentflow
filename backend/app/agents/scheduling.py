"""Scheduling agent: propose interview slots and write the invitation."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from ..config import get_settings
from ..llm import run_structured
from ..models import Candidate, Job


class Invitation(BaseModel):
    subject: str
    body: str


SYSTEM = """You are the scheduling agent in a recruiting pipeline. Write a brief interview
invitation that lists the proposed time slots exactly as given and asks the candidate to
reply with the one that works best. Keep it under 120 words. Sign off as "The {company} Recruiting Team"."""


def propose_slots(now: datetime | None = None, count: int = 3) -> list[datetime]:
    """One slot per business day starting tomorrow, rotating through working hours in TIMEZONE."""
    s = get_settings()
    now = (now or datetime.now(ZoneInfo(s.timezone))).astimezone(ZoneInfo(s.timezone))
    day = now.replace(minute=0, second=0, microsecond=0) + timedelta(days=1)
    span = max(1, s.working_hours_end - s.working_hours_start - 1)
    slots = []
    while len(slots) < count:
        if day.weekday() < 5:
            hour = s.working_hours_start + (len(slots) * 2) % span
            slots.append(day.replace(hour=hour))
        day += timedelta(days=1)
    return slots


def format_slot(t: datetime) -> str:
    return f"{t:%A, %B %d at %H:%M} ({get_settings().timezone})"


def plan(job: Job, candidate: Candidate) -> dict:
    s = get_settings()
    slots = propose_slots()
    labels = [format_slot(t) for t in slots]
    first_name = candidate.name.split()[0] if candidate.name else "there"
    listed = "\n".join(f"- {label}" for label in labels)

    invitation = run_structured(
        agent="scheduling",
        system=SYSTEM.format(company=s.company_name),
        prompt=(
            f"Role: {job.title}\nCandidate: {candidate.name}\nInterview length: {s.interview_duration_minutes} minutes\n"
            f"Proposed slots:\n{listed}\n\nWrite the invitation."
        ),
        schema=Invitation,
        heuristic=lambda: Invitation(
            subject=f"Interview for {job.title} at {s.company_name}",
            body=(
                f"Hi {first_name},\n\nThanks for your interest in the {job.title} role! We'd like to schedule a "
                f"{s.interview_duration_minutes}-minute interview. Do any of these times work?\n\n{listed}\n\n"
                f"Just reply with your preferred slot.\n\nBest,\nThe {s.company_name} Recruiting Team"
            ),
        ),
    )
    return {
        "proposed_slots": [t.isoformat() for t in slots],
        "confirmed_slot": None,
        "duration_minutes": s.interview_duration_minutes,
        "invitation": invitation.model_dump(),
    }
