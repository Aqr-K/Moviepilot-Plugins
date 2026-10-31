"""仪表盘注册与只读概览的行为验证。"""
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.plugins.automaticsubscriptionassistant import AutomaticSubscriptionAssistant


def _plugin():
    """构造仅装配概览边界的插件，避免触发真实订阅或网络。"""
    plugin = AutomaticSubscriptionAssistant.__new__(AutomaticSubscriptionAssistant)
    plugin.api_status = MagicMock(return_value={
        "enabled": True,
        "providers": [{"provider_id": "douban", "enabled": True}],
        "running": [{"provider_id": "douban", "processed": 2}],
        "stats": {"total": 99, "by_status": {"subscribed": 80, "blacklisted": 19}},
    })
    manager = MagicMock()
    manager.list_mine.return_value = [{"id": 1, "state": "R"}, {"id": 2, "state": "S"}]
    plugin._AutomaticSubscriptionAssistant__subscribe_manager = MagicMock(return_value=manager)
    history = MagicMock()
    history.query.return_value = ([{"unique": "tv:1:s2", "season": 2, "status": "subscribed"}], 80)
    plugin._AutomaticSubscriptionAssistant__history_store = MagicMock(return_value=history)
    plugin.blacklist_store = MagicMock(return_value=SimpleNamespace(list=lambda: [{"id": "rule"}]))
    return plugin


def test_dashboard_hook_preserves_existing_overview_key_and_layout():
    plugin = _plugin()
    assert plugin.get_dashboard_meta() == [{"key": "overview", "name": "自动订阅助手 · 订阅概览"}]
    cols, attrs, elements = plugin.get_dashboard("overview")
    assert cols == {"cols": 12, "md": 6}
    assert attrs["refresh"] == 300
    assert elements is None
    assert plugin.get_dashboard("") == plugin.get_dashboard("overview")
    assert plugin.get_dashboard("missing") is None


def test_dashboard_uses_current_subscription_and_rule_counts_independently_of_history():
    plugin = _plugin()
    result = plugin.api_dashboard(lang="en-US")
    assert result["code"] == 0
    assert result["counts"] == {"history": 99, "subscriptions": 2, "paused": 1, "blacklist": 1}
    assert result["providers"][0]["provider_id"] == "douban"
    assert result["running"][0]["processed"] == 2
    assert result["recent"][0]["season"] == 2
    plugin.api_status.assert_called_once_with(lang="en-US")
    plugin._AutomaticSubscriptionAssistant__history_store().query.assert_called_once_with(status="subscribed", page=1, count=5)
    plugin._AutomaticSubscriptionAssistant__subscribe_manager().delete.assert_not_called()


def test_dashboard_read_failure_returns_business_error_instead_of_false_zero_counts():
    plugin = _plugin()
    plugin._AutomaticSubscriptionAssistant__subscribe_manager().list_mine.side_effect = RuntimeError("storage unavailable")
    result = plugin.api_dashboard()
    assert result["code"] == 1
    assert "counts" not in result
    assert "重试" in result["message"]


def test_dashboard_api_is_authenticated_and_read_only():
    plugin = _plugin()
    routes = [route for route in plugin.get_api() if route["path"] == "/dashboard"]
    assert len(routes) == 1
    assert routes[0]["methods"] == ["GET"]
    assert routes[0]["auth"] == "bear"
