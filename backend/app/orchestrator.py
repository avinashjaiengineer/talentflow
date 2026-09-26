"""The orchestrator: a pipeline state machine that decides which agent runs next.

Agents never change an application's stage themselves. Every transition goes through
`_move()`, which checks it against TRANSITIONS and writes it to the event log. When a
transition hands work to an agent, the orchestrator enqueues an AgentTask in the same
transaction; the worker (app/worker.py) picks it up and calls `run_agent_step()`.

    sourced -> screening -> screened --[human: advance]--> outreach -> contacted
    contacted --[candidate replied]--> scheduling -> interview_scheduled
    interview_scheduled --[notes submitted]--> evaluation -> evaluated --[human: offer]--> offer
    any open stage --[human]--> rejected
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .agents import evaluation, outreach, scheduling, screening, sourcing
from .embeddings import embed_one
from .events import log_event
from .llm import LLMError
from .models import (
    AgentTask,
    Application,
    Approval,
    ApprovalKind,
    ApprovalStatus,
    CallStatus,
    Job,
    MessageKind,
    Stage,
    TaskKind,
    TaskStatus,
)

log = logging.getLogger(__name__)

TRANSITIONS: dict[Stage, set[Stage]] = {
    Stage.sourced: {Stage.screening},
    Stage.screening: {Stage.screened},
    Stage.screened: {Stage.outreach},
    Stage.outreach: {Stage.contacted},
    Stage.contacted: {Stage.scheduling},
    Stage.scheduling: {Stage.interview_scheduled},
    Stage.interview_scheduled: {Stage.evaluation},
    Stage.evaluation: {Stage.evaluated},
    Stage.evaluated: {Stage.offer},
    Stage.offer: set(),
    Stage.rejected: set(),
    Stage.failed: set(),
}
# Stages in which an agent is (or should be) working.
AGENT_STAGES = {Stage.screening, Stage.outreach, Stage.scheduling, Stage.evaluation}
CLOSED_STAGES = {Stage.offer, Stage.rejected}


class TransitionError(ValueError):
    pass


def _move(db: Session, app: Application, to: Stage, *, actor: str, reason: str = "") -> None:
    if to != Stage.rejected and to not in TRANSITIONS[app.stage]:
        raise TransitionError(f"Cannot move from {app.stage.value} to {to.value}")
    if to == Stage.rejected and app.stage in CLOSED_STAGES:
        raise TransitionError(f"Application is already {app.stage.value}")
    previous = app.stage
    app.stage = to
    app.error = None
    log_event(
        db,
        actor=actor,
        type="stage_changed",
        message=f"{previous.value} → {to.value}" + (f": {reason}" if reason else ""),
        application=app,
        data={"from": previous.value, "to": to.value},
    )
    if to in AGENT_STAGES:
        enqueue(db, TaskKind.agent_step, application_id=app.id)
    if to in CLOSED_STAGES:
        _cancel_pending_calls(db, app, reason=f"candidate {to.value}")


def _cancel_pending_calls(db: Session, app: Application, *, reason: str) -> None:
    """Calls that haven't started yet (e.g. a reminder for tomorrow) must not go ahead."""
    for call in app.calls:
        if call.status in (CallStatus.scheduled, CallStatus.queued):
            call.status = CallStatus.canceled
            call.error = f"Canceled: {reason}"
            log_event(db, actor="orchestrator", type="call_canceled",
                      message=f"Canceled the {call.purpose.value} call ({reason})", application=app)


def enqueue(db: Session, kind: TaskKind, *, application_id: str | None = None, job_id: str | None = None,
            payload: dict | None = None) -> AgentTask:
    """Queue work for the worker. Committed by the caller, together with the change that needs it."""
    task = AgentTask(kind=kind, application_id=application_id, job_id=job_id, payload=payload)
    db.add(task)
    db.flush()
    return task


def has_open_task(db: Session, application_id: str) -> bool:
    return db.scalar(
        select(AgentTask.id).where(
            AgentTask.application_id == application_id,
            AgentTask.status.in_([TaskStatus.queued, TaskStatus.running]),
        ).limit(1)
    ) is not None


# ---------------------------------------------------------------- work run by the worker


def run_agent_step(db: Session, app: Application) -> None:
    """Run the agent for the application's current stage. Raises on failure; the worker
    decides whether to retry. A no-op when the application has already moved on."""
    if app.stage not in AGENT_STAGES:
        return
    job, candidate = app.job, app.candidate

    if app.stage == Stage.screening:
        result = screening.screen(job, candidate)
        app.screening = result.model_dump()
        app.screening_score = result.score
        log_event(db, actor="screening", type="screened",
                  message=f"Scored {result.score}/100, recommends {result.recommendation}",
                  application=app, data={"score": result.score, "recommendation": result.recommendation})
        _move(db, app, Stage.screened, actor="orchestrator")
        db.add(Approval(application=app, kind=ApprovalKind.advance,
                        recommendation=f"{result.recommendation} ({result.score}/100): {result.summary}"))
        log_event(db, actor="orchestrator", type="approval_requested",
                  message="Waiting for a recruiter to advance or reject", application=app)

    elif app.stage == Stage.outreach:
        from . import comms

        draft = outreach.draft(job, candidate, app.screening)
        msg = comms.draft_message(db, app, MessageKind.outreach, subject=draft.subject, body=draft.body)
        app.outreach = {**draft.model_dump(), "to": candidate.email, "message_id": msg.id}
        log_event(db, actor="outreach", type="outreach_drafted",
                  message=f"Drafted an email to {candidate.email or candidate.name}: {draft.subject}. Waiting for a recruiter to send it",
                  application=app)
        _move(db, app, Stage.contacted, actor="orchestrator")

    elif app.stage == Stage.scheduling:
        from . import comms

        slots = comms.free_slots(db, job)
        if not slots:
            raise LLMError("No free interview slots in the next two weeks; check the interviewers' calendars")
        app.scheduling = scheduling.plan(job, candidate, slots)
        invitation = app.scheduling["invitation"]
        comms.draft_message(db, app, MessageKind.invitation, subject=invitation["subject"], body=invitation["body"])
        log_event(db, actor="scheduling", type="slots_proposed",
                  message=f"Proposed {len(app.scheduling['proposed_slots'])} interview slots",
                  application=app, data={"slots": app.scheduling["proposed_slots"]})
        _move(db, app, Stage.interview_scheduled, actor="orchestrator")

    elif app.stage == Stage.evaluation:
        card = evaluation.evaluate(job, candidate, app.interview_notes or "")
        app.scorecard = card.model_dump()
        log_event(db, actor="evaluation", type="scorecard_created",
                  message=f"Rated {card.overall_rating}/5, recommends {card.recommendation}",
                  application=app, data={"rating": card.overall_rating, "recommendation": card.recommendation})
        _move(db, app, Stage.evaluated, actor="orchestrator")
        db.add(Approval(application=app, kind=ApprovalKind.offer,
                        recommendation=f"{card.recommendation} ({card.overall_rating}/5): {card.summary}"))
        log_event(db, actor="orchestrator", type="approval_requested",
                  message="Waiting for a hiring manager to make an offer or reject", application=app)


def run_sourcing(db: Session, job: Job, *, limit: int = 20, auto_screen: bool = True) -> dict:
    """Sourcing agent: add the best-matching pool candidates to this job at stage `sourced`."""
    if job.embedding is None:
        job.embedding = embed_one(f"{job.title}\n{job.description}\n{' '.join(job.requirements)}")
    matches = sourcing.find_matches(db, job, limit=limit)
    ids = []
    for m in matches:
        app = Application(job=job, candidate=m.candidate, match_score=m.similarity)
        db.add(app)
        db.flush()
        why = f"; keywords: {', '.join(m.keywords[:6])}" if m.keywords else ""
        log_event(db, actor="sourcing", type="sourced",
                  message=f"Matched {m.candidate.name} (similarity {m.similarity:.2f}{why})", application=app,
                  data={"similarity": m.similarity, "keywords": m.keywords, "passage": (m.passage or "")[:600] or None})
        if auto_screen:
            _move(db, app, Stage.screening, actor="orchestrator")
        ids.append(app.id)
    log_event(db, actor="sourcing", type="sourcing_complete",
              message=f"Found {len(ids)} new candidates for {job.title}", job_id=job.id)
    return {"application_ids": ids, "count": len(ids)}


# ---------------------------------------------------------------- entry points (API)


def request_sourcing(db: Session, job: Job, *, limit: int, auto_screen: bool, by: str) -> AgentTask:
    task = enqueue(db, TaskKind.source, job_id=job.id, payload={"limit": limit, "auto_screen": auto_screen})
    log_event(db, actor="human", type="sourcing_requested", message=f"{by} asked the sourcing agent for {limit} candidates",
              job_id=job.id)
    db.commit()
    return task


def add_to_pipeline(db: Session, job: Job, candidate_id: str, *, by: str, auto_screen: bool) -> Application:
    existing = db.scalar(select(Application).where(Application.job_id == job.id, Application.candidate_id == candidate_id))
    if existing:
        return existing
    app = Application(job_id=job.id, candidate_id=candidate_id)
    db.add(app)
    db.flush()
    log_event(db, actor="human", type="added", message=f"{by} added the candidate to the pipeline", application=app)
    if auto_screen:
        _move(db, app, Stage.screening, actor="orchestrator")
    db.commit()
    return app


def add_applicant(db: Session, job: Job, candidate, *, actor: str, note: str, auto_screen: bool) -> Application:
    """Add a candidate who applied through a job portal. Committed by the caller."""
    db.flush()
    existing = db.scalar(select(Application).where(Application.job_id == job.id, Application.candidate_id == candidate.id))
    if existing:
        return existing
    app = Application(job=job, candidate=candidate)
    db.add(app)
    db.flush()
    log_event(db, actor=actor, type="applied", message=note, application=app)
    if auto_screen:
        _move(db, app, Stage.screening, actor="orchestrator")
    return app


def start_screening(db: Session, app: Application) -> None:
    _move(db, app, Stage.screening, actor="orchestrator")
    db.commit()


def retry(db: Session, app: Application) -> None:
    sched = app.scheduling or {}
    if app.stage in AGENT_STAGES:
        kind, what = TaskKind.agent_step, "Agent step"
    elif sched.get("confirmed_slot") and not (sched.get("meeting") or {}).get("booked_at"):
        kind, what = TaskKind.book_meeting, "Interview booking"
    else:
        raise TransitionError("Nothing to retry at this stage")
    if has_open_task(db, app.id):
        raise TransitionError("TalentFlow is already working on this candidate")
    app.error = None
    enqueue(db, kind, application_id=app.id)
    log_event(db, actor="human", type="retry_requested", message=f"{what} re-queued", application=app)
    db.commit()


def decide(db: Session, approval: Approval, *, approve: bool, by: str, comment: str | None) -> Application:
    if approval.status != ApprovalStatus.pending:
        raise TransitionError("This approval has already been decided")
    approval.status = ApprovalStatus.approved if approve else ApprovalStatus.rejected
    approval.decided_by = by
    approval.comment = comment
    approval.decided_at = datetime.now(UTC)
    app = approval.application
    verb = {ApprovalKind.advance: "advanced", ApprovalKind.offer: "approved an offer for"}[approval.kind]
    log_event(db, actor="human", type="approval_decided",
              message=f"{by} {verb if approve else 'rejected'} the candidate" + (f": {comment}" if comment else ""),
              application=app, data={"kind": approval.kind.value, "approved": approve, "by": by})
    if not approve:
        _move(db, app, Stage.rejected, actor="human", reason=comment or "")
    elif approval.kind == ApprovalKind.advance:
        _move(db, app, Stage.outreach, actor="orchestrator")
    else:
        _move(db, app, Stage.offer, actor="orchestrator")
    db.commit()
    return app


def mark_replied(db: Session, app: Application, *, by: str) -> None:
    log_event(db, actor="human", type="candidate_replied", message=f"{by} logged the candidate's reply", application=app)
    _move(db, app, Stage.scheduling, actor="orchestrator")
    db.commit()


def confirm_slot(db: Session, app: Application, slot: str, *, by: str) -> None:
    if app.stage != Stage.interview_scheduled or not app.scheduling:
        raise TransitionError("No interview is being scheduled")
    if slot not in app.scheduling["proposed_slots"]:
        raise TransitionError("Slot is not one of the proposed slots")
    app.scheduling = {**app.scheduling, "confirmed_slot": slot}
    booked = scheduling.format_slot(datetime.fromisoformat(slot))
    log_event(db, actor="human", type="slot_confirmed", message=f"{by} booked the interview for {booked}", application=app)
    db.commit()


def submit_notes(db: Session, app: Application, notes: str, *, by: str) -> None:
    if app.stage != Stage.interview_scheduled:
        raise TransitionError(f"Cannot submit interview notes at stage {app.stage.value}")
    app.interview_notes = notes
    log_event(db, actor="human", type="notes_submitted", message=f"{by} submitted interview notes", application=app)
    _move(db, app, Stage.evaluation, actor="orchestrator")
    db.commit()


def reject(db: Session, app: Application, *, by: str, reason: str | None) -> None:
    for approval in app.approvals:
        if approval.status == ApprovalStatus.pending:
            approval.status = ApprovalStatus.rejected
            approval.decided_by = by
            approval.decided_at = datetime.now(UTC)
    _move(db, app, Stage.rejected, actor="human", reason=reason or f"rejected by {by}")
    db.commit()
