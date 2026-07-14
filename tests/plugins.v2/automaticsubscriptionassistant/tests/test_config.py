"""core/config.py 单元测试：类型转换器、反射默认、provider 配置回退。"""
from __future__ import annotations

from app.plugins.automaticsubscriptionassistant.core.config import (
    DEFAULT_USERNAME,
    GlobalConfig,
    PluginSettings,
    ProviderConfig,
    TypedConfigAccess,
    build_defaults,
)
from app.plugins.automaticsubscriptionassistant.core.models import FieldSpec, ProviderSpec
from app.plugins.automaticsubscriptionassistant.core.registry import registry


# ---------- TypedConfigAccess 转换器边界 ----------

def test_get_bool():
    acc = TypedConfigAccess({"t": True, "f": False, "s_yes": "YES", "s_no": "nope",
                             "one": "1", "on": "on", "num1": 1, "num0": 0})
    assert acc.get_bool("t") is True
    assert acc.get_bool("f") is False
    assert acc.get_bool("s_yes") is True
    assert acc.get_bool("s_no") is False
    assert acc.get_bool("one") is True
    assert acc.get_bool("on") is True
    assert acc.get_bool("num1") is True
    assert acc.get_bool("num0") is False
    # 缺失回退默认
    assert acc.get_bool("missing", True) is True
    assert acc.get_bool("missing") is False


def test_get_int():
    acc = TypedConfigAccess({"s": "3.7", "i": 5, "bad": "abc", "none": None})
    assert acc.get_int("s") == 3
    assert acc.get_int("i") == 5
    assert acc.get_int("bad", 9) == 9
    assert acc.get_int("none", 7) == 7
    assert acc.get_int("missing", 4) == 4


def test_get_float():
    acc = TypedConfigAccess({"s": "2.5", "bad": "x", "none": None})
    assert acc.get_float("s") == 2.5
    assert acc.get_float("bad", 1.1) == 1.1
    assert acc.get_float("none", 3.3) == 3.3
    assert acc.get_float("missing", 0.5) == 0.5


def test_get_str():
    acc = TypedConfigAccess({"i": 123, "none": None})
    assert acc.get_str("i") == "123"
    assert acc.get_str("none", "d") == "d"
    assert acc.get_str("missing", "fallback") == "fallback"


def test_get_list():
    acc = TypedConfigAccess({"lst": ["a", " b ", "", "c"], "csv": "x, y ,,z", "num": 123})
    assert acc.get_list("lst") == ["a", "b", "c"]
    assert acc.get_list("csv") == ["x", "y", "z"]
    # 非 list/str -> 返回默认
    assert acc.get_list("num", ["d"]) == ["d"]
    assert acc.get_list("missing") == []


def test_typed_access_none_raw():
    # 构造 None 时内部回退空 dict
    acc = TypedConfigAccess(None)
    assert acc.get_bool("x", True) is True


# ---------- GlobalConfig ----------

def test_global_config_defaults():
    g = GlobalConfig({})
    assert g.enabled is False
    assert g.username == DEFAULT_USERNAME
    assert g.exist_ok is True
    assert g.notify is False
    assert g.onlyonce is False
    assert g.clear is False


def test_global_config_overrides():
    g = GlobalConfig({"enabled": True, "username": "自定义", "exist_ok": False,
                      "notify": True, "onlyonce": True, "clear": True})
    assert g.enabled is True
    assert g.username == "自定义"
    assert g.exist_ok is False
    assert g.notify is True
    assert g.onlyonce is True
    assert g.clear is True


# ---------- ProviderConfig option/filter 回退与转换 ----------

def _demo_spec() -> ProviderSpec:
    return ProviderSpec(
        provider_id="demo",
        provider_name="示例",
        default_cron="0 8 * * *",
        options_schema=[
            FieldSpec(key="sw", label="", kind="switch", default=True),
            FieldSpec(key="n", label="", kind="number", default=5),
            FieldSpec(key="n_none", label="", kind="number", default=None),
            FieldSpec(key="fl", label="", kind="float", default=1.5),
            FieldSpec(key="fl_none", label="", kind="float", default=None),
            FieldSpec(key="ms", label="", kind="multi-select", default=["a"]),
            FieldSpec(key="ms_none", label="", kind="multi-select", default=None),
            FieldSpec(key="txt", label="", kind="text", default="hello"),
            FieldSpec(key="txt_none", label="", kind="text", default=None),
        ],
        filters_schema=[
            FieldSpec(key="year", label="", kind="number", default=0),
            FieldSpec(key="media_type", label="", kind="select", default="all"),
        ],
    )


def test_provider_config_option_defaults_fallback():
    pc = ProviderConfig({}, _demo_spec())
    assert pc.option("sw") is True
    assert pc.option("n") == 5
    assert pc.option("n_none") == 0
    assert pc.option("fl") == 1.5
    assert pc.option("fl_none") == 0.0
    assert pc.option("ms") == ["a"]
    assert pc.option("ms_none") == []
    assert pc.option("txt") == "hello"
    assert pc.option("txt_none") == ""
    # 不在 schema 的键：直接取原始（无则 None）
    assert pc.option("unknown") is None


def test_provider_config_option_conversions():
    raw = {"options": {"sw": "no", "n": "9", "fl": "2.5", "ms": "x,y",
                       "txt": 123, "extra": "kept"}}
    pc = ProviderConfig(raw, _demo_spec())
    assert pc.option("sw") is False
    assert pc.option("n") == 9
    assert pc.option("fl") == 2.5
    assert pc.option("ms") == ["x", "y"]
    assert pc.option("txt") == "123"
    # schema 外的原始键透传
    assert pc.option("extra") == "kept"


def test_provider_config_filter_and_meta():
    pc = ProviderConfig({"enabled": True, "cron": "1 2 3 4 5",
                         "filters": {"year": "2020"}}, _demo_spec())
    assert pc.enabled is True
    assert pc.cron == "1 2 3 4 5"
    assert pc.filter("year") == 2020
    assert pc.filter("media_type") == "all"   # 默认回退
    assert pc.filter("unknown") is None


def test_provider_config_cron_default_from_spec():
    pc = ProviderConfig({}, _demo_spec())
    assert pc.cron == "0 8 * * *"
    assert pc.enabled is False


# ---------- build_defaults 反射 ----------

def test_build_defaults_global_keys():
    specs = [p.get_spec() for p in registry.create_all()]
    defaults = build_defaults(specs)
    g = defaults["global"]
    assert g == {
        "enabled": False,
        "username": DEFAULT_USERNAME,
        "exist_ok": True,
        "notify": False,
        "onlyonce": False,
        "clear": False,
    }


def test_build_defaults_covers_all_providers():
    specs = [p.get_spec() for p in registry.create_all()]
    defaults = build_defaults(specs)
    prov = defaults["providers"]
    # 反射出全部已注册 provider
    assert set(prov.keys()) == set(registry.ids())
    for spec in specs:
        block = prov[spec.provider_id]
        assert block["enabled"] is False
        assert block["cron"] == spec.default_cron
        # options/filters 键与各自 schema 完全对应，值为字段默认
        assert set(block["options"].keys()) == {f.key for f in spec.options_schema}
        assert set(block["filters"].keys()) == {f.key for f in spec.filters_schema}
        for f in spec.options_schema:
            assert block["options"][f.key] == f.default
        for f in spec.filters_schema:
            assert block["filters"][f.key] == f.default


# ---------- PluginSettings ----------

def test_plugin_settings_split():
    raw = {"global": {"username": "abc"},
           "providers": {"douban": {"enabled": True, "cron": "x"}}}
    settings = PluginSettings(raw)
    assert settings.global_config.username == "abc"
    assert settings.provider_raw("douban") == {"enabled": True, "cron": "x"}
    # 不存在的 provider -> 空 dict
    assert settings.provider_raw("nope") == {}


def test_plugin_settings_empty():
    settings = PluginSettings(None)
    assert settings.global_config.username == DEFAULT_USERNAME
    assert settings.provider_raw("douban") == {}
