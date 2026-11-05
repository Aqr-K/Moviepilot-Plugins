"""音乐身份与艺术家信息，与影视历史共用生命周期。"""

import sqlalchemy as sa
from alembic import op

revision = "asa_0003_music"
down_revision = "asa_0002_blacklist"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("subscribe_history", sa.Column("music_type", sa.String(32)))
    op.add_column("subscribe_history", sa.Column("artists", sa.JSON))
    op.add_column("subscribe_history", sa.Column("album", sa.Text))


def downgrade():
    raise RuntimeError("禁止自动降级插件数据库，请使用升级前备份恢复")
