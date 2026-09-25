import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.config import get_settings
from app.db import SessionLocal
from app.integrations.calendar import GraphCalendar
from app.integrations.email import GraphEmail
from app.integrations.graph import GraphClient
from app.models import AgentTask, Call, CallStatus, TaskStatus
from app.seed import RESUMES

JOB = {
    "title": "Senior Backend Engineer",
    "description": "Build Python APIs on PostgreSQL and Kubernetes.",
    "requirements": ["Python", "PostgreSQL", "Kubernetes"],
    "interviewer_emails": ["lead@example.com"],
}


def _contacted(client, work):
    """One candidate advanced past screening, outreach drafted."""
    job = client.post("/api/jobs", json=JOB).json()
    cand = client.post("/api/candidates", json={"resume_text": RESUMES[0]}).json()
    app = client.post(f"/api/jobs/{job['id']}/applications", json={"candidate_id": cand["id"]}).json()
    work()
    approval = client.get(f"/api/applications/{app['id']}").json()["pending_approval"]
    client.post(f"/api/approvals/{approval['id']}/decide", json={"approve": True})
    work()
    return client.get(f"/api/applications/{app['id']}").json()


def _interview_proposed(client, work):
    app = _contacted(client, work)
    client.post(f"/api/applications/{app['id']}/replied")
    work()
    return client.get(f"/api/applications/{app['id']}").json()


def _start_call(client, work, app_id, purpose):
    r = client.post(f"/api/applications/{app_id}/calls", json={"purpose": purpose})
    assert r.status_code == 201, r.text
    call = r.json()
    assert call["transcript"][0]["role"] == "agent" and "AI assistant" in call["transcript"][0]["text"]
    work()  # places the (simulated) call
    return call["id"]


def _say(client, call_id, text):
    r = client.post(f"/api/calls/{call_id}/simulate", json={"text": text})
    assert r.status_code == 200, r.text
    return r.json()


def test_prescreen_call_end_to_end(client, work):
    app = _contacted(client, work)
    call_id = _start_call(client, work, app["id"], "prescreen")
    call = _say(client, call_id, "Yes, now is fine.")
    assert call["status"] == "in_progress" and call["outcome"]["consent"] == "yes"
    for answer in ["Yes, I'm open and the scale sounds exciting.", "I led our Kubernetes migration.",
                   "Lots of PostgreSQL schema design.", "Four weeks notice.", "Around 180k."]:
        call = _say(client, call_id, answer)
        if call["status"] != "in_progress":
            break
    assert call["status"] == "completed"
    work()  # summarize
    call = next(c for c in client.get(f"/api/applications/{app['id']}").json()["calls"] if c["id"] == call_id)
    assert call["summary"]["answers"]
    assert any("Four weeks" in a["answer"] for a in call["summary"]["answers"])
    types = {e["type"] for e in client.get(f"/api/events?application_id={app['id']}").json()}
    assert {"call_requested", "call_started", "call_ended", "call_summarized"} <= types


def test_no_consent_ends_the_call(client, work):
    app = _contacted(client, work)
    call_id = _start_call(client, work, app["id"], "prescreen")
    call = _say(client, call_id, "No, I'm busy right now.")
    assert call["status"] == "declined" and call["outcome"]["consent"] == "no"
    assert _say_status(client, call_id) == 409  # can't keep talking on an ended call


def _say_status(client, call_id):
    return client.post(f"/api/calls/{call_id}/simulate", json={"text": "hello?"}).status_code


def test_opt_out_blocks_future_calls(client, work):
    app = _contacted(client, work)
    call_id = _start_call(client, work, app["id"], "prescreen")
    call = _say(client, call_id, "Please stop calling me.")
    assert call["status"] == "declined" and call["outcome"]["opt_out"] is True
    cand = client.get(f"/api/candidates/{app['candidate']['id']}").json()
    assert cand["do_not_call"] is True
    r = client.post(f"/api/applications/{app['id']}/calls", json={"purpose": "prescreen"})
    assert r.status_code == 409 and "asked not to be called" in r.json()["detail"]


def test_scheduling_call_books_the_chosen_slot(client, work):
    app = _interview_proposed(client, work)
    slots = app["scheduling"]["proposed_slots"]
    call_id = _start_call(client, work, app["id"], "schedule")
    _say(client, call_id, "Sure.")
    call = _say(client, call_id, "The second one works for me.")
    assert call["status"] == "completed" and call["outcome"]["booked_slot"] == slots[1]
    work()  # summarize -> confirm slot -> book meeting
    work()
    app = client.get(f"/api/applications/{app['id']}").json()
    assert app["scheduling"]["confirmed_slot"] == slots[1]
    assert app["scheduling"]["meeting"]["booked_at"]
    assert any(m["kind"] == "calendar_invite" for m in app["messages"])


def test_reminder_call_waits_until_the_day_before(client, work):
    app = _interview_proposed(client, work)
    slot = app["scheduling"]["proposed_slots"][2]  # at least two business days out
    client.post(f"/api/applications/{app['id']}/confirm-slot", json={"slot": slot})
    work()
    r = client.post(f"/api/applications/{app['id']}/calls", json={"purpose": "reminder"})
    call = r.json()
    assert call["status"] == "scheduled"
    expected = datetime.fromisoformat(slot) - timedelta(hours=get_settings().reminder_hours_before)
    assert abs(datetime.fromisoformat(call["scheduled_for"]) - expected) < timedelta(seconds=1)
    work()
    assert client.get(f"/api/applications/{app['id']}").json()["calls"][0]["status"] == "scheduled"  # not yet

    with SessionLocal() as db:  # time passes
        task = db.query(AgentTask).filter(AgentTask.status == TaskStatus.queued).one()
        task.run_after = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    work()
    _say(client, call["id"], "Yes, go ahead.")
    call = _say(client, call["id"], "Yes, I'll be there.")
    assert call["status"] == "completed" and call["outcome"]["reminder_status"] == "confirmed"


def test_call_rules(client, work):
    app = _contacted(client, work)
    # scheduling and reminder calls don't fit this stage
    assert client.post(f"/api/applications/{app['id']}/calls", json={"purpose": "schedule"}).status_code == 409
    assert client.post(f"/api/applications/{app['id']}/calls", json={"purpose": "reminder"}).status_code == 409
    # one active call at a time; queued calls can be canceled
    call = client.post(f"/api/applications/{app['id']}/calls", json={"purpose": "prescreen"}).json()
    assert client.post(f"/api/applications/{app['id']}/calls", json={"purpose": "prescreen"}).status_code == 409
    assert client.post(f"/api/calls/{call['id']}/cancel").json()["status"] == "canceled"


def test_hang_up_simulated_call(client, work):
    app = _contacted(client, work)
    call_id = _start_call(client, work, app["id"], "prescreen")
    _say(client, call_id, "Yes.")
    call = client.post(f"/api/calls/{call_id}/hang-up").json()
    assert call["status"] == "completed" and call["ended_at"]


def test_candidate_contact_details_can_be_edited(client):
    cand = client.post("/api/candidates", json={"resume_text": RESUMES[1]}).json()
    r = client.patch(f"/api/candidates/{cand['id']}", json={"phone": "+14155550100", "do_not_call": True})
    assert r.json()["phone"] == "+14155550100" and r.json()["do_not_call"] is True
    assert client.patch(f"/api/candidates/{cand['id']}", json={"email": "not-an-email"}).status_code == 422


# ---------------------------------------------------------------- Microsoft Graph


def _graph(handler, monkeypatch):
    s = get_settings()
    for key, value in {"ms_tenant_id": "t", "ms_client_id": "c", "ms_client_secret": "s", "ms_sender": "hr@acme.test"}.items():
        monkeypatch.setattr(s, key, value)

    def route(request: httpx.Request):
        if request.url.host == "login.microsoftonline.com":
            assert b"client_credentials" in request.content
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        assert request.headers["authorization"] == "Bearer tok"
        return handler(request)

    return GraphClient(s, transport=httpx.MockTransport(route))


def test_graph_email_sends_from_the_shared_mailbox(monkeypatch):
    seen = {}

    def handler(request):
        seen["path"], seen["body"] = request.url.path, json.loads(request.content)
        return httpx.Response(202)

    GraphEmail(_graph(handler, monkeypatch)).send(to="cand@example.com", subject="Hi", body="Hello")
    assert seen["path"] == "/v1.0/users/hr@acme.test/sendMail"
    assert seen["body"]["message"]["toRecipients"][0]["emailAddress"]["address"] == "cand@example.com"


def test_graph_errors_are_classified(monkeypatch):
    from app.integrations import IntegrationError

    email = GraphEmail(_graph(lambda r: httpx.Response(429, json={"error": {"message": "slow down"}}), monkeypatch))
    with pytest.raises(IntegrationError) as e:
        email.send(to="a@b.co", subject="x", body="y")
    assert e.value.retryable and "slow down" in str(e.value)
    email = GraphEmail(_graph(lambda r: httpx.Response(403, json={"error": {"message": "denied"}}), monkeypatch))
    with pytest.raises(IntegrationError) as e:
        email.send(to="a@b.co", subject="x", body="y")
    assert not e.value.retryable


def test_graph_calendar_skips_busy_times_and_creates_teams_meeting(monkeypatch):
    monday = datetime(2026, 10, 5, 6, 0, tzinfo=UTC)  # the Friday before is "now"
    now = monday - timedelta(days=3)
    booked = {}

    def handler(request):
        body = json.loads(request.content)
        if request.url.path.endswith("/getSchedule"):
            assert body["schedules"] == ["lead@example.com"]
            busy_all_monday = {"status": "busy", "start": {"dateTime": "2026-10-05T00:00:00.0000000"},
                               "end": {"dateTime": "2026-10-06T00:00:00.0000000"}}
            return httpx.Response(200, json={"value": [{"scheduleItems": [busy_all_monday]}]})
        booked.update(body)
        return httpx.Response(201, json={"id": "evt1", "onlineMeeting": {"joinUrl": "https://teams.microsoft.com/l/meetup-join/x"}})

    cal = GraphCalendar(_graph(handler, monkeypatch))
    slots = cal.free_slots(["lead@example.com"], count=3, duration=timedelta(minutes=45), now=now)
    assert len(slots) == 3 and all(s.date() != monday.date() for s in slots)
    meeting = cal.create_meeting(subject="Interview", body="b", start=slots[0], duration=timedelta(minutes=45),
                                 attendees=[("cand@example.com", "Cand")])
    assert meeting.join_url.startswith("https://teams.microsoft.com/")
    assert booked["isOnlineMeeting"] is True and booked["onlineMeetingProvider"] == "teamsForBusiness"


# ---------------------------------------------------------------- Twilio


@pytest.fixture()
def twilio_settings(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "twilio_auth_token", "secret-token")
    monkeypatch.setattr(s, "twilio_account_sid", "AC" + "0" * 32)
    monkeypatch.setattr(s, "twilio_from_number", "+15005550006")
    monkeypatch.setattr(s, "public_base_url", "https://talent.example.com")
    return s


def _twilio_call(app_id: str) -> Call:
    with SessionLocal() as db:
        call = Call(application_id=app_id, purpose="prescreen", provider="twilio", status=CallStatus.dialing,
                    to_number="+15005550006", context={"candidate_name": "Priya", "job_title": "Backend",
                                                       "questions": ["What's your notice period?"]},
                    transcript=[{"role": "agent", "text": "Hi, this is an AI assistant. Is now a good time?", "at": ""}])
        db.add(call)
        db.commit()
        return call


def test_twiml_connects_to_the_relay(twilio_settings):
    from app.integrations.voice import TwilioVoice

    xml = TwilioVoice().twiml(call_id="abc", relay_token="tok", greeting="Hi there")
    assert 'url="wss://talent.example.com/api/voice/relay/abc?token=tok"' in xml
    assert 'welcomeGreeting="Hi there"' in xml and "<ConversationRelay" in xml


def test_status_webhook_requires_twilio_signature(client, work, twilio_settings):
    from twilio.request_validator import RequestValidator

    app = _contacted(client, work)
    call = _twilio_call(app["id"])
    url = f"https://talent.example.com/api/voice/status/{call.id}"
    params = {"CallStatus": "no-answer", "CallSid": "CA123"}
    assert client.post(f"/api/voice/status/{call.id}", data=params, headers={"X-Twilio-Signature": "forged"}).status_code == 403
    signature = RequestValidator("secret-token").compute_signature(url, params)
    assert client.post(f"/api/voice/status/{call.id}", data=params, headers={"X-Twilio-Signature": signature}).status_code == 204
    with SessionLocal() as db:
        assert db.get(Call, call.id).status == CallStatus.no_answer


def test_relay_websocket_runs_the_conversation(client, work, twilio_settings):
    from starlette.websockets import WebSocketDisconnect

    app = _contacted(client, work)
    call = _twilio_call(app["id"])
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/api/voice/relay/{call.id}?token=wrong") as ws:
            ws.receive_json()
    with client.websocket_connect(f"/api/voice/relay/{call.id}?token={call.relay_token}") as ws:
        ws.send_json({"type": "setup", "callSid": "CA1", "customParameters": {"call_id": call.id}})
        ws.send_json({"type": "prompt", "voicePrompt": "Yes, sure.", "last": True})
        reply = ws.receive_json()
        assert reply["type"] == "text" and "notice period" in reply["token"]
    with SessionLocal() as db:
        saved = db.get(Call, call.id)
        assert [t["role"] for t in saved.transcript] == ["agent", "candidate", "agent"]
        assert saved.status == CallStatus.completed  # hanging up ends the call
