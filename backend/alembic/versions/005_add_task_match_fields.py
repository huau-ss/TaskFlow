"""Add match_method and match_confidence to tasks table

Revision ID: 005_add_task_match_fields
Revises: 004
Create Date: 2026-06-18

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '005_add_task_match_fields'
down_revision = '004_add_messages'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'tasks',
        sa.Column('match_method', sa.String(length=20), nullable=True)
    )
    op.add_column(
        'tasks',
        sa.Column('match_confidence', sa.Float(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('tasks', 'match_confidence')
    op.drop_column('tasks', 'match_method')
