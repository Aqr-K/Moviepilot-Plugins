"""core/history.py 单元测试：自有表读写、去重判定、分页、增删清统计。"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.plugins.automaticsubscriptionassistant.core.history import HistoryStore
from app.plugins.automaticsubscriptionassistant.core.models import HistoryRecord


def _make_store(initial=None):
    """建一个跑在内存库上的仓库，并按需预置记录。

    ``StaticPool`` 让所有会话共用同一条连接：内存库随连接存亡，默认连接池会给每个
    会话新开一条连接，那样建好的表在下一个会话里就不见了。
    """
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    store = HistoryStore(sessionmaker(bind=engine))
    for raw in initial or []:
        if raw.get("unique"):
            store.record(HistoryRecord.from_dict(raw))
    return store, store


def _rec(unique, provider="douban", status="subscribed", time="2026-07-12 08:00:00", title="T"):
    return HistoryRecord(unique=unique, provider=provider, title=title, status=status, time=time)


def test_init_loads_handled_only_for_positive_status():
    # 仅正向终态（subscribed/media_exists/subscription_exists）进入已处理集合。
    store, _ = _make_store([
        {"unique": "a", "status": "subscribed"},
        {"unique": "b", "status": "media_exists"},
        {"unique": "c", "status": "filtered"},      # 非正向 → 不入 handled
        {"unique": "d", "status": "unrecognized"},  # 非正向 → 不入 handled
        {"no_unique": 1, "status": "subscribed"},   # 无 unique → 忽略
    ])
    assert store.is_handled("a") is True
    assert store.is_handled("b") is True
    assert store.is_handled("c") is False
    assert store.is_handled("d") is False
    assert store.is_handled("e") is False


def test_init_empty_when_none():
    store, _ = _make_store(None)
    assert store.is_handled("x") is False


def test_mark_handled():
    store, _ = _make_store()
    store.mark_handled("k")
    assert store.is_handled("k") is True


def test_handled_follows_record_status():
    # 是否已处理由记录的 status 决定：正向终态即已处理，非正向终态仍可被其他渠道重试。
    store, _ = _make_store()
    store.record(_rec("douban:1", status="subscribed"))
    assert store.is_handled("douban:1") is True
    store.record(_rec("douban:2", status="filtered"))
    assert store.is_handled("douban:2") is False
    store.record(_rec("douban:3", status="unrecognized"))
    assert store.is_handled("douban:3") is False
    assert store.query()[1] == 3


def test_record_persists_fields():
    store, _ = _make_store()
    store.record(_rec("douban:1"))
    records, total = store.query()
    assert total == 1
    assert records[0]["unique"] == "douban:1"


def test_record_same_unique_replaces():
    store, _ = _make_store()
    store.record(_rec("k", status="filtered"))
    store.record(_rec("k", status="subscribed"))
    records, total = store.query()
    assert total == 1
    assert records[0]["status"] == "subscribed"


def test_flush_persists():
    store, _ = _make_store()
    store.record(_rec("k"))
    store.flush()
    assert store.values()[0]["unique"] == "k"


def test_query_filter_by_provider_and_status():
    store, _ = _make_store()
    store.record(_rec("a", provider="douban", status="subscribed"))
    store.record(_rec("b", provider="maoyan", status="subscribed"))
    store.record(_rec("c", provider="douban", status="filtered"))

    only_douban, total = store.query(provider="douban")
    assert total == 2
    assert {r["unique"] for r in only_douban} == {"a", "c"}

    subscribed, total = store.query(status="subscribed")
    assert total == 2

    combo, total = store.query(provider="douban", status="filtered")
    assert total == 1 and combo[0]["unique"] == "c"


def test_query_by_keyword():
    store, _ = _make_store()
    store.record(_rec("a", title="沙丘"))
    store.record(_rec("b", title="沙丘2"))
    store.record(_rec("c", title="奥本海默"))
    hits, total = store.query(keyword="沙丘")
    assert total == 2 and {r["unique"] for r in hits} == {"a", "b"}
    # 不区分大小写 + 无匹配
    store.record(_rec("d", title="Dune"))
    assert store.query(keyword="dune")[1] == 1
    assert store.query(keyword="不存在")[1] == 0
    # 空关键词不过滤
    assert store.query(keyword="  ")[1] == 4


def test_query_pagination_and_reverse_time():
    store, _ = _make_store()
    # 时间升序写入，query 应按 time 倒序返回
    for i in range(1, 6):
        store.record(_rec(f"k{i}", time=f"2026-07-12 08:0{i}:00"))
    page1, total = store.query(page=1, count=2)
    assert total == 5
    assert [r["unique"] for r in page1] == ["k5", "k4"]
    page2, _ = store.query(page=2, count=2)
    assert [r["unique"] for r in page2] == ["k3", "k2"]
    page3, _ = store.query(page=3, count=2)
    assert [r["unique"] for r in page3] == ["k1"]
    # 非法分页参数归一
    page0, _ = store.query(page=0, count=0)
    assert len(page0) == 1


def test_delete():
    store, _ = _make_store()
    store.record(_rec("k1"))
    store.record(_rec("k2"))
    store.mark_handled("k1")
    assert store.delete("k1") is True
    assert store.is_handled("k1") is False  # 删除同时从已处理集合移除
    # 落盘
    assert {r["unique"] for r in store.values()} == {"k2"}
    # 不存在的 unique
    assert store.delete("nope") is False


def test_delete_many():
    store, _ = _make_store()
    for u in ("a", "b", "c", "d"):
        store.record(_rec(u))
    store.mark_handled("a")
    store.mark_handled("b")
    removed = store.delete_many(["a", "c", "nope", None])
    assert removed == 2  # a、c 存在被删；nope/None 忽略
    assert {r["unique"] for r in store.values()} == {"b", "d"}
    assert store.is_handled("a") is False  # 从已处理集合移除
    assert store.is_handled("b") is True
    # 空输入不动
    assert store.delete_many([]) == 0


def test_clear_all_and_by_provider():
    store, _ = _make_store()
    store.record(_rec("a", provider="douban"))
    store.record(_rec("b", provider="maoyan"))
    store.mark_handled("a")
    store.mark_handled("b")
    store.clear(provider="douban")
    remaining, total = store.query()
    assert total == 1 and remaining[0]["provider"] == "maoyan"
    # 按来源清空后，已处理集合据剩余记录（正向终态）重建：a 移除、b 仍在
    assert store.is_handled("a") is False
    assert store.is_handled("b") is True
    # 清空全部
    store.clear()
    _, total = store.query()
    assert total == 0
    assert store.values() == []


def test_prune_keeps_most_recent():
    store, _ = _make_store()
    for i in range(1, 6):
        store.record(_rec(f"k{i}", time=f"2026-07-12 08:0{i}:00"))
    removed = store.prune(2)
    assert removed == 3
    assert {r["unique"] for r in store.values()} == {"k5", "k4"}


def test_prune_is_a_no_op_without_limit():
    store, _ = _make_store()
    store.record(_rec("k1"))
    assert store.prune(0) == 0
    assert store.prune(-1) == 0
    assert store.count() == 1


def test_uniques_applies_same_filters():
    store, _ = _make_store()
    store.record(_rec("a", provider="douban", status="subscribed"))
    store.record(_rec("b", provider="maoyan", status="subscribed"))
    store.record(_rec("c", provider="douban", status="filtered"))
    assert set(store.uniques()) == {"a", "b", "c"}
    assert set(store.uniques(provider="douban")) == {"a", "c"}
    assert set(store.uniques(provider="douban", status="subscribed")) == {"a"}


def test_query_count_is_capped():
    store, _ = _make_store()
    store.record(_rec("k1"))
    # 超大 count 被夹到上限，不会放大成巨型响应
    records, total = store.query(count=10 ** 6)
    assert total == 1 and len(records) == 1


def test_stats():
    store, _ = _make_store()
    store.record(_rec("a", provider="douban", status="subscribed"))
    store.record(_rec("b", provider="douban", status="filtered"))
    store.record(_rec("c", provider="maoyan", status="subscribed"))
    stats = store.stats()
    assert stats["total"] == 3
    assert stats["by_provider"] == {"douban": 2, "maoyan": 1}
    assert stats["by_status"] == {"subscribed": 2, "filtered": 1}
