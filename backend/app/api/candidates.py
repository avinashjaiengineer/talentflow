from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..llm import LLMError
from ..models import Candidate
from ..resume import build_candidate, extract_text
from ..schemas import ApplicationOut, CandidateDetail, CandidateIn, CandidateOut, CandidateUpdate
from .serializers import application_out

router = APIRouter(prefix="/candidates", tags=["candidates"])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def _create(db: Session, text: str, *, filename: str | None, name: str | None = None, email: str | None = None) -> Candidate:
    try:
        candidate = build_candidate(text, filename=filename, name=name, email=email)
    except LLMError as e:
        raise HTTPException(502, f"Could not parse resume: {e}") from e
    db.add(candidate)
    db.commit()
    return candidate


@router.get("", response_model=list[CandidateOut])
def list_candidates(q: str | None = None, db: Session = Depends(get_db)):
    stmt = select(Candidate).order_by(Candidate.created_at.desc())
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Candidate.name.ilike(like), Candidate.headline.ilike(like), Candidate.resume_text.ilike(like)))
    return db.scalars(stmt.limit(500)).all()


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
    return _create(db, text, filename=file.filename)


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
    db.delete(candidate)
    db.commit()
