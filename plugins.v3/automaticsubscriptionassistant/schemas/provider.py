"""来源配置与字段描述契约。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FieldSpec:
    """前端动态渲染用的单个配置字段描述。"""

    key: str
    label: str
    kind: str  # switch|number|float|text|select|multi-select|cron|textarea|hidden|rule-list
    default: Any = None
    options: list[dict[str, Any]] | None = None
    hint: str = ""
    advanced: bool = False  # 前端归入“高级选项”，默认折叠不直接显示
    # 规则卡片编辑器：字段、预设及有界校验由来源声明。
    fields: list[FieldSpec] | None = None
    presets: list[dict[str, Any]] | None = None
    minimum: float | None = None
    maximum: float | None = None
    required: bool = False
    visible_when: dict[str, list[Any]] | None = None
    options_by: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """序列化为前端可消费的 dict。"""
        result = {
            "key": self.key,
            "label": self.label,
            "kind": self.kind,
            "default": self.default,
            "options": self.options,
            "hint": self.hint,
            "advanced": self.advanced,
        }
        for key in ("minimum", "maximum", "visible_when", "options_by", "presets"):
            value = getattr(self, key)
            if value is not None:
                result[key] = value
        if self.fields is not None:
            result["fields"] = [f.to_dict() for f in self.fields]
        if self.required:
            result["required"] = True
        return result


@dataclass
class ProviderSpec:
    """来源（Provider）的元描述：标识、默认周期与可配置字段。"""

    provider_id: str
    provider_name: str
    default_cron: str
    options_schema: list[FieldSpec] = field(default_factory=list)
    filters_schema: list[FieldSpec] = field(default_factory=list)
    # 来源级告示：前端在该来源配置区顶部以提示条展示（如某能力停更下线的说明）。
    notice: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """序列化整个来源描述，含选项与过滤器 schema。"""
        return {
            "provider_id": self.provider_id,
            "provider_name": self.provider_name,
            "default_cron": self.default_cron,
            "options_schema": [f.to_dict() for f in self.options_schema],
            "filters_schema": [f.to_dict() for f in self.filters_schema],
            "notice": self.notice,
        }
