"""Background worker: runs queued agent tasks.   python -m app.worker

Safe to run several copies. On Postgres, tasks are claimed with SELECT ... FOR UPDATE
SKIP LOCKED, so each one runs exactly once. Transient failures (rate limits, network,
5xx) are retried with exponential backoff; anything else fails fast and surfaces a
Retry button in the UI. Tasks left `running` by a crashed worker are re-queued.
"""

import logging
import os
import signal
import socket
import threading
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError

from . import comms, orchestrator
from .config import get_settings
from .db import SessionLocal
from .events import log_event
from .integrations import IntegrationError
from .llm import LLMError
from .logging_setup import configure_logging
from .models import AgentTask, Application, Job, TaskKind, TaskStatus

log = logging.getLogger("talentflow.worker")
WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"


def _backoff(attempt: int) -> timedelta:
    return timedelta(seconds=min(300, 5 * 2 ** (attempt - 1)))


def requeue_stale() -> int:
    cutoff = datetime.now(UTC) - timedelta(minutes=get_settings().task_stale_minutes)
    with SessionLocal() as db:
        result = db.execute(
            update(AgentTask)
            .where(AgentTask.status == TaskStatus.running, AgentTask.locked_at < cutoff)
            .values(status=TaskStatus.queued, locked_at=None, locked_by=None)
        )
        db.commit()
        if result.rowcount:
            log.warning("Re-queued %d stale tasks", result.rowcount)
        return result.rowcount


def claim() -> int | None:
    with SessionLocal() as db:
        task = db.scalar(
            select(AgentTask)
            .where(AgentTask.status == TaskStatus.queued, AgentTask.run_after <= datetime.now(UTC))
            .order_by(AgentTask.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if task is None:
            return None
        task.status = TaskStatus.running
        task.attempts += 1
        task.locked_at = datetime.now(UTC)
        task.locked_by = WORKER_ID
        db.commit()
        return task.id


def execute(task_id: int) -> None:
    started = time.monotonic()
    with SessionLocal() as db:
        task = db.get(AgentTask, task_id)
        try:
            if task.kind == TaskKind.agent_step:
                app = db.get(Application, task.application_id)
                if app is not None:
                    orchestrator.run_agent_step(db, app)
            elif task.kind == TaskKind.source:
                job = db.get(Job, task.job_id)
                if job is not None:
                    task.result = orchestrator.run_sourcing(db, job, **(task.payload or {}))
            else:
                comms.run_task(db, task.kind, task.application_id, task.payload or {})
            task.status = TaskStatus.succeeded
            task.last_error = None
            db.commit()
            log.info("task %s %s succeeded in %.1fs", task_id, task.kind.value, time.monotonic() - started)
            return
        except Exception as e:  # noqa: BLE001 - every failure is recorded on the task
            db.rollback()
            error = e

    retryable = isinstance(error, OperationalError) or (
        isinstance(error, LLMError | IntegrationError) and error.retryable
    )
    with SessionLocal() as db:
        task = db.get(AgentTask, task_id)
        max_attempts = get_settings().task_max_attempts
        will_retry = retryable and task.attempts < max_attempts
        task.last_error = str(error)
        task.locked_at = task.locked_by = None
        if will_retry:
            task.status = TaskStatus.queued
            task.run_after = datetime.now(UTC) + _backoff(task.attempts)
        else:
            task.status = TaskStatus.failed
        app = db.get(Application, task.application_id) if task.application_id else None
        if app is not None:
            app.error = f"{error} (retrying, attempt {task.attempts} of {max_attempts})" if will_retry else str(error)
        log_event(db, actor="orchestrator", type="agent_retrying" if will_retry else "agent_failed",
                  message=str(error), application=app, job_id=task.job_id)
        db.commit()
    log.log(logging.WARNING if will_retry else logging.ERROR, "task %s failed (attempt %s, retry=%s): %s",
            task_id, task.attempts, will_retry, error, exc_info=not retryable)


def drain(max_tasks: int = 1000) -> int:
    """Run queued tasks until none are ready. Used by tests and one-off scripts."""
    done = 0
    while done < max_tasks and (task_id := claim()) is not None:
        execute(task_id)
        done += 1
    return done


def run_forever(stop_event: threading.Event | None = None) -> None:
    settings = get_settings()
    stop_event = stop_event or threading.Event()

    if threading.current_thread() is threading.main_thread():
        def stop(*_):
            stop_event.set()
            log.info("Shutting down after the current task")

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
    log.info("Worker %s started", WORKER_ID)
    last_sweep = 0.0
    while not stop_event.is_set():
        try:
            if time.monotonic() - last_sweep > 60:
                requeue_stale()
                last_sweep = time.monotonic()
            task_id = claim()
            if task_id is None:
                stop_event.wait(settings.worker_poll_seconds)
                continue
            execute(task_id)
        except OperationalError:
            log.exception("Database unavailable; retrying in 5s")
            stop_event.wait(5)


def start_embedded() -> tuple[threading.Thread, threading.Event]:
    """Run the worker on a daemon thread inside the API process (development convenience)."""
    stop_event = threading.Event()
    thread = threading.Thread(target=run_forever, args=(stop_event,), name="agent-worker", daemon=True)
    thread.start()
    return thread, stop_event


if __name__ == "__main__":
    configure_logging()
    run_forever()
