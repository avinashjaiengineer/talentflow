"""Twilio webhooks and the ConversationRelay websocket. Public endpoints: HTTP callbacks are
authenticated with Twilio's request signature, the websocket with a per-call secret token."""

import asyncio
import hmac
import json
import logging

from fastapi import APIRouter, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool

from .. import comms
from ..config import get_settings
from ..db import SessionLocal
from ..integrations.voice import validate_twilio_signature
from ..models import Call, CallStatus

log = logging.getLogger("talentflow.voice")
router = APIRouter(prefix="/voice", tags=["voice"])

# Twilio call status -> our status, for calls that ended without a conversation
NOT_CONNECTED = {"busy": CallStatus.no_answer, "no-answer": CallStatus.no_answer, "failed": CallStatus.failed, "canceled": CallStatus.failed}


async def _verified_form(request: Request) -> dict:
    form = dict(await request.form())
    base = (get_settings().public_base_url or "").rstrip("/")
    url = base + request.url.path + (f"?{request.url.query}" if request.url.query else "")
    if not validate_twilio_signature(url, form, request.headers.get("x-twilio-signature", "")):
        raise HTTPException(403, "Invalid Twilio signature")
    return form


@router.post("/status/{call_id}", status_code=204)
async def call_status(call_id: str, request: Request):
    form = await _verified_form(request)
    status = form.get("CallStatus", "")
    with SessionLocal() as db:
        call = db.get(Call, call_id)
        if call is None:
            return Response(status_code=204)
        if status in NOT_CONNECTED and call.status in (CallStatus.dialing, CallStatus.queued):
            call.status = NOT_CONNECTED[status]
            call.ended_at = comms._now()
            comms.log_event(db, actor="caller", type="call_not_connected", message=f"Call not connected: {status}", application=call.application)
        elif status == "in-progress" and call.status == CallStatus.dialing:
            call.status = CallStatus.in_progress
            call.started_at = comms._now()
        db.commit()
    if status == "completed":
        await run_in_threadpool(comms.end_call, call_id)
    return Response(status_code=204)


@router.post("/session-end/{call_id}")
async def session_end(call_id: str, request: Request):
    await _verified_form(request)
    await run_in_threadpool(comms.end_call, call_id)
    # Tell Twilio to hang up once the conversation session is over.
    return Response('<?xml version="1.0" encoding="UTF-8"?><Response><Hangup/></Response>', media_type="application/xml")


@router.websocket("/relay/{call_id}")
async def relay(websocket: WebSocket, call_id: str, token: str = ""):
    with SessionLocal() as db:
        call = db.get(Call, call_id)
        valid = (
            call is not None
            and call.provider == "twilio"
            and call.status in (CallStatus.dialing, CallStatus.in_progress)
            and hmac.compare_digest(call.relay_token, token)
        )
    if not valid:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    try:
        while True:
            message = await websocket.receive_json()
            kind = message.get("type")
            if kind == "setup":
                log.info("call %s connected (%s)", call_id, message.get("callSid"))
            elif kind == "prompt" and message.get("last", True):
                text = (message.get("voicePrompt") or "").strip()
                if not text:
                    continue
                turn = await run_in_threadpool(comms.candidate_said, call_id, text)
                await websocket.send_json({"type": "text", "token": turn.say, "last": True})
                if turn.end_call:
                    # Let the goodbye finish playing before ending the session.
                    await asyncio.sleep(min(10, 1.5 + len(turn.say) / 14))
                    await websocket.send_json({"type": "end", "handoffData": json.dumps({"reason": "conversation complete"})})
                    break
            elif kind == "error":
                log.warning("call %s relay error: %s", call_id, message.get("description"))
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("call %s relay crashed", call_id)
    finally:
        await run_in_threadpool(comms.end_call, call_id)
