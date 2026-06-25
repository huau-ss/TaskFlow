"""Add meeting_relations table for cross-meeting links

Revision ID: 008_add_meeting_relations
Revises: 007_set_voiceprint_model_version_default
Create Date: 2026-06-23
"""
from alembic import op
import sqlalchemy as sa


revision = '008_add_meeting_relations'
down_revision = '007_set_voiceprint_model_version_default'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'meeting_relations',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('meeting_a_id', sa.Integer(), sa.ForeignKey('meetings.id'), nullable=False, index=True),
        sa.Column('meeting_b_id', sa.Integer(), sa.ForeignKey('meetings.id'), nullable=False, index=True),
        sa.Column(
            'relation_type',
            sa.Enum('follow_up', 'related', 'prerequisite', name='relation_type', create_type=False),
            nullable=False,
        ),
        sa.Column('confidence', sa.Float(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    # 每个会议对只保留一条记录，避免重复
    op.create_index(
        'ix_meeting_relations_pair_unique',
        'meeting_relations',
        ['meeting_a_id', 'meeting_b_id'],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index('ix_meeting_relations_pair_unique', table_name='meeting_relations')
    op.drop_table('meeting_relations')
