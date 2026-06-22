"""Add model_version to voice_prints

区分 MFCC 256-d 与 ECAPA-TDNN 192-d embedding，两者不在同一向量空间，
识别时必须按 model_version 过滤，否则跨空间余弦相似度无意义。

列级 server_default 当时设为 'mfcc-v1' 是为了兼容旧行（脚本统一把已有
行标成 mfcc-v1 并降级为 unverified）。后续由 migration 007 切到 'ecapa-tdnn'。

Revision ID: 006_add_voiceprint_model_version
Revises: 005_add_task_match_fields
Create Date: 2026-06-22
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '006_add_voiceprint_model_version'
down_revision = '005_add_task_match_fields'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 注意：server_default='mfcc-v1' 是迁移期临时值，仅用于兼容已有旧行。
    # 008 列级 default 切到 'ecapa-tdnn'，避免新 INSERT 漏传时回退到 mfcc。
    op.add_column(
        'voice_prints',
        sa.Column(
            'model_version',
            sa.String(length=32),
            nullable=False,
            server_default='mfcc-v1',
        ),
    )
    # 旧声纹全部标记为 mfcc-v1 并降级为未验证，强制管理员在新模型下重新注册
    op.execute(
        "UPDATE voice_prints SET model_version = 'mfcc-v1', is_verified = false "
        "WHERE model_version IS NULL OR model_version = '' OR model_version = 'mfcc-v1'"
    )


def downgrade() -> None:
    op.drop_column('voice_prints', 'model_version')
