"""resume intake from job portals

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-26 10:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('intake_items',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('source', sa.String(length=30), nullable=False),
    sa.Column('external_id', sa.String(length=500), nullable=False),
    sa.Column('portal', sa.String(length=60), nullable=True),
    sa.Column('subject', sa.String(length=500), nullable=True),
    sa.Column('sender', sa.String(length=320), nullable=True),
    sa.Column('status', sa.Enum('imported', 'duplicate', 'skipped', 'failed', name='intakestatus'), nullable=False),
    sa.Column('detail', sa.Text(), nullable=True),
    sa.Column('candidate_id', sa.String(length=32), nullable=True),
    sa.Column('job_id', sa.String(length=32), nullable=True),
    sa.Column('application_id', sa.String(length=32), nullable=True),
    sa.Column('received_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['candidate_id'], ['candidates.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source', 'external_id')
    )
    with op.batch_alter_table('intake_items', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_intake_items_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_intake_items_status'), ['status'], unique=False)

    # Postgres stores task kinds as a native enum; SQLite stores plain strings.
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TYPE taskkind ADD VALUE IF NOT EXISTS 'intake'")


def downgrade() -> None:
    # Postgres can't drop enum values; the extra task kind is left in place (harmless).
    op.execute("DELETE FROM agent_tasks WHERE kind = 'intake'")
    with op.batch_alter_table('intake_items', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_intake_items_status'))
        batch_op.drop_index(batch_op.f('ix_intake_items_created_at'))

    op.drop_table('intake_items')
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TYPE IF EXISTS intakestatus")
