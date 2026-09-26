"""Job-writer agent: turn a recruiter's few words into a complete job posting.

The draft is returned to the recruiter to review and edit; nothing is saved until they
create the job. Its requirements feed the screening agent, so they must be concrete
enough to check against a resume."""

import re

from pydantic import BaseModel, Field

from ..config import get_settings
from ..llm import run_structured
from ..resume import find_skills


class JobDraft(BaseModel):
    title: str = Field(description="A standard, searchable job title, e.g. 'Senior Backend Engineer'")
    department: str | None = Field(None, description="e.g. Engineering, Sales; null if the brief doesn't imply one")
    location: str | None = Field(None, description="City, 'Remote', or 'Hybrid - City'; null if the brief doesn't say")
    description: str = Field(
        description="Plain-text job description (no Markdown) with short sections: About the role, "
        "What you'll do, What we're looking for, Nice to have"
    )
    requirements: list[str] = Field(
        description="4-8 must-have requirements, each concrete and checkable against a resume, "
        "e.g. '5+ years building backend services in Python'"
    )


SYSTEM = """You are the job-writer agent in a recruiting pipeline for {company}. A recruiter gives
you a few words about a role; you write a complete, accurate job posting.

- Expand the brief with what the role normally involves, but never invent specifics the brief
  doesn't support: no salary, benefits, team size, funding, or product names. Where a detail
  would help but is unknown, leave it out rather than using a placeholder.
- Requirements are used to screen resumes automatically, so each one must be concrete and
  checkable (a skill, a technology, a number of years, a kind of experience). Only list true
  must-haves; put everything else under "Nice to have" in the description.
- Use inclusive language: no gendered words, no age proxies ("young", "digital native"), no
  "rockstar" or "ninja", and don't require a degree unless the brief asks for one.
- Keep the description under 350 words."""

_YEARS = re.compile(r"(\d{1,2})\s*\+?\s*(?:years|yrs|yr|y)\b", re.I)


def _heuristic(brief: str) -> JobDraft:
    """Offline mode: a plain template filled from the brief."""
    text = " ".join(brief.split())
    head = re.split(r"[,;\n.]", text)[0].strip()
    title = " ".join(w if w.isupper() else w.capitalize() for w in head.split())[:120] or "New role"
    skills = find_skills(text)
    years = _YEARS.search(text)
    requirements = []
    if years:
        requirements.append(f"{years.group(1)}+ years of relevant experience")
    requirements += skills
    if not requirements:
        requirements = [f"Experience as a {title}"]
    return JobDraft(
        title=title,
        description=(
            f"About the role\nWe're hiring a {title} to join {get_settings().company_name}.\n\n"
            f"What you'll do\n{text}\n\n"
            "What we're looking for\n" + "\n".join(f"- {r}" for r in requirements)
        ),
        requirements=requirements,
    )


def draft(brief: str) -> JobDraft:
    result = run_structured(
        agent="job_writer",
        system=SYSTEM.replace("{company}", get_settings().company_name),
        prompt=f"<brief>\n{brief}\n</brief>\n\nWrite the job posting.",
        schema=JobDraft,
        heuristic=lambda: _heuristic(brief),
        effort="medium",  # a recruiter is waiting on the form
    )
    result.requirements = [r.strip() for r in result.requirements if r.strip()][:10]
    return result
