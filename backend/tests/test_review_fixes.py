"""Regression tests for issues found in the codebase review."""

from datetime import UTC, datetime, timedelta

from app.db import SessionLocal
from app.integrations import IntegrationError
from app.models import AgentTask, Call, CallStatus, TaskStatus
from app.seed import RESUMES
from tests.test_comms import _contacted, _interview_proposed


def _make_due():
    with SessionLocal() as db:
        for t in db.query(AgentTask).filter(AgentTask.status == TaskStatus.queued):
            t.run_after = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()


def test_rejecting_cancels_scheduled_calls(client, work):
    """A rejected candidate must never get the reminder call booked before the rejection."""
    app = _interview_proposed(client, work)
    client.post(f"/api/applications/{app['id']}/confirm-slot", json={"slot": app["scheduling"]["proposed_slots"][2]})
    work()
    call = client.post(f"/api/applications/{app['id']}/calls", json={"purpose": "reminder"}).json()
    assert call["status"] == "scheduled"
    client.post(f"/api/applications/{app['id']}/reject", json={"reason": "role filled"})
    _make_due()
    work()
    call = client.get(f"/api/applications/{app['id']}").json()["calls"][0]
    assert call["status"] == "canceled"


def test_prescreen_calls_wait_for_the_advance_decision(client, work):
    """Calling a candidate is contact; it must not happen before a recruiter advances them."""
    job = client.post("/api/jobs", json={"title": "Backend", "description": "Python", "requirements": ["Python"]}).json()
    cand = client.post("/api/candidates", json={"resume_text": RESUMES[0]}).json()
    app = client.post(f"/api/jobs/{job['id']}/applications", json={"candidate_id": cand["id"]}).json()
    work()
    assert client.get(f"/api/applications/{app['id']}").json()["stage"] == "screened"
    assert client.post(f"/api/applications/{app['id']}/calls", json={"purpose": "prescreen"}).status_code == 409


def test_a_call_that_cannot_be_placed_does_not_block_future_calls(client, work, monkeypatch):
    app = _contacted(client, work)

    class BrokenVoice:
        name = "simulated"

        def place_call(self, **_):
            raise IntegrationError("Twilio refused the call: invalid number")

    monkeypatch.setattr("app.comms.get_voice", lambda: BrokenVoice())
    client.post(f"/api/applications/{app['id']}/calls", json={"purpose": "prescreen"})
    work()
    shown = client.get(f"/api/applications/{app['id']}").json()
    assert shown["calls"][0]["status"] == "failed"
    assert "invalid number" in shown["calls"][0]["error"]
    assert shown["error"] is None  # shown on the call card, not as a stuck pipeline error
    monkeypatch.undo()
    assert client.post(f"/api/applications/{app['id']}/calls", json={"purpose": "prescreen"}).status_code == 201


def test_failed_booking_can_be_retried(client, work, monkeypatch):
    app = _interview_proposed(client, work)

    class DownCalendar:
        name = "graph"

        def create_meeting(self, **_):
            raise IntegrationError("Microsoft Graph error 403: Access denied")

        def free_slots(self, *a, **k):
            return []

    monkeypatch.setattr("app.comms.get_calendar", lambda: DownCalendar())
    client.post(f"/api/applications/{app['id']}/confirm-slot", json={"slot": app["scheduling"]["proposed_slots"][0]})
    work()
    shown = client.get(f"/api/applications/{app['id']}").json()
    assert "Access denied" in shown["error"]
    monkeypatch.undo()
    assert client.post(f"/api/applications/{app['id']}/retry").status_code == 200
    work()
    shown = client.get(f"/api/applications/{app['id']}").json()
    assert shown["error"] is None and shown["scheduling"]["meeting"]["booked_at"]


def test_failed_summary_is_recorded_instead_of_polling_forever(client, work, monkeypatch):
    app = _contacted(client, work)
    call_id = client.post(f"/api/applications/{app['id']}/calls", json={"purpose": "prescreen"}).json()["id"]
    work()
    client.post(f"/api/calls/{call_id}/simulate", json={"text": "Yes, sure."})
    client.post(f"/api/calls/{call_id}/simulate", json={"text": "I'm open to it."})
    client.post(f"/api/calls/{call_id}/hang-up")

    def boom(*_):
        raise ValueError("summary model returned garbage")

    monkeypatch.setattr("app.agents.caller.summarize", boom)
    work()
    with SessionLocal() as db:
        call = db.get(Call, call_id)
        assert call.status == CallStatus.completed
        assert call.summary and "couldn't be summarized" in call.summary["summary"]


def test_two_candidates_cannot_book_the_same_interview_slot(client, work):
    job = client.post("/api/jobs", json={"title": "Backend", "description": "Python", "requirements": ["Python"],
                                         "interviewer_emails": ["lead@example.com"]}).json()
    apps = []
    for text in RESUMES[:2]:
        cand = client.post("/api/candidates", json={"resume_text": text}).json()
        apps.append(client.post(f"/api/jobs/{job['id']}/applications", json={"candidate_id": cand["id"]}).json())
    work()
    for a in apps:
        approval = client.get(f"/api/applications/{a['id']}").json()["pending_approval"]
        client.post(f"/api/approvals/{approval['id']}/decide", json={"approve": True})
        work()
        client.post(f"/api/applications/{a['id']}/replied")
        work()
    first, second = (client.get(f"/api/applications/{a['id']}").json() for a in apps)
    slot = first["scheduling"]["proposed_slots"][0]
    assert client.post(f"/api/applications/{first['id']}/confirm-slot", json={"slot": slot}).status_code == 200
    # the second candidate is no longer offered that time...
    third = client.post("/api/candidates", json={"resume_text": RESUMES[5]}).json()
    late = client.post(f"/api/jobs/{job['id']}/applications", json={"candidate_id": third["id"]}).json()
    work()
    approval = client.get(f"/api/applications/{late['id']}").json()["pending_approval"]
    client.post(f"/api/approvals/{approval['id']}/decide", json={"approve": True})
    work()
    client.post(f"/api/applications/{late['id']}/replied")
    work()
    assert slot not in client.get(f"/api/applications/{late['id']}").json()["scheduling"]["proposed_slots"]
    # ...and can't be booked into it even if it was offered earlier
    if slot in second["scheduling"]["proposed_slots"]:
        r = client.post(f"/api/applications/{second['id']}/confirm-slot", json={"slot": slot})
        assert r.status_code == 409 and "already booked" in r.json()["detail"]


def test_public_health_check_does_not_leak_configuration(anon):
    body = anon.get("/api/health").json()
    assert body["status"] == "ok"
    assert "models" not in body and "integrations" not in body and "llm" not in body


def test_system_details_require_sign_in(client):
    body = client.get("/api/system").json()
    assert body["llm"].startswith("mock") and body["integrations"]["voice"] == "simulated"
    client.post("/api/auth/logout")
    assert client.get("/api/system").status_code == 401


def test_list_endpoints_stay_light(client, work):
    """Board and list views don't ship every email body and call transcript."""
    app = _contacted(client, work)
    listed = client.get(f"/api/jobs/{app['job_id']}/applications").json()[0]
    assert listed["messages"] == [] and listed["calls"] == []
    detail = client.get(f"/api/applications/{app['id']}").json()
    assert detail["messages"]


def test_invalid_timezone_is_rejected_at_startup():
    import pytest
    from pydantic import ValidationError

    from app.config import Settings

    with pytest.raises(ValidationError, match="TIMEZONE"):
        Settings(timezone="Mars/Olympus_Mons")


def test_simultaneous_decisions_cannot_both_win(client, work, monkeypatch):
    """Advance and Reject clicked at the same moment: exactly one wins (Postgres row locks)."""
    import threading
    import time

    import pytest
    from fastapi.testclient import TestClient

    from app import orchestrator
    from app.db import engine
    from app.main import app as asgi_app

    if engine.dialect.name != "postgresql":
        pytest.skip("row locks need Postgres")

    job = client.post("/api/jobs", json={"title": "Race", "description": "Python", "requirements": ["Python"]}).json()
    cand = client.post("/api/candidates", json={"resume_text": RESUMES[0]}).json()
    app = client.post(f"/api/jobs/{job['id']}/applications", json={"candidate_id": cand["id"]}).json()
    work()
    approval = client.get(f"/api/applications/{app['id']}").json()["pending_approval"]

    real_log = orchestrator.log_event

    def slow_log(db, **kw):  # widen the race window inside the decision
        if kw.get("type") == "approval_decided":
            time.sleep(0.5)
        return real_log(db, **kw)

    monkeypatch.setattr(orchestrator, "log_event", slow_log)
    results = {}

    clients = {}
    for v in (True, False):  # sign in up front; no lifespan (the app is already running)
        clients[v] = TestClient(asgi_app)
        clients[v].post("/api/auth/login", json={"email": "admin@example.com", "password": "admin-password-123"})

    def decide(approve):
        try:
            results[approve] = clients[approve].post(f"/api/approvals/{approval['id']}/decide", json={"approve": approve}).status_code
        except Exception as e:  # surface thread failures in the assertion below
            results[approve] = repr(e)

    threads = [threading.Thread(target=decide, args=(v,)) for v in (True, False)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(map(str, results.values())) == ["200", "409"], results
    stage = client.get(f"/api/applications/{app['id']}").json()["stage"]
    assert stage == ("outreach" if results[True] == 200 else "rejected") or (stage == "contacted" and results[True] == 200)


def test_jobs_can_be_edited(client):
    job = client.post("/api/jobs", json={"title": "Backend", "description": "Python", "requirements": ["Python"]}).json()
    r = client.patch(f"/api/jobs/{job['id']}", json={"title": "Senior Backend", "requirements": ["Python", "Go"],
                                                      "interviewer_emails": ["lead@example.com"]})
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "Senior Backend" and body["requirements"] == ["Python", "Go"]
    assert body["interviewer_emails"] == ["lead@example.com"]
    assert client.patch(f"/api/jobs/{job['id']}", json={"interviewer_emails": ["not-an-email"]}).status_code == 422


def test_admin_can_reset_a_users_password(client):
    rita = client.post("/api/users", json={"email": "rita@example.com", "name": "Rita", "password": "first-password-1"}).json()
    old = client.post("/api/auth/login", json={"email": "rita@example.com", "password": "first-password-1"}).json()["token"]
    client.cookies.clear()
    client.post("/api/auth/login", json={"email": "admin@example.com", "password": "admin-password-123"})
    assert client.patch(f"/api/users/{rita['id']}", json={"password": "reset-password-2"}).status_code == 200
    client.cookies.clear()
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {old}"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "rita@example.com", "password": "reset-password-2"}).status_code == 200
