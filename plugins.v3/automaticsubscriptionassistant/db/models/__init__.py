"""插件数据库模型声明；迁移不导入这里的可变元数据。"""

from .base import Base
from .blacklist import DatabaseState, SubscriptionBlacklist
from .history import SubscribeHandled, SubscribeHistory

MODELS = (SubscribeHistory, SubscribeHandled, SubscriptionBlacklist, DatabaseState)

__all__ = [
    "MODELS",
    "Base",
    "DatabaseState",
    "SubscribeHandled",
    "SubscribeHistory",
    "SubscriptionBlacklist",
]
