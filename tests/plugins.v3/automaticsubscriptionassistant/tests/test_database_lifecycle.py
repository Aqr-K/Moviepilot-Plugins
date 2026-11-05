"""插件数据库生命周期：版本升级、故障、事务、旧 KV 接管和快照恢复。"""

import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Event, Lock
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from alembic import command
from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.plugins.automaticsubscriptionassistant import (
    AutomaticSubscriptionAssistant as Plugin,
)
from app.plugins.automaticsubscriptionassistant.database.backup import (
    DatabaseBackup,
    checksum,
)
from app.plugins.automaticsubscriptionassistant.database.blacklist import (
    migrate_blacklist_from_kv,
)
from app.plugins.automaticsubscriptionassistant.database.legacy import (
    migrate_history_from_kv,
)
from app.plugins.automaticsubscriptionassistant.database.lifecycle import (
    DatabaseCompatibilityError,
    ensure_schema,
    migration_config,
)
from app.plugins.automaticsubscriptionassistant.db.models import (
    Base,
)
from app.plugins.automaticsubscriptionassistant.schemas.history import HistoryRecord
from app.plugins.automaticsubscriptionassistant.services.blacklist import (
    BlacklistStore,
)
from app.plugins.automaticsubscriptionassistant.services.history import HistoryStore
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

HEAD = "asa_0003_music"


@pytest.fixture
def database(tmp_path):
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    factory = sessionmaker(bind=engine)
    yield SimpleNamespace(
        engine=engine,
        factory=factory,
        history=HistoryStore(factory),
        blacklist=BlacklistStore(factory),
        backup=DatabaseBackup(engine, "test-instance", tmp_path / "backups"),
    )
    engine.dispose()


def kv(data):
    return (
        lambda key: deepcopy(data.get(key)),
        lambda key, value: data.__setitem__(key, deepcopy(value)),
        lambda key: data.pop(key, None),
    )


def legacy_add(data, media, *, season=None):
    """构造已发布版本的 KV 快照，迁移测试不依赖旧 CRUD 实现。"""
    from app.plugins.automaticsubscriptionassistant.schemas.blacklist import media_snapshot
    from uuid import uuid4
    snapshot = media_snapshot(media)
    row = {**snapshot, "season": season, "aliases": [snapshot],
           "id": uuid4().hex, "time": "2026-11-04 00:00:00"}
    data.setdefault("subscription_blacklist", []).insert(0, row)
    return row


def heads(engine):
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_heads()


def seed(database):
    database.history.record(
        HistoryRecord(
            unique="tmdb:tv:42:s0:gabc",
            provider="douban",
            title="特别篇",
            season=0,
            episode_group="abc",
            media_source="themoviedb",
            media_id="42",
            candidate_key="candidate:42",
            year="2026",
            status="subscribed",
        )
    )
    return database.blacklist.add(
        {"title": "忽略剧", "type": "电视剧", "tmdbid": 7}, season=0
    )


def test_blank_database_migrates_and_repeated_upgrade_keeps_data(database):
    rule = seed(database)
    ensure_schema(database.engine)
    assert heads(database.engine) == (HEAD,)
    assert (
        database.history.providers_for(["tmdb:tv:42:s0:gabc"])["tmdb:tv:42:s0:gabc"]
        == "douban"
    )
    assert database.history.is_handled("candidate:42")
    assert (
        database.blacklist.match(
            {"title": "忽略剧", "type": "电视剧", "tmdbid": 7}, season=0
        )["id"]
        == rule["id"]
    )
    with database.engine.connect() as connection:
        indexes = inspect(connection).get_indexes("subscribe_history")
        assert any(
            index["unique"] and index["column_names"] == ["unique"] for index in indexes
        )


def test_unknown_revision_rejects_upgrade_without_changing_records(database):
    seed(database)
    with database.engine.begin() as connection:
        connection.execute(
            text("UPDATE alembic_version SET version_num = 'future_revision'")
        )
    with pytest.raises(DatabaseCompatibilityError):
        ensure_schema(database.engine)
    assert heads(database.engine) == ("future_revision",)
    with database.engine.connect() as connection:
        assert (
            connection.execute(text("SELECT COUNT(*) FROM subscribe_history")).scalar()
            == 1
        )


def test_partial_schema_is_not_silently_recreated(database):
    seed(database)
    with database.engine.begin() as connection:
        connection.execute(text("DROP TABLE subscribe_handled"))
    with pytest.raises(DatabaseCompatibilityError, match="subscribe_handled"):
        ensure_schema(database.engine)
    assert not inspect(database.engine).has_table("subscribe_handled")


def test_same_engine_after_complete_rebuild_is_not_cached(database):
    seed(database)
    Base.metadata.drop_all(database.engine)
    with database.engine.begin() as connection:
        connection.execute(text("DROP TABLE alembic_version"))
    fresh = HistoryStore(database.factory)
    assert fresh.count() == 0
    assert heads(database.engine) == (HEAD,)


def test_failed_ddl_is_rolled_back_then_retry_upgrades(database, monkeypatch):
    with database.engine.begin() as connection:
        connection.execute(
            text(
                'CREATE TABLE subscribe_history (id INTEGER PRIMARY KEY, "unique" VARCHAR(255), '
                "provider VARCHAR(64), title VARCHAR(512), status VARCHAR(32), time VARCHAR(32))"
            )
        )
    original = Operations.add_column

    def fail(self, table, column, **kwargs):
        if column.name == "year_num":
            raise RuntimeError("simulated interruption")
        return original(self, table, column, **kwargs)

    monkeypatch.setattr(Operations, "add_column", fail)
    with pytest.raises(RuntimeError, match="interruption"):
        ensure_schema(database.engine)
    assert "year" not in {
        column["name"]
        for column in inspect(database.engine).get_columns("subscribe_history")
    }
    assert heads(database.engine) == ()
    monkeypatch.setattr(Operations, "add_column", original)
    ensure_schema(database.engine)
    assert heads(database.engine) == (HEAD,)


def test_migration_uses_supplied_connection_without_a_database_url(database):
    with database.engine.begin() as connection:
        command.upgrade(migration_config(connection), "head")
    assert heads(database.engine) == (HEAD,)


def test_concurrent_first_access_does_not_interleave_alembic_contexts(database):
    def write(index):
        HistoryStore(database.factory).record(
            HistoryRecord(unique=f"movie:{index}", provider="douban", title="T")
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(write, range(12)))
    assert database.history.count() == 12
    assert heads(database.engine) == (HEAD,)


def test_uow_rolls_back_and_closes_on_commit_failure(database):
    ensure_schema(database.engine)
    calls = []

    class FailingSession(Session):
        def commit(self):
            self.flush()
            raise RuntimeError("commit failed")

        def rollback(self):
            calls.append("rollback")
            return super().rollback()

        def close(self):
            calls.append("close")
            return super().close()

    store = HistoryStore(sessionmaker(bind=database.engine, class_=FailingSession))
    with pytest.raises(RuntimeError, match="commit failed"):
        store.record(
            HistoryRecord(
                unique="new", title="T", provider="douban", status="subscribed"
            )
        )
    assert calls == ["rollback", "close"]
    assert database.history.count() == 0
    assert not database.history.is_handled("new")


def test_old_kv_blacklist_is_atomic_archived_and_preserves_ids(database):
    data = {}
    row = legacy_add(data, {"title": "特别篇", "type": "电视剧", "tmdbid": 1}, season=0)
    migrate_blacklist_from_kv(database.factory, *kv(data))
    assert "subscription_blacklist" not in data
    assert data["subscription_blacklist_migrated_backup"] == [row]
    assert database.blacklist.list() == [row]
    # 后续启动不能把已删除的 SQL 规则从归档重新导入。
    database.blacklist.delete([row["id"]])
    migrate_blacklist_from_kv(database.factory, *kv(data))
    assert database.blacklist.list() == []


def test_blacklist_corrupt_second_row_rolls_back_entire_batch(database):
    data = {}
    legacy_add(data, {"title": "T", "type": "电影"})
    data["subscription_blacklist"].append({"id": "broken"})
    original = deepcopy(data["subscription_blacklist"])
    with pytest.raises(ValueError):
        migrate_blacklist_from_kv(database.factory, *kv(data))
    assert data["subscription_blacklist"] == original
    assert database.blacklist.list() == []


def test_blacklist_backup_readback_failure_keeps_source(database):
    data = {}
    legacy_add(data, {"title": "T", "type": "电影"})
    get, _, delete = kv(data)
    with pytest.raises(RuntimeError, match="备份"):
        migrate_blacklist_from_kv(database.factory, get, lambda *_: None, delete)
    assert len(data["subscription_blacklist"]) == 1
    assert database.blacklist.list() == []


def test_blacklist_cleanup_retry_does_not_resurrect_deleted_rule(database):
    data = {}
    get, save, delete = kv(data)
    row = legacy_add(data, {"title": "T", "type": "电影"})
    with pytest.raises(RuntimeError, match="收尾"):
        migrate_blacklist_from_kv(database.factory, get, save, lambda *_: False)
    database.blacklist.delete([row["id"]])
    migrate_blacklist_from_kv(database.factory, get, save, delete)
    assert database.blacklist.list() == []
    assert "subscription_blacklist" not in data


def test_history_backup_must_be_readable_before_source_is_deleted(database):
    data = {"history": [{"unique": "old", "provider": "douban", "title": "T"}]}
    get, _, delete = kv(data)
    result = migrate_history_from_kv(database.history, get, lambda *_: None, delete)
    assert result.error and "回读" in result.error
    assert "history" in data
    assert database.history.count() == 0


def test_upgrade_backup_is_created_once_and_retains_legacy_columns(database):
    with database.engine.begin() as connection:
        connection.execute(
            text(
                'CREATE TABLE subscribe_history (id INTEGER PRIMARY KEY, "unique" VARCHAR(255), '
                "provider VARCHAR(64), title VARCHAR(512), status VARCHAR(32), time VARCHAR(32), imdbid VARCHAR(64))"
            )
        )
        connection.execute(
            text(
                "INSERT INTO subscribe_history VALUES (1,'old','douban','T','subscribed','','tt1')"
            )
        )
    path = database.backup.before_upgrade()
    snapshot = json.loads(path.read_text())
    assert snapshot["payload"]["tables"]["subscribe_history"][0]["imdbid"] == "tt1"
    assert snapshot["checksum"] == checksum(snapshot["payload"])
    ensure_schema(database.engine)
    assert database.backup.before_upgrade() is None
    assert len(list(path.parent.glob("*.json"))) == 1


def test_upgrade_backup_failure_prevents_plugin_job_start(
    database, monkeypatch, tmp_path
):
    plugin, _ = bare_plugin(database, monkeypatch, tmp_path)
    monkeypatch.setattr(
        DatabaseBackup, "before_upgrade", MagicMock(side_effect=OSError("disk full"))
    )
    config = {"global": {"enabled": True, "onlyonce": True}}
    plugin.init_plugin(config)
    assert not plugin._database_ready
    assert not plugin.get_state()
    assert plugin.get_service() == []
    plugin._schedule_once.assert_not_called()
    assert config["global"]["onlyonce"] is True
    assert "disk full" in plugin._database_error
    assert not inspect(database.engine).has_table("subscribe_history")


def bare_plugin(database, monkeypatch, tmp_path, data=None):
    import app.plugins.automaticsubscriptionassistant as entry

    plugin = Plugin.__new__(Plugin)
    plugin._event, plugin._scheduler = Event(), None
    plugin._run_state, plugin._run_lock = {}, Lock()
    plugin._test_last, plugin._test_lock = {}, Lock()
    plugin._database_ready = False
    handle = SimpleNamespace(
        engine=database.engine,
        session=database.factory,
        plugin_id="test-instance",
        dispose=MagicMock(),
    )
    plugin.get_database = lambda: handle
    plugin.get_data_path = lambda: tmp_path
    data = data if data is not None else {}
    plugin.get_data, plugin.save_data, plugin.del_data = kv(data)
    plugin._schedule_once = MagicMock()
    plugin._reset_oneshot_flags = MagicMock()
    monkeypatch.setattr(entry, "DownloadChain", MagicMock())
    monkeypatch.setattr(entry, "SubscribeChain", MagicMock())
    return plugin, handle


def test_failed_import_disables_all_execution_then_can_retry(
    database, monkeypatch, tmp_path
):
    data = {
        "history": [
            {
                "unique": "old",
                "provider": "douban",
                "title": "T",
                "status": "subscribed",
            }
        ]
    }
    plugin, handle = bare_plugin(database, monkeypatch, tmp_path, data)
    save = plugin.save_data
    plugin.save_data = lambda *_: False
    plugin.init_plugin({"global": {"enabled": True, "onlyonce": True}})
    assert not plugin._database_ready and plugin._event.is_set()
    assert plugin.api_run({"provider_id": "douban"})["code"] == 1
    assert plugin.api_history_recognize({"unique": "old"})["code"] == 1
    plugin._schedule_once.assert_not_called()
    plugin.save_data = save
    plugin.init_plugin({"global": {"enabled": True}})
    assert plugin._database_ready and not plugin._event.is_set()
    assert database.history.is_handled("old")
    plugin.stop_service()
    assert not plugin._database_ready
    handle.dispose.assert_not_called()
    assert database.history.is_handled("old")


@pytest.mark.parametrize("mode", ["merge", "replace"])
def test_restore_keeps_season_zero_group_source_ledger_and_blacklist(database, mode):
    row = seed(database)
    snapshot = database.backup.export()
    database.history.clear()
    database.blacklist.delete([row["id"]])
    database.backup.restore(snapshot, stopped=True, mode=mode)
    record = database.history.get("tmdb:tv:42:s0:gabc")
    assert (record["season"], record["episode_group"], record["media_source"]) == (
        0,
        "abc",
        "themoviedb",
    )
    assert database.history.is_handled("candidate:42")
    assert database.history.providers_for([record["unique"]]) == {
        record["unique"]: "douban"
    }
    assert database.blacklist.list() == [row]
    # 恢复后自增主键仍可写入。
    database.history.record(HistoryRecord(unique="new", provider="douban", title="N"))
    assert database.history.count() == 2


def test_merge_restore_does_not_downgrade_existing_success(database):
    database.history.record(
        HistoryRecord(unique="a", title="T", provider="douban", status="filtered")
    )
    snapshot = database.backup.export()
    database.history.record(
        HistoryRecord(unique="a", title="T", provider="mikan", status="subscribed")
    )
    database.backup.restore(snapshot, stopped=True)
    assert database.history.get("a")["status"] == "subscribed"
    assert database.history.get("a")["provider"] == "mikan"


@pytest.mark.parametrize(
    "change", ["checksum", "instance", "revision", "table", "rule"]
)
def test_restore_rejects_invalid_snapshot_without_modifying_data(database, change):
    seed(database)
    snapshot = database.backup.export()
    before = deepcopy(snapshot["payload"]["tables"])
    if change == "checksum":
        snapshot["checksum"] = "bad"
    else:
        payload = snapshot["payload"]
        if change == "instance":
            payload["instance"] = "other-instance"
        if change == "revision":
            payload["revisions"] = ["future"]
        if change == "table":
            payload["tables"]["arbitrary_host_table"] = []
        if change == "rule":
            payload["tables"]["subscription_blacklist"][0]["payload"]["aliases"] = None
        snapshot["checksum"] = checksum(payload)
    with pytest.raises(ValueError):
        database.backup.restore(snapshot, stopped=True, mode="replace")
    assert database.backup.export()["payload"]["tables"] == before


def test_restore_requires_stopped_and_rolls_back_inserts_after_delete(database):
    seed(database)
    snapshot = database.backup.export()
    with pytest.raises(ValueError, match="停止"):
        database.backup.restore(snapshot)
    snapshot["payload"]["tables"]["subscribe_history"].append(
        deepcopy(snapshot["payload"]["tables"]["subscribe_history"][0])
    )
    snapshot["checksum"] = checksum(snapshot["payload"])
    with pytest.raises(IntegrityError):
        database.backup.restore(snapshot, stopped=True, mode="replace")
    assert database.history.is_handled("candidate:42")
    assert database.history.count() == 1
    assert len(database.blacklist.list()) == 1
    assert len(list(database.backup.directory.glob("*before-restore*.json"))) == 1


def test_sql_blacklist_used_by_executor_even_without_kv(database):
    from app.plugins.automaticsubscriptionassistant.core.config import GlobalConfig
    from app.plugins.automaticsubscriptionassistant.core.executor import (
        SubscribeExecutor,
    )
    from app.plugins.automaticsubscriptionassistant.core.filters import FilterChain
    from app.plugins.automaticsubscriptionassistant.core.provider import ProviderContext
    from app.plugins.automaticsubscriptionassistant.schemas import (
        RankMediaItem,
        SubscribeStatus,
    )
    from app.schemas.types import MediaType

    database.blacklist.add({"title": "T", "type": "电影", "tmdbid": 9})
    ctx = ProviderContext(
        MagicMock(), MagicMock(), MagicMock(), MagicMock(), blacklist=database.blacklist
    )
    result = SubscribeExecutor(ctx, GlobalConfig({})).process(
        RankMediaItem(title="T", tmdb_id=9, type_hint=MediaType.MOVIE),
        SimpleNamespace(provider_id="douban"),
        FilterChain([]),
        database.history,
        {},
    )
    assert result.status == SubscribeStatus.BLACKLISTED
    ctx.chain.recognize_media.assert_not_called()
    ctx.subscribechain.add.assert_not_called()


def test_missing_unique_index_is_rejected(database):
    seed(database)
    with database.engine.begin() as connection:
        connection.execute(text("DROP INDEX ix_subscribe_history_unique"))
    with pytest.raises(DatabaseCompatibilityError, match="唯一约束"):
        ensure_schema(database.engine)


def test_old_session_notices_revision_changed_after_initialization(database):
    seed(database)
    with database.engine.begin() as connection:
        connection.execute(
            text("UPDATE alembic_version SET version_num = 'future_revision'")
        )
    with pytest.raises(DatabaseCompatibilityError):
        database.history.record(
            HistoryRecord(unique="unsafe", provider="douban", title="T")
        )
    with database.engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT COUNT(*) FROM subscribe_history WHERE \"unique\"='unsafe'")
            ).scalar()
            == 0
        )


@pytest.mark.parametrize("phase", ["recognition", "library", "subscription"])
def test_stop_during_network_does_not_subscribe_or_write_old_history(database, phase):
    from app.plugins.automaticsubscriptionassistant.core.config import GlobalConfig
    from app.plugins.automaticsubscriptionassistant.core.executor import (
        SubscribeExecutor,
    )
    from app.plugins.automaticsubscriptionassistant.core.filters import FilterChain
    from app.plugins.automaticsubscriptionassistant.schemas import (
        RankMediaItem,
        SubscribeStatus,
    )
    from app.schemas.types import MediaType
    from test_executor import _PROVIDER, _make_ctx, _mediainfo

    ctx = _make_ctx()
    ctx.event = Event()
    ctx.blacklist = database.blacklist

    def recognize(**kwargs):
        if phase == "recognition":
            ctx.event.set()
        return _mediainfo()

    def library(**kwargs):
        if phase == "library":
            ctx.event.set()
            return True, {}
        return False, {}

    def existing(**kwargs):
        ctx.event.set()
        return True

    ctx.chain.recognize_media.side_effect = recognize
    ctx.downloadchain.get_no_exists_info.side_effect = library
    ctx.subscribechain.exists.side_effect = existing
    result = SubscribeExecutor(ctx, GlobalConfig({})).process(
        RankMediaItem(title="T", tmdb_id=9, type_hint=MediaType.MOVIE),
        _PROVIDER,
        FilterChain([]),
        database.history,
        {},
    )
    assert result.status == SubscribeStatus.ERROR
    ctx.subscribechain.add.assert_not_called()
    assert database.history.count() == 0


def test_sqlite_upgrade_backup_includes_wal_commits_and_version(tmp_path):
    import sqlite3

    engine = create_engine(f"sqlite:///{tmp_path / 'plugin.db'}")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("PRAGMA journal_mode=WAL")
            connection.exec_driver_sql("CREATE TABLE subscribe_history (marker TEXT)")
            connection.exec_driver_sql(
                "INSERT INTO subscribe_history VALUES ('committed-in-wal')"
            )
        backup = DatabaseBackup(engine, "test-instance", tmp_path / "backups")
        path = backup.before_upgrade()
        with sqlite3.connect(path.with_suffix(".sqlite")) as snapshot:
            assert snapshot.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert (
                snapshot.execute("SELECT marker FROM subscribe_history").fetchone()[0]
                == "committed-in-wal"
            )
        assert path.with_suffix(".sqlite").stat().st_mode & 0o777 == 0o600
    finally:
        engine.dispose()


def test_history_source_change_during_import_is_not_deleted(database):
    data = {"history": [{"unique": "a", "title": "A", "provider": "douban"}]}
    get, save, delete = kv(data)

    class ConcurrentSource:
        def get(self, key):
            return database.history.get(key)

        def record(self, record):
            database.history.record(record)
            data["history"].append({"unique": "b", "title": "B", "provider": "mikan"})

    result = migrate_history_from_kv(ConcurrentSource(), get, save, delete)
    assert result.error and "变化" in result.error
    assert len(data["history"]) == 2
    assert "history_migration" not in data


def test_blacklist_sql_commit_failure_keeps_kv_and_rolls_back_checkpoint(database):
    data = {}
    get, save, delete = kv(data)
    legacy_add(data, {"title": "T", "type": "电影"})
    ensure_schema(database.engine)

    class BrokenCommit(Session):
        def commit(self):
            self.flush()
            raise RuntimeError("commit failure")

    with pytest.raises(RuntimeError, match="commit failure"):
        migrate_blacklist_from_kv(
            sessionmaker(bind=database.engine, class_=BrokenCommit), get, save, delete
        )
    assert "subscription_blacklist" in data
    assert database.blacklist.list() == []
    migrate_blacklist_from_kv(database.factory, get, save, delete)
    assert "subscription_blacklist" not in data
    assert len(database.blacklist.list()) == 1


def test_restore_does_not_silently_replace_null_with_orm_default(database):
    seed(database)
    snapshot = database.backup.export()
    snapshot["payload"]["tables"]["subscribe_history"][0]["provider"] = None
    snapshot["checksum"] = checksum(snapshot["payload"])
    with pytest.raises(ValueError, match="不能为空"):
        database.backup.restore(snapshot, stopped=True, mode="replace")
    assert database.history.get("tmdb:tv:42:s0:gabc")["provider"] == "douban"
