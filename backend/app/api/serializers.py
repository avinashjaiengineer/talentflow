from ..models import Application, Approval, ApprovalStatus
from ..schemas import ApplicationOut, ApprovalOut, CandidateOut


def approval_out(approval: Approval) -> ApprovalOut:
    out = ApprovalOut.model_validate(approval)
    out.candidate_name = approval.application.candidate.name
    out.job_title = approval.application.job.title
    return out


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
