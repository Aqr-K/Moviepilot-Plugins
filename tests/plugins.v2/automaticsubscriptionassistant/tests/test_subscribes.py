"""core/subscribes.py 单元测试：订阅手动管理（列表/退订/暂停恢复）。

用 MagicMock 造 SubscribeOper，SimpleNamespace 造订阅对象；断言映射、计数、回调与容错。
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.plugins.automaticsubscriptionassistant.core.subscribes import SubscribeManager


def _sub(sid, name="沙丘", **kw):
    base = dict(id=sid, name=name, year="2021", type="电影", tmdbid=438631, doubanid="D1",
                bangumiid=None, season=None, poster="p.jpg", state="R",
                total_episode=0, lack_episode=0, date="2026-07-01 00:00:00",
                last_update="2026-07-02 00:00:00")
    base.update(kw)
    return SimpleNamespace(**base)


def _oper(subs=None):
    oper = MagicMock()
    subs = subs or []
    oper.list_by_username.return_value = subs
    index = {s.id: s for s in subs}
    oper.get.side_effect = lambda sid: index.get(sid)
    return oper


def test_list_mine_maps_fields():
    oper = _oper([_sub(1), _sub(2, name="剧", type="电视剧", season=2)])
    mgr = SubscribeManager(oper)
    rows = mgr.list_mine()
    oper.list_by_username.assert_called_once_with("自动订阅助手")
    assert [r["id"] for r in rows] == [1, 2]
    assert rows[0]["name"] == "沙丘" and rows[0]["type"] == "电影"
    assert rows[1]["season"] == 2 and rows[1]["state"] == "R"
    # 关键字段齐备
    for k in ("id", "name", "year", "type", "tmdbid", "poster", "state", "date"):
        assert k in rows[0]


def test_delete_calls_oper_and_callback():
    deleted = []
    oper = _oper([_sub(1), _sub(2)])
    mgr = SubscribeManager(oper, on_deleted=lambda sid, sub: deleted.append((sid, sub.name)))
    res = mgr.delete([1, 2])
    assert res == {"ok": 2, "failed": 0}
    assert oper.delete.call_count == 2
    assert deleted == [(1, "沙丘"), (2, "沙丘")]


def test_delete_skips_missing_and_counts_failed():
    oper = _oper([_sub(1)])
    mgr = SubscribeManager(oper)
    res = mgr.delete([1, 999])  # 999 不存在
    assert res == {"ok": 1, "failed": 1}
    oper.delete.assert_called_once_with(1)


def test_delete_tolerates_callback_error():
    # 单条回调/删除异常不应中断整体，计入 failed。
    oper = _oper([_sub(1), _sub(2)])
    oper.delete.side_effect = [None, RuntimeError("boom")]
    mgr = SubscribeManager(oper, on_deleted=lambda sid, sub: None)
    res = mgr.delete([1, 2])
    assert res == {"ok": 1, "failed": 1}


def test_set_state_updates_each():
    oper = _oper([_sub(1), _sub(2)])
    mgr = SubscribeManager(oper)
    res = mgr.set_state([1, 2], "S")
    assert res == {"ok": 2, "failed": 0}
    assert oper.update.call_count == 2
    oper.update.assert_any_call(1, {"state": "S"})


def test_set_state_rejects_invalid_state():
    oper = _oper([_sub(1)])
    mgr = SubscribeManager(oper)
    with pytest.raises(ValueError):
        mgr.set_state([1], "X")
    oper.update.assert_not_called()


def test_empty_ids_noop():
    oper = _oper([_sub(1)])
    mgr = SubscribeManager(oper)
    assert mgr.delete([]) == {"ok": 0, "failed": 0}
    assert mgr.set_state([], "R") == {"ok": 0, "failed": 0}
    oper.delete.assert_not_called()
    oper.update.assert_not_called()
