"""Screening agent: score a resume against a job's requirements."""

from typing import Literal

from pydantic import BaseModel, Field

from ..llm import run_structured
from ..models import Candidate, Job
from ..resume import find_skills
from . import FAIRNESS, candidate_brief, job_brief


class RequirementMatch(BaseModel):
    requirement: str
    status: Literal["met", "partial", "not_met"]
    evidence: str = Field(description="Quote or close paraphrase from the resume, or why it is missing")


class ScreeningResult(BaseModel):
    score: int = Field(description="Overall fit from 0 to 100")
    recommendation: Literal["advance", "hold", "reject"]
    summary: str = Field(description="Two or three sentences a recruiter can read in ten seconds")
    strengths: list[str]
    gaps: list[str]
    requirements: list[RequirementMatch]


SYSTEM = f"""You are the screening agent in a recruiting pipeline. You assess how well a
candidate's resume fits a job and recommend whether a human recruiter should advance them.

{FAIRNESS}

Scoring guide: 85-100 exceeds every core requirement; 70-84 meets the core requirements;
50-69 meets some and could grow into the role; below 50 misses core requirements.
Recommend "advance" at 70+, "hold" for 50-69, and "reject" below 50. A human makes the final call."""


def _heuristic(job: Job, candidate: Candidate) -> ScreeningResult:
    have = {s.lower() for s in candidate.skills} | {s.lower() for s in find_skills(candidate.resume_text)}
    resume = candidate.resume_text.lower()
    matches = []
    for req in job.requirements:
        words = [w for w in req.lower().replace(",", " ").split() if len(w) > 2]
        hits = sum(1 for w in words if w in resume or w in have)
        ratio = hits / len(words) if words else 0
        status = "met" if ratio >= 0.6 else "partial" if ratio > 0 else "not_met"
        matches.append(RequirementMatch(requirement=req, status=status, evidence="Keyword match in resume (offline mode)"))
    points = {"met": 1.0, "partial": 0.5, "not_met": 0.0}
    score = round(100 * sum(points[m.status] for m in matches) / len(matches)) if matches else 50
    return ScreeningResult(
        score=score,
        recommendation="advance" if score >= 70 else "hold" if score >= 50 else "reject",
        summary=f"{candidate.name} matches {sum(m.status == 'met' for m in matches)} of {len(matches)} requirements (offline keyword screening).",
        strengths=[m.requirement for m in matches if m.status == "met"],
        gaps=[m.requirement for m in matches if m.status == "not_met"],
        requirements=matches,
    )


def screen(job: Job, candidate: Candidate) -> ScreeningResult:
    result = run_structured(
        agent="screening",
        system=SYSTEM,
        prompt=f"{job_brief(job)}\n\n{candidate_brief(candidate)}\n\nScreen this candidate against the job.",
        schema=ScreeningResult,
        heuristic=lambda: _heuristic(job, candidate),
    )
    result.score = max(0, min(100, result.score))
    return result
