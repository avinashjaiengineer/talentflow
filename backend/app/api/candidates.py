from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..llm import LLMError
from ..models import Candidate, CandidateSkillGroup
from ..resume import ResumeUnreadable, build_candidate, extract_text
from ..schemas import ApplicationOut, CandidateDetail, CandidateIn, CandidateOut, CandidateUpdate, GroupCount
from ..storage import content_type, delete_resume, disposition, get_storage, save_resume
from .serializers import application_out

router = APIRouter(prefix="/candidates", tags=["candidates"])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def _create(db: Session, text: str, *, filename: str | None, name: str | None = None, email: str | None = None,
            original: bytes | None = None) -> Candidate:
    try:
        candidate = build_candidate(text, filename=filename, name=name, email=email)
    except LLMError as e:
        raise HTTPException(502, f"Could not parse resume: {e}") from e
    except ResumeUnreadable as e:
        raise HTTPException(422, str(e)) from e
    if original is not None and filename:
        candidate.resume_file_key = save_resume(filename, original)
    db.add(candidate)
    db.commit()
    return candidate


@router.get("", response_model=list[CandidateOut])
def list_candidates(q: str | None = None, group: str | None = None, db: Session = Depends(get_db)):
    stmt = select(Candidate).order_by(Candidate.created_at.desc())
    if group:
        stmt = stmt.where(Candidate.id.in_(select(CandidateSkillGroup.candidate_id).where(CandidateSkillGroup.name == group)))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Candidate.name.ilike(like), Candidate.headline.ilike(like), Candidate.resume_text.ilike(like)))
    return db.scalars(stmt.limit(500)).all()


@router.get("/groups", response_model=list[GroupCount])
def skill_group_counts(db: Session = Depends(get_db)):
    """How many candidates are in each skill group, largest first."""
    rows = db.execute(
        select(CandidateSkillGroup.name, func.count()).group_by(CandidateSkillGroup.name).order_by(func.count().desc())
    ).all()
    return [GroupCount(name=name, count=n) for name, n in rows]


@router.post("/upload", response_model=CandidateOut, status_code=201)
async def upload_resume(file: UploadFile = File(...), db: Session = Depends(get_db)):
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Resume is larger than 10 MB")
    try:
        text = extract_text(file.filename or "resume.txt", data)
    except ValueError as e:
        raise HTTPException(415, str(e)) from e
    if len(text) < 20:
        raise HTTPException(422, "Could not read any text from this file (is it a scanned image?)")
    # Parsing and embedding take seconds; keep them off the event loop.
    return await run_in_threadpool(_create, db, text, filename=file.filename, original=data)


@router.post("", response_model=CandidateOut, status_code=201)
def create_candidate(body: CandidateIn, db: Session = Depends(get_db)):
    return _create(db, body.resume_text, filename=None, name=body.name, email=body.email)


@router.get("/{candidate_id}", response_model=CandidateDetail)
def get_candidate(candidate_id: str, db: Session = Depends(get_db)):
    candidate = db.get(Candidate, candidate_id)
    if candidate is None:
        raise HTTPException(404, "Candidate not found")
    return candidate


@router.get("/{candidate_id}/applications", response_model=list[ApplicationOut])
def candidate_applications(candidate_id: str, db: Session = Depends(get_db)):
    candidate = db.get(Candidate, candidate_id)
    if candidate is None:
        raise HTTPException(404, "Candidate not found")
    return [application_out(a, detail=False) for a in candidate.applications]


@router.patch("/{candidate_id}", response_model=CandidateDetail)
def update_candidate(candidate_id: str, body: CandidateUpdate, db: Session = Depends(get_db)):
    candidate = db.get(Candidate, candidate_id)
    if candidate is None:
        raise HTTPException(404, "Candidate not found")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(candidate, key, value)
    db.commit()
    return candidate


@router.delete("/{candidate_id}", status_code=204)
def delete_candidate(candidate_id: str, db: Session = Depends(get_db)):
    candidate = db.get(Candidate, candidate_id)
    if candidate is None:
        raise HTTPException(404, "Candidate not found")
    key = candidate.resume_file_key
    db.delete(candidate)
    db.commit()
    delete_resume(key)


@router.get("/{candidate_id}/resume")
def download_resume(candidate_id: str, db: Session = Depends(get_db)):
    """The original resume file, as uploaded or received from a job portal."""
    candidate = db.get(Candidate, candidate_id)
    storage = get_storage()
    if candidate is None or not candidate.resume_file_key or storage is None:
        raise HTTPException(404, "No original file is stored for this candidate")
    filename = candidate.resume_filename or "resume"
    if url := storage.download_url(candidate.resume_file_key, filename):
        return RedirectResponse(url, status_code=307)
    try:
        data = storage.get(candidate.resume_file_key)
    except FileNotFoundError as e:
        raise HTTPException(404, "The stored file is missing") from e
    return Response(data, media_type=content_type(filename),
                    headers={"Content-Disposition": disposition(filename), "Cache-Control": "private, no-store"})
