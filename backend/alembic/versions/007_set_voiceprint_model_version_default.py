"""Set voice_prints.model_version default to ecapa-tdnn

迁移期 migration 006 把 model_version 列加进去时，server_default 设为 'mfcc-v1'
是为了兼容旧行（脚本统一把已有行标成 mfcc-v1 并降级为 unverified）。

现在 8003 主用 ECAPA-TDNN 192-d，所有新代码路径都显式写入 model_version='ecapa-tdnn'，
但列级 server_default 仍是 mfcc-v1——若未来有脚本直接 INSERT 漏掉此字段，
会把 ECAPA 192-d 向量错标成 mfcc-v1，导致 _recognize_speaker 用 mfcc-v1 库
去和 ECAPA 向量做余弦比对，跨空间匹配。

本 migration 把列 default 切到 'ecapa-tdnn'。已有行的值不动（迁移历史数据
保持 mfcc-v1，由 re_register_voiceprints.py 配合管理员逐个重新注册）。

Revision ID: 007_set_voiceprint_model_version_default
Revises: 006_add_voiceprint_model_version
Create Date: 2026-06-22
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '007_set_voiceprint_model_version_default'
down_revision = '006_add_voiceprint_model_version'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite / Postgres 都支持 ALTER COLUMN SET DEFAULT
    with op.batch_alter_table('voice_prints') as batch_op:
        batch_op.alter_column(
            'model_version',
            server_default='ecapa-tdnn',
        )


def downgrade() -> None:
    with op.batch_alter_table('voice_prints') as batch_op:
        batch_op.alter_column(
            'model_version',
            server_default='mfcc-v1',
        )