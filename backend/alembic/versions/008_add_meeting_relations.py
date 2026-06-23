"""Add meeting_relations table for cross-meeting links

Revision ID: 008_add_meeting_relations
Revises: 007_set_voiceprint_model_version_default
Create Date: 2026-06-23
"""
from alembic import op


revision = '008_add_meeting_relations'
down_revision = '007_set_voiceprint_model_version_default'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'meeting_relations',
        op.Column('id', op.Integer(), primary_key=True),
        op.Column('meeting_a_id', op.Integer(), op.ForeignKey('meetings.id'), nullable=False, index=True),
        op.Column('meeting_b_id', op.Integer(), op.ForeignKey('meetings.id'), nullable=False, index=True),
        op.Column(
            'relation_type',
            op.Enum('follow_up', 'related', 'prerequisite', name='relation_type', create_type=False),
            nullable=False,
        ),
        op.Column('confidence', op.Float(), nullable=False),
        op.Column('reason', op.Text(), nullable=True),
        op.Column('created_at', op.DateTime(timezone=True), server_default=op.func.now(), nullable=False),
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
