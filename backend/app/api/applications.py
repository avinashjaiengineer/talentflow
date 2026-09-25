from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import comms, orchestrator
from ..db import get_db
from ..models import AgentTask, Application, Approval, ApprovalStatus, Stage, User
from ..schemas import ApplicationOut, ApprovalOut, Decision, Notes, RejectRequest, SlotChoice, TaskOut
from .deps import current_user
from .serializers import LIST_LOAD, application_out, approval_out, approval_rank

router = APIRouter(tags=["pipeline"])


def _get_app(db: Session, application_id: str, *, lock: bool = False) -> Application:
    """lock=True takes a row lock (Postgres) for the rest of the request, so two people acting
    on the same candidate at once are serialized instead of both passing the same checks."""
    app = db.get(Application, application_id, with_for_update=lock, populate_existing=lock)
    if app is None:
        raise HTTPException(404, "Application not found")
    return app


def _guard(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except orchestrator.TransitionError as e:
        raise HTTPException(409, str(e)) from e


@router.get("/applications", response_model=list[ApplicationOut])
def list_applications(stage: Stage | None = None, db: Session = Depends(get_db)):
    stmt = select(Application).order_by(Application.updated_at.desc())
    if stage:
        stmt = stmt.where(Application.stage == stage)
    return [application_out(a, detail=False) for a in db.scalars(stmt.options(*LIST_LOAD).limit(500)).all()]


@router.get("/applications/{application_id}", response_model=ApplicationOut)
def get_application(application_id: str, db: Session = Depends(get_db)):
    return application_out(_get_app(db, application_id))


@router.post("/applications/{application_id}/screen", response_model=ApplicationOut)
def screen(application_id: str, db: Session = Depends(get_db)):
    app = _get_app(db, application_id, lock=True)
    _guard(orchestrator.start_screening, db, app)
    return application_out(app)


@router.post("/applications/{application_id}/retry", response_model=ApplicationOut)
def retry(application_id: str, db: Session = Depends(get_db)):
    app = _get_app(db, application_id, lock=True)
    _guard(orchestrator.retry, db, app)
    return application_out(app)


@router.post("/applications/{application_id}/replied", response_model=ApplicationOut)
def candidate_replied(application_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    app = _get_app(db, application_id, lock=True)
    _guard(orchestrator.mark_replied, db, app, by=user.name)
    return application_out(app)


@router.post("/applications/{application_id}/confirm-slot", response_model=ApplicationOut)
def confirm_slot(application_id: str, body: SlotChoice, user: User = Depends(current_user), db: Session = Depends(get_db)):
    app = _get_app(db, application_id, lock=True)
    _guard(comms.confirm_and_book, db, app, body.slot, by=user.name)
    return application_out(app)


@router.post("/applications/{application_id}/notes", response_model=ApplicationOut)
def submit_notes(application_id: str, body: Notes, user: User = Depends(current_user), db: Session = Depends(get_db)):
    app = _get_app(db, application_id, lock=True)
    _guard(orchestrator.submit_notes, db, app, body.notes, by=user.name)
    return application_out(app)


@router.post("/applications/{application_id}/reject", response_model=ApplicationOut)
def reject(application_id: str, body: RejectRequest, user: User = Depends(current_user), db: Session = Depends(get_db)):
    app = _get_app(db, application_id, lock=True)
    _guard(orchestrator.reject, db, app, by=user.name, reason=body.reason)
    return application_out(app)


@router.get("/approvals", response_model=list[ApprovalOut])
def list_approvals(status: ApprovalStatus | None = None, db: Session = Depends(get_db)):
    stmt = select(Approval).order_by(Approval.created_at.desc())
    if status:
        stmt = stmt.where(Approval.status == status)
    items = [approval_out(a) for a in db.scalars(stmt.limit(500)).all()]
    if status == ApprovalStatus.pending:
        # The review queue leads with what's most worth a recruiter's time.
        items.sort(key=approval_rank, reverse=True)
    return items


@router.post("/approvals/{approval_id}/decide", response_model=ApplicationOut)
def decide(approval_id: str, body: Decision, user: User = Depends(current_user), db: Session = Depends(get_db)):
    approval = db.get(Approval, approval_id)
    if approval is None:
        raise HTTPException(404, "Approval not found")
    # Lock the application, then re-read the approval: a decision made a moment ago by someone
    # else is visible here, so the second click gets a clean 409 instead of a double transition.
    _get_app(db, approval.application_id, lock=True)
    db.refresh(approval)
    app = _guard(orchestrator.decide, db, approval, approve=body.approve, by=user.name, comment=body.comment)
    return application_out(app)


@router.get("/tasks/{task_id}", response_model=TaskOut)
def get_task(task_id: int, db: Session = Depends(get_db)):
    task = db.get(AgentTask, task_id)
    if task is None:
        raise HTTPException(404, "Task not found")
    return task
