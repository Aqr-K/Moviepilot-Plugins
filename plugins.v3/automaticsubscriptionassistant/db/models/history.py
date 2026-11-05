"""订阅展示历史与独立成功账本。"""

from sqlalchemy import JSON, Column, Index, Integer, String, Text

from .base import Base


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
    # v3 宿主通用媒体身份；下面三类 ID 列是旧表遗留，只用于兼容历史与前端展示。
    # 新来源必须写入 media_source/media_id，不再新增 anilistid/imdbid/tvdbid 等单源列。
    media_source = Column(String(64))
    media_id = Column(String(255))
    episode_group = Column(String(128))
    poster = Column(Text)
    season = Column(Integer)
    music_type = Column(String(32))
    artists = Column(JSON)
    album = Column(Text)
    candidate_key = Column(String(80))
    source_item = Column(JSON)
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
            "music_type": self.music_type,
            "artists": self.artists or [],
            "album": self.album,
            "provider": self.provider,
            "title": self.title,
            "year": self.year,
            "type": self.type,
            "tmdbid": self.tmdbid,
            "doubanid": self.doubanid,
            "bangumiid": self.bangumiid,
            "media_source": self.media_source,
            "media_id": self.media_id,
            "episode_group": self.episode_group,
            "poster": self.poster,
            "season": self.season,
            "candidate_key": self.candidate_key,
            "source_item": self.source_item,
            "status": self.status,
            "reason": self.reason,
            "time": self.time,
        }


class SubscribeHandled(Base):
    """独立的成功事实与候选别名，不随展示历史的保留上限删除。"""

    __tablename__ = "subscribe_handled"

    key = Column(String(255), primary_key=True)
    canonical = Column(String(255), nullable=False, index=True)
    provider = Column(String(64), nullable=False, default="")
