import base64
import binascii
import hashlib
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import intake
from ..config import get_settings
from ..db import get_db
from ..integrations.mailbox import Attachment
from ..llm import LLMError
from ..models import AgentTask, IntakeItem, Job, TaskKind, TaskStatus, User
from ..schemas import IntakeItemOut, IntakeStatusOut, IntakeWebhook, TaskOut
from .deps import current_user

router = APIRouter(prefix="/intake", tags=["intake"])
# Token-authenticated, for job portals and automation tools that push applications.
public_router = APIRouter(prefix="/intake", tags=["intake"])

MAX_RESUME_BYTES = 10 * 1024 * 1024


def _out(item: IntakeItem) -> IntakeItemOut:
    out = IntakeItemOut.model_validate(item)
    out.candidate_name = item.candidate.name if item.candidate else None
    out.job_title = item.job.title if item.job else None
    return out


@router.get("/status", response_model=IntakeStatusOut)
def status(db: Session = Depends(get_db)):
    s = get_settings()
    checking = db.scalar(
        select(AgentTask.id).where(AgentTask.kind == TaskKind.intake,
                                   AgentTask.status.in_([TaskStatus.queued, TaskStatus.running])).limit(1)
    ) is not None
    return IntakeStatusOut(
        mailbox_enabled=s.intake_provider == "graph",
        mailbox=s.intake_mailbox_address if s.intake_provider == "graph" else None,
        poll_minutes=s.intake_poll_minutes,
        webhook_enabled=bool(s.intake_webhook_token),
        auto_screen=s.intake_auto_screen,
        last_checked=intake.last_checked(db),
        checking=checking,
    )


@router.get("/items", response_model=list[IntakeItemOut])
def list_items(limit: int = 50, db: Session = Depends(get_db)):
    items = db.scalars(
        select(IntakeItem).options(selectinload(IntakeItem.candidate), selectinload(IntakeItem.job))
        .order_by(IntakeItem.created_at.desc()).limit(min(max(limit, 1), 200))
    ).all()
    return [_out(i) for i in items]


@router.post("/check", response_model=TaskOut, status_code=202)
def check_now(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Queue a mailbox check. Poll GET /api/tasks/{id}."""
    try:
        return intake.request_check(db, by=user.name)
    except intake.IntakeUnavailable as e:
        raise HTTPException(409, str(e)) from e


@public_router.post("/webhook", response_model=IntakeItemOut, status_code=201)
def webhook(
    body: IntakeWebhook,
    x_intake_token: str | None = Header(None),
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
):
    """Receive one application. Send the token as `X-Intake-Token` or `Authorization: Bearer`.
    Sending the same external_id (or the same resume) again returns the original result."""
    expected = get_settings().intake_webhook_token
    if not expected:
        raise HTTPException(404, "Webhook intake is off (set INTAKE_WEBHOOK_TOKEN)")
    given = x_intake_token or (authorization[7:].strip() if (authorization or "").lower().startswith("bearer ") else "")
    if not secrets.compare_digest(given.encode(), expected.encode()):
        raise HTTPException(401, "Invalid intake token")

    resume = None
    if body.resume_base64:
        if not body.filename:
            raise HTTPException(422, "filename is required with resume_base64, e.g. resume.pdf")
        try:
            data = base64.b64decode(body.resume_base64, validate=True)
        except (binascii.Error, ValueError) as e:
            raise HTTPException(422, "resume_base64 is not valid base64") from e
        if len(data) > MAX_RESUME_BYTES:
            raise HTTPException(413, "Resume is larger than 10 MB")
        resume = Attachment(filename=body.filename, data=data)
    elif not body.resume_text:
        raise HTTPException(422, "Send resume_text, or resume_base64 with filename")

    job = None
    if body.job_id:
        job = db.get(Job, body.job_id)
        if job is None:
            raise HTTPException(404, "Job not found")
    content = resume.data if resume else body.resume_text.encode()
    external_id = body.external_id or "sha256:" + hashlib.sha256((body.email or "").lower().encode() + content).hexdigest()
    try:
        item = intake.process(db, intake.Inbound(
            source="webhook", external_id=external_id, subject=body.job_title or (job.title if job else ""),
            resume=resume, resume_text=body.resume_text if resume is None else None, name=body.name,
            email=body.email, phone=body.phone, portal=body.portal, job=job, job_title=body.job_title,
        ))
    except LLMError as e:
        raise HTTPException(503, f"Couldn't process the resume right now, try again: {e}", headers={"Retry-After": "30"}) from e
    db.refresh(item)
    return _out(item)
