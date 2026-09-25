from ..models import Application, Approval, ApprovalKind, ApprovalStatus
from ..schemas import ApplicationOut, ApprovalOut, CandidateOut


def approval_out(approval: Approval) -> ApprovalOut:
    app = approval.application
    out = ApprovalOut.model_validate(approval)
    out.candidate_name = app.candidate.name
    out.job_title = app.job.title
    if approval.kind == ApprovalKind.offer and app.scorecard:
        out.score, out.score_max = app.scorecard.get("overall_rating"), 5
    elif app.screening_score is not None:
        out.score, out.score_max = app.screening_score, 100
    return out


def approval_rank(out: ApprovalOut) -> float:
    """Offer decisions first, then the strongest candidates."""
    fraction = out.score / out.score_max if out.score is not None and out.score_max else -1
    return (out.kind == ApprovalKind.offer) + fraction


def application_out(app: Application) -> ApplicationOut:
    pending = next((a for a in app.approvals if a.status == ApprovalStatus.pending), None)
    return ApplicationOut(
        id=app.id,
        job_id=app.job_id,
        job_title=app.job.title,
        candidate=CandidateOut.model_validate(app.candidate),
        stage=app.stage,
        match_score=app.match_score,
        screening_score=app.screening_score,
        screening=app.screening,
        outreach=app.outreach,
        scheduling=app.scheduling,
        interview_notes=app.interview_notes,
        scorecard=app.scorecard,
        error=app.error,
        created_at=app.created_at,
        updated_at=app.updated_at,
        pending_approval=approval_out(pending) if pending else None,
    )
