from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from .models import ApprovalKind, ApprovalStatus, JobStatus, Role, Stage, TaskKind, TaskStatus

# SQLite drops tzinfo on read; every stored timestamp is UTC, so say so on the way out.
UTCDateTime = Annotated[datetime, AfterValidator(lambda d: d if d.tzinfo else d.replace(tzinfo=UTC))]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class JobIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    department: str | None = None
    location: str | None = None
    description: str = Field(min_length=1)
    requirements: list[str] = []


class JobUpdate(BaseModel):
    title: str | None = None
    department: str | None = None
    location: str | None = None
    description: str | None = None
    requirements: list[str] | None = None
    status: JobStatus | None = None


class JobOut(ORM):
    id: str
    title: str
    department: str | None
    location: str | None
    description: str
    requirements: list[str]
    status: JobStatus
    created_at: UTCDateTime
    stage_counts: dict[str, int] = {}


class CandidateIn(BaseModel):
    resume_text: str = Field(min_length=20)
    name: str | None = None
    email: str | None = None


class CandidateOut(ORM):
    id: str
    name: str
    email: str | None
    phone: str | None
    location: str | None
    headline: str | None
    skills: list[str]
    years_experience: float | None
    resume_filename: str | None
    created_at: UTCDateTime


class CandidateDetail(CandidateOut):
    resume_text: str


class ApprovalOut(ORM):
    id: str
    application_id: str
    kind: ApprovalKind
    status: ApprovalStatus
    recommendation: str | None
    decided_by: str | None
    comment: str | None
    created_at: UTCDateTime
    decided_at: UTCDateTime | None
    candidate_name: str | None = None
    job_title: str | None = None
    score: int | None = None  # screening score (0-100) or scorecard rating (1-5)
    score_max: int | None = None


class ApplicationOut(ORM):
    id: str
    job_id: str
    job_title: str
    candidate: CandidateOut
    stage: Stage
    match_score: float | None
    screening_score: int | None
    screening: dict | None
    outreach: dict | None
    scheduling: dict | None
    interview_notes: str | None
    scorecard: dict | None
    error: str | None
    created_at: UTCDateTime
    updated_at: UTCDateTime
    pending_approval: ApprovalOut | None = None


class EventOut(ORM):
    id: int
    application_id: str | None
    job_id: str | None
    actor: str
    type: str
    message: str
    data: dict | None
    created_at: UTCDateTime
    candidate_name: str | None = None
    job_title: str | None = None


class SourceRequest(BaseModel):
    limit: int = Field(10, ge=1, le=100)
    auto_screen: bool = True


class AddCandidate(BaseModel):
    candidate_id: str
    auto_screen: bool = True


class Decision(BaseModel):
    approve: bool
    comment: str | None = Field(None, max_length=2000)


class SlotChoice(BaseModel):
    slot: str


class Notes(BaseModel):
    notes: str = Field(min_length=10, max_length=50_000)


class RejectRequest(BaseModel):
    reason: str | None = Field(None, max_length=2000)


class Health(BaseModel):
    status: str
    version: str
    environment: str
    llm: str
    models: dict[str, str]
    embeddings: str
    database: str


class UserOut(ORM):
    id: str
    email: str
    name: str
    role: Role
    is_active: bool
    created_at: UTCDateTime
    last_login_at: UTCDateTime | None


class TaskOut(ORM):
    id: int
    kind: TaskKind
    status: TaskStatus
    application_id: str | None
    job_id: str | None
    result: dict | None
    attempts: int
    last_error: str | None
    created_at: UTCDateTime
    updated_at: UTCDateTime
