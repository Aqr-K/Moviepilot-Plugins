"""来源媒体候选及缓存序列化契约。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from hashlib import sha256
from typing import TYPE_CHECKING, Any

from .identity import (
    _legacy_source_identity,
    _normalize_media_identity,
    _source_value,
    media_identity,
)

if TYPE_CHECKING:
    from app.schemas.types import MediaType


@dataclass
class RankMediaItem:
    """抓取阶段产出的标准化中间条目。

    ``media_source/media_id`` 是 v3 的主身份；旧的 tmdb/douban/bangumi 字段仅保留
    为已有 Provider、缓存与历史数据提供过渡兼容。新来源不再新增对应的字段。
    """

    title: str
    year: str | None = None
    type_hint: MediaType | None = None
    douban_id: str | None = None
    tmdb_id: int | None = None
    bangumi_id: int | None = None
    tvdb_id: int | None = None
    imdb_id: str | None = None
    season: int | None = None
    poster: str | None = None
    source_meta: dict = field(default_factory=dict)
    unique_seed: str = ""
    music_type: str | None = None
    artists: list[str] = field(default_factory=list)
    album: str | None = None
    isrc: str | None = None
    media_source: Any = None
    media_id: str | None = None
    episode_group: str | None = None

    def candidate_key(self) -> str:
        """按原始候选的身份、标题、年份和季号生成精确的持久查重别名。

        不包含海报、热度等易变字段；保留标题和年份，避免来源未填季号时把后续季
        当成同一个整剧候选。跨来源合并仍以识别后的规范媒体身份为准。
        """
        values = self.to_dict()
        for key in ("poster", "source_meta", "unique_seed"):
            values.pop(key, None)
        values["title"] = (self.title or "").strip().casefold()
        payload = json.dumps(values, sort_keys=True, ensure_ascii=False)
        return "candidate:" + sha256(payload.encode("utf-8")).hexdigest()

    def dedup_key(self, provider_id: str) -> str:
        """返回去重键：``{provider_id}:{unique_seed}``。"""
        return f"{provider_id}:{self.unique_seed}"

    def identity(self) -> str:
        """媒体身份键（用条目自带的强标识；无强标识时回退名称）。

        与 :func:`media_identity` 一致，供历史记录去重合并。剧集是否按季由 ``type_hint`` 判定。
        """
        is_tv = bool(self.type_hint) and self.type_hint.value == "电视剧"
        source, media_id = self.source_identity()
        return media_identity(
            tmdb_id=self.tmdb_id,
            douban_id=self.douban_id,
            bangumi_id=self.bangumi_id,
            media_source=source,
            media_id=media_id,
            is_tv=is_tv,
            season=self.season,
            title=self.title,
            year=self.year,
            episode_group=self.episode_group,
            is_music=bool(self.type_hint) and self.type_hint.value == "音乐",
            music_type=self.music_type,
            artists=self.artists,
        )

    def source_identity(self) -> tuple[Any, str | None]:
        """返回条目的主来源身份，优先使用 v3 通用字段，兼容旧 ID 槽位。"""
        source, media_id = _normalize_media_identity(self.media_source, self.media_id)
        if source and media_id:
            return source, media_id
        return _legacy_source_identity(
            tmdb_id=self.tmdb_id,
            douban_id=self.douban_id,
            bangumi_id=self.bangumi_id,
            # tvdb/imdb 是旧缓存对象可能携带的字段；它们只作兼容输入，不能成为
            # v3 持久化模型或新增来源的扩展方式。
            imdb_id=self.imdb_id,
            tvdb_id=self.tvdb_id,
        )

    def strong_identities(self) -> list[tuple[Any, str]]:
        """返回全部可用强身份，供保守的宿主订阅快速索引使用。"""
        candidates = [
            (self.media_source, self.media_id),
            ("themoviedb", self.tmdb_id),
            ("douban", self.douban_id),
            ("bangumi", self.bangumi_id),
            ("imdb", self.imdb_id),
            ("tvdb", self.tvdb_id),
        ]
        result: list[tuple[Any, str]] = []
        seen = set()
        for source, media_id in candidates:
            normalized_source, normalized_id = _normalize_media_identity(
                source, media_id
            )
            if not normalized_source or not normalized_id:
                continue
            key = (_source_value(normalized_source), normalized_id)
            if key in seen:
                continue
            seen.add(key)
            result.append((normalized_source, normalized_id))
        return result

    def to_dict(self) -> dict[str, Any]:
        """序列化为 JSON 安全 dict（供持久化到插件 KV，如奈飞两级缓存的 L2）。

        ``type_hint`` 为 ``MediaType`` 枚举 → 取 ``.value``（中文串）以 JSON 安全；
        ``source_meta`` 已是原始 dict、原样带出；其余字段均为原始标量。
        """
        result = {
            "title": self.title,
            "year": self.year,
            "type_hint": self.type_hint.value if self.type_hint else None,
            "douban_id": self.douban_id,
            "tmdb_id": self.tmdb_id,
            "bangumi_id": self.bangumi_id,
            "tvdb_id": self.tvdb_id,
            "imdb_id": self.imdb_id,
            "season": self.season,
            "poster": self.poster,
            "source_meta": self.source_meta,
            "unique_seed": self.unique_seed,
            "media_source": _source_value(self.media_source),
            "media_id": self.media_id,
            "episode_group": self.episode_group,
        }

        if self.type_hint and self.type_hint.value == "音乐":
            result.update(
                music_type=self.music_type,
                artists=list(self.artists),
                album=self.album,
                isrc=self.isrc,
            )
        return result

    @classmethod
    def from_dict(cls, d: dict) -> RankMediaItem:
        """从持久化 dict 还原；缺字段走 dataclass 安全默认。

        ``MediaType`` 运行时局部 import（本模块 TYPE_CHECKING 保护导入以便离线测试）；
        ``type_hint`` 由 ``.value`` 串还原为枚举（空则 None）。
        """
        from app.schemas.types import MediaType

        d = d or {}
        type_value = d.get("type_hint")
        media_source, media_id = _normalize_media_identity(
            d.get("media_source"), d.get("media_id")
        )
        return cls(
            title=d.get("title", ""),
            music_type=d.get("music_type"),
            artists=list(d.get("artists") or []),
            album=d.get("album"),
            isrc=d.get("isrc"),
            year=d.get("year"),
            type_hint=MediaType(type_value) if type_value else None,
            douban_id=d.get("douban_id"),
            tmdb_id=d.get("tmdb_id"),
            bangumi_id=d.get("bangumi_id"),
            tvdb_id=d.get("tvdb_id"),
            imdb_id=d.get("imdb_id"),
            season=d.get("season"),
            poster=d.get("poster"),
            source_meta=d.get("source_meta") or {},
            unique_seed=d.get("unique_seed", ""),
            media_source=media_source,
            media_id=media_id,
            episode_group=d.get("episode_group"),
        )
