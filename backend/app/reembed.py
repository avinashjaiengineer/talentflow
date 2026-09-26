"""Rebuild search embeddings.   python -m app.reembed [--missing-only]

Run this after changing EMBEDDING_PROVIDER, EMBEDDING_MODEL, or EMBEDDING_DIM, and once after
upgrading to resume pieces (migration 0005). No LLM calls: it re-uses the parsed profiles.

On Postgres, when EMBEDDING_DIM has changed, it first resizes the vector columns (clearing the
old vectors, which can't be compared with new ones) and rebuilds the HNSW indexes.

--missing-only  re-embed only candidates with no pieces from the current model (fast, resumable)
"""

import argparse
import logging
import time

from sqlalchemy import Engine, func, select, text

from .config import get_settings
from .db import SessionLocal, engine
from .embeddings import embed_one, model_id
from .logging_setup import configure_logging
from .models import Candidate, Job, ResumeChunk
from .search_index import index_candidate

log = logging.getLogger("talentflow.reembed")

VECTOR_COLUMNS = {  # table -> HNSW index to rebuild (None: no index)
    "candidates": "ix_candidates_embedding_hnsw",
    "resume_chunks": "ix_resume_chunks_embedding_hnsw",
    "jobs": None,
}


def column_dimensions(eng: Engine) -> dict[str, str]:
    """{'candidates': 'vector(384)', ...} on Postgres; empty elsewhere."""
    if eng.dialect.name != "postgresql":
        return {}
    with eng.connect() as conn:
        return {
            table: conn.scalar(text(
                "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
                "WHERE attrelid = CAST(:t AS regclass) AND attname = 'embedding'"
            ), {"t": table})
            for table in VECTOR_COLUMNS
        }


def dimension_mismatches(eng: Engine = engine) -> list[str]:
    want = f"vector({get_settings().embedding_dim})"
    return [t for t, have in column_dimensions(eng).items() if have and have != want]


def resize_vector_columns(eng: Engine = engine) -> list[str]:
    """Match the vector columns to EMBEDDING_DIM. Old vectors are cleared: they must be re-embedded."""
    tables = dimension_mismatches(eng)
    dim = get_settings().embedding_dim
    with eng.begin() as conn:
        for table in tables:
            index = VECTOR_COLUMNS[table]
            if index:
                conn.execute(text(f"DROP INDEX IF EXISTS {index}"))
            conn.execute(text(f"ALTER TABLE {table} ALTER COLUMN embedding TYPE vector({dim}) USING NULL"))
            if index:
                conn.execute(text(f"CREATE INDEX {index} ON {table} USING hnsw (embedding vector_cosine_ops)"))
            log.info("Resized %s.embedding to vector(%d)", table, dim)
    return tables


def run(*, missing_only: bool = False, batch: int = 25) -> dict:
    resized = resize_vector_columns()
    if resized:
        missing_only = False  # every vector in a resized table was cleared
    model = model_id()
    started, done = time.monotonic(), 0
    with SessionLocal() as db:
        stmt = select(Candidate.id).order_by(Candidate.created_at)
        if missing_only:
            stmt = stmt.where(~Candidate.chunks.any(ResumeChunk.model == model))
        ids = list(db.scalars(stmt))
        log.info("Re-embedding %d candidates with %s", len(ids), model)
        for i in range(0, len(ids), batch):
            for candidate in db.scalars(select(Candidate).where(Candidate.id.in_(ids[i:i + batch]))):
                index_candidate(candidate)
                done += 1
            db.commit()
            log.info("%d/%d candidates", done, len(ids))

        jobs = 0
        if not missing_only:
            for job in db.scalars(select(Job)):
                job.embedding = embed_one(f"{job.title}\n{job.description}\n{' '.join(job.requirements)}")
                jobs += 1
            db.commit()
        pieces = db.scalar(select(func.count()).select_from(ResumeChunk)) or 0
    result = {"candidates": done, "jobs": jobs, "pieces": pieces, "resized": resized, "model": model,
              "seconds": round(time.monotonic() - started, 1)}
    log.info("Done: %s", result)
    return result


if __name__ == "__main__":
    configure_logging()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--missing-only", action="store_true", help="only candidates without current-model pieces")
    run(missing_only=parser.parse_args().missing_only)
