"""五个来源的运行通知独立控制，失败与部分统计只发送一次。"""

from threading import Event, Lock
from unittest.mock import MagicMock

import pytest
from app.plugins.automaticsubscriptionassistant import (
    AutomaticSubscriptionAssistant as Plugin,
)
from app.plugins.automaticsubscriptionassistant.core.config import (
    PluginSettings,
    ProviderConfig,
    build_defaults,
)
from app.plugins.automaticsubscriptionassistant.core.dedup import SubscribedIndex
from app.plugins.automaticsubscriptionassistant.schemas import (
    ProviderSpec,
    RankMediaItem,
)
from test_executor import _make_ctx, _make_store


class Source:
    def __init__(self, provider_id, behavior):
        self.provider_id = provider_id
        self.provider_name = provider_id
        self.behavior = behavior

    def get_spec(self):
        return ProviderSpec(self.provider_id, self.provider_name, "0 8 * * *")

    def fetch(self, options, context):
        if self.behavior == "cancelled":
            context.event.set()
            return
        if self.behavior == "partial":
            yield RankMediaItem(title="未识别作品")
        if self.behavior in {"failed", "partial"}:
            raise RuntimeError("source unavailable")


def plugin_for(monkeypatch, sources, config):
    import app.plugins.automaticsubscriptionassistant as entry

    plugin = Plugin.__new__(Plugin)
    ctx = _make_ctx()
    ctx.chain.recognize_media.return_value = None
    plugin.chain = ctx.chain
    plugin._downloadchain, plugin._subscribechain = (
        ctx.downloadchain,
        ctx.subscribechain,
    )
    plugin._event = Event()
    plugin._database_ready = True
    plugin._settings = PluginSettings(config)
    plugin._run_lock, plugin._run_state = Lock(), {}
    plugin._providers = list(sources.values())
    plugin.systemmessage = MagicMock()
    plugin.get_data = MagicMock()
    plugin.save_data = MagicMock()
    history, _ = _make_store()
    plugin._history_store = lambda: history
    plugin.blacklist_store = lambda: ctx.blacklist
    monkeypatch.setattr(entry.registry, "get", sources.get)
    return plugin


@pytest.mark.parametrize(
    "provider_id", ["douban", "popular", "mikan", "netflix", "maoyan"]
)
@pytest.mark.parametrize("notify", [True, False])
@pytest.mark.parametrize("behavior", ["empty", "failed", "partial"])
def test_source_switch_controls_results_and_failures(
    monkeypatch, provider_id, notify, behavior
):
    source = Source(provider_id, behavior)
    plugin = plugin_for(
        monkeypatch,
        {provider_id: source},
        {
            # 旧全局值不作为通知回退或总开关。
            "global": {"notify": not notify},
            "providers": {provider_id: {"notify": notify}},
        },
    )
    plugin.run_provider(provider_id, SubscribedIndex())
    assert plugin.systemmessage.put.call_count == int(notify)
    assert plugin._run_state == {}
    if notify:
        message = plugin.systemmessage.put.call_args.args[0]
        assert provider_id in message
        if behavior == "empty":
            assert "未获取到待处理条目" in message
        else:
            assert "运行失败" in message
            assert "运行完成" not in message
            if behavior == "partial":
                assert "未识别：1" in message


def test_two_sources_share_no_notification_switch(monkeypatch):
    sources = {pid: Source(pid, "empty") for pid in ("douban", "netflix")}
    plugin = plugin_for(
        monkeypatch,
        sources,
        {"providers": {"douban": {"notify": True}, "netflix": {"notify": False}}},
    )
    plugin.run_provider("netflix", SubscribedIndex())
    plugin.run_provider("douban", SubscribedIndex())
    plugin.systemmessage.put.assert_called_once()
    assert "douban" in plugin.systemmessage.put.call_args.args[0]


def test_cancelled_old_run_sends_no_completion(monkeypatch):
    plugin = plugin_for(
        monkeypatch,
        {"douban": Source("douban", "cancelled")},
        {"providers": {"douban": {"notify": True}}},
    )
    plugin.run_provider("douban", SubscribedIndex())
    plugin.systemmessage.put.assert_not_called()


def test_notification_failure_is_not_retried_as_a_job_failure(monkeypatch):
    plugin = plugin_for(
        monkeypatch,
        {"douban": Source("douban", "empty")},
        {"providers": {"douban": {"notify": True}}},
    )
    plugin.systemmessage.put.side_effect = RuntimeError("notification unavailable")
    plugin.run_provider("douban", SubscribedIndex())
    plugin.systemmessage.put.assert_called_once()
    assert plugin._run_state == {}


def test_unexpected_runner_failure_uses_source_switch(monkeypatch):
    import app.plugins.automaticsubscriptionassistant as entry

    plugin = plugin_for(
        monkeypatch,
        {"douban": Source("douban", "empty")},
        {"providers": {"douban": {"notify": True}}},
    )
    runner = MagicMock()
    runner.run.side_effect = RuntimeError("unexpected runner failure")
    monkeypatch.setattr(entry, "ProviderRunner", MagicMock(return_value=runner))
    plugin.run_provider("douban", SubscribedIndex())
    plugin.systemmessage.put.assert_called_once()
    assert "unexpected runner failure" in plugin.systemmessage.put.call_args.args[0]


def test_notify_defaults_are_explicit_for_every_source():
    specs = [
        Source(pid, "empty").get_spec()
        for pid in ("douban", "popular", "mikan", "netflix", "maoyan")
    ]
    defaults = build_defaults(specs)
    assert "notify" not in defaults["global"]
    for spec in specs:
        assert defaults["providers"][spec.provider_id]["notify"] is False
        assert ProviderConfig({}, spec).notify is False
        assert ProviderConfig({"notify": "yes"}, spec).notify is True


@pytest.mark.parametrize("notify", [True, False])
def test_invalid_schedule_notice_obeys_source_switch(monkeypatch, notify):
    plugin = plugin_for(
        monkeypatch,
        {"douban": Source("douban", "empty")},
        {
            "global": {"enabled": True},
            "providers": {
                "douban": {"enabled": True, "notify": notify, "cron": "invalid"}
            },
        },
    )
    assert plugin.get_service() == []
    assert plugin.systemmessage.put.call_count == int(notify)
