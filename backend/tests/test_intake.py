import base64

import httpx
import pytest

from app import intake
from app.config import get_settings
from app.db import SessionLocal
from app.integrations.graph import GraphClient
from app.integrations.mailbox import GraphMailbox
from app.models import AgentTask, IntakeItem, TaskKind
from app.seed import RESUMES

JOB = {
    "title": "Senior Backend Engineer",
    "description": "Build Python APIs on PostgreSQL and Kubernetes.",
    "requirements": ["Python", "PostgreSQL", "Kubernetes"],
}
TOKEN = "portal-secret-token"


# ---------------------------------------------------------------- job writer


def test_job_writer_drafts_a_posting_from_a_few_words(client):
    r = client.post("/api/jobs/draft", json={"brief": "senior backend engineer, 5 yrs Python and PostgreSQL, fintech"})
    assert r.status_code == 200
    draft = r.json()
    assert draft["title"] == "Senior Backend Engineer"
    assert "5+ years of relevant experience" in draft["requirements"]
    assert {"Python", "PostgreSQL"} <= set(draft["requirements"])
    assert draft["description"]
    # Nothing is saved until the recruiter creates the job.
    assert client.get("/api/jobs").json() == []


def test_job_writer_needs_a_brief_and_a_session(anon, client):
    assert client.post("/api/jobs/draft", json={"brief": "x"}).status_code == 422
    client.post("/api/auth/logout")
    assert client.post("/api/jobs/draft", json={"brief": "data analyst"}).status_code == 401


# ---------------------------------------------------------------- webhook


@pytest.fixture()
def webhook_on(monkeypatch):
    monkeypatch.setattr(get_settings(), "intake_webhook_token", TOKEN)


def _push(client, body, token=TOKEN):
    return client.post("/api/intake/webhook", json=body, headers={"X-Intake-Token": token})


def test_webhook_is_off_until_a_token_is_set(anon):
    assert _push(anon, {"resume_text": RESUMES[0]}).status_code == 404


def test_webhook_rejects_a_wrong_token(anon, webhook_on):
    assert _push(anon, {"resume_text": RESUMES[0]}, token="nope").status_code == 401
    assert _push(anon, {"portal": "Naukri"}).status_code == 422  # no resume


def test_webhook_imports_screens_and_dedupes(client, work, webhook_on):
    job = client.post("/api/jobs", json=JOB).json()
    body = {"external_id": "naukri-123", "portal": "Naukri", "job_id": job["id"], "resume_text": RESUMES[0]}

    r = _push(client, body)
    assert r.status_code == 201
    item = r.json()
    assert item["status"] == "imported"
    assert item["portal"] == "Naukri"
    assert item["job_title"] == JOB["title"]
    assert item["candidate_name"] == "Priya Raman"

    work()  # the applicant is screened like any sourced candidate
    app = client.get(f"/api/applications/{item['application_id']}").json()
    assert app["stage"] == "screened"
    assert app["pending_approval"] is not None

    # The portal retrying the same push changes nothing.
    assert _push(client, body).json()["id"] == item["id"]
    # The same person applying again through another portal is matched by email.
    again = _push(client, {**body, "external_id": "linkedin-9", "portal": "LinkedIn"}).json()
    assert again["status"] == "duplicate"
    assert again["candidate_id"] == item["candidate_id"]
    assert len(client.get("/api/candidates").json()) == 1


def test_webhook_accepts_a_file_and_matches_the_job_by_title(client, webhook_on):
    client.post("/api/jobs", json=JOB)
    resume = base64.b64encode(RESUMES[1].encode()).decode()
    item = _push(client, {"job_title": "senior backend engineer", "resume_base64": resume, "filename": "cv.txt"}).json()
    assert item["status"] == "imported"
    assert item["job_title"] == JOB["title"]

    stray = _push(client, {"job_title": "Chef", "resume_text": RESUMES[2]}).json()
    assert stray["status"] == "imported"
    assert stray["job_id"] is None  # waits in the talent pool for a recruiter
    assert [i["id"] for i in client.get("/api/intake/items").json()] == [stray["id"], item["id"]]


# ---------------------------------------------------------------- mailbox


def _mailbox(monkeypatch, messages):
    s = get_settings()
    for key, value in {"ms_tenant_id": "t", "ms_client_id": "c", "ms_client_secret": "s", "ms_sender": "hr@acme.test",
                       "intake_provider": "graph"}.items():
        monkeypatch.setattr(s, key, value)
    files = {m["id"]: m.pop("files") for m in messages}

    def route(request: httpx.Request):
        if request.url.host == "login.microsoftonline.com":
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        path = request.url.path
        if path.endswith("/mailFolders/inbox/messages"):
            assert "hasAttachments eq true" in request.url.params["$filter"]
            return httpx.Response(200, json={"value": messages})
        parts = path.split("/")
        msg_id = parts[parts.index("messages") + 1]
        if path.endswith("/attachments"):
            return httpx.Response(200, json={"value": [
                {"@odata.type": "#microsoft.graph.fileAttachment", "id": name, "name": name, "size": len(data)}
                for name, data in files[msg_id].items()
            ]})
        name = parts[-1]
        return httpx.Response(200, json={"contentBytes": base64.b64encode(files[msg_id][name].encode()).decode()})

    return GraphMailbox(GraphClient(s, transport=httpx.MockTransport(route)), s)


def _email(i, subject, sender, files):
    return {"id": f"m{i}", "internetMessageId": f"<{i}@mail>", "subject": subject, "receivedDateTime": "2026-09-26T08:00:00Z",
            "from": {"emailAddress": {"address": sender}}, "body": {"content": "Please find the resume attached."},
            "files": files}


def test_mailbox_intake_imports_applications_once(client, work, monkeypatch):
    job = client.post("/api/jobs", json=JOB).json()
    mailbox = _mailbox(monkeypatch, [
        _email(1, "Naukri: New application for Senior Backend Engineer", "jobs@naukri.com", {"Priya_Resume.txt": RESUMES[0]}),
        _email(2, "Job alert: 20 new jobs for you", "alerts@indeed.com", {"brochure.pdf": "not a resume"}),
        _email(3, "Application for Product Designer", "someone@gmail.com", {"cv.txt": RESUMES[1]}),
    ])

    with SessionLocal() as db:
        result = intake.poll_mailbox(db, mailbox)
    assert result == {"count": 3, "imported": 2, "skipped": 1}

    items = {i["subject"]: i for i in client.get("/api/intake/items").json()}
    naukri = items["Naukri: New application for Senior Backend Engineer"]
    assert naukri["portal"] == "Naukri"
    assert naukri["job_id"] == job["id"]
    assert items["Job alert: 20 new jobs for you"]["status"] == "skipped"
    assert items["Application for Product Designer"]["job_id"] is None

    work()
    assert client.get(f"/api/applications/{naukri['application_id']}").json()["stage"] == "screened"

    with SessionLocal() as db:  # the same emails on the next check are ignored
        assert intake.poll_mailbox(db, mailbox) == {"count": 0}
        assert db.query(IntakeItem).count() == 3


def test_check_now_needs_mailbox_intake(client, monkeypatch):
    assert client.post("/api/intake/check").status_code == 409
    assert client.get("/api/intake/status").json()["mailbox_enabled"] is False

    monkeypatch.setattr(get_settings(), "intake_provider", "graph")
    monkeypatch.setattr(get_settings(), "ms_sender", "hr@acme.test")
    first = client.post("/api/intake/check").json()
    assert first["kind"] == "intake"
    assert client.post("/api/intake/check").json()["id"] == first["id"]  # already queued
    status = client.get("/api/intake/status").json()
    assert status["checking"] is True and status["mailbox"] == "hr@acme.test"


def test_worker_schedules_mailbox_checks(anon, monkeypatch):
    s = get_settings()
    with SessionLocal() as db:
        assert intake.schedule_if_due(db) is None  # intake off

        monkeypatch.setattr(s, "intake_provider", "graph")
        monkeypatch.setattr(s, "intake_poll_minutes", 15)
        assert intake.schedule_if_due(db) is not None
        assert intake.schedule_if_due(db) is None  # one is already queued
        assert db.query(AgentTask).filter(AgentTask.kind == TaskKind.intake).count() == 1
