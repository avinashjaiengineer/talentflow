"""Candidate communication: emails, interview booking, and AI phone calls.

Everything that reaches a candidate starts with a person clicking a button (Send, Call,
Book); the work itself runs on the task queue so a slow provider never blocks the UI.
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import orchestrator
from .agents import caller
from .agents.scheduling import format_slot
from .config import get_settings
from .db import SessionLocal
from .events import log_event
from .integrations import IntegrationError
from .integrations.calendar import get_calendar
from .integrations.email import get_email_sender
from .integrations.voice import get_voice
from .models import (
    Application,
    Call,
    CallPurpose,
    CallStatus,
    Message,
    MessageKind,
    MessageStatus,
    Stage,
    TaskKind,
)
from .orchestrator import TransitionError, enqueue

log = logging.getLogger(__name__)

ACTIVE_CALL = {CallStatus.scheduled, CallStatus.queued, CallStatus.dialing, CallStatus.in_progress}
ENDED_CALL = {CallStatus.completed, CallStatus.no_answer, CallStatus.declined, CallStatus.failed, CallStatus.canceled}


def _now() -> datetime:
    return datetime.now(UTC)


def _first_name(name: str | None) -> str:
    return (name or "there").split()[0]


# ---------------------------------------------------------------- email


def draft_message(db: Session, app: Application, kind: MessageKind, *, subject: str, body: str) -> Message:
    msg = Message(application=app, kind=kind, to=app.candidate.email, subject=subject, body=body)
    db.add(msg)
    db.flush()
    return msg


def update_draft(db: Session, msg: Message, *, to: str | None, subject: str | None, body: str | None) -> None:
    if msg.status not in (MessageStatus.draft, MessageStatus.failed):
        raise TransitionError("Only drafts can be edited")
    if to is not None:
        msg.to = to
    if subject is not None:
        msg.subject = subject
    if body is not None:
        msg.body = body
    db.commit()


def request_send(db: Session, msg: Message, *, by: str) -> None:
    if msg.status not in (MessageStatus.draft, MessageStatus.failed):
        raise TransitionError(f"This email is already {msg.status.value}")
    if not msg.to:
        raise TransitionError("The candidate has no email address; add one first")
    msg.status = MessageStatus.queued
    msg.sent_by = by
    msg.error = None
    enqueue(db, TaskKind.send_email, application_id=msg.application_id, payload={"message_id": msg.id})
    log_event(db, actor="human", type="email_requested", message=f"{by} sent the {msg.kind.value} email", application=msg.application)
    db.commit()


def run_send_email(db: Session, message_id: str) -> None:
    msg = db.get(Message, message_id)
    if msg is None or msg.status != MessageStatus.queued:
        return
    sender = get_email_sender()
    try:
        sender.send(to=msg.to, subject=msg.subject, body=msg.body)
    except IntegrationError as e:
        if not e.retryable:
            msg.status = MessageStatus.failed
            msg.error = str(e)
            log_event(db, actor="orchestrator", type="email_failed", message=str(e), application=msg.application)
            db.commit()
            return
        raise
    msg.status = MessageStatus.sent
    msg.provider = sender.name
    msg.sent_at = _now()
    where = "via Outlook" if sender.name == "graph" else "(recorded only: email delivery isn't configured)"
    log_event(db, actor="outreach", type="email_sent", message=f"Emailed {msg.to}: {msg.subject} {where}", application=msg.application)


# ---------------------------------------------------------------- interview booking


def free_slots(job, count: int = 3) -> list[datetime]:
    duration = timedelta(minutes=get_settings().interview_duration_minutes)
    return get_calendar().free_slots(list(job.interviewer_emails or []), count=count, duration=duration)


def run_book_meeting(db: Session, app: Application) -> None:
    sched = app.scheduling or {}
    slot = sched.get("confirmed_slot")
    if not slot or (sched.get("meeting") or {}).get("booked_at"):
        return
    if not app.candidate.email:
        raise IntegrationError("The candidate has no email address, so they can't be invited")
    settings = get_settings()
    start = datetime.fromisoformat(slot)
    duration = timedelta(minutes=settings.interview_duration_minutes)
    job, cand = app.job, app.candidate
    subject = f"Interview: {cand.name} for {job.title} ({settings.company_name})"
    body = (
        f"Interview for the {job.title} role at {settings.company_name}.\n\n"
        f"Candidate: {cand.name}\nInterviewers: {', '.join(job.interviewer_emails) or 'the hiring team'}\n"
        f"Duration: {settings.interview_duration_minutes} minutes."
    )
    calendar = get_calendar()
    attendees = [(cand.email, cand.name)] + [(e, e) for e in job.interviewer_emails]
    meeting = calendar.create_meeting(subject=subject, body=body, start=start, duration=duration, attendees=attendees)
    app.scheduling = {
        **sched,
        "meeting": {"provider": meeting.provider, "event_id": meeting.event_id, "join_url": meeting.join_url, "booked_at": _now().isoformat()},
    }
    invite = Message(application=app, kind=MessageKind.calendar_invite, to=cand.email, subject=subject, body=body,
                     status=MessageStatus.sent, provider=calendar.name, sent_at=_now(), sent_by="calendar")
    db.add(invite)
    detail = "Teams meeting created; Outlook sent the invitations" if calendar.name == "graph" else (
        "recorded only: calendar isn't connected, so send the invite yourself")
    log_event(db, actor="scheduling", type="meeting_booked", message=f"Booked {format_slot(start)}: {detail}", application=app,
              data={"join_url": meeting.join_url})


def confirm_and_book(db: Session, app: Application, slot: str, *, by: str) -> None:
    orchestrator.confirm_slot(db, app, slot, by=by)  # commits
    enqueue(db, TaskKind.book_meeting, application_id=app.id)
    db.commit()


# ---------------------------------------------------------------- calls


def _call_context(app: Application, purpose: CallPurpose) -> dict:
    cand, job = app.candidate, app.job
    ctx: dict = {"candidate_name": cand.name, "job_title": job.title}
    if purpose == CallPurpose.prescreen:
        gaps = [r["requirement"] for r in (app.screening or {}).get("requirements", []) if r.get("status") != "met"]
        focus = (gaps or list(job.requirements))[:2]
        ctx["questions"] = [
            f"Are you currently open to new opportunities, and what interests you about the {job.title} role?",
            *[f"Their experience relevant to this requirement: {req}" for req in focus],
            "What's your notice period, or how soon could you start?",
            "And what salary range are you looking for?",
        ]
    elif purpose == CallPurpose.schedule:
        slots = (app.scheduling or {}).get("proposed_slots") or []
        ctx["slots"] = [{"iso": s, "label": format_slot(datetime.fromisoformat(s))} for s in slots]
    elif purpose == CallPurpose.reminder:
        slot = (app.scheduling or {}).get("confirmed_slot")
        ctx["interview_label"] = format_slot(datetime.fromisoformat(slot)) if slot else None
    return ctx


def request_call(db: Session, app: Application, purpose: CallPurpose, *, by: str) -> Call:
    cand = app.candidate
    voice = get_voice()
    if cand.do_not_call:
        raise TransitionError(f"{cand.name} asked not to be called")
    if voice.name != "simulated" and not cand.phone:
        raise TransitionError("The candidate has no phone number; add one first")
    if db.scalar(select(Call.id).where(Call.application_id == app.id, Call.status.in_(ACTIVE_CALL)).limit(1)):
        raise TransitionError("There's already a call in progress or scheduled for this candidate")
    sched = app.scheduling or {}
    if purpose == CallPurpose.prescreen and app.stage not in (Stage.contacted, Stage.screened):
        raise TransitionError("Pre-screen calls happen after screening, before scheduling")
    if purpose == CallPurpose.schedule and (app.stage != Stage.interview_scheduled or sched.get("confirmed_slot")):
        raise TransitionError("Scheduling calls need proposed slots and no booked interview")
    if purpose == CallPurpose.reminder and not sched.get("confirmed_slot"):
        raise TransitionError("Book the interview before scheduling a reminder")

    context = _call_context(app, purpose)
    greet = caller.greeting(purpose.value, first_name=_first_name(cand.name), job_title=app.job.title)
    call = Call(application=app, purpose=purpose, provider=voice.name, to_number=cand.phone, requested_by=by, context=context,
                transcript=[{"role": "agent", "text": greet, "at": _now().isoformat()}])
    run_after = None
    if purpose == CallPurpose.reminder:
        interview = datetime.fromisoformat(sched["confirmed_slot"])
        when = interview - timedelta(hours=get_settings().reminder_hours_before)
        if when > _now():
            call.status = CallStatus.scheduled
            call.scheduled_for = run_after = when
    db.add(call)
    db.flush()
    task = enqueue(db, TaskKind.place_call, application_id=app.id, payload={"call_id": call.id})
    if run_after:
        task.run_after = run_after
    label = {"prescreen": "pre-screen", "schedule": "scheduling", "reminder": "reminder"}[purpose.value]
    when_text = f" for {format_slot(run_after)}" if run_after else ""
    log_event(db, actor="human", type="call_requested", message=f"{by} requested a {label} call{when_text}", application=app)
    db.commit()
    return call


def cancel_call(db: Session, call: Call, *, by: str) -> None:
    if call.status not in (CallStatus.scheduled, CallStatus.queued):
        raise TransitionError("Only calls that haven't started can be canceled")
    call.status = CallStatus.canceled
    call.ended_at = _now()
    log_event(db, actor="human", type="call_canceled", message=f"{by} canceled the {call.purpose.value} call", application=call.application)
    db.commit()


def run_place_call(db: Session, call_id: str) -> None:
    call = db.get(Call, call_id)
    if call is None or call.status not in (CallStatus.scheduled, CallStatus.queued):
        return
    if call.application.candidate.do_not_call:
        call.status = CallStatus.canceled
        call.error = "Candidate opted out of calls"
        return
    voice = get_voice()
    sid = voice.place_call(call_id=call.id, to_number=call.to_number, relay_token=call.relay_token, greeting=call.transcript[0]["text"])
    call.provider_sid = sid
    if voice.name == "simulated":
        call.status = CallStatus.in_progress
        call.started_at = _now()
        msg = "Simulated call started: open the candidate and reply as them"
    else:
        call.status = CallStatus.dialing
        msg = f"Dialing {call.to_number}"
    log_event(db, actor="caller", type="call_started", message=msg, application=call.application)


def candidate_said(call_id: str, text: str) -> caller.CallTurn:
    """One conversational turn. Opens its own session so it can run from a websocket thread."""
    with SessionLocal() as db:
        call = db.get(Call, call_id)
        if call is None or call.status not in (CallStatus.in_progress, CallStatus.dialing):
            raise TransitionError("This call isn't active")
        if call.status == CallStatus.dialing:
            call.status = CallStatus.in_progress
            call.started_at = call.started_at or _now()
        transcript = [*call.transcript, {"role": "candidate", "text": text.strip(), "at": _now().isoformat()}]
        turns = sum(1 for t in transcript if t["role"] == "candidate")
        if turns >= get_settings().call_max_turns:
            turn = caller.CallTurn(say="I need to wrap up here. The recruiting team will follow up. Thank you, goodbye!",
                                   end_call=True, consent="yes", opt_out=False, wants_human=False)
        else:
            turn = caller.next_turn(call.purpose.value, call.context, transcript)
        transcript.append({"role": "agent", "text": turn.say, "at": _now().isoformat()})
        call.transcript = transcript
        outcome = dict(call.outcome or {})
        if turns == 1 or turn.consent != "unclear":
            outcome.setdefault("consent", turn.consent)
        for key in ("opt_out", "wants_human"):
            if getattr(turn, key):
                outcome[key] = True
        if turn.booked_slot is not None:
            outcome["booked_slot"] = call.context["slots"][turn.booked_slot - 1]["iso"]
        if turn.reminder_status:
            outcome["reminder_status"] = turn.reminder_status
        call.outcome = outcome
        if turn.end_call:
            _finish(db, call)
        db.commit()
        return turn


def _finish(db: Session, call: Call, status: CallStatus | None = None) -> None:
    if call.status in ENDED_CALL:
        return
    outcome = call.outcome or {}
    declined = outcome.get("consent") == "no" or outcome.get("opt_out")
    call.status = status or (CallStatus.declined if declined else CallStatus.completed)
    call.ended_at = _now()
    if outcome.get("opt_out"):
        call.application.candidate.do_not_call = True
        log_event(db, actor="caller", type="opted_out", message="Candidate asked not to be called again; calls are now blocked",
                  application=call.application)
    if call.status in (CallStatus.completed, CallStatus.declined):
        enqueue(db, TaskKind.summarize_call, application_id=call.application_id, payload={"call_id": call.id})
    log_event(db, actor="caller", type="call_ended", message=f"{call.purpose.value.title()} call ended: {call.status.value.replace('_', ' ')}",
              application=call.application)


def end_call(call_id: str, status: CallStatus | None = None) -> None:
    with SessionLocal() as db:
        call = db.get(Call, call_id)
        if call is not None:
            _finish(db, call, status)
            db.commit()


def run_summarize_call(db: Session, call_id: str) -> None:
    call = db.get(Call, call_id)
    if call is None or call.summary is not None:
        return
    app = call.application
    if sum(1 for t in call.transcript if t["role"] == "candidate") > 1:
        call.summary = caller.summarize(call.purpose.value, call.context, call.transcript).model_dump()
        log_event(db, actor="caller", type="call_summarized", message=call.summary["summary"], application=app)
    else:
        call.summary = {"summary": "The call ended before any conversation.", "answers": [], "concerns": []}
    outcome = call.outcome or {}
    if outcome.get("wants_human"):
        log_event(db, actor="caller", type="needs_human", message="Candidate asked to speak with a recruiter", application=app)
    if call.purpose == CallPurpose.schedule and outcome.get("booked_slot"):
        if app.stage == Stage.interview_scheduled and not (app.scheduling or {}).get("confirmed_slot"):
            orchestrator.confirm_slot(db, app, outcome["booked_slot"], by="AI scheduling call")
            enqueue(db, TaskKind.book_meeting, application_id=app.id)
    if call.purpose == CallPurpose.reminder and outcome.get("reminder_status"):
        verb = "confirmed they'll attend" if outcome["reminder_status"] == "confirmed" else "asked to reschedule"
        log_event(db, actor="caller", type="reminder_result", message=f"Candidate {verb}", application=app)


def run_task(db: Session, kind: TaskKind, application_id: str | None, payload: dict) -> None:
    """Dispatch for the communication task kinds (called by the worker)."""
    if kind == TaskKind.send_email:
        run_send_email(db, payload["message_id"])
    elif kind == TaskKind.book_meeting:
        run_book_meeting(db, db.get(Application, application_id))
    elif kind == TaskKind.place_call:
        run_place_call(db, payload["call_id"])
    elif kind == TaskKind.summarize_call:
        run_summarize_call(db, payload["call_id"])
