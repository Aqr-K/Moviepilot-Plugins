"""配置解析层：类型安全访问器 + 嵌套配置包装 + 默认值反射。

配置为嵌套结构::

    {
      "global": {"enabled": bool, "username": str, "exist_ok": bool, "notify": bool,
                 "onlyonce": bool, "clear": bool},
      "providers": {
        "<provider_id>": {"enabled": bool, "cron": str, "options": {...}, "filters": {...}}
      }
    }

``TypedConfigAccess`` 的转换器实现对齐参考插件 subscribeassistantenhanced/shared/config.py，
避免各处重复且行为一致。``build_defaults`` 由 ProviderSpec 反射生成完整默认，杜绝表单/配置漂移。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List

if TYPE_CHECKING:
    from .models import FieldSpec, ProviderSpec

# 全局默认值集中定义，避免散落。
DEFAULT_USERNAME = "自动订阅助手"


class TypedConfigAccess:
    """原始 dict -> 类型安全访问器。缺失 key 一律回退默认值。"""

    def __init__(self, raw: dict):
        self._raw = raw or {}

    def get_bool(self, key: str, default: bool = False) -> bool:
        """布尔解析：bool 直返；字符串支持 true/on/yes/1。"""
        val = self._raw.get(key)
        if val is None:
            return default
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            return val.strip().lower() in ("true", "on", "yes", "1")
        return bool(val)

    def get_int(self, key: str, default: int = 0) -> int:
        """整数解析：用 int(float(v)) 容错，非法回退默认。"""
        val = self._raw.get(key)
        if val is None:
            return default
        try:
            return int(float(val))
        except (ValueError, TypeError):
            return default

    def get_float(self, key: str, default: float = 0.0) -> float:
        """浮点解析：非法回退默认。"""
        val = self._raw.get(key)
        if val is None:
            return default
        try:
            return float(val)
        except (ValueError, TypeError):
            return default

    def get_str(self, key: str, default: str = "") -> str:
        """字符串解析：None 回退默认，其余强转 str。"""
        val = self._raw.get(key)
        if val is None:
            return default
        return str(val)

    def get_list(self, key: str, default=None) -> list:
        """列表解析：list 直返；逗号分隔字符串拆分去空；其余返回默认。"""
        val = self._raw.get(key)
        if isinstance(val, list):
            return [str(v).strip() for v in val if str(v).strip()]
        if isinstance(val, str):
            return [v.strip() for v in val.split(",") if v.strip()]
        return list(default or [])


def _read_field(access: TypedConfigAccess, spec_field: "FieldSpec") -> Any:
    """按 FieldSpec.kind 用对应转换器读取值，缺失回退 spec 默认。"""
    kind = spec_field.kind
    default = spec_field.default
    if kind == "switch":
        return access.get_bool(spec_field.key, bool(default))
    if kind == "number":
        return access.get_int(spec_field.key, int(default) if default not in (None, "") else 0)
    if kind == "float":
        return access.get_float(spec_field.key, float(default) if default not in (None, "") else 0.0)
    if kind == "multi-select":
        return access.get_list(spec_field.key, default if isinstance(default, list) else [])
    # text / select / cron / textarea / hidden 等按字符串处理
    return access.get_str(spec_field.key, str(default) if default is not None else "")


class GlobalConfig(TypedConfigAccess):
    """全局配置：作用于所有来源的公共项。"""

    @property
    def enabled(self) -> bool:
        """插件总开关：关闭后不注册任何定时任务。"""
        return self.get_bool("enabled", False)

    @property
    def username(self) -> str:
        """订阅落地使用的用户名。"""
        return self.get_str("username", DEFAULT_USERNAME)

    @property
    def exist_ok(self) -> bool:
        """加订阅时允许已存在（避免重复报错）。"""
        return self.get_bool("exist_ok", True)

    @property
    def notify(self) -> bool:
        """是否推送运行结果通知。"""
        return self.get_bool("notify", False)

    @property
    def onlyonce(self) -> bool:
        """保存后立即运行一次，执行后自动复位。"""
        return self.get_bool("onlyonce", False)

    @property
    def clear(self) -> bool:
        """清空历史记录，执行后自动复位。"""
        return self.get_bool("clear", False)


class ProviderConfig(TypedConfigAccess):
    """单个来源配置包装：``{enabled, cron, options, filters}``。"""

    def __init__(self, raw: dict, spec: "ProviderSpec"):
        super().__init__(raw)
        self.spec = spec
        self.options: dict = dict(self._raw.get("options") or {})
        self.filters: dict = dict(self._raw.get("filters") or {})
        self._options_access = TypedConfigAccess(self.options)
        self._filters_access = TypedConfigAccess(self.filters)
        self._options_specs: Dict[str, "FieldSpec"] = {f.key: f for f in (spec.options_schema or [])}
        self._filters_specs: Dict[str, "FieldSpec"] = {f.key: f for f in (spec.filters_schema or [])}

    @property
    def enabled(self) -> bool:
        """该来源是否启用。"""
        return self.get_bool("enabled", False)

    @property
    def cron(self) -> str:
        """定时表达式，默认取 spec.default_cron。"""
        return self.get_str("cron", self.spec.default_cron)

    def option(self, key: str) -> Any:
        """读取某个 option，带 spec 默认值回退。"""
        spec_field = self._options_specs.get(key)
        if spec_field is not None:
            return _read_field(self._options_access, spec_field)
        return self.options.get(key)

    def filter(self, key: str) -> Any:
        """读取某个 filter，带 spec 默认值回退。"""
        spec_field = self._filters_specs.get(key)
        if spec_field is not None:
            return _read_field(self._filters_access, spec_field)
        return self.filters.get(key)


class PluginSettings:
    """顶层配置访问器：拆分 global 与各 provider 的原始 dict。"""

    def __init__(self, raw: dict):
        self._raw = raw or {}

    @property
    def global_config(self) -> GlobalConfig:
        """返回全局配置访问器。"""
        return GlobalConfig(self._raw.get("global") or {})

    def provider_raw(self, provider_id: str) -> dict:
        """返回指定来源的原始配置 dict（不存在则空 dict）。"""
        providers = self._raw.get("providers") or {}
        return providers.get(provider_id) or {}


def build_defaults(specs: List["ProviderSpec"]) -> dict:
    """由 ProviderSpec 列表反射出完整默认配置，供 get_form 第二项使用。"""
    defaults: Dict[str, Any] = {
        "global": {
            "enabled": False,
            "username": DEFAULT_USERNAME,
            "exist_ok": True,
            "notify": False,
            "onlyonce": False,
            "clear": False,
        },
        "providers": {},
    }
    for spec in specs:
        options = {f.key: f.default for f in (spec.options_schema or [])}
        filters = {f.key: f.default for f in (spec.filters_schema or [])}
        defaults["providers"][spec.provider_id] = {
            "enabled": False,
            "cron": spec.default_cron,
            "options": options,
            "filters": filters,
        }
    return defaults
