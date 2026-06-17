"""Initial schema

Revision ID: 001
Revises:
Create Date: 2026-06-17
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "employees",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("manager_id", sa.Integer(), sa.ForeignKey("employees.id"), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "meetings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column("nas_path", sa.String(512), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("uploaded", "transcribing", "transcribed", "failed", name="meeting_status"),
            server_default="uploaded",
        ),
        sa.Column("asr_error", sa.Text(), nullable=True),
        sa.Column("creator_id", sa.Integer(), sa.ForeignKey("employees.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "transcript_segments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("meeting_id", sa.Integer(), sa.ForeignKey("meetings.id"), nullable=False, index=True),
        sa.Column("speaker_label", sa.String(50), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("start_time", sa.Float(), nullable=True),
        sa.Column("end_time", sa.Float(), nullable=True),
        sa.Column("sequence", sa.Integer(), server_default="0"),
    )
    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending", "accepted", "rejected", "in_progress", "completed",
                "incomplete", "overdue", "escalated", name="task_status",
            ),
            server_default="pending",
        ),
        sa.Column("executor_id", sa.Integer(), sa.ForeignKey("employees.id"), nullable=True),
        sa.Column("meeting_id", sa.Integer(), sa.ForeignKey("meetings.id"), nullable=True),
        sa.Column("source_segment_ids", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "task_updates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("update_type", sa.String(20), nullable=False),
        sa.Column("status_snapshot", sa.String(20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "permission_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("executor_id", sa.Integer(), sa.ForeignKey("employees.id"), nullable=True),
        sa.Column("escalation_manager_id", sa.Integer(), sa.ForeignKey("employees.id"), nullable=True),
        sa.Column("skip_direct_manager", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("auto_escalate", sa.Boolean(), server_default=sa.text("true")),
    )
    op.create_table(
        "email_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id"), nullable=True),
        sa.Column("recipient_email", sa.String(255), nullable=False),
        sa.Column("message_id", sa.String(255), nullable=True),
        sa.Column("action_token", sa.String(512), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("email_logs")
    op.drop_table("permission_rules")
    op.drop_table("task_updates")
    op.drop_table("tasks")
    op.drop_table("transcript_segments")
    op.drop_table("meetings")
    op.drop_table("employees")
    op.execute("DROP TYPE IF EXISTS meeting_status")
    op.execute("DROP TYPE IF EXISTS task_status")
