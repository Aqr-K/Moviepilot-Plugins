"""core/registry.py 单元测试：注册、整体/按需实例化、id 列举。"""
from __future__ import annotations

from app.plugins.automaticsubscriptionassistant.core.provider import RankProvider
from app.plugins.automaticsubscriptionassistant.core.registry import (
    ProviderRegistry,
    registry,
)


class _DummyProvider(RankProvider):
    provider_id = "dummy"
    provider_name = "示例来源"

    def get_spec(self):  # pragma: no cover - 本测试不需要 spec
        return None

    def fetch(self, options, context):  # pragma: no cover - 本测试不需要 fetch
        return iter(())


def test_register_and_create_all():
    reg = ProviderRegistry()
    returned = reg.register(_DummyProvider)
    # register 返回原类（装饰器语义）
    assert returned is _DummyProvider
    instances = reg.create_all()
    assert len(instances) == 1
    assert isinstance(instances[0], _DummyProvider)


def test_get_and_ids():
    reg = ProviderRegistry()
    reg.register(_DummyProvider)
    got = reg.get("dummy")
    assert isinstance(got, _DummyProvider)
    # 每次 get 产出新实例
    assert reg.get("dummy") is not got
    assert reg.get("missing") is None
    assert reg.ids() == ["dummy"]


def test_module_registry_has_builtin_providers():
    # providers/__init__.py 的导入副作用注册了三源
    ids = set(registry.ids())
    assert {"douban", "maoyan", "popular"} <= ids
    # create_all 可实例化全部
    created = {p.provider_id for p in registry.create_all()}
    assert {"douban", "maoyan", "popular"} <= created
