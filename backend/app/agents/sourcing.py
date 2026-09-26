"""Sourcing agent: find the candidates in the talent pool that best match a job."""

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..llm import run_structured
from ..models import Job
from ..search_index import Match, hybrid_search
from . import job_brief


class SearchProfile(BaseModel):
    ideal_candidate: str = Field(description="A paragraph describing the ideal candidate's background, written like a resume summary")
    key_skills: list[str] = Field(
        description="The skills that matter most for this role, each as it would appear verbatim in a "
        "resume: 1-4 words, e.g. 'Kafka', 'PostgreSQL', 'REST API design'"
    )


SYSTEM = """You are the sourcing agent in a recruiting pipeline. Given a job posting, describe
the ideal candidate as a resume-style summary. This text is embedded and used for semantic
search over the talent pool, so write it in the vocabulary resumes actually use. The key
skills are also matched as keywords, so list the exact terms a strong resume would contain."""


def search_profile(job: Job) -> SearchProfile:
    return run_structured(
        agent="sourcing",
        system=SYSTEM,
        prompt=f"{job_brief(job)}\n\nDescribe the ideal candidate for this role.",
        schema=SearchProfile,
        heuristic=lambda: SearchProfile(
            ideal_candidate=f"{job.title}. {' '.join(job.requirements)} {job.description}",
            key_skills=list(job.requirements),
        ),
    )


def find_matches(db: Session, job: Job, *, limit: int = 20, min_similarity: float = 0.0) -> list[Match]:
    """Rank candidates not yet in this job's pipeline: hybrid search over every resume piece,
    by meaning (the ideal-candidate profile) and by keyword (the key skills)."""
    profile = search_profile(job)
    return hybrid_search(
        db,
        query_text=f"{profile.ideal_candidate}\nSkills: {', '.join(profile.key_skills)}",
        terms=profile.key_skills,
        exclude_job_id=job.id,
        limit=limit,
        min_similarity=min_similarity,
    )
