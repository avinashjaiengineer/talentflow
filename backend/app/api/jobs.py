from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import orchestrator
from ..db import get_db
from ..embeddings import embed_one
from ..events import log_event
from ..models import Application, Candidate, Job, User
from ..schemas import AddCandidate, ApplicationOut, JobIn, JobOut, JobUpdate, SourceRequest, TaskOut
from .deps import current_user
from .serializers import LIST_LOAD, application_out

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _job_text(job: Job) -> str:
    return f"{job.title}\n{job.description}\n{' '.join(job.requirements)}"


def _get_job(db: Session, job_id: str) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return job


def _with_counts(db: Session, jobs: list[Job]) -> list[JobOut]:
    rows = db.execute(
        select(Application.job_id, Application.stage, func.count())
        .where(Application.job_id.in_([j.id for j in jobs]))
        .group_by(Application.job_id, Application.stage)
    ).all()
    counts: dict[str, dict[str, int]] = {}
    for job_id, stage, n in rows:
        counts.setdefault(job_id, {})[stage.value] = n
    out = []
    for job in jobs:
        item = JobOut.model_validate(job)
        item.stage_counts = counts.get(job.id, {})
        out.append(item)
    return out


@router.get("", response_model=list[JobOut])
def list_jobs(db: Session = Depends(get_db)):
    jobs = db.scalars(select(Job).order_by(Job.created_at.desc())).all()
    return _with_counts(db, list(jobs))


@router.post("", response_model=JobOut, status_code=201)
def create_job(body: JobIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    job = Job(**body.model_dump())
    job.embedding = embed_one(_job_text(job))
    db.add(job)
    db.flush()
    log_event(db, actor="human", type="job_created", message=f"{user.name} opened {job.title}", job_id=job.id)
    db.commit()
    return _with_counts(db, [job])[0]


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: str, db: Session = Depends(get_db)):
    return _with_counts(db, [_get_job(db, job_id)])[0]


@router.patch("/{job_id}", response_model=JobOut)
def update_job(job_id: str, body: JobUpdate, db: Session = Depends(get_db)):
    job = _get_job(db, job_id)
    changes = body.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(job, key, value)
    if changes.keys() & {"title", "description", "requirements"}:
        job.embedding = embed_one(_job_text(job))
    db.commit()
    return _with_counts(db, [job])[0]


@router.delete("/{job_id}", status_code=204)
def delete_job(job_id: str, db: Session = Depends(get_db)):
    db.delete(_get_job(db, job_id))
    db.commit()


@router.get("/{job_id}/applications", response_model=list[ApplicationOut])
def list_applications(job_id: str, db: Session = Depends(get_db)):
    _get_job(db, job_id)
    apps = db.scalars(select(Application).where(Application.job_id == job_id).options(*LIST_LOAD)).all()
    apps = sorted(apps, key=lambda a: (a.screening_score or -1, a.match_score or 0), reverse=True)
    return [application_out(a, detail=False) for a in apps]


@router.post("/{job_id}/source", response_model=TaskOut, status_code=202)
def source(job_id: str, body: SourceRequest, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Queue the sourcing agent. Poll GET /api/tasks/{id}; matches are screened automatically."""
    job = _get_job(db, job_id)
    if job.status.value == "closed":
        raise HTTPException(409, "This job is closed")
    return orchestrator.request_sourcing(db, job, limit=body.limit, auto_screen=body.auto_screen, by=user.name)


@router.post("/{job_id}/applications", response_model=ApplicationOut, status_code=201)
def add_candidate(job_id: str, body: AddCandidate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    job = _get_job(db, job_id)
    if db.get(Candidate, body.candidate_id) is None:
        raise HTTPException(404, "Candidate not found")
    app = orchestrator.add_to_pipeline(db, job, body.candidate_id, by=user.name, auto_screen=body.auto_screen)
    db.refresh(app)
    return application_out(app)
