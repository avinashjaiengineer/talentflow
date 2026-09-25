from datetime import UTC, datetime, timedelta

from app import worker
from app.db import SessionLocal
from app.llm import LLMError
from app.models import AgentTask, TaskStatus
from app.seed import RESUMES


def _one_screening_app(client):
    job = client.post("/api/jobs", json={"title": "Backend", "description": "Python APIs", "requirements": ["Python"]}).json()
    cand = client.post("/api/candidates", json={"resume_text": RESUMES[0]}).json()
    return client.post(f"/api/jobs/{job['id']}/applications", json={"candidate_id": cand["id"]}).json()


def _make_ready(db):
    # Skip the backoff delay so the next drain picks the task up immediately.
    for t in db.query(AgentTask).filter(AgentTask.status == TaskStatus.queued):
        t.run_after = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()


def test_transient_errors_retry_then_succeed(client, monkeypatch):
    app = _one_screening_app(client)
    calls = {"n": 0}
    real = worker.orchestrator.run_agent_step

    def flaky(db, application):
        calls["n"] += 1
        if calls["n"] < 3:
            raise LLMError("Rate limited", retryable=True)
        return real(db, application)

    monkeypatch.setattr(worker.orchestrator, "run_agent_step", flaky)
    worker.drain()
    shown = client.get(f"/api/applications/{app['id']}").json()
    assert shown["stage"] == "screening"
    assert "retrying, attempt 1" in shown["error"]

    with SessionLocal() as db:
        _make_ready(db)
    worker.drain()
    with SessionLocal() as db:
        _make_ready(db)
    worker.drain()

    shown = client.get(f"/api/applications/{app['id']}").json()
    assert shown["stage"] == "screened"
    assert shown["error"] is None
    with SessionLocal() as db:
        task = db.query(AgentTask).filter(AgentTask.application_id == app["id"]).one()
        assert task.status == TaskStatus.succeeded and task.attempts == 3


def test_permanent_errors_fail_fast_and_can_be_retried(client, monkeypatch):
    app = _one_screening_app(client)
    real = worker.orchestrator.run_agent_step
    monkeypatch.setattr(worker.orchestrator, "run_agent_step", lambda db, a: (_ for _ in ()).throw(LLMError("Model not found")))
    worker.drain()
    shown = client.get(f"/api/applications/{app['id']}").json()
    assert shown["error"] == "Model not found"
    assert "agent_failed" in {e["type"] for e in client.get(f"/api/events?application_id={app['id']}").json()}

    monkeypatch.setattr(worker.orchestrator, "run_agent_step", real)
    assert client.post(f"/api/applications/{app['id']}/retry").status_code == 200
    assert client.post(f"/api/applications/{app['id']}/retry").status_code == 409  # already queued
    worker.drain()
    assert client.get(f"/api/applications/{app['id']}").json()["stage"] == "screened"


def test_stale_running_tasks_are_requeued(client):
    app = _one_screening_app(client)
    task_id = worker.claim()  # a worker claims the task... and then "crashes"
    with SessionLocal() as db:
        task = db.get(AgentTask, task_id)
        assert task.status == TaskStatus.running
        task.locked_at = datetime.now(UTC) - timedelta(hours=1)
        db.commit()
    assert worker.requeue_stale() == 1
    worker.drain()
    assert client.get(f"/api/applications/{app['id']}").json()["stage"] == "screened"


def test_task_is_claimed_once(client):
    _one_screening_app(client)
    first = worker.claim()
    assert first is not None
    assert worker.claim() is None
