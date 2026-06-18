"""Add messages and message_actions tables

Revision ID: 004_add_messages
Revises: 003_add_is_admin
Create Date: 2026-06-18

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '004_add_messages'
down_revision = '003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 创建 message_type 枚举
    message_type = postgresql.ENUM(
        'task_created', 'task_reminder', 'task_escalation', 'task_response',
        name='message_type', create_type=False
    )
    message_type.create(op.get_bind(), checkfirst=True)

    # 创建 messages 表
    op.create_table(
        'messages',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('type', message_type, nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('content', sa.Text(), nullable=True),
        sa.Column('task_id', sa.Integer(), nullable=True),
        sa.Column('sender_id', sa.Integer(), nullable=True),
        sa.Column('recipient_id', sa.Integer(), nullable=False),
        sa.Column('action_token', sa.String(length=512), nullable=True),
        sa.Column('action_url', sa.String(length=512), nullable=True),
        sa.Column('is_read', sa.Boolean(), nullable=True, default=False),
        sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ),
        sa.ForeignKeyConstraint(['sender_id'], ['employees.id'], ),
        sa.ForeignKeyConstraint(['recipient_id'], ['employees.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_messages_task_id'), 'messages', ['task_id'], unique=False)
    op.create_index(op.f('ix_messages_recipient_id'), 'messages', ['recipient_id'], unique=False)

    # 创建 message_actions 表
    op.create_table(
        'message_actions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('message_id', sa.Integer(), nullable=False),
        sa.Column('action', sa.String(length=20), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['message_id'], ['messages.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_message_actions_message_id'), 'message_actions', ['message_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_message_actions_message_id'), table_name='message_actions')
    op.drop_table('message_actions')
    op.drop_index(op.f('ix_messages_recipient_id'), table_name='messages')
    op.drop_index(op.f('ix_messages_task_id'), table_name='messages')
    op.drop_table('messages')

    # 删除枚举类型（小心其他表可能也在用）
    op.execute('DROP TYPE IF EXISTS message_type')
