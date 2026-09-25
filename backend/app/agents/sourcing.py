"""Sourcing agent: find the candidates in the talent pool that best match a job."""

from pydantic import BaseModel, Field
from sqlalchemy import Float, bindparam, select
from sqlalchemy.orm import Session

from ..db import is_postgres
from ..embeddings import cosine, embed_one
from ..llm import run_structured
from ..models import Application, Candidate, Job
from . import job_brief


class SearchProfile(BaseModel):
    ideal_candidate: str = Field(description="A paragraph describing the ideal candidate's background, written like a resume summary")
    key_skills: list[str] = Field(description="The skills that matter most for this role")


SYSTEM = """You are the sourcing agent in a recruiting pipeline. Given a job posting, describe
the ideal candidate as a resume-style summary. This text is embedded and used for semantic
search over the talent pool, so write it in the vocabulary resumes actually use."""


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


def find_matches(db: Session, job: Job, *, limit: int = 20, min_similarity: float = 0.0) -> list[tuple[Candidate, float]]:
    """Rank candidates not yet in this job's pipeline by similarity to the ideal profile."""
    profile = search_profile(job)
    query = embed_one(f"{profile.ideal_candidate}\nSkills: {', '.join(profile.key_skills)}", kind="query")

    already = select(Application.candidate_id).where(Application.job_id == job.id)
    base = select(Candidate).where(Candidate.embedding.is_not(None), Candidate.id.not_in(already))

    if is_postgres():
        from pgvector.sqlalchemy import Vector

        vec = bindparam("query_embedding", query, type_=Vector(len(query)))
        distance = Candidate.embedding.op("<=>", return_type=Float)(vec)
        rows = db.execute(base.add_columns(distance).order_by(distance).limit(limit)).all()
        scored = [(c, 1.0 - float(d)) for c, d in rows]
    else:
        candidates = db.scalars(base).all()
        scored = sorted(((c, cosine(query, c.embedding)) for c in candidates), key=lambda x: x[1], reverse=True)[:limit]

    return [(c, round(s, 4)) for c, s in scored if s >= min_similarity]
