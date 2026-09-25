from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from .. import __version__
from ..config import get_settings
from ..db import engine, get_db
from ..embeddings import get_embedder
from ..llm import MockLLM, get_llm
from ..models import AgentTask, Application, Approval, ApprovalStatus, Candidate, Event, Job, JobStatus, TaskStatus
from ..schemas import EventOut, Health

public_router = APIRouter(tags=["system"])
router = APIRouter(tags=["system"])

AGENTS = ("sourcing", "screening", "outreach", "scheduling", "evaluation")


@public_router.get("/health")
def health():
    """Liveness: the process is up. Public, so it reveals nothing about the configuration."""
    return {"status": "ok", "version": __version__}


@router.get("/system", response_model=Health)
def system_info():
    """Configuration summary for signed-in users (sidebar, admin checks)."""
    s = get_settings()
    mock = isinstance(get_llm(), MockLLM)
    return Health(
        status="ok",
        version=__version__,
        environment=s.environment,
        llm="mock (offline heuristics)" if mock else "anthropic",
        models={} if mock else {a: s.model_for(a) for a in AGENTS},
        embeddings=type(get_embedder()).__name__.removesuffix("Embedder").lower(),
        database=engine.dialect.name,
        integrations={"email": s.email_provider, "calendar": s.calendar_provider, "voice": s.voice_provider},
    )


@public_router.get("/ready")
def ready(db: Session = Depends(get_db)):
    """Readiness: the database answers and migrations have run."""
    try:
        db.execute(text("SELECT 1"))
        db.execute(select(func.count()).select_from(AgentTask).limit(1))
    except Exception as e:
        raise HTTPException(503, f"Database not ready: {type(e).__name__}") from e
    return {"status": "ready"}


@router.get("/stats")
def stats(db: Session = Depends(get_db)):
    by_stage = dict(db.execute(select(Application.stage, func.count()).group_by(Application.stage)).all())
    return {
        "open_jobs": db.scalar(select(func.count()).select_from(Job).where(Job.status == JobStatus.open)),
        "candidates": db.scalar(select(func.count()).select_from(Candidate)),
        "pending_approvals": db.scalar(select(func.count()).select_from(Approval).where(Approval.status == ApprovalStatus.pending)),
        "queued_tasks": db.scalar(
            select(func.count()).select_from(AgentTask).where(AgentTask.status.in_([TaskStatus.queued, TaskStatus.running]))
        ),
        "stages": {stage.value: n for stage, n in by_stage.items()},
    }


@router.get("/events", response_model=list[EventOut])
def list_events(
    application_id: str | None = None, job_id: str | None = None, limit: int = 100, db: Session = Depends(get_db)
):
    stmt = (
        select(Event, Candidate.name, Job.title)
        .outerjoin(Application, Event.application_id == Application.id)
        .outerjoin(Candidate, Application.candidate_id == Candidate.id)
        .outerjoin(Job, Event.job_id == Job.id)
        .order_by(Event.id.desc())
        .limit(max(1, min(limit, 500)))
    )
    if application_id:
        stmt = stmt.where(Event.application_id == application_id)
    if job_id:
        stmt = stmt.where(Event.job_id == job_id)
    out = []
    for event, candidate_name, job_title in db.execute(stmt).all():
        item = EventOut.model_validate(event)
        item.candidate_name, item.job_title = candidate_name, job_title
        out.append(item)
    return out
