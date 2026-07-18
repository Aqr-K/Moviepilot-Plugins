"""get_service 定时服务注册结构测试。

回归点：MoviePilot 主程序 scheduler ``update_plugin_job`` 仅将 ``func_kwargs``
作为业务函数入参（``job["kwargs"] = service.get("func_kwargs")``），而 ``kwargs``
会被展开为 APScheduler ``add_job`` 的调度参数，不会传给 ``run_provider``。
因此来源的 ``provider_id`` 必须放在 ``func_kwargs``，否则到点执行时
``run_provider()`` 缺少 ``provider_id`` 位置参数直接 TypeError（见 issue #7）。
"""
from __future__ import annotations

from types import SimpleNamespace

from app.plugins.automaticsubscriptionassistant import AutomaticSubscriptionAssistant as Plugin
from app.plugins.automaticsubscriptionassistant.core.models import ProviderSpec


def _bare_plugin(providers, enabled=True):
    """构造未初始化的裸插件实例并注入 get_service 所需的最小依赖。"""
    plugin = Plugin.__new__(Plugin)
    plugin._providers = providers
    plugin._settings = SimpleNamespace(
        global_config=SimpleNamespace(enabled=enabled),
        provider_raw=lambda pid: {"enabled": True, "cron": "0 8 * * *"},
    )
    return plugin


def _provider(pid: str, name: str):
    spec = ProviderSpec(provider_id=pid, provider_name=name, default_cron="0 8 * * *")
    return SimpleNamespace(get_spec=lambda: spec)


def test_get_service_passes_provider_id_via_func_kwargs():
    plugin = _bare_plugin([_provider("douban", "豆瓣榜单")])

    services = plugin.get_service()

    assert len(services) == 1
    svc = services[0]
    # 业务参数必须走 func_kwargs（主程序 scheduler 只认它作为函数入参）
    assert svc["func_kwargs"] == {"provider_id": "douban"}
    # 绝不能塞进 kwargs：会被当作 APScheduler add_job 参数而丢失，
    # 导致 run_provider() 缺少 provider_id 而 TypeError。
    assert "provider_id" not in (svc.get("kwargs") or {})
    assert svc["func"] == plugin.run_provider
    assert svc["id"] == f"{plugin.plugin_config_prefix}douban"


def test_get_service_empty_when_globally_disabled():
    plugin = _bare_plugin([_provider("douban", "豆瓣榜单")], enabled=False)
    assert plugin.get_service() == []
