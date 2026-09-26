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
    # Interviewers whose calendars are checked for free slots and who join the Teams meeting.
    interviewer_emails: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), default=JobStatus.open)
    # The skill groups the sourcing agent searches for this job, chosen from the job title.
    skill_groups: Mapped[list[str] | None] = mapped_column(JSON)
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
    # Parsed details: links, employment_history, education, certifications, projects, years_from_dates.
    profile: Mapped[dict | None] = mapped_column(JSON)
    resume_text: Mapped[str] = mapped_column(Text)
    resume_filename: Mapped[str | None] = mapped_column(String(300))
    resume_file_key: Mapped[str | None] = mapped_column(String(500))  # the original file in storage.py
    do_not_call: Mapped[bool] = mapped_column(Boolean, default=False)  # set when a candidate opts out
    embedding: Mapped[list[float] | None] = mapped_column(EmbeddingType(EMBEDDING_DIM))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    applications: Mapped[list["Application"]] = relationship(back_populates="candidate", cascade="all, delete-orphan")
    chunks: Mapped[list["ResumeChunk"]] = relationship(
        back_populates="candidate", cascade="all, delete-orphan", order_by="ResumeChunk.position"
    )
    group_links: Mapped[list["CandidateSkillGroup"]] = relationship(
        cascade="all, delete-orphan", order_by="CandidateSkillGroup.position", lazy="selectin"
    )

    @property
    def has_original_file(self) -> bool:
        return self.resume_file_key is not None

    @property
    def skill_groups(self) -> list[str]:
        """The candidate's skill groups (skill_groups.py), most relevant first."""
        return [link.name for link in self.group_links]

    def set_skill_groups(self, groups: list[str]) -> None:
        self.group_links = [CandidateSkillGroup(name=g, position=i) for i, g in enumerate(groups)]


class CandidateSkillGroup(Base):
    """A candidate's membership in a skill group. A table (not a JSON list) so sourcing can
    filter the pool by group with an index on any database."""

    __tablename__ = "candidate_skill_groups"

    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), primary_key=True)
    name: Mapped[str] = mapped_column(String(60), primary_key=True, index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)


class ResumeChunk(Base):
    """One searchable piece of a resume: the profile summary, a section, or a single job."""

    __tablename__ = "resume_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(30))  # profile | summary | experience | skills | education | ...
    position: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(200))  # embeddings.model_id() that produced the vector
    embedding: Mapped[list[float] | None] = mapped_column(EmbeddingType(EMBEDDING_DIM))

    candidate: Mapped["Candidate"] = relationship(back_populates="chunks")


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
    messages: Mapped[list["Message"]] = relationship(
        back_populates="application", cascade="all, delete-orphan", order_by="Message.created_at"
    )
    calls: Mapped[list["Call"]] = relationship(back_populates="application", cascade="all, delete-orphan", order_by="Call.created_at")


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
    send_email = "send_email"
    book_meeting = "book_meeting"
    place_call = "place_call"
    summarize_call = "summarize_call"
    intake = "intake"  # check the job-portal mailbox for new applications


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


class MessageKind(str, enum.Enum):
    outreach = "outreach"
    invitation = "invitation"  # interview slot options
    calendar_invite = "calendar_invite"  # the booked meeting (sent by the calendar system)


class MessageStatus(str, enum.Enum):
    draft = "draft"
    queued = "queued"
    sent = "sent"
    failed = "failed"


class Message(Base):
    """An email to a candidate. Drafted by an agent; sent only when a person clicks Send."""

    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    kind: Mapped[MessageKind] = mapped_column(Enum(MessageKind))
    status: Mapped[MessageStatus] = mapped_column(Enum(MessageStatus), default=MessageStatus.draft)
    to: Mapped[str | None] = mapped_column(String(320))
    subject: Mapped[str] = mapped_column(String(500))
    body: Mapped[str] = mapped_column(Text)
    provider: Mapped[str | None] = mapped_column(String(30))  # "graph", or "outbox" when not actually sent
    error: Mapped[str | None] = mapped_column(Text)
    sent_by: Mapped[str | None] = mapped_column(String(200))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    application: Mapped[Application] = relationship(back_populates="messages")


class CallPurpose(str, enum.Enum):
    prescreen = "prescreen"
    schedule = "schedule"
    reminder = "reminder"


class CallStatus(str, enum.Enum):
    scheduled = "scheduled"  # waiting for its time (reminders)
    queued = "queued"
    dialing = "dialing"
    in_progress = "in_progress"
    completed = "completed"
    no_answer = "no_answer"
    declined = "declined"  # candidate didn't consent or opted out
    failed = "failed"
    canceled = "canceled"


class Call(Base):
    """An AI phone call to a candidate. Started only when a person clicks Call."""

    __tablename__ = "calls"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    purpose: Mapped[CallPurpose] = mapped_column(Enum(CallPurpose))
    status: Mapped[CallStatus] = mapped_column(Enum(CallStatus), default=CallStatus.queued, index=True)
    provider: Mapped[str] = mapped_column(String(30))
    provider_sid: Mapped[str | None] = mapped_column(String(64), index=True)
    to_number: Mapped[str | None] = mapped_column(String(50))
    relay_token: Mapped[str] = mapped_column(String(64), default=lambda: uuid.uuid4().hex + uuid.uuid4().hex)
    context: Mapped[dict] = mapped_column(JSON, default=dict)  # questions asked, slots offered, interview time
    transcript: Mapped[list[dict]] = mapped_column(JSON, default=list)  # [{role: agent|candidate, text, at}]
    outcome: Mapped[dict] = mapped_column(JSON, default=dict)  # consent, booked_slot, reminder_status, opt_out
    summary: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    requested_by: Mapped[str | None] = mapped_column(String(200))
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    application: Mapped[Application] = relationship(back_populates="calls")


class IntakeStatus(str, enum.Enum):
    imported = "imported"  # new candidate added to the talent pool
    duplicate = "duplicate"  # candidate was already in the pool; linked to the job only
    skipped = "skipped"  # not an application, or no readable resume
    failed = "failed"


class IntakeItem(Base):
    """One application received from a job portal, by email or webhook. The unique
    (source, external_id) pair makes intake idempotent: an email is processed once."""

    __tablename__ = "intake_items"
    __table_args__ = (UniqueConstraint("source", "external_id"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    source: Mapped[str] = mapped_column(String(30))  # "mailbox" | "webhook"
    external_id: Mapped[str] = mapped_column(String(500))
    portal: Mapped[str | None] = mapped_column(String(60))  # e.g. Naukri, LinkedIn, Indeed
    subject: Mapped[str | None] = mapped_column(String(500))
    sender: Mapped[str | None] = mapped_column(String(320))
    status: Mapped[IntakeStatus] = mapped_column(Enum(IntakeStatus), index=True)
    detail: Mapped[str | None] = mapped_column(Text)
    candidate_id: Mapped[str | None] = mapped_column(ForeignKey("candidates.id", ondelete="SET NULL"))
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    application_id: Mapped[str | None] = mapped_column(ForeignKey("applications.id", ondelete="SET NULL"))
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)

    candidate: Mapped[Candidate | None] = relationship()
    job: Mapped[Job | None] = relationship()
