"""Evaluation agent: turn interview notes into a structured scorecard."""

from typing import Literal

from pydantic import BaseModel, Field

from ..llm import run_structured
from ..models import Candidate, Job
from . import FAIRNESS, candidate_brief, job_brief


class Competency(BaseModel):
    name: str
    rating: int = Field(description="1 (weak) to 5 (exceptional)")
    evidence: str


class Scorecard(BaseModel):
    overall_rating: int = Field(description="1 (weak) to 5 (exceptional)")
    recommendation: Literal["strong_hire", "hire", "no_hire", "strong_no_hire"]
    summary: str
    competencies: list[Competency]
    risks: list[str] = Field(description="Open questions or concerns to probe before an offer")


SYSTEM = f"""You are the evaluation agent in a recruiting pipeline. Turn an interviewer's notes
into a structured scorecard. Rate each core competency the job requires, using only what the
notes and resume show; when the notes are silent on a competency, give it a 3 and say it was
not assessed. A human hiring manager makes the final offer decision.

{FAIRNESS}"""

_POSITIVE = ("strong", "excellent", "great", "impressive", "solid", "clear", "deep", "good")
_NEGATIVE = ("weak", "struggled", "unclear", "lacked", "poor", "concern", "shallow", "missed")


def _heuristic(job: Job, notes: str) -> Scorecard:
    text = notes.lower()
    balance = sum(text.count(w) for w in _POSITIVE) - sum(text.count(w) for w in _NEGATIVE)
    rating = max(1, min(5, 3 + balance))
    rec = {5: "strong_hire", 4: "hire", 3: "hire", 2: "no_hire", 1: "strong_no_hire"}[rating]
    return Scorecard(
        overall_rating=rating,
        recommendation=rec,
        summary="Offline scorecard from keyword sentiment in the interview notes.",
        competencies=[
            Competency(name=req, rating=rating, evidence="Not individually assessed (offline mode)")
            for req in job.requirements[:6]
        ],
        risks=[] if rating >= 3 else ["Interview notes contain several concerns"],
    )


def evaluate(job: Job, candidate: Candidate, notes: str) -> Scorecard:
    card = run_structured(
        agent="evaluation",
        system=SYSTEM,
        prompt=f"{job_brief(job)}\n\n{candidate_brief(candidate)}\n\n<interview_notes>\n{notes}\n</interview_notes>\n\nProduce the scorecard.",
        schema=Scorecard,
        heuristic=lambda: _heuristic(job, notes),
    )
    card.overall_rating = max(1, min(5, card.overall_rating))
    return card
