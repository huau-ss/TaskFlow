"""Migrate to FunASR CAM++ embeddings — clear old MFCC voiceprints

MFCC 256-dim embeddings (from deprecated 8003 service) are incompatible with
FunASR CAM++ embeddings. All existing voiceprints must be cleared and re-registered
through the new FunASR embedding endpoint.

Revision ID: 006
Revises: 005
Create Date: 2026-06-22

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "006"
down_revision = "005_add_task_match_fields"
branch_labels = None
depends_on = None


def upgrade():
    # 清空旧的 MFCC 声纹（与 CAM++ 维度不兼容，无法恢复）
    op.execute("DELETE FROM voice_prints")

    # 添加 embedding_model 列，标记声纹来源模型
    op.add_column(
        "voice_prints",
        sa.Column(
            "embedding_model",
            sa.String(100),
            nullable=True,
            server_default="cam++",
        ),
    )


def downgrade():
    op.drop_column("voice_prints", "embedding_model")
    # 注意：数据丢失是故意的 — MFCC 和 CAM++ 之间不可互转
