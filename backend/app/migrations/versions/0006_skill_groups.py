"""skill groups for candidates and jobs

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-26 16:00:00.000000

Existing candidates are grouped here with the keyword rules in app.skill_groups (no LLM).
New resumes are grouped by the parsing agent.
"""

import sqlalchemy as sa
from alembic import op

from app.skill_groups import groups_for_candidate

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('candidate_skill_groups',
    sa.Column('candidate_id', sa.String(length=32), nullable=False),
    sa.Column('name', sa.String(length=60), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['candidate_id'], ['candidates.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('candidate_id', 'name')
    )
    with op.batch_alter_table('candidate_skill_groups', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_candidate_skill_groups_name'), ['name'], unique=False)

    with op.batch_alter_table('jobs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('skill_groups', sa.JSON(), nullable=True))

    bind = op.get_bind()
    candidates = sa.table('candidates', sa.column('id'), sa.column('headline'), sa.column('skills', sa.JSON),
                          sa.column('profile', sa.JSON))
    links = sa.table('candidate_skill_groups', sa.column('candidate_id'), sa.column('name'), sa.column('position'))
    rows = []
    for cid, headline, skills, profile in bind.execute(
        sa.select(candidates.c.id, candidates.c.headline, candidates.c.skills, candidates.c.profile)
    ):
        titles = [j.get("title") or "" for j in ((profile or {}).get("employment_history") or [])]
        for i, name in enumerate(groups_for_candidate(headline, skills or [], titles)):
            rows.append({"candidate_id": cid, "name": name, "position": i})
    if rows:
        op.bulk_insert(links, rows)


def downgrade() -> None:
    with op.batch_alter_table('jobs', schema=None) as batch_op:
        batch_op.drop_column('skill_groups')
    with op.batch_alter_table('candidate_skill_groups', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_candidate_skill_groups_name'))
    op.drop_table('candidate_skill_groups')
