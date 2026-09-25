from app.seed import RESUMES

BACKEND_JOB = {
    "title": "Senior Backend Engineer",
    "description": "Build Python APIs on PostgreSQL and Kubernetes.",
    "requirements": ["Python", "PostgreSQL", "Kubernetes", "REST API design"],
}


def _setup(client):
    job = client.post("/api/jobs", json=BACKEND_JOB).json()
    for text in RESUMES:
        assert client.post("/api/candidates", json={"resume_text": text}).status_code == 201
    return job


def _source(client, work, job_id, limit, auto_screen=True):
    r = client.post(f"/api/jobs/{job_id}/source", json={"limit": limit, "auto_screen": auto_screen})
    assert r.status_code == 202
    task = r.json()
    assert task["status"] == "queued"
    work()
    task = client.get(f"/api/tasks/{task['id']}").json()
    assert task["status"] == "succeeded"
    return [client.get(f"/api/applications/{i}").json() for i in task["result"]["application_ids"]]


def test_health_is_public(anon):
    body = anon.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["llm"].startswith("mock")
    assert body["database"] in ("sqlite", "postgresql")
    assert anon.get("/api/ready").json() == {"status": "ready"}


def test_resume_upload_parses_profile(client):
    r = client.post("/api/candidates/upload", files={"file": ("priya.txt", RESUMES[0].encode(), "text/plain")})
    assert r.status_code == 201
    c = r.json()
    assert c["name"] == "Priya Raman"
    assert c["email"] == "priya.raman@example.com"
    assert "PostgreSQL" in c["skills"]


def test_upload_rejects_unknown_type(client):
    r = client.post("/api/candidates/upload", files={"file": ("x.exe", b"MZ" * 50, "application/octet-stream")})
    assert r.status_code == 415


def test_sourcing_ranks_relevant_candidates_first(client, work):
    job = _setup(client)
    apps = _source(client, work, job["id"], 3, auto_screen=False)
    assert len(apps) == 3
    assert "Sofia Alvarez" not in [a["candidate"]["name"] for a in apps]  # the designer shouldn't surface
    assert all(a["stage"] == "sourced" for a in apps)
    # sourcing again must not duplicate candidates already in the pipeline
    again = _source(client, work, job["id"], 3, auto_screen=False)
    assert not {a["candidate"]["id"] for a in again} & {a["candidate"]["id"] for a in apps}


def test_full_pipeline_with_approval_gates(client, work):
    job = _setup(client)
    app_id = _source(client, work, job["id"], 1)[0]["id"]

    # Screening ran on the worker and stopped at the human gate.
    app = client.get(f"/api/applications/{app_id}").json()
    assert app["stage"] == "screened"
    assert app["screening_score"] is not None
    approval = app["pending_approval"]
    assert approval and approval["kind"] == "advance"
    assert any(a["id"] == approval["id"] for a in client.get("/api/approvals?status=pending").json())

    # Human advances -> outreach agent emails -> contacted
    app = client.post(f"/api/approvals/{approval['id']}/decide", json={"approve": True}).json()
    assert app["stage"] == "outreach"
    work()
    app = client.get(f"/api/applications/{app_id}").json()
    assert app["stage"] == "contacted"
    assert app["outreach"]["subject"]
    decided = client.get("/api/approvals?status=approved").json()[0]
    assert decided["decided_by"] == "Admin"  # recorded from the session, not the request body

    assert client.post(f"/api/approvals/{approval['id']}/decide", json={"approve": True}).status_code == 409

    # Candidate replies -> scheduling agent proposes slots
    client.post(f"/api/applications/{app_id}/replied")
    work()
    app = client.get(f"/api/applications/{app_id}").json()
    assert app["stage"] == "interview_scheduled"
    slots = app["scheduling"]["proposed_slots"]
    assert len(slots) == 3
    assert client.post(f"/api/applications/{app_id}/confirm-slot", json={"slot": "nope"}).status_code == 409
    app = client.post(f"/api/applications/{app_id}/confirm-slot", json={"slot": slots[0]}).json()
    assert app["scheduling"]["confirmed_slot"] == slots[0]

    # Notes -> evaluation agent -> offer gate
    notes = "Strong system design, excellent communication, deep PostgreSQL knowledge."
    client.post(f"/api/applications/{app_id}/notes", json={"notes": notes})
    work()
    app = client.get(f"/api/applications/{app_id}").json()
    assert app["stage"] == "evaluated"
    assert app["scorecard"]["overall_rating"] >= 4
    offer = app["pending_approval"]
    assert offer["kind"] == "offer"

    client.post(f"/api/approvals/{offer['id']}/decide", json={"approve": True})
    assert client.get(f"/api/applications/{app_id}").json()["stage"] == "offer"

    types = {e["type"] for e in client.get(f"/api/events?application_id={app_id}").json()}
    assert {"sourced", "screened", "outreach_sent", "slots_proposed", "scorecard_created", "approval_decided"} <= types


def test_invalid_transitions_are_refused(client, work):
    job = _setup(client)
    app = _source(client, work, job["id"], 1, auto_screen=False)[0]
    assert client.post(f"/api/applications/{app['id']}/replied").status_code == 409
    assert client.post(f"/api/applications/{app['id']}/notes", json={"notes": "great candidate overall"}).status_code == 409
    assert client.post(f"/api/applications/{app['id']}/reject", json={"reason": "role filled"}).json()["stage"] == "rejected"
    assert client.post(f"/api/applications/{app['id']}/reject", json={}).status_code == 409


def test_rejecting_at_screening_gate(client, work):
    job = _setup(client)
    app = _source(client, work, job["id"], 1)[0]
    approval = client.get(f"/api/applications/{app['id']}").json()["pending_approval"]
    result = client.post(f"/api/approvals/{approval['id']}/decide", json={"approve": False, "comment": "Not enough Go"}).json()
    assert result["stage"] == "rejected"
    assert result["pending_approval"] is None


def test_stats(client):
    _setup(client)
    s = client.get("/api/stats").json()
    assert s["open_jobs"] == 1 and s["candidates"] == len(RESUMES)
