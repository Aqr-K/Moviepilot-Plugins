"""core/subscribes.py 单元测试：订阅手动管理（列表/退订/暂停恢复）。

用 MagicMock 隔离订阅写入与查询 SDK，使用真实只读快照验证映射、归属和容错。
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.sdk.queries import MAX_QUERY_PAGE_SIZE, QueryPage, QuerySortDirection, QuerySortField, SubscriptionSnapshot

from app.plugins.automaticsubscriptionassistant.core.subscribes import (
    PLUGIN_USERNAME,
    SubscribeManager,
    list_subscriptions,
)


def _sub(sid, name="沙丘", **kw):
    base = dict(id=sid, name=name, year="2021", type="电影",
                media_source="themoviedb", media_id="438631",
                season=None, poster="p.jpg", state="R",
                # 归属判据：写操作只认用户名与管理器一致的订阅。
                username=PLUGIN_USERNAME,
                total_episode=0, lack_episode=0, date="2026-07-01 00:00:00",
                last_update="2026-07-02 00:00:00")
    base.update(kw)
    return SubscriptionSnapshot(**base)


def _oper(subs=None):
    oper = MagicMock()
    subs = subs or []
    oper.list_subscriptions.return_value = QueryPage[SubscriptionSnapshot](items=subs, total=len(subs))
    index = {s.id: s for s in subs}
    oper.get_subscription.side_effect = lambda sid: index.get(sid)
    return oper


def test_list_mine_maps_fields():
    oper = _oper([_sub(1), _sub(2, name="剧", type="电视剧", season=2)])
    mgr = SubscribeManager(oper, queries=oper)
    rows = mgr.list_mine()
    assert oper.list_subscriptions.call_args.kwargs["filters"].usernames == ("自动订阅助手",)
    assert [r["id"] for r in rows] == [1, 2]
    assert rows[0]["name"] == "沙丘" and rows[0]["type"] == "电影"
    assert rows[1]["season"] == 2 and rows[1]["state"] == "R"
    # 关键字段齐备：媒体身份须成对出现，单独的 media_id 不足以定位媒体
    for k in ("id", "name", "year", "type", "media_source", "media_id", "poster", "state", "date"):
        assert k in rows[0]
    assert rows[0]["media_source"] == "themoviedb" and rows[0]["media_id"] == "438631"


def test_delete_calls_oper_and_callback():
    deleted = []
    oper = _oper([_sub(1), _sub(2)])
    mgr = SubscribeManager(oper, queries=oper, on_deleted=lambda sid, sub: deleted.append((sid, sub.name)))
    res = mgr.delete([1, 2])
    assert {key: res[key] for key in ("ok", "failed")} == {"ok": 2, "failed": 0}
    assert oper.delete.call_count == 2
    assert deleted == [(1, "沙丘"), (2, "沙丘")]


def test_delete_skips_missing_and_counts_failed():
    oper = _oper([_sub(1)])
    mgr = SubscribeManager(oper, queries=oper)
    res = mgr.delete([1, 999])  # 999 不存在
    assert {key: res[key] for key in ("ok", "failed")} == {"ok": 1, "failed": 1}
    oper.delete.assert_called_once_with(1)


def test_delete_tolerates_callback_error():
    # 单条回调/删除异常不应中断整体，计入 failed。
    oper = _oper([_sub(1), _sub(2)])
    oper.delete.side_effect = [None, RuntimeError("boom")]
    mgr = SubscribeManager(oper, queries=oper, on_deleted=lambda sid, sub: None)
    res = mgr.delete([1, 2])
    assert {key: res[key] for key in ("ok", "failed")} == {"ok": 1, "failed": 1}


def test_set_state_updates_each():
    oper = _oper([_sub(1), _sub(2)])
    mgr = SubscribeManager(oper, queries=oper)
    res = mgr.set_state([1, 2], "S")
    assert {key: res[key] for key in ("ok", "failed")} == {"ok": 2, "failed": 0}
    assert oper.update.call_count == 2
    oper.update.assert_any_call(1, {"state": "S"})


def test_delete_refuses_subscription_of_other_owner():
    # 订阅 ID 是自增整数、极易猜到，写操作必须复核归属，不能只凭 ID 就删。
    other = _sub(7, name="别人的订阅")
    other.username = "别的用户"
    oper = _oper([other])
    mgr = SubscribeManager(oper, queries=oper)
    res = mgr.delete([7])
    assert {key: res[key] for key in ("ok", "failed")} == {"ok": 0, "failed": 1}
    oper.delete.assert_not_called()


def test_set_state_refuses_subscription_of_other_owner():
    other = _sub(7)
    other.username = "别的用户"
    oper = _oper([other])
    mgr = SubscribeManager(oper, queries=oper)
    res = mgr.set_state([7], "S")
    assert {key: res[key] for key in ("ok", "failed")} == {"ok": 0, "failed": 1}
    oper.update.assert_not_called()


def test_set_state_counts_missing_as_failed():
    # oper.update 对不存在的 ID 只返回 None 而不抛错，不复核就会虚报成功条数。
    oper = _oper([_sub(1)])
    mgr = SubscribeManager(oper, queries=oper)
    res = mgr.set_state([1, 999], "S")
    assert {key: res[key] for key in ("ok", "failed")} == {"ok": 1, "failed": 1}
    oper.update.assert_called_once_with(1, {"state": "S"})


def test_manager_honours_configured_username():
    # 用户在配置里改了订阅用户名时，管理器须按同一个名字认归属。
    sub = _sub(1)
    sub.username = "我的助手"
    oper = _oper([sub])
    mgr = SubscribeManager(oper, queries=oper, username="我的助手")
    assert mgr.delete([1]) == {"ok": 1, "failed": 0, "ok_ids": [1], "failed_ids": []}
    assert mgr.list_mine()[0]["id"] == 1
    assert oper.list_subscriptions.call_args.kwargs["filters"].usernames == ("我的助手",)


def test_set_state_rejects_invalid_state():
    oper = _oper([_sub(1)])
    mgr = SubscribeManager(oper, queries=oper)
    with pytest.raises(ValueError):
        mgr.set_state([1], "X")
    oper.update.assert_not_called()


def test_empty_ids_noop():
    oper = _oper([_sub(1)])
    mgr = SubscribeManager(oper, queries=oper)
    assert mgr.delete([]) == {"ok": 0, "failed": 0, "ok_ids": [], "failed_ids": []}
    assert mgr.set_state([], "R") == {"ok": 0, "failed": 0, "ok_ids": [], "failed_ids": []}
    oper.delete.assert_not_called()
    oper.update.assert_not_called()


def test_partial_failure_identifies_retry_targets():
    """客户端可仅保留失败项，精确重试而不重复操作成功项。"""
    oper = _oper([_sub(1)])
    result = SubscribeManager(oper, queries=oper).delete([1, 999])
    assert result["ok_ids"] == [1]
    assert result["failed_ids"] == [999]


def test_sdk_query_reads_all_pages_with_stable_order():
    """
    订阅超过单页上限时读取所有页，并使用固定 ID 升序和精确用户名筛选。
    """
    items = [_sub(number) for number in range(1, MAX_QUERY_PAGE_SIZE * 2 + 2)]
    queries = MagicMock()
    queries.list_subscriptions.side_effect = [
        QueryPage[SubscriptionSnapshot](
            items=items[offset:offset + MAX_QUERY_PAGE_SIZE], total=len(items),
            page=page_number, count=MAX_QUERY_PAGE_SIZE)
        for page_number, offset in enumerate(range(0, len(items), MAX_QUERY_PAGE_SIZE), start=1)
    ]

    result = list_subscriptions(PLUGIN_USERNAME, queries=queries)

    assert [item.id for item in result] == list(range(1, len(items) + 1))
    assert queries.list_subscriptions.call_count == 3
    for page_number, call in enumerate(queries.list_subscriptions.call_args_list, start=1):
        assert call.kwargs["filters"].usernames == (PLUGIN_USERNAME,)
        page = call.kwargs["page"]
        assert page.page == page_number and page.count == MAX_QUERY_PAGE_SIZE
        assert page.sort.field == QuerySortField.ID
        assert page.sort.direction == QuerySortDirection.ASC


def test_sdk_query_all_users_and_empty_page():
    """
    全量索引不按用户名过滤，扫描期间出现空页时及时结束。
    """
    queries = MagicMock()
    queries.list_subscriptions.return_value = QueryPage[SubscriptionSnapshot](
        items=[], total=MAX_QUERY_PAGE_SIZE + 1, count=MAX_QUERY_PAGE_SIZE)
    assert list_subscriptions(queries=queries) == []
    assert queries.list_subscriptions.call_args.kwargs["filters"].usernames == ()
    queries.list_subscriptions.assert_called_once()


def test_sdk_query_failure_is_not_an_empty_list():
    """
    SDK 查询失败向调用方传播，避免用空列表掩盖故障。
    """
    queries = MagicMock()
    queries.list_subscriptions.side_effect = RuntimeError("query unavailable")
    with pytest.raises(RuntimeError, match="query unavailable"):
        list_subscriptions(queries=queries)


@pytest.mark.parametrize("action", ["delete", "set_state"])
def test_sdk_ownership_query_failure_prevents_writes(action):
    """
    SDK 无法确认归属时不删除订阅或修改状态。
    """
    oper = _oper([_sub(1)])
    oper.get_subscription.side_effect = RuntimeError("query unavailable")
    manager = SubscribeManager(oper, queries=oper)
    result = manager.delete([1]) if action == "delete" else manager.set_state([1], "S")
    assert result["failed_ids"] == [1]
    assert result["ok_ids"] == []
    oper.delete.assert_not_called()
    oper.update.assert_not_called()


def test_plugin_deletion_event_uses_sdk_snapshot(monkeypatch):
    """
    删除事件由 SDK 订阅快照生成完整 JSON 数据，不依赖 ORM 表对象。
    """
    from types import SimpleNamespace
    from app.plugins import automaticsubscriptionassistant as plugin_module
    from app.plugins.automaticsubscriptionassistant.core import subscribes as subscribes_module

    subscription = _sub(1, name="测试剧", type="电视剧", season=2)
    oper = MagicMock()
    monkeypatch.setattr(plugin_module, "SubscribeOper", lambda: oper)
    monkeypatch.setattr(subscribes_module.subscription_queries, "get_subscription", lambda sid: subscription)
    send_event = MagicMock()
    monkeypatch.setattr(plugin_module.eventmanager, "send_event", send_event)
    plugin = plugin_module.AutomaticSubscriptionAssistant.__new__(plugin_module.AutomaticSubscriptionAssistant)
    plugin._settings = SimpleNamespace(global_config=SimpleNamespace(username=PLUGIN_USERNAME))

    result = plugin._AutomaticSubscriptionAssistant__subscribe_manager().delete([1])

    assert result["ok_ids"] == [1]
    payload = send_event.call_args.args[1]
    assert payload["subscribe_id"] == 1
    assert payload["subscribe_info"] == subscription.model_dump(mode="json")
    assert payload["subscribe_info"]["season"] == 2
    assert payload["subscribe_info"]["media_source"] == "themoviedb"
