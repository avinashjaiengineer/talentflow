from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import comms
from ..db import get_db
from ..llm import LLMError
from ..models import Application, Call, CallStatus, Message, User
from ..orchestrator import TransitionError
from ..schemas import CallOut, CallRequest, MessageOut, MessageUpdate, SimulatedReply
from .deps import current_user

router = APIRouter(tags=["communication"])


def _get(db: Session, model, id_: str, what: str):
    obj = db.get(model, id_)
    if obj is None:
        raise HTTPException(404, f"{what} not found")
    return obj


def _guard(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except TransitionError as e:
        raise HTTPException(409, str(e)) from e


@router.patch("/messages/{message_id}", response_model=MessageOut)
def edit_message(message_id: str, body: MessageUpdate, db: Session = Depends(get_db)):
    msg = _get(db, Message, message_id, "Email")
    _guard(comms.update_draft, db, msg, to=body.to, subject=body.subject, body=body.body)
    return msg


@router.post("/messages/{message_id}/send", response_model=MessageOut)
def send_message(message_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    msg = _get(db, Message, message_id, "Email")
    _guard(comms.request_send, db, msg, by=user.name)
    return msg


@router.post("/applications/{application_id}/calls", response_model=CallOut, status_code=201)
def request_call(application_id: str, body: CallRequest, user: User = Depends(current_user), db: Session = Depends(get_db)):
    app = _get(db, Application, application_id, "Application")
    return _guard(comms.request_call, db, app, body.purpose, by=user.name)


@router.post("/calls/{call_id}/cancel", response_model=CallOut)
def cancel_call(call_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    call = _get(db, Call, call_id, "Call")
    _guard(comms.cancel_call, db, call, by=user.name)
    return call


@router.post("/calls/{call_id}/simulate", response_model=CallOut)
def simulate_reply(call_id: str, body: SimulatedReply, db: Session = Depends(get_db)):
    """Play the candidate in a simulated call: send what they'd say, get the agent's reply."""
    call = _get(db, Call, call_id, "Call")
    if call.provider != "simulated":
        raise HTTPException(409, "Only simulated calls can be answered from the app")
    try:
        comms.candidate_said(call.id, body.text)
    except TransitionError as e:
        raise HTTPException(409, str(e)) from e
    except LLMError as e:
        raise HTTPException(502, f"The calling agent failed: {e}") from e
    db.expire_all()
    return db.get(Call, call_id)


@router.post("/calls/{call_id}/hang-up", response_model=CallOut)
def hang_up(call_id: str, db: Session = Depends(get_db)):
    call = _get(db, Call, call_id, "Call")
    if call.provider != "simulated" or call.status != CallStatus.in_progress:
        raise HTTPException(409, "Only an active simulated call can be hung up from the app")
    comms.end_call(call.id)
    db.expire_all()
    return db.get(Call, call_id)
