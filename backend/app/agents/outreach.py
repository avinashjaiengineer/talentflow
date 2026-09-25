"""Outreach agent: write a personalized first-contact email."""

from pydantic import BaseModel

from ..config import get_settings
from ..llm import run_structured
from ..models import Candidate, Job
from . import candidate_brief, job_brief


class OutreachDraft(BaseModel):
    subject: str
    body: str


SYSTEM = """You are the outreach agent in a recruiting pipeline. Write a short, warm, specific
email inviting a candidate to talk about a role. Reference one or two concrete things from
their background that make them a fit. No hype, no buzzwords, under 150 words, and end by
asking whether they are open to a 30-minute conversation. Sign off as "The {company} Recruiting Team"."""


def draft(job: Job, candidate: Candidate, screening: dict | None) -> OutreachDraft:
    company = get_settings().company_name
    strengths = (screening or {}).get("strengths") or []
    first_name = candidate.name.split()[0] if candidate.name else "there"

    def heuristic() -> OutreachDraft:
        hook = f" Your experience with {strengths[0]} stood out to us." if strengths else ""
        return OutreachDraft(
            subject=f"{job.title} at {company}",
            body=(
                f"Hi {first_name},\n\nI came across your profile and think you could be a great fit for our "
                f"{job.title} role.{hook}\n\nWould you be open to a 30-minute conversation this week?\n\n"
                f"Best,\nThe {company} Recruiting Team"
            ),
        )

    notes = f"\n\nScreening highlights: {', '.join(strengths)}" if strengths else ""
    return run_structured(
        agent="outreach",
        system=SYSTEM.format(company=company),
        prompt=f"{job_brief(job)}\n\n{candidate_brief(candidate)}{notes}\n\nWrite the outreach email.",
        schema=OutreachDraft,
        heuristic=heuristic,
    )
