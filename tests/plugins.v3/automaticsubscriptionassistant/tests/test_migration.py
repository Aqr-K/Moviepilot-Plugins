"""core/migration.py 单元测试：存量历史从插件 KV 搬进自有表。"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.plugins.automaticsubscriptionassistant.core.history import HISTORY_KEY, HistoryStore
from app.plugins.automaticsubscriptionassistant.core.migration import (
    BACKUP_KEY,
    MIGRATION_KEY,
    migrate_history_from_kv,
)


def _store():
    """建一个跑在内存库上的仓库。"""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    return HistoryStore(sessionmaker(bind=engine))


def _kv(initial=None):
    """伪造 _PluginBase 的 get_data/save_data/del_data 三件套。"""
    data = dict(initial or {})
    return data, (lambda k: data.get(k),
                  lambda k, v: data.__setitem__(k, v),
                  lambda k: data.pop(k, None))


def _rec(unique, status="subscribed", title="T", time="2026-01-01 08:00:00"):
    return {"unique": unique, "provider": "douban", "title": title,
            "year": "2021", "status": status, "time": time}


def test_migrates_records_and_archives_source():
    data, (get_data, save_data, del_data) = _kv({
        HISTORY_KEY: [_rec("tmdb:movie:1"), _rec("tmdb:movie:2", status="filtered")],
    })
    store = _store()

    result = migrate_history_from_kv(store, get_data, save_data, del_data)

    assert result.performed is True
    assert result.imported == 2 and result.skipped == 0
    # 记录进了表
    assert store.count() == 2
    assert {r["unique"] for r in store.values()} == {"tmdb:movie:1", "tmdb:movie:2"}
    # 状态语义随记录一并迁移
    assert store.is_handled("tmdb:movie:1") is True
    assert store.is_handled("tmdb:movie:2") is False
    # 原键移除，原值留档，并写下可追溯的标记
    assert HISTORY_KEY not in data
    assert len(data[BACKUP_KEY]) == 2
    assert data[MIGRATION_KEY]["imported"] == 2
    assert data[MIGRATION_KEY]["source_total"] == 2
    assert data[MIGRATION_KEY]["migrated_at"]


def test_preserves_all_fields():
    source = _rec("tmdb:tv:1396")
    source.update({"type": "电视剧", "tmdbid": 1396, "doubanid": "d1",
                   "bangumiid": 7, "poster": "p.jpg", "season": 5,
                   "reason": "媒体库已存在"})
    data, (get_data, save_data, del_data) = _kv({HISTORY_KEY: [source]})
    store = _store()

    migrate_history_from_kv(store, get_data, save_data, del_data)

    got = store.get("tmdb:tv:1396")
    for field in ("provider", "title", "year", "type", "tmdbid", "doubanid",
                  "bangumiid", "poster", "season", "status", "reason", "time"):
        assert got[field] == source[field], field


def test_year_becomes_filterable():
    # 迁移时解析出年份整数列，发行年份区间筛选才能下推 SQL。
    data, (get_data, save_data, del_data) = _kv({
        HISTORY_KEY: [_rec("a"), dict(_rec("b"), year="1999"), dict(_rec("c"), year="")],
    })
    store = _store()

    migrate_history_from_kv(store, get_data, save_data, del_data)

    assert {r["unique"] for r in store.query(year_min=2000)[0]} == {"a"}
    assert {r["unique"] for r in store.query(year_max=2000)[0]} == {"b"}
    # 年份缺失的记录在有区间约束时不入选，无约束时照常返回
    assert store.query()[1] == 3


def test_no_op_when_nothing_to_migrate():
    data, (get_data, save_data, del_data) = _kv({})
    store = _store()

    result = migrate_history_from_kv(store, get_data, save_data, del_data)

    assert result.performed is False
    assert store.count() == 0
    assert MIGRATION_KEY not in data and BACKUP_KEY not in data


def test_empty_legacy_list_is_cleaned_without_marker():
    data, (get_data, save_data, del_data) = _kv({HISTORY_KEY: []})
    store = _store()

    result = migrate_history_from_kv(store, get_data, save_data, del_data)

    assert result.performed is False
    assert HISTORY_KEY not in data
    assert MIGRATION_KEY not in data


def test_skips_unusable_records_but_keeps_the_rest():
    data, (get_data, save_data, del_data) = _kv({
        HISTORY_KEY: [_rec("good"), {"no_unique": 1}, "不是字典", {"unique": ""}],
    })
    store = _store()

    result = migrate_history_from_kv(store, get_data, save_data, del_data)

    assert result.performed is True
    assert result.imported == 1 and result.skipped == 3
    assert {r["unique"] for r in store.values()} == {"good"}
    assert data[MIGRATION_KEY]["skipped"] == 3


def test_keeps_source_when_nothing_could_be_imported():
    # 一条都搬不动时原值原地保留，等修复后重跑，不写完成标记。
    data, (get_data, save_data, del_data) = _kv({HISTORY_KEY: [{"no_unique": 1}]})
    store = _store()

    result = migrate_history_from_kv(store, get_data, save_data, del_data)

    assert result.performed is False
    assert result.error
    assert data[HISTORY_KEY]
    assert MIGRATION_KEY not in data


def test_second_run_is_a_no_op():
    data, (get_data, save_data, del_data) = _kv({HISTORY_KEY: [_rec("a"), _rec("b")]})
    store = _store()

    first = migrate_history_from_kv(store, get_data, save_data, del_data)
    second = migrate_history_from_kv(store, get_data, save_data, del_data)

    assert first.performed is True and second.performed is False
    assert store.count() == 2
    assert data[MIGRATION_KEY]["imported"] == 2


def test_rerun_after_partial_failure_does_not_duplicate():
    # 收尾没做完（原键还在）时重跑，按 unique 覆盖而不是插出重复行。
    data, (get_data, save_data, del_data) = _kv({HISTORY_KEY: [_rec("a"), _rec("b")]})
    store = _store()

    migrate_history_from_kv(store, get_data, save_data, del_data)
    data[HISTORY_KEY] = [_rec("a"), _rec("b")]
    migrate_history_from_kv(store, get_data, save_data, del_data)

    assert store.count() == 2


def test_survives_unreadable_kv():
    def _boom(_key):
        raise RuntimeError("kv down")

    store = _store()
    result = migrate_history_from_kv(store, _boom, lambda k, v: None, lambda k: None)

    assert result.performed is False
    assert "kv down" in (result.error or "")
