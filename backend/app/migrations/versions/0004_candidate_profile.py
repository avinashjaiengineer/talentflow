"""structured candidate profile: work history, education, certifications, projects, links

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-26 12:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('candidates', schema=None) as batch_op:
        batch_op.add_column(sa.Column('profile', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('candidates', schema=None) as batch_op:
        batch_op.drop_column('profile')
