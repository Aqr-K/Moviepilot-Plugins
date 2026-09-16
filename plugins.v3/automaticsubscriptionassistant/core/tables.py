"""插件自有表定义。

表建在插件独立的库与 ``MetaData`` 上，与宿主表互不干扰；宿主在插件启动时按
``get_database_models()`` 建表，存储层另有幂等兜底，故不依赖宿主的建表时机。

``time`` 用 ``"%Y-%m-%d %H:%M:%S"`` 文本存放：该格式字典序即时间序，可直接参与
SQL 排序与范围比较，也与前端既有展示同形，无需换算。
"""
from __future__ import annotations

from sqlalchemy import Column, Index, Integer, String, Text

from app.sdk.database import plugin_declarative_base

Base = plugin_declarative_base()


class SubscribeHistory(Base):
    """一条订阅历史：一个媒体身份键对应一行。"""

    __tablename__ = "subscribe_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # 媒体身份键，跨来源合并的依据；同一媒体重复命中只保留一行。
    unique = Column(String(255), nullable=False, unique=True, index=True)
    provider = Column(String(64), nullable=False, default="")
    title = Column(String(512), nullable=False, default="")
    year = Column(String(16))
    # year 的整数形态，写入时解析好。发行年份区间筛选按本列比较：直接 CAST 文本列不可移植
    # （SQLite 把无法解析的值当 0，PostgreSQL 直接报错），解析不出年份的记录此列为空，
    # 带区间约束时不会被选中。
    year_num = Column(Integer, index=True)
    # 中文 MediaType.value，未识别时为空串。
    type = Column(String(32))
    tmdbid = Column(Integer)
    doubanid = Column(String(64))
    bangumiid = Column(Integer)
    poster = Column(Text)
    season = Column(Integer)
    # SubscribeStatus.value。
    status = Column(String(32), nullable=False, default="", index=True)
    reason = Column(Text)
    time = Column(String(32), nullable=False, default="", index=True)

    # 列表页的默认视图是「按状态/来源筛选 + 按时间倒序分页」，按此建复合索引。
    __table_args__ = (
        Index("ix_subscribe_history_status_time", "status", "time"),
        Index("ix_subscribe_history_provider_time", "provider", "time"),
    )

    def to_dict(self) -> dict:
        """序列化为前端所需的 dict（不含自增主键）。"""
        return {
            "unique": self.unique,
            "provider": self.provider,
            "title": self.title,
            "year": self.year,
            "type": self.type,
            "tmdbid": self.tmdbid,
            "doubanid": self.doubanid,
            "bangumiid": self.bangumiid,
            "poster": self.poster,
            "season": self.season,
            "status": self.status,
            "reason": self.reason,
            "time": self.time,
        }


# 供 get_database_models() 声明与存储层取用。
MODELS = [SubscribeHistory]
