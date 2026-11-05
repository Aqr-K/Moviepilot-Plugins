"""可选真实 PostgreSQL 验证。仅连接显式传入的测试库，schema 随测试销毁。"""

import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic import command
from app.plugins.automaticsubscriptionassistant.database.backup import DatabaseBackup
from app.plugins.automaticsubscriptionassistant.database.lifecycle import (
    ensure_schema,
    migration_config,
)
from app.plugins.automaticsubscriptionassistant.schemas.history import HistoryRecord
from app.plugins.automaticsubscriptionassistant.services.blacklist import BlacklistStore
from app.plugins.automaticsubscriptionassistant.services.history import HistoryStore
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import sessionmaker

pytestmark = pytest.mark.skipif(
    not os.environ.get("ASA_TEST_POSTGRES_URL"), reason="未指定隔离的 PostgreSQL 测试库"
)


@pytest.fixture
def pg(tmp_path):
    engine = create_engine(os.environ["ASA_TEST_POSTGRES_URL"])
    schema = "asa_test_" + uuid4().hex
    other = schema + "_other"
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        connection.exec_driver_sql(f'CREATE SCHEMA "{other}"')
        connection.exec_driver_sql(
            f'CREATE TABLE "{other}".subscribe_history (marker TEXT)'
        )
        connection.exec_driver_sql(
            f"INSERT INTO \"{other}\".subscribe_history VALUES ('host-sentinel')"
        )
    scoped = engine.execution_options(schema_translate_map={None: schema})

    # 与 SDK 句柄相同：每个事务只允许在实例 schema 解析未限定名称。
    def begin(connection):
        connection.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')

    event.listen(scoped, "begin", begin)
    factory = sessionmaker(bind=scoped)
    db = SimpleNamespace(
        engine=scoped,
        factory=factory,
        history=HistoryStore(factory),
        blacklist=BlacklistStore(factory),
        backup=DatabaseBackup(scoped, "pg-instance", tmp_path),
        schema=schema,
        other=other,
    )
    try:
        yield db
    finally:
        event.remove(scoped, "begin", begin)
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
            connection.exec_driver_sql(f'DROP SCHEMA "{other}" CASCADE')
        engine.dispose()


def test_postgres_migration_and_restore_use_only_instance_schema(pg):
    pg.history.record(
        HistoryRecord(
            unique="tmdb:tv:42:s0:ggroup",
            provider="douban",
            title="特别篇",
            season=0,
            episode_group="group",
            status="subscribed",
            candidate_key="candidate:42",
        )
    )
    rule = pg.blacklist.add({"title": "T", "type": "电视剧", "tmdbid": 7}, season=0)
    snapshot = pg.backup.export()
    pg.history.clear()
    pg.blacklist.delete([rule["id"]])
    pg.backup.restore(snapshot, stopped=True, mode="replace")
    assert pg.history.is_handled("candidate:42")
    assert pg.history.get("tmdb:tv:42:s0:ggroup")["season"] == 0
    assert pg.blacklist.list() == [rule]
    pg.history.record(
        HistoryRecord(unique="new", provider="douban", title="after restore")
    )
    assert pg.history.count() == 2
    with pg.engine.connect() as connection:
        assert (
            connection.exec_driver_sql(
                f'SELECT marker FROM "{pg.other}".subscribe_history'
            ).scalar()
            == "host-sentinel"
        )
        assert inspect(connection).has_table("alembic_version", schema=pg.schema)


def test_postgres_adopts_legacy_schema_without_losing_source_or_success(pg):
    with pg.engine.begin() as connection:
        connection.execute(
            text(
                'CREATE TABLE subscribe_history (id SERIAL PRIMARY KEY, "unique" VARCHAR(255), '
                "provider VARCHAR(64), title VARCHAR(512), status VARCHAR(32), time VARCHAR(32), "
                "year VARCHAR(16), season INTEGER, imdbid VARCHAR(64))"
            )
        )
        connection.execute(
            text(
                'INSERT INTO subscribe_history ("unique", provider,title,status,time,year,season,imdbid) '
                "VALUES ('imdb:tv:tt1:s0','douban','T','subscribed','','2026',0,'tt1')"
            )
        )
    assert pg.backup.before_upgrade().exists()
    ensure_schema(pg.engine)
    row = pg.history.get("imdb:tv:tt1:s0")
    assert (row["media_source"], row["media_id"], row["season"]) == ("imdb", "tt1", 0)
    assert pg.history.query(year_min=2026)[1] == 1
    assert pg.history.is_handled("imdb:tv:tt1:s0")
    assert pg.backup.before_upgrade() is None


def test_postgres_supplied_migration_connection_stays_open(pg):
    with pg.engine.begin() as connection:
        command.upgrade(migration_config(connection), "head")
        assert not connection.closed
        assert (
            connection.execute(
                text("SELECT COUNT(*) FROM subscription_blacklist")
            ).scalar()
            == 0
        )
    ensure_schema(pg.engine)


def test_postgres_music_snapshot_preserves_artist_and_entity(pg):
    pg.history.record(
        HistoryRecord(
            unique="musicbrainz:music:recording:uuid",
            provider="qqmusic",
            title="歌名",
            type="音乐",
            music_type="recording",
            artists=["艺术家"],
            album="专辑",
            media_source="musicbrainz",
            media_id="uuid",
            status="subscribed",
        )
    )
    row = pg.blacklist.add(
        {
            "title": "歌名",
            "type": "音乐",
            "music_type": "recording",
            "artists": ["艺术家"],
            "media_source": "musicbrainz",
            "media_id": "uuid",
        }
    )
    snapshot = pg.backup.export()
    pg.history.clear()
    pg.backup.restore(snapshot, stopped=True, mode="replace")
    item = pg.history.get("musicbrainz:music:recording:uuid")
    assert (
        item["artists"] == ["艺术家"]
        and item["music_type"] == "recording"
        and item["album"] == "专辑"
    )
    assert pg.blacklist.list() == [row]
