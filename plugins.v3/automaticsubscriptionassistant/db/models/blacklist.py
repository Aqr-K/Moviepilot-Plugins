"""手动忽略规则；与历史和成功事实一起属于插件数据库。"""

from sqlalchemy import JSON, Column, String

from .base import Base


class SubscriptionBlacklist(Base):
    __tablename__ = "subscription_blacklist"
    id = Column(String(32), primary_key=True)
    fingerprint = Column(String(64), nullable=False, unique=True)
    payload = Column(JSON, nullable=False)


class DatabaseState(Base):
    """迁移检查点，禁止用进程内缓存代替持久状态。"""

    __tablename__ = "database_state"
    key = Column(String(64), primary_key=True)
    value = Column(JSON, nullable=False)
