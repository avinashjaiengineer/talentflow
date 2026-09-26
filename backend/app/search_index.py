"""Talent-pool search: resume pieces, a vector index, and hybrid ranking.

Indexing: each resume becomes a short profile summary plus one piece per section, with every
job in the work history as its own piece. Pieces are sized for the embedding model's input
limit, so a long resume is searched end to end rather than cut off after the first page.

Searching: the nearest pieces by meaning (pgvector HNSW on Postgres) and full-text keyword
matches (Postgres GIN index) are combined with reciprocal rank fusion. Meaning finds "built RAG
pipelines" for "LLM applications"; keywords make sure an exact "Kafka" or "SAP FICO" counts.
On SQLite (development and tests) the same ranking runs in Python.
"""

import re
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import Float, bindparam, exists, func, literal_column, or_, select, text
from sqlalchemy.orm import Session

from .config import get_settings
from .db import is_postgres
from .embeddings import cosine, embed_many, embed_one, model_id
from .models import Application, Candidate, CandidateSkillGroup, ResumeChunk
from .resume import _RANGE, _heading

# Must match the ix_candidates_fts index expression (migration 0005) exactly.
FTS_DOCUMENT = "to_tsvector('simple', coalesce(headline, '') || ' ' || resume_text)"
RRF_K = 60  # the standard reciprocal-rank-fusion constant


@dataclass
class Match:
    candidate: Candidate
    similarity: float  # cosine similarity of the best-matching piece, 0-1
    passage: str | None = None  # that piece, to show why the candidate matched
    keywords: list[str] = field(default_factory=list)  # search terms found in the resume


# ---------------------------------------------------------------- indexing


def profile_text(c: Candidate) -> str:
    """A compact summary of the parsed profile: the first piece, and Candidate.embedding."""
    p = c.profile or {}
    lines = [c.headline or "", f"Skills: {', '.join(c.skills)}" if c.skills else ""]
    if c.years_experience is not None:
        lines.append(f"{c.years_experience:g} years of experience")
    for job in p.get("employment_history") or []:
        lines.append(" at ".join(x for x in (job.get("title"), job.get("company")) if x))
    for ed in p.get("education") or []:
        lines.append(", ".join(v for v in (ed.get("degree"), ed.get("field"), ed.get("institution")) if v))
    if p.get("certifications"):
        lines.append("Certifications: " + ", ".join(p["certifications"]))
    return "\n".join(ln for ln in lines if ln).strip() or c.resume_text[:1500]


def chunk_resume(resume: str, max_chars: int) -> list[tuple[str, str]]:
    """[(section, text)] covering the whole resume, each piece at most ~max_chars."""
    blocks: list[tuple[str, list[str]]] = []
    section = "summary"
    for raw in resume.splitlines():
        line = raw.strip()
        if not line:
            continue
        if found := _heading(line):
            section, rest = found
            blocks.append((section, [rest] if rest else []))
            continue
        if not blocks or blocks[-1][0] != section:
            blocks.append((section, []))
        elif section == "experience" and _RANGE.search(line) and blocks[-1][1]:
            blocks.append((section, []))  # a dated line starts the next job
        blocks[-1][1].append(line)

    chunks: list[tuple[str, str]] = []
    for section, lines in blocks:
        label, buf = section.capitalize(), ""
        for line in lines:
            if buf and len(buf) + len(line) + 1 > max_chars:
                chunks.append((section, f"{label}:\n{buf}"))
                buf = ""
            while len(line) > max_chars:
                chunks.append((section, f"{label}:\n{line[:max_chars]}"))
                line = line[max_chars:]
            buf = f"{buf}\n{line}" if buf else line
        if buf:
            chunks.append((section, f"{label}:\n{buf}"))
    return chunks


def index_candidate(c: Candidate) -> None:
    """(Re)build the candidate's searchable pieces and whole-profile vector."""
    pieces = [("profile", profile_text(c))] + chunk_resume(c.resume_text, get_settings().embedding_chunk_chars)
    vectors = embed_many([t for _, t in pieces])
    model = model_id()
    c.embedding = vectors[0]
    c.chunks = [
        ResumeChunk(kind=kind, position=i, text=piece, model=model, embedding=vec)
        for i, ((kind, piece), vec) in enumerate(zip(pieces, vectors, strict=True))
    ]


# ---------------------------------------------------------------- keywords


def clean_terms(terms: list[str]) -> list[str]:
    """Search terms short enough to appear verbatim in a resume ("Kafka", "REST API design")."""
    out, seen = [], set()
    for t in terms:
        t = re.sub(r"[\"()]", " ", t).strip()
        if t and len(t) <= 40 and len(t.split()) <= 4 and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out[:20]


def matched_terms(c: Candidate, terms: list[str]) -> list[str]:
    haystack = f"{c.headline or ''}\n{' '.join(c.skills)}\n{c.resume_text}".lower()
    return [t for t in terms if re.search(rf"(?<![a-z0-9]){re.escape(t.lower())}(?![a-z0-9])", haystack)]


# ---------------------------------------------------------------- retrieval


def _excluded(job_id: str | None):
    return select(Application.candidate_id).where(Application.job_id == job_id)


def _pool(col, *, exclude_job_id: str | None, groups: list[str] | None):
    """Candidates eligible for a search: not already in the job, and in one of the skill groups.
    Candidates without any group yet are always eligible, so nobody silently drops out."""
    clause = col.not_in(_excluded(exclude_job_id))
    if groups:
        in_groups = select(CandidateSkillGroup.candidate_id).where(CandidateSkillGroup.name.in_(groups))
        ungrouped = ~exists().where(CandidateSkillGroup.candidate_id == col)
        clause = clause & or_(col.in_(in_groups), ungrouped)
    return clause


def group_is_empty(db: Session, groups: list[str]) -> bool:
    """True when no candidate in the pool belongs to any of these groups."""
    return db.scalar(
        select(CandidateSkillGroup.candidate_id).where(CandidateSkillGroup.name.in_(groups)).limit(1)
    ) is None


def _keep_best(hits: dict, cid: str, sim: float, passage: str | None) -> None:
    if cid not in hits or sim > hits[cid][0]:
        hits[cid] = (sim, passage)


def vector_hits(db: Session, query: list[float], *, exclude_job_id: str | None, pool: int,
                groups: list[str] | None = None) -> dict[str, tuple[float, str | None]]:
    """{candidate_id: (best similarity, best passage)} for the nearest resume pieces."""
    model, hits = model_id(), {}
    chunk_pool = _pool(ResumeChunk.candidate_id, exclude_job_id=exclude_job_id, groups=groups)
    cand_pool = _pool(Candidate.id, exclude_job_id=exclude_job_id, groups=groups)
    legacy = ~Candidate.chunks.any()  # indexed before resume pieces existed: use the whole-resume vector

    if is_postgres():
        from pgvector.sqlalchemy import Vector

        vec = bindparam("query_embedding", query, type_=Vector(len(query)))
        # HNSW filters after the index scan; widen the scan so enough rows survive the filters.
        db.execute(text(f"SET LOCAL hnsw.ef_search = {max(40, min(int(pool), 1000))}"))
        dist = ResumeChunk.embedding.op("<=>", return_type=Float)(vec)
        rows = db.execute(
            select(ResumeChunk.candidate_id, ResumeChunk.text, dist)
            .where(ResumeChunk.model == model, ResumeChunk.embedding.is_not(None), chunk_pool)
            .order_by(dist).limit(pool)
        ).all()
        for cid, piece, d in rows:
            _keep_best(hits, cid, 1.0 - float(d), piece)
        cdist = Candidate.embedding.op("<=>", return_type=Float)(vec)
        for cid, d in db.execute(
            select(Candidate.id, cdist)
            .where(Candidate.embedding.is_not(None), cand_pool, legacy)
            .order_by(cdist).limit(pool)
        ).all():
            _keep_best(hits, cid, 1.0 - float(d), None)
        return hits

    rows = db.execute(
        select(ResumeChunk.candidate_id, ResumeChunk.text, ResumeChunk.embedding)
        .where(ResumeChunk.model == model, ResumeChunk.embedding.is_not(None), chunk_pool)
    ).all()
    for cid, piece, emb in rows:
        _keep_best(hits, cid, cosine(query, emb), piece)
    for cid, emb in db.execute(
        select(Candidate.id, Candidate.embedding).where(Candidate.embedding.is_not(None), cand_pool, legacy)
    ).all():
        _keep_best(hits, cid, cosine(query, emb), None)
    return dict(sorted(hits.items(), key=lambda kv: -kv[1][0])[:pool])


def similarity_for(db: Session, query: list[float], ids: list[str]) -> dict[str, tuple[float, str | None]]:
    """Best similarity for specific candidates (those found only by keyword)."""
    hits: dict[str, tuple[float, str | None]] = {}
    if not ids:
        return hits
    for cid, piece, emb in db.execute(
        select(ResumeChunk.candidate_id, ResumeChunk.text, ResumeChunk.embedding)
        .where(ResumeChunk.candidate_id.in_(ids), ResumeChunk.model == model_id(), ResumeChunk.embedding.is_not(None))
    ).all():
        _keep_best(hits, cid, cosine(query, emb), piece)
    for cid, emb in db.execute(select(Candidate.id, Candidate.embedding).where(Candidate.id.in_(ids))).all():
        if cid not in hits and emb is not None:
            hits[cid] = (cosine(query, emb), None)
    return hits


def keyword_hits(db: Session, terms: list[str], *, exclude_job_id: str | None, pool: int,
                 groups: list[str] | None = None) -> list[str]:
    """Candidate ids ranked by keyword relevance; only candidates matching at least one term."""
    if not terms:
        return []
    eligible = _pool(Candidate.id, exclude_job_id=exclude_job_id, groups=groups)
    if is_postgres():
        # websearch_to_tsquery never raises on user input; quoted terms are matched as phrases.
        query = func.websearch_to_tsquery("simple", " OR ".join(f'"{t}"' for t in terms))
        doc = literal_column(FTS_DOCUMENT)
        return list(db.scalars(
            select(Candidate.id).where(doc.op("@@")(query), eligible)
            .order_by(func.ts_rank_cd(doc, query).desc()).limit(pool)
        ))
    scored = []
    for c in db.scalars(select(Candidate).where(eligible)):
        if n := len(matched_terms(c, terms)):
            scored.append((n, c.id))
    return [cid for _, cid in sorted(scored, key=lambda x: -x[0])[:pool]]


def fuse(*rankings: list[str], k: int = RRF_K) -> list[str]:
    """Reciprocal rank fusion: a candidate near the top of either list rises to the top."""
    scores: dict[str, float] = defaultdict(float)
    for ranking in rankings:
        for rank, cid in enumerate(ranking):
            scores[cid] += 1.0 / (k + rank + 1)
    return sorted(scores, key=lambda cid: -scores[cid])


def hybrid_search(
    db: Session, *, query_text: str, terms: list[str], exclude_job_id: str | None, limit: int, min_similarity: float = 0.0,
    groups: list[str] | None = None,
) -> list[Match]:
    query = embed_one(query_text, kind="query")
    terms = clean_terms(terms)
    pool = max(limit * 5, 50)
    vhits = vector_hits(db, query, exclude_job_id=exclude_job_id, pool=pool, groups=groups)
    ranked = fuse(sorted(vhits, key=lambda cid: -vhits[cid][0]), keyword_hits(db, terms, exclude_job_id=exclude_job_id, pool=pool, groups=groups))
    ranked = ranked[: limit * 3]
    vhits.update(similarity_for(db, query, [cid for cid in ranked if cid not in vhits]))
    candidates = {c.id: c for c in db.scalars(select(Candidate).where(Candidate.id.in_(ranked)))}

    matches = []
    for cid in ranked:
        sim, passage = vhits.get(cid, (0.0, None))
        if sim < min_similarity or cid not in candidates:
            continue
        c = candidates[cid]
        matches.append(Match(candidate=c, similarity=round(sim, 4), passage=passage, keywords=matched_terms(c, terms)))
        if len(matches) == limit:
            break
    return matches


def unindexed_count(db: Session) -> int:
    """Candidates without any resume pieces (added before pieces existed)."""
    return db.scalar(select(func.count()).select_from(Candidate).where(~Candidate.chunks.any())) or 0


def stale_piece_count(db: Session) -> int:
    """Pieces embedded by a different model than the current one (they're ignored by search)."""
    return db.scalar(select(func.count()).select_from(ResumeChunk).where(ResumeChunk.model != model_id())) or 0
