"""来源注册表：模块级单例 + ``@register`` 装饰器。"""
from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Optional, Type

if TYPE_CHECKING:
    from .provider import RankProvider


class ProviderRegistry:
    """按 provider_id 索引来源类，支持整体实例化与按需实例化。"""

    def __init__(self):
        self._providers: Dict[str, Type["RankProvider"]] = {}

    def register(self, cls: Type["RankProvider"]) -> Type["RankProvider"]:
        """注册来源类（以 cls.provider_id 为键）。"""
        self._providers[cls.provider_id] = cls
        return cls

    def create_all(self) -> List["RankProvider"]:
        """实例化所有已注册来源。"""
        return [cls() for cls in self._providers.values()]

    def get(self, provider_id: str) -> Optional["RankProvider"]:
        """按 id 实例化单个来源，未注册返回 None。"""
        cls = self._providers.get(provider_id)
        return cls() if cls else None

    def ids(self) -> List[str]:
        """返回所有已注册来源 id。"""
        return list(self._providers.keys())


# 模块级单例：providers/*.py 用 @register 装饰各自的 Provider 类完成注册。
registry = ProviderRegistry()


def register(cls: Type["RankProvider"]) -> Type["RankProvider"]:
    """装饰器：把来源类注册到模块级 registry。"""
    return registry.register(cls)
