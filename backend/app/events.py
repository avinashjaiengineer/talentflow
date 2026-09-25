from sqlalchemy.orm import Session

from .models import Application, Event


def log_event(
    db: Session,
    *,
    actor: str,
    type: str,
    message: str,
    application: Application | None = None,
    job_id: str | None = None,
    data: dict | None = None,
) -> Event:
    event = Event(
        actor=actor,
        type=type,
        message=message,
        application_id=application.id if application else None,
        job_id=job_id or (application.job_id if application else None),
        data=data,
    )
    db.add(event)
    return event
