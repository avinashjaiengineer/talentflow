"""Sourcing agent: find the candidates in the talent pool that best match a job.

The job title leads: it decides which skill groups of the talent pool are searched (a Backend
Engineer job searches Backend and Full-Stack Engineering, not Design), and it opens the search
query. Within those groups, candidates are ranked by hybrid search over every resume piece.
"""

from dataclasses import dataclass, field

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import skill_groups
from ..llm import run_structured
from ..models import Job
from ..resume import SkillGroup
from ..search_index import Match, group_is_empty, hybrid_search
from . import job_brief


class SearchProfile(BaseModel):
    skill_groups: list[SkillGroup] = Field(
        description="The 1-3 skill groups to search for this job title: the job's own group first, then "
        "closely related groups people are often hired from (e.g. Backend -> Full-Stack)"
    )
    ideal_candidate: str = Field(description="A paragraph describing the ideal candidate's background, written like a resume summary")
    key_skills: list[str] = Field(
        description="The skills that matter most for this role, each as it would appear verbatim in a "
        "resume: 1-4 words, e.g. 'Kafka', 'PostgreSQL', 'REST API design'"
    )


SYSTEM = """You are the sourcing agent in a recruiting pipeline. Given a job posting, decide which
skill groups of the talent pool to search, judged mainly by the job title, then describe the
ideal candidate as a resume-style summary. The summary is embedded and used for semantic
search, so write it in the vocabulary resumes actually use. The key skills are also matched
as keywords, so list the exact terms a strong resume would contain."""


@dataclass
class SourcingResult:
    matches: list[Match]
    groups: list[str]  # the skill groups searched
    widened: bool = False  # no candidates in those groups, so the whole pool was searched
    keywords: list[str] = field(default_factory=list)


def search_profile(job: Job) -> SearchProfile:
    return run_structured(
        agent="sourcing",
        system=SYSTEM,
        prompt=f"{job_brief(job)}\n\nChoose the skill groups to search and describe the ideal candidate for this role.",
        schema=SearchProfile,
        heuristic=lambda: SearchProfile(
            skill_groups=skill_groups.groups_for_job(job.title, job.requirements),
            ideal_candidate=f"{job.title}. {' '.join(job.requirements)} {job.description}",
            key_skills=list(job.requirements),
        ),
    )


def find_matches(db: Session, job: Job, *, limit: int = 20, min_similarity: float = 0.0) -> SourcingResult:
    """Candidates not yet in this job's pipeline, from the skill groups that match the job title,
    ranked by meaning (the title and ideal-candidate profile) and keyword (the title and key skills)."""
    profile = search_profile(job)
    groups = skill_groups.clean(list(profile.skill_groups)) or skill_groups.groups_for_job(job.title, job.requirements)
    search = dict(
        query_text=f"{job.title}\n{profile.ideal_candidate}\nSkills: {', '.join(profile.key_skills)}",
        terms=[job.title, *profile.key_skills],
        exclude_job_id=job.id,
        limit=limit,
        min_similarity=min_similarity,
    )
    matches = hybrid_search(db, groups=groups, **search)
    widened = not matches and group_is_empty(db, groups)
    if widened:
        matches = hybrid_search(db, groups=None, **search)
    return SourcingResult(matches=matches, groups=groups, widened=widened, keywords=profile.key_skills)
