"""Add voice prints and speaker recognition

Revision ID: 002
Revises: 001
Create Date: 2026-06-17 11:00:00.000000

这个迁移添加了：
1. voice_prints 表：存储员工的声纹特征
2. transcript_segments.employee_id 字段：关联识别出的说话人
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. 创建 voice_prints 表
    op.create_table(
        "voice_prints",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id"), nullable=False, index=True),
        # 声纹特征向量，存储为 JSON 字符串
        sa.Column("embedding", sa.Text(), nullable=False),
        # 来源音频路径
        sa.Column("source_audio_path", sa.String(512), nullable=True),
        # 音频时长（秒）
        sa.Column("audio_duration", sa.Float(), nullable=True),
        # 是否已验证
        sa.Column("is_verified", sa.Boolean(), server_default=sa.text("false")),
        # 备注
        sa.Column("note", sa.String(255), nullable=True),
        # 创建时间
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # 2. 给 transcript_segments 添加 employee_id 字段
    op.add_column(
        "transcript_segments",
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id"), nullable=True, index=True)
    )

    # 3. 添加索引以加快说话人查询（如果不存在则创建）
    op.create_index(
        "ix_transcript_segments_employee_id",
        "transcript_segments",
        ["employee_id"],
        if_not_exists=True
    )
    op.create_index(
        "ix_voice_prints_employee_verified",
        "voice_prints",
        ["employee_id", "is_verified"],
        if_not_exists=True
    )


def downgrade() -> None:
    # 1. 删除索引
    op.drop_index("ix_voice_prints_employee_verified", table_name="voice_prints")
    op.drop_index("ix_transcript_segments_employee_id", table_name="transcript_segments")

    # 2. 删除 employee_id 列
    op.drop_column("transcript_segments", "employee_id")

    # 3. 删除 voice_prints 表
    op.drop_table("voice_prints")
