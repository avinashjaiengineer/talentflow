import sys

import pytest
from sqlalchemy import select, update

from app import reembed
from app.config import get_settings
from app.db import SessionLocal
from app.embeddings import get_embedder
from app.models import Candidate, ResumeChunk
from app.search_index import chunk_resume, fuse, stale_piece_count, unindexed_count
from app.seed import RESUMES
from app.storage import LocalStorage

FILLER = "\n".join(f"- Maintained internal reporting dashboards and on-call rotation, quarter {i}." for i in range(160))
LONG_RESUME = f"""Ravi Kumar
Senior Engineer, 12 years
ravi.kumar@example.com | Pune, India

EXPERIENCE
Acme Payments (2018 - present), Senior Engineer
{FILLER}

Initech (2012 - 2018), Engineer
- Built the settlement engine in Elixir and Phoenix, with Erlang OTP supervision trees.

SKILLS
Java, Spring
"""


def test_chunks_cover_the_whole_resume_one_job_per_piece():
    chunks = chunk_resume(LONG_RESUME, 1500)
    assert all(len(text) <= 1500 + len("Experience:\n") for _, text in chunks)
    joined = "\n".join(text for _, text in chunks)
    assert "Elixir and Phoenix" in joined  # well past the 8,000 characters a single vector used to see
    assert any(text.startswith("Experience:\nInitech") for _, text in chunks)  # a new job starts a new piece
    assert chunks[-1] == ("skills", "Skills:\nJava, Spring")


def test_fusion_rewards_candidates_high_in_either_list():
    assert fuse(["a", "b", "c"], ["c", "d"]) == ["c", "a", "b", "d"]
    assert fuse(["a"], []) == ["a"]


def test_sourcing_finds_skills_deep_in_a_long_resume(client, work):
    for text in RESUMES:
        client.post("/api/candidates", json={"resume_text": text})
    ravi = client.post("/api/candidates", json={"resume_text": LONG_RESUME}).json()
    job = client.post("/api/jobs", json={
        "title": "Elixir Engineer", "description": "Build payment systems in Elixir on the BEAM.",
        "requirements": ["Elixir", "Phoenix", "Erlang OTP"],
    }).json()

    task = client.post(f"/api/jobs/{job['id']}/source", json={"limit": 2, "auto_screen": False}).json()
    work()
    ids = client.get(f"/api/tasks/{task['id']}").json()["result"]["application_ids"]
    first = client.get(f"/api/applications/{ids[0]}").json()
    assert first["candidate"]["id"] == ravi["id"]

    event = next(e for e in client.get(f"/api/events?job_id={job['id']}").json() if e["type"] == "sourced"
                 and e["application_id"] == ids[0])
    assert {"Elixir", "Phoenix"} <= set(event["data"]["keywords"])
    assert "Elixir" in event["data"]["passage"]


def test_candidates_indexed_before_pieces_existed_are_still_found(client, work):
    cand = client.post("/api/candidates", json={"resume_text": RESUMES[0]}).json()
    with SessionLocal() as db:
        db.query(ResumeChunk).delete()
        db.commit()
        assert unindexed_count(db) == 1
    job = client.post("/api/jobs", json={"title": "Backend", "description": "Python APIs", "requirements": ["Python"]}).json()
    task = client.post(f"/api/jobs/{job['id']}/source", json={"limit": 5, "auto_screen": False}).json()
    work()
    ids = client.get(f"/api/tasks/{task['id']}").json()["result"]["application_ids"]
    assert [client.get(f"/api/applications/{i}").json()["candidate"]["id"] for i in ids] == [cand["id"]]


def test_reembed_rebuilds_pieces_from_another_model(client):
    client.post("/api/candidates", json={"resume_text": RESUMES[0]})
    client.post("/api/candidates", json={"resume_text": RESUMES[1]})
    with SessionLocal() as db:
        db.execute(update(ResumeChunk).values(model="fastembed:old-model:384"))
        db.commit()
        assert stale_piece_count(db) > 0

    result = reembed.run(missing_only=True)
    assert result["candidates"] == 2
    with SessionLocal() as db:
        assert stale_piece_count(db) == 0
        assert all(c.chunks for c in db.scalars(select(Candidate)))
    assert reembed.run(missing_only=True)["candidates"] == 0  # nothing left to do


def test_missing_embedding_package_fails_loudly(monkeypatch):
    monkeypatch.setattr(get_settings(), "embedding_provider", "voyage")
    monkeypatch.setitem(sys.modules, "voyageai", None)  # makes `import voyageai` raise ImportError
    get_embedder.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="pip install voyageai"):
            get_embedder()
    finally:
        get_embedder.cache_clear()


# ---------------------------------------------------------------- original files


def test_original_resume_is_stored_and_downloadable(client):
    data = RESUMES[0].encode()
    cand = client.post("/api/candidates/upload", files={"file": ("Priya CV (final).txt", data, "text/plain")}).json()
    assert cand["has_original_file"] is True

    r = client.get(f"/api/candidates/{cand['id']}/resume")
    assert r.status_code == 200
    assert r.content == data
    assert r.headers["content-disposition"] == 'attachment; filename="Priya_CV_final_.txt"'

    with SessionLocal() as db:
        key = db.get(Candidate, cand["id"]).resume_file_key
    storage = LocalStorage(get_settings().storage_dir)
    assert storage.get(key) == data
    assert client.delete(f"/api/candidates/{cand['id']}").status_code == 204
    with pytest.raises(FileNotFoundError):
        storage.get(key)


def test_pasted_resumes_have_no_file(client):
    cand = client.post("/api/candidates", json={"resume_text": RESUMES[1]}).json()
    assert cand["has_original_file"] is False
    assert client.get(f"/api/candidates/{cand['id']}/resume").status_code == 404


def test_storage_keys_cannot_escape_the_directory(tmp_path):
    with pytest.raises(ValueError):
        LocalStorage(str(tmp_path)).get("../../etc/passwd")
