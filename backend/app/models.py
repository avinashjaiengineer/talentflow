import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .config import get_settings
from .db import Base, EmbeddingType

EMBEDDING_DIM = get_settings().embedding_dim


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(UTC)


class Stage(str, enum.Enum):
    """Pipeline stages. The orchestrator owns every transition between them."""

    sourced = "sourced"
    screening = "screening"
    screened = "screened"  # waiting on the human approval gate
    outreach = "outreach"
    contacted = "contacted"
    scheduling = "scheduling"
    interview_scheduled = "interview_scheduled"
    evaluation = "evaluation"
    evaluated = "evaluated"  # waiting on the offer decision
    offer = "offer"
    rejected = "rejected"
    failed = "failed"


class JobStatus(str, enum.Enum):
    open = "open"
    closed = "closed"


class ApprovalKind(str, enum.Enum):
    advance = "advance"  # after screening: move forward or reject
    offer = "offer"  # after evaluation: make an offer or reject


class ApprovalStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(200))
    department: Mapped[str | None] = mapped_column(String(120))
    location: Mapped[str | None] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text)
    requirements: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), default=JobStatus.open)
    embedding: Mapped[list[float] | None] = mapped_column(EmbeddingType(EMBEDDING_DIM))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    applications: Mapped[list["Application"]] = relationship(back_populates="job", cascade="all, delete-orphan")


class Candidate(Base):
    __tablename__ = "candidates"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(50))
    location: Mapped[str | None] = mapped_column(String(120))
    headline: Mapped[str | None] = mapped_column(String(300))
    skills: Mapped[list[str]] = mapped_column(JSON, default=list)
    years_experience: Mapped[float | None] = mapped_column(Float)
    resume_text: Mapped[str] = mapped_column(Text)
    resume_filename: Mapped[str | None] = mapped_column(String(300))
    embedding: Mapped[list[float] | None] = mapped_column(EmbeddingType(EMBEDDING_DIM))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    applications: Mapped[list["Application"]] = relationship(back_populates="candidate", cascade="all, delete-orphan")


class Application(Base):
    """One candidate moving through one job's pipeline."""

    __tablename__ = "applications"
    __table_args__ = (UniqueConstraint("job_id", "candidate_id"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), index=True)
    stage: Mapped[Stage] = mapped_column(Enum(Stage), default=Stage.sourced, index=True)
    match_score: Mapped[float | None] = mapped_column(Float)  # vector similarity from sourcing
    screening_score: Mapped[int | None] = mapped_column(Integer)  # 0-100 from the screening agent
    screening: Mapped[dict | None] = mapped_column(JSON)
    outreach: Mapped[dict | None] = mapped_column(JSON)
    scheduling: Mapped[dict | None] = mapped_column(JSON)
    interview_notes: Mapped[str | None] = mapped_column(Text)
    scorecard: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    job: Mapped[Job] = relationship(back_populates="applications")
    candidate: Mapped[Candidate] = relationship(back_populates="applications")
    approvals: Mapped[list["Approval"]] = relationship(back_populates="application", cascade="all, delete-orphan")


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    kind: Mapped[ApprovalKind] = mapped_column(Enum(ApprovalKind))
    status: Mapped[ApprovalStatus] = mapped_column(Enum(ApprovalStatus), default=ApprovalStatus.pending, index=True)
    recommendation: Mapped[str | None] = mapped_column(Text)
    decided_by: Mapped[str | None] = mapped_column(String(200))
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    application: Mapped[Application] = relationship(back_populates="approvals")


class Event(Base):
    """Append-only log of everything agents and humans do."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    application_id: Mapped[str | None] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    actor: Mapped[str] = mapped_column(String(50))  # agent name, "human", or "orchestrator"
    type: Mapped[str] = mapped_column(String(80))
    message: Mapped[str] = mapped_column(Text)
    data: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)


class Role(str, enum.Enum):
    admin = "admin"  # manages users, plus everything a recruiter can do
    recruiter = "recruiter"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(300))
    role: Mapped[Role] = mapped_column(Enum(Role), default=Role.recruiter)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Bumped on password change or deactivation to invalidate existing sessions.
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TaskKind(str, enum.Enum):
    agent_step = "agent_step"  # run the agent for an application's current stage
    source = "source"  # run the sourcing agent for a job


class TaskStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class AgentTask(Base):
    """Durable work queue. Rows are written in the same transaction as the stage change
    that needs them, so a crash can never lose or duplicate an agent run."""

    __tablename__ = "agent_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[TaskKind] = mapped_column(Enum(TaskKind))
    status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus), default=TaskStatus.queued, index=True)
    application_id: Mapped[str | None] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    payload: Mapped[dict | None] = mapped_column(JSON)
    result: Mapped[dict | None] = mapped_column(JSON)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
