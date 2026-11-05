"""媒体身份与旧身份输入的兼容解析。"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote


def _normalize_media_identity(source, media_id) -> tuple[Any, str | None]:
    """把来源与原生 ID 规范化为 v3 宿主使用的二元组。

    这里故意延迟导入宿主模块：模型层仍可在脱离 MoviePilot 的纯单元测试中导入，
    同时真实运行时复用宿主对内置别名和插件扩展来源的校验逻辑。
    """
    if source is None or media_id is None:
        return None, None
    try:
        from app.sdk.media import normalize_media_source

        normalized_source = normalize_media_source(source)
    except (ImportError, ModuleNotFoundError):
        normalized_source = source
    normalized_id = str(media_id).strip()
    if not normalized_source or not normalized_id or normalized_id == "0":
        return None, None
    return normalized_source, normalized_id


def _source_value(source) -> str | None:
    """取 MediaSource 枚举或裸字符串的稳定值。"""
    if source is None:
        return None
    return str(getattr(source, "value", source))


def _source_prefix(source) -> str:
    """将宿主来源转换为历史键命名空间，未知扩展来源使用自身值。"""
    try:
        from app.sdk.media import MEDIA_SOURCE_PREFIXES

        return MEDIA_SOURCE_PREFIXES.get(source, _source_value(source))
    except (ImportError, ModuleNotFoundError):
        return (
            "tmdb" if _source_value(source) == "themoviedb" else _source_value(source)
        )


def _identity_group_suffix(episode_group) -> str:
    """为身份键追加无歧义的剧集组片段；无组时保持旧键完全不变。"""
    if episode_group is None or not str(episode_group).strip():
        return ""
    return f":g{quote(str(episode_group).strip(), safe='')}"


def _legacy_source_identity(
    tmdb_id=None,
    douban_id=None,
    bangumi_id=None,
    anilist_id=None,
    imdb_id=None,
    tvdb_id=None,
):
    """将旧版分散 ID 字段转换成宿主身份。

    这里只是迁移/兼容适配器，不是 v3 数据模型。新数据只写
    ``media_source/media_id``，后续新增来源不应再在这里增加字段。
    """
    for source, media_id in (
        ("themoviedb", tmdb_id),
        ("douban", douban_id),
        ("bangumi", bangumi_id),
        ("anilist", anilist_id),
        ("imdb", imdb_id),
        ("tvdb", tvdb_id),
    ):
        normalized_source, normalized_id = _normalize_media_identity(source, media_id)
        if normalized_source and normalized_id:
            return normalized_source, normalized_id
    return None, None


def media_identity(
    tmdb_id: int | None = None,
    douban_id: str | None = None,
    bangumi_id: int | None = None,
    is_tv: bool = False,
    season: int | None = None,
    title: str = "",
    year: str | None = None,
    media_source=None,
    media_id=None,
    episode_group: str | None = None,
    is_music: bool = False,
    music_type: str | None = None,
    artists=(),
) -> str:
    """从最强可用标识生成稳定的「媒体身份键」，供历史记录去重（跨渠道合并展示）。

    优先级：显式 ``media_source/media_id`` > 旧版 tmdb/douban/bangumi 字段 >
    名称回退。所有新来源都必须通过通用身份传入，不再为每个来源增加参数。
    名称回退仅用于展示层的记录合并，**绝不**可用于跳过识别/订阅（避免同名不同作品误伤）。
    """
    source, identity = _normalize_media_identity(media_source, media_id)
    if not source or not identity:
        source, identity = _legacy_source_identity(
            tmdb_id=tmdb_id, douban_id=douban_id, bangumi_id=bangumi_id
        )
    if is_music:
        kind = music_type or "unknown"
        if source and identity:
            return f"{_source_prefix(source)}:music:{kind}:{identity}"
        artist_key = quote(
            "|".join(sorted(str(name).strip().casefold() for name in artists)), safe=""
        )
        return f"name:music:{kind}:{artist_key}:{(title or '').strip().casefold()}:{year or ''}"
    group = _identity_group_suffix(episode_group)
    if source and identity:
        prefix = _source_prefix(source)
        if prefix == "tmdb":
            if is_tv:
                return (
                    f"tmdb:tv:{identity}:s{season}{group}"
                    if season is not None
                    else f"tmdb:tv:{identity}{group}"
                )
            return f"tmdb:movie:{identity}{group}"
        if is_tv:
            return (
                f"{prefix}:tv:{identity}:s{season}{group}"
                if season is not None
                else f"{prefix}:tv:{identity}{group}"
            )
        return f"{prefix}:{identity}{group}"
    return f"name:{(title or '').strip().lower()}:{year or ''}{group}"
