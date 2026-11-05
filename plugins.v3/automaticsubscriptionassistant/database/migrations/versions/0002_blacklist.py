"""忽略规则与持久迁移状态纳入自有数据库。"""

import sqlalchemy as sa
from alembic import op

revision = "asa_0002_blacklist"
down_revision = "asa_0001_history"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "subscription_blacklist",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("fingerprint", sa.String(64), nullable=False, unique=True),
        sa.Column("payload", sa.JSON, nullable=False),
    )
    op.create_table(
        "database_state",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", sa.JSON, nullable=False),
    )


def downgrade():
    raise RuntimeError("禁止自动降级插件数据库，请使用升级前备份恢复")
