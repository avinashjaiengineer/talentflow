"""Resume intake: bring applications from job portals into the talent pool and pipelines.

Two ways in:
- mailbox: portals (Naukri, LinkedIn, Indeed, ...) email each application with the resume
  attached. The worker checks the intake mailbox every INTAKE_POLL_MINUTES, or when a
  recruiter clicks "Check inbox now".
- webhook: portals with an API, careers pages, and automation tools (Zapier, Make, n8n)
  POST applications to /api/intake/webhook.

For each application the intake agent decides whether it's really an application and which
open job it's for; the resume is parsed into a candidate (or matched to an existing one by
email), and the candidate joins that job's pipeline, where screening starts as usual.
Every item is recorded once per (source, external_id), so re-reading an email is a no-op.
"""

import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import orchestrator
from .agents import intake as intake_agent
from .config import get_settings
from .events import log_event
from .integrations.mailbox import Attachment, GraphMailbox, get_mailbox, pick_resume
from .llm import LLMError
from .models import AgentTask, Candidate, IntakeItem, IntakeStatus, Job, JobStatus, TaskKind, TaskStatus
from .resume import ResumeUnreadable, build_candidate, extract_text

log = logging.getLogger(__name__)


@dataclass
class Inbound:
    source: str  # "mailbox" | "webhook"
    external_id: str
    subject: str = ""
    sender: str | None = None
    body: str = ""
    received_at: datetime | None = None
    resume: Attachment | None = None
    resume_text: str | None = None
    attachment_names: list[str] = field(default_factory=list)
    # Webhook pushes may already know these.
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    portal: str | None = None
    job: Job | None = None
    job_title: str | None = None


class IntakeUnavailable(RuntimeError):
    pass


def open_jobs(db: Session) -> list[Job]:
    return list(db.scalars(select(Job).where(Job.status == JobStatus.open).order_by(Job.created_at.desc())))


def find_job_by_title(jobs: list[Job], title: str | None) -> Job | None:
    if not title:
        return None
    t = title.strip().lower()
    return next((j for j in jobs if j.title.lower() == t), None) or next(
        (j for j in sorted(jobs, key=lambda j: -len(j.title)) if j.title.lower() in t or t in j.title.lower()), None
    )


def existing_candidate(db: Session, email: str | None) -> Candidate | None:
    if not email:
        return None
    return db.scalar(select(Candidate).where(func.lower(Candidate.email) == email.strip().lower()).limit(1))


def _seen(db: Session, source: str, external_id: str) -> IntakeItem | None:
    return db.scalar(select(IntakeItem).where(IntakeItem.source == source, IntakeItem.external_id == external_id))


def process(db: Session, item: Inbound) -> IntakeItem:
    """Import one application. Commits. Raises only for retryable failures (rate limits,
    network), so the caller can try again later; anything else is recorded as `failed`."""
    if (done := _seen(db, item.source, item.external_id)) is not None:
        return done
    record = IntakeItem(source=item.source, external_id=item.external_id[:500], subject=(item.subject or None) and item.subject[:500],
                        sender=item.sender, received_at=item.received_at, portal=item.portal)
    try:
        _import(db, item, record)
    except LLMError as e:
        db.rollback()
        if e.retryable:
            raise
        record = IntakeItem(**{c: getattr(record, c) for c in ("source", "external_id", "subject", "sender", "received_at", "portal")},
                            status=IntakeStatus.failed, detail=str(e))
    db.add(record)
    try:
        db.commit()
    except IntegrityError:  # another worker processed the same email at the same moment
        db.rollback()
        return _seen(db, item.source, item.external_id)
    return record


def _import(db: Session, item: Inbound, record: IntakeItem) -> None:
    text, problem = item.resume_text or "", None
    if not text and item.resume is not None:
        try:
            text = extract_text(item.resume.filename, item.resume.data)
        except Exception as e:  # noqa: BLE001 - corrupt or unsupported files are skipped, not fatal
            problem = f"Couldn't read {item.resume.filename}: {e}"
    has_resume = len(text.strip()) >= 20

    jobs = open_jobs(db)
    job = item.job
    if item.source == "mailbox":
        decision = intake_agent.classify(subject=item.subject, sender=item.sender, body=item.body,
                                         attachments=item.attachment_names, has_resume=has_resume, jobs=jobs)
        record.portal = decision.portal
        if not decision.is_application:
            record.status, record.detail = IntakeStatus.skipped, decision.reason
            return
        job = job or next((j for j in jobs if j.id == decision.job_id), None)
    else:
        record.portal = item.portal or intake_agent.portal_from_sender(item.sender) or "Webhook"
        job = job or find_job_by_title(jobs, item.job_title)

    if not has_resume:
        record.status = IntakeStatus.skipped
        record.detail = problem or "No readable resume (PDF, DOCX, or TXT) attached. Scanned images can't be read."
        return

    # Match returning applicants by email, so one person applying twice is one candidate.
    candidate = existing_candidate(db, item.email)
    is_new = False
    if candidate is None:
        filename = item.resume.filename if item.resume else None
        try:
            parsed = build_candidate(text, filename=filename, name=item.name, email=item.email, phone=item.phone)
        except ResumeUnreadable as e:
            record.status, record.detail = IntakeStatus.skipped, str(e)
            return
        candidate = existing_candidate(db, parsed.email)
        if candidate is None:
            db.add(parsed)
            db.flush()
            candidate, is_new = parsed, True
    record.status = IntakeStatus.imported if is_new else IntakeStatus.duplicate
    record.candidate_id = candidate.id

    where = f" from {record.portal}" if record.portal else ""
    if job is not None and job.status == JobStatus.open:
        app = orchestrator.add_applicant(
            db, job, candidate, actor="intake", auto_screen=get_settings().intake_auto_screen,
            note=f"{candidate.name} applied{where}",
        )
        record.job_id, record.application_id = job.id, app.id
        record.detail = f"Added to {job.title}"
    else:
        record.detail = "In the talent pool; no open job matched, so assign it from the job page"
        log_event(db, actor="intake", type="resume_imported", message=f"Imported {candidate.name}{where}; no open job matched")


# ---------------------------------------------------------------- mailbox


def poll_mailbox(db: Session, mailbox: GraphMailbox | None = None) -> dict:
    """Import new applications from the intake mailbox (run by the worker)."""
    mailbox = mailbox or get_mailbox(get_settings())
    counts: Counter[str] = Counter()
    for email in mailbox.recent():
        if _seen(db, "mailbox", email.external_id) is not None:
            continue
        resume = pick_resume(mailbox.attachments(email))
        record = process(db, Inbound(
            source="mailbox", external_id=email.external_id, subject=email.subject, sender=email.sender,
            body=email.body, received_at=email.received_at, resume=resume, attachment_names=email.attachment_names,
        ))
        counts[record.status.value] += 1
    summary = ", ".join(f"{n} {status}" for status, n in counts.items()) or "nothing new"
    log_event(db, actor="intake", type="mailbox_checked", message=f"Checked {mailbox.mailbox}: {summary}")
    db.commit()
    return {"count": sum(counts.values()), **counts}


def _open_or_latest_task(db: Session) -> AgentTask | None:
    return db.scalar(select(AgentTask).where(AgentTask.kind == TaskKind.intake).order_by(AgentTask.id.desc()).limit(1))


def request_check(db: Session, *, by: str) -> AgentTask:
    """Queue a mailbox check now (the "Check inbox now" button)."""
    if get_settings().intake_provider != "graph":
        raise IntakeUnavailable("Mailbox intake is off. Set INTAKE_PROVIDER=graph to read applications from Outlook.")
    latest = _open_or_latest_task(db)
    if latest is not None and latest.status in (TaskStatus.queued, TaskStatus.running):
        return latest
    task = orchestrator.enqueue(db, TaskKind.intake)
    log_event(db, actor="human", type="intake_requested", message=f"{by} asked the intake agent to check the inbox")
    db.commit()
    return task


def schedule_if_due(db: Session) -> AgentTask | None:
    """Called by the worker every minute: queue a mailbox check every INTAKE_POLL_MINUTES."""
    s = get_settings()
    if s.intake_provider != "graph" or s.intake_poll_minutes <= 0:
        return None
    latest = _open_or_latest_task(db)
    if latest is not None:
        if latest.status in (TaskStatus.queued, TaskStatus.running):
            return None
        created = latest.created_at if latest.created_at.tzinfo else latest.created_at.replace(tzinfo=UTC)
        if datetime.now(UTC) - created < timedelta(minutes=s.intake_poll_minutes):
            return None
    task = orchestrator.enqueue(db, TaskKind.intake)
    db.commit()
    return task


def last_checked(db: Session) -> datetime | None:
    return db.scalar(
        select(AgentTask.updated_at)
        .where(AgentTask.kind == TaskKind.intake, AgentTask.status == TaskStatus.succeeded)
        .order_by(AgentTask.id.desc())
        .limit(1)
    )
