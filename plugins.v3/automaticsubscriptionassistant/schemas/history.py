"""历史记录的业务序列化契约，与数据库表模型分离。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .identity import _legacy_source_identity, _normalize_media_identity, _source_value


@dataclass
class HistoryRecord:
    """写入插件自有表的一条历史记录。

    旧的三类 ID 字段继续保留供 UI/迁移兼容；通用身份字段用于保存 v3 宿主的
    任意内置或扩展来源。新来源不会再增加新的单源列。
    """

    unique: str
    provider: str
    title: str
    year: str | None = None
    type: str | None = None  # 中文 MediaType.value 或 ''
    tmdbid: int | None = None
    doubanid: str | None = None
    bangumiid: int | None = None
    poster: str | None = None
    season: int | None = None
    status: str = ""  # SubscribeStatus.value
    reason: str | None = None
    time: str = ""  # "%Y-%m-%d %H:%M:%S"
    media_source: Any = None
    media_id: str | None = None
    episode_group: str | None = None

    music_type: str | None = None
    artists: list[str] = field(default_factory=list)
    album: str | None = None

    candidate_key: str | None = None
    source_item: dict | None = None

    def to_dict(self) -> dict[str, Any]:
        """序列化为可持久化 dict。"""
        return {
            "unique": self.unique,
            "music_type": self.music_type,
            "artists": self.artists,
            "album": self.album,
            "candidate_key": self.candidate_key,
            "source_item": self.source_item,
            "provider": self.provider,
            "title": self.title,
            "year": self.year,
            "type": self.type,
            "tmdbid": self.tmdbid,
            "doubanid": self.doubanid,
            "bangumiid": self.bangumiid,
            "media_source": _source_value(self.media_source),
            "media_id": self.media_id,
            "episode_group": self.episode_group,
            "poster": self.poster,
            "season": self.season,
            "status": self.status,
            "reason": self.reason,
            "time": self.time,
        }

    @classmethod
    def from_dict(cls, data: dict, migrate_legacy: bool = False) -> HistoryRecord:
        """从持久化 dict 反序列化，缺字段走安全默认。

        ``migrate_legacy=True`` 仅供旧 KV/旧表迁移使用：把历史单源字段转换成
        通用身份。默认不改变旧调用点的对象值，避免普通反序列化隐式改写数据。
        """
        data = data or {}
        media_source, media_id = _normalize_media_identity(
            data.get("media_source"), data.get("media_id")
        )
        if migrate_legacy and (not media_source or not media_id):
            # 只在读取旧 KV/旧表投影时解析历史单源字段；解析后统一落到通用身份，
            # 不把这些字段带入新的 HistoryRecord 或数据库 schema。
            media_source, media_id = _legacy_source_identity(
                tmdb_id=data.get("tmdbid"),
                douban_id=data.get("doubanid"),
                bangumi_id=data.get("bangumiid"),
                anilist_id=data.get("anilistid"),
                imdb_id=data.get("imdbid"),
                tvdb_id=data.get("tvdbid"),
            )
        return cls(
            unique=data.get("unique", ""),
            music_type=data.get("music_type"),
            artists=list(data.get("artists") or []),
            album=data.get("album"),
            candidate_key=data.get("candidate_key"),
            source_item=data.get("source_item"),
            provider=data.get("provider", ""),
            title=data.get("title", ""),
            year=data.get("year"),
            type=data.get("type"),
            tmdbid=data.get("tmdbid"),
            doubanid=data.get("doubanid"),
            bangumiid=data.get("bangumiid"),
            media_source=media_source,
            media_id=media_id,
            episode_group=data.get("episode_group"),
            poster=data.get("poster"),
            season=data.get("season"),
            status=data.get("status", ""),
            reason=data.get("reason"),
            time=data.get("time", ""),
        )
