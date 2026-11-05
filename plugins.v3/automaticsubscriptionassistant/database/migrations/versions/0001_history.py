"""接管未版本化的历史表，回填身份、年份与独立成功账本。"""

import sqlalchemy as sa
from alembic import op

revision = "asa_0001_history"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    columns = [
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("unique", sa.String(255), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("year", sa.String(16)),
        sa.Column("year_num", sa.Integer),
        sa.Column("type", sa.String(32)),
        sa.Column("tmdbid", sa.Integer),
        sa.Column("doubanid", sa.String(64)),
        sa.Column("bangumiid", sa.Integer),
        sa.Column("media_source", sa.String(64)),
        sa.Column("media_id", sa.String(255)),
        sa.Column("episode_group", sa.String(128)),
        sa.Column("poster", sa.Text),
        sa.Column("season", sa.Integer),
        sa.Column("candidate_key", sa.String(80)),
        sa.Column("source_item", sa.JSON),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("reason", sa.Text),
        sa.Column("time", sa.String(32), nullable=False),
    ]
    inspector = sa.inspect(connection)
    if not inspector.has_table("subscribe_history"):
        op.create_table("subscribe_history", *columns)
    else:
        existing = {c["name"] for c in inspector.get_columns("subscribe_history")}
        if not {"id", "unique", "provider", "title", "status", "time"} <= existing:
            raise RuntimeError("无法接管历史表：缺少必要字段，请先恢复完整备份")
        for column in columns:
            if column.name not in existing:
                op.add_column("subscribe_history", column)
    if not sa.inspect(connection).has_table("subscribe_handled"):
        op.create_table(
            "subscribe_handled",
            sa.Column("key", sa.String(255), primary_key=True),
            sa.Column("canonical", sa.String(255), nullable=False),
            sa.Column("provider", sa.String(64), nullable=False),
        )
    # 按旧字段优先级回填，不改写已有通用身份，不重算季号或身份键。
    history = sa.Table("subscribe_history", sa.MetaData(), autoload_with=connection)
    handled = sa.Table("subscribe_handled", sa.MetaData(), autoload_with=connection)
    rows = connection.execute(sa.select(history)).mappings().all()
    for row in rows:
        values = {}
        try:
            values["year_num"] = int(str(row["year"]).strip())
        except (TypeError, ValueError):
            values["year_num"] = None
        if not row["media_source"] or not row["media_id"]:
            for source, field in (
                ("themoviedb", "tmdbid"),
                ("douban", "doubanid"),
                ("bangumi", "bangumiid"),
                ("anilist", "anilistid"),
                ("imdb", "imdbid"),
                ("tvdb", "tvdbid"),
            ):
                identity = str(row.get(field) or "").strip()
                if identity and identity != "0":
                    values.update(media_source=source, media_id=identity)
                    break
        connection.execute(
            history.update().where(history.c.id == row["id"]).values(**values)
        )
        if row["status"] in {"subscribed", "media_exists", "subscription_exists"}:
            for key in (row["unique"], row["candidate_key"]):
                if (
                    key
                    and connection.execute(
                        sa.select(handled.c.key).where(handled.c.key == key)
                    ).first()
                    is None
                ):
                    connection.execute(
                        handled.insert().values(
                            key=key, canonical=row["unique"], provider=row["provider"]
                        )
                    )
    for table, name, fields, unique in (
        ("subscribe_history", "ix_subscribe_history_unique", ["unique"], True),
        ("subscribe_history", "ix_subscribe_history_year_num", ["year_num"], False),
        ("subscribe_history", "ix_subscribe_history_status", ["status"], False),
        ("subscribe_history", "ix_subscribe_history_time", ["time"], False),
        (
            "subscribe_history",
            "ix_subscribe_history_status_time",
            ["status", "time"],
            False,
        ),
        (
            "subscribe_history",
            "ix_subscribe_history_provider_time",
            ["provider", "time"],
            False,
        ),
        ("subscribe_handled", "ix_subscribe_handled_canonical", ["canonical"], False),
    ):
        if name not in {
            index["name"] for index in sa.inspect(connection).get_indexes(table)
        }:
            op.create_index(name, table, fields, unique=unique)


def downgrade():
    raise RuntimeError("禁止自动降级插件数据库，请使用升级前备份恢复")
