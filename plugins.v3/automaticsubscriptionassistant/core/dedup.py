"""已订阅强标识索引：识别前的预去重快速路径。

宿主 v3 的订阅身份是通用的 ``(media_source, media_id)`` 二元组，本模块直接沿用
这套模型，按媒体类型与季号补充快速查重键。它只是 ``SubscribeChain.exists()`` 的
保守快速路径：未命中或来源无法规范化时仍交给宿主识别与查重，不把本地索引当成
最终事实来源。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote

from app.schemas.types import MediaSource

from .models import media_identity

if TYPE_CHECKING:
    from .models import RankMediaItem


def _normalize_source(media_source):
    """复用宿主 v3 的来源规范化，兼容测试中的裸字符串。"""
    if media_source is None:
        return None
    try:
        from app.schemas.media import normalize_media_source

        return normalize_media_source(media_source)
    except (ImportError, ModuleNotFoundError):
        try:
            return MediaSource(media_source)
        except (TypeError, ValueError):
            return None


def _source_value(media_source) -> Optional[str]:
    """取媒体来源的规范字符串值。"""
    source = _normalize_source(media_source)
    return str(getattr(source, "value", source)) if source else None


def _source_prefix(media_source) -> Optional[str]:
    """取历史/索引命名空间，TMDB 使用兼容旧版的 tmdb 前缀。"""
    source = _normalize_source(media_source)
    if not source:
        return None
    try:
        from app.schemas.media import MEDIA_SOURCE_PREFIXES

        return MEDIA_SOURCE_PREFIXES.get(source, _source_value(source))
    except (ImportError, ModuleNotFoundError):
        return "tmdb" if _source_value(source) == MediaSource.TMDB.value else _source_value(source)


def _is_tv(mtype) -> bool:
    """判断媒体类型是否剧集：兼容 MediaType 枚举与中文/英文字符串。"""
    if mtype is None:
        return False
    val = getattr(mtype, "value", mtype)
    return str(val) in ("电视剧", "tv", "TV")


def _has_type(mtype) -> bool:
    """判断类型是否已知，未知类型不能安全套用电影键。"""
    if mtype is None:
        return False
    val = getattr(mtype, "value", mtype)
    return str(val) in ("电视剧", "tv", "TV", "电影", "movie", "MOVIE")


def _group_suffix(episode_group) -> str:
    """将剧集组纳入快速键；None 与空串保持宿主的无组语义。"""
    if episode_group is None or not str(episode_group).strip():
        return ""
    return f":g{quote(str(episode_group).strip(), safe='')}"


def _strong_keys(media_source, media_id, is_tv: bool, season,
                 type_known: bool, for_item: bool = False,
                 episode_group=None) -> List[str]:
    """按宿主身份生成快速查重键。

    TMDB 保持旧版的 ``m:tmdb`` / ``tv:tmdb`` 键形态。其它来源使用相同的类型和
    季号语义，同时保留无类型旧数据的 ``{source}:{id}`` 兼容键；电视订阅不会写
    这个无类型别名，避免不同季误命中。
    """
    prefix = _source_prefix(media_source)
    if not prefix or not media_id:
        return []
    media_id = str(media_id).strip()
    if not media_id or media_id == "0":
        return []
    group = _group_suffix(episode_group)

    if prefix == "tmdb":
        if not type_known:
            return []
        if is_tv:
            if for_item:
                if season is None:
                    return [f"tv:tmdb:{media_id}:*{group}"]
                return [f"tv:tmdb:{media_id}:s{season}{group}"]
            keys = [f"tv:tmdb:{media_id}:*{group}"]
            if season is not None:
                keys.append(f"tv:tmdb:{media_id}:s{season}{group}")
            return keys
        return [f"m:tmdb:{media_id}{group}"]

    if is_tv:
        if for_item:
            if season is None:
                return [f"tv:{prefix}:{media_id}:*{group}"]
            return [f"tv:{prefix}:{media_id}:s{season}{group}"]
        keys = [f"tv:{prefix}:{media_id}:*{group}"]
        if season is not None:
            keys.append(f"tv:{prefix}:{media_id}:s{season}{group}")
        return keys

    if type_known:
        # 无类型别名只用于非电视剧，兼容旧版 add_media(doubanid=...) 与历史索引。
        return [f"m:{prefix}:{media_id}{group}", f"{prefix}:{media_id}{group}"]
    return [f"{prefix}:{media_id}{group}"]


class SubscribedIndex:
    """强标识键 → 规范媒体身份键的映射。"""

    def __init__(self) -> None:
        self._keys: Dict[str, str] = {}

    def add_media(self, tmdbid: Optional[int] = None, doubanid: Optional[str] = None,
                  bangumiid: Optional[int] = None, mtype=None, season: Optional[int] = None,
                  title: str = "", year: Optional[str] = None, media_source=None,
                  media_id=None, episode_group: Optional[str] = None) -> None:
        """登记一条媒体的全部强身份。

        前三个参数是旧调用点的兼容入口；新的宿主订阅行应传
        ``media_source/media_id``。同一条数据带多个辅助 ID 时，每个 ID 都会指向
        同一个规范身份，以支持榜单来源之间的安全合并。
        """
        identities: List[Tuple[object, object]] = [(media_source, media_id)]
        identities.extend([
            ("themoviedb", tmdbid),
            ("douban", doubanid),
            ("bangumi", bangumiid),
        ])
        normalized: List[Tuple[object, str]] = []
        seen = set()
        for source, value in identities:
            normalized_source = _normalize_source(source)
            normalized_id = str(value).strip() if value is not None else ""
            if not normalized_source or not normalized_id or normalized_id == "0":
                continue
            key = (_source_value(normalized_source), normalized_id)
            if key not in seen:
                normalized.append((normalized_source, normalized_id))
                seen.add(key)
        if not normalized:
            return

        is_tv = _is_tv(mtype)
        type_known = _has_type(mtype)
        primary_source, primary_id = normalized[0]
        canonical = media_identity(
            media_source=primary_source, media_id=primary_id,
            is_tv=is_tv, season=season, title=title, year=year,
            episode_group=episode_group)
        for source, value in normalized:
            for key in _strong_keys(source, value, is_tv, season, type_known,
                                    episode_group=episode_group):
                # 首个登记者定规范身份，保证跨渠道命中回同一条历史记录。
                self._keys.setdefault(key, canonical)

    def _match_key(self, item: "RankMediaItem") -> Optional[str]:
        """返回条目命中的强标识键，未命中返回 None。"""
        is_tv = _is_tv(item.type_hint)
        type_known = _has_type(item.type_hint)
        for source, media_id in item.strong_identities():
            for key in _strong_keys(source, media_id, is_tv, item.season,
                                    type_known, for_item=True,
                                    episode_group=getattr(item, "episode_group", None)):
                if key in self._keys:
                    return key
        return None

    def contains(self, item: "RankMediaItem") -> bool:
        """条目是否被强标识命中（已订阅 / 本轮已处理）。"""
        return self._match_key(item) is not None

    def identity_for(self, item: "RankMediaItem") -> Optional[str]:
        """命中时返回其规范媒体身份键（用于跨渠道合并历史记录），否则 None。"""
        key = self._match_key(item)
        return self._keys.get(key) if key else None


def build_subscribed_index(subscriptions: Iterable) -> SubscribedIndex:
    """从宿主订阅对象预加载索引。

    宿主行的 ``media_source/media_id`` 是事实来源，不再通过固定白名单投影成
    三个旧 ID 槽位，因此 IMDb、TVDB、AniList 与合法插件扩展来源都可参与快速路。
    单条异常不影响整体构建，未能解析的行仍由宿主 ``exists`` 兜底。
    """
    index = SubscribedIndex()
    for sub in subscriptions or []:
        try:
            source = getattr(sub, "media_source", None)
            media_id = getattr(sub, "media_id", None)
            if not _normalize_source(source) or not media_id:
                continue
            index.add_media(
                media_source=source,
                media_id=media_id,
                mtype=getattr(sub, "type", None),
                season=getattr(sub, "season", None),
                episode_group=getattr(sub, "episode_group", None),
                title=getattr(sub, "name", "") or getattr(sub, "title", ""),
                year=getattr(sub, "year", None),
            )
        except Exception:  # noqa: BLE001 - 单条订阅解析失败不应阻断整体预加载
            continue
    return index
