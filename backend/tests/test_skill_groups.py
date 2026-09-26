from pathlib import Path

from alembic import command
from alembic.config import Config

from app import skill_groups
from app.db import SessionLocal
from app.models import CandidateSkillGroup
from app.seed import RESUMES


def _pool(client):
    ids = {}
    for text in RESUMES:
        c = client.post("/api/candidates", json={"resume_text": text}).json()
        ids[c["name"]] = c
    return ids


def _source(client, work, job, limit=10):
    task = client.post(f"/api/jobs/{job['id']}/source", json={"limit": limit, "auto_screen": False}).json()
    work()
    result = client.get(f"/api/tasks/{task['id']}").json()["result"]
    names = [client.get(f"/api/applications/{i}").json()["candidate"]["name"] for i in result["application_ids"]]
    return result, names


def test_offline_rules_group_people_by_what_they_do():
    assert skill_groups.groups_for_candidate("Senior Backend Engineer, 8 years", ["Python", "PostgreSQL"])[0] == "Backend Engineering"
    assert skill_groups.groups_for_candidate("Product Designer, 6 years", ["Figma", "User research"])[0] == "Design (UI/UX)"
    assert skill_groups.groups_for_candidate("Machine Learning Engineer", ["PyTorch", "NLP"])[0] == "Data Science & ML"
    assert skill_groups.groups_for_candidate("Chef", []) == ["Other"]
    assert skill_groups.groups_for_job("Senior Backend Engineer") == ["Backend Engineering", "Full-Stack Engineering"]
    assert skill_groups.groups_for_job("Product Designer") == ["Design (UI/UX)"]
    assert skill_groups.clean(["Design (UI/UX)", "Made up", "Design (UI/UX)"]) == ["Design (UI/UX)"]


def test_parsed_candidates_are_grouped_and_filterable(client):
    pool = _pool(client)
    assert pool["Priya Raman"]["skill_groups"][0] == "Backend Engineering"
    assert pool["Sofia Alvarez"]["skill_groups"][0] == "Design (UI/UX)"

    counts = {g["name"]: g["count"] for g in client.get("/api/candidates/groups").json()}
    assert counts["Design (UI/UX)"] == 1 and counts["Backend Engineering"] >= 3
    design = client.get("/api/candidates", params={"group": "Design (UI/UX)"}).json()
    assert [c["name"] for c in design] == ["Sofia Alvarez"]


def test_sourcing_searches_the_groups_that_match_the_job_title(client, work):
    _pool(client)
    designer = client.post("/api/jobs", json={
        "title": "Product Designer", "description": "Own the design of our B2B product.", "requirements": ["Figma"],
    }).json()
    result, names = _source(client, work, designer)
    assert names == ["Sofia Alvarez"]  # the engineers aren't searched for a design job
    assert result["groups"] == ["Design (UI/UX)"] and result["widened"] is False
    assert client.get(f"/api/jobs/{designer['id']}").json()["skill_groups"] == ["Design (UI/UX)"]

    backend = client.post("/api/jobs", json={
        "title": "Senior Backend Engineer", "description": "Python APIs", "requirements": ["Python", "PostgreSQL"],
    }).json()
    result, names = _source(client, work, backend)
    assert "Sofia Alvarez" not in names and "Priya Raman" in names
    events = client.get("/api/events", params={"job_id": backend["id"]}).json()
    assert any(e["type"] == "groups_chosen" and "Backend Engineering" in e["message"] for e in events)


def test_sourcing_widens_to_the_whole_pool_when_the_groups_are_empty(client, work):
    _pool(client)
    job = client.post("/api/jobs", json={
        "title": "Payroll Specialist", "description": "Run monthly payroll.", "requirements": ["payroll"],
    }).json()
    result, names = _source(client, work, job, limit=3)
    assert result["groups"] == ["HR & Recruiting"] and result["widened"] is True
    assert len(names) == 3


def test_migration_groups_existing_candidates(client):
    _pool(client)
    with SessionLocal() as db:
        db.query(CandidateSkillGroup).delete()
        db.commit()
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "app" / "migrations"))
    command.downgrade(cfg, "0005")
    command.upgrade(cfg, "head")

    counts = {g["name"]: g["count"] for g in client.get("/api/candidates/groups").json()}
    assert counts.get("Design (UI/UX)") == 1
    assert all(c["skill_groups"] for c in client.get("/api/candidates").json())
