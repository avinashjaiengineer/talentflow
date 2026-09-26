"""resume pieces for search, vector and keyword indexes, original resume files

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-26 14:00:00.000000

Existing candidates have no pieces yet; run `python -m app.reembed --missing-only` once after
upgrading (until then, search falls back to their whole-resume vector).
"""

import sqlalchemy as sa
from alembic import op

import app.db
from app.config import get_settings

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None

EMBEDDING_DIM = get_settings().embedding_dim
# Must match app.search_index.FTS_DOCUMENT exactly, or Postgres won't use the index.
FTS_DOCUMENT = "to_tsvector('simple', coalesce(headline, '') || ' ' || resume_text)"


def upgrade() -> None:
    op.create_table('resume_chunks',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('candidate_id', sa.String(length=32), nullable=False),
    sa.Column('kind', sa.String(length=30), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('model', sa.String(length=200), nullable=False),
    sa.Column('embedding', app.db.EmbeddingType(EMBEDDING_DIM), nullable=True),
    sa.ForeignKeyConstraint(['candidate_id'], ['candidates.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('resume_chunks', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_resume_chunks_candidate_id'), ['candidate_id'], unique=False)

    with op.batch_alter_table('candidates', schema=None) as batch_op:
        batch_op.add_column(sa.Column('resume_file_key', sa.String(length=500), nullable=True))

    if op.get_bind().dialect.name == "postgresql":
        # HNSW: approximate nearest-neighbour search that stays fast at millions of vectors.
        op.execute("CREATE INDEX IF NOT EXISTS ix_resume_chunks_embedding_hnsw "
                   "ON resume_chunks USING hnsw (embedding vector_cosine_ops)")
        op.execute("CREATE INDEX IF NOT EXISTS ix_candidates_embedding_hnsw "
                   "ON candidates USING hnsw (embedding vector_cosine_ops)")
        # Full-text index for the keyword half of hybrid search.
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_candidates_fts ON candidates USING gin ({FTS_DOCUMENT})")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_candidates_fts")
        op.execute("DROP INDEX IF EXISTS ix_candidates_embedding_hnsw")
    with op.batch_alter_table('candidates', schema=None) as batch_op:
        batch_op.drop_column('resume_file_key')
    with op.batch_alter_table('resume_chunks', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_resume_chunks_candidate_id'))
    op.drop_table('resume_chunks')
