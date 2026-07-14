"""两阶段媒体过滤器。

阶段：``pre``（识别前，仅有 RankMediaItem）、``post``（识别后，附 MediaInfo）。
每个过滤器阈值为 0 / None 时视为未启用，直接放行。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Dict, List, Optional, Type

from app.schemas.types import MediaType

from .models import FilterVerdict, RankMediaItem

if TYPE_CHECKING:
    from app.core.context import MediaInfo


def _to_int(value) -> int:
    """安全转 int，失败返回 0。"""
    if value is None:
        return 0
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return 0


def _to_float(value) -> float:
    """安全转 float，失败返回 0.0。"""
    if value is None:
        return 0.0
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0


class MediaFilter(ABC):
    """过滤器基类。"""

    filter_id: str = ""
    stage: str = "pre"  # "pre" | "post"

    @abstractmethod
    def accept(self, item: RankMediaItem, mediainfo: Optional["MediaInfo"], config: dict) -> FilterVerdict:
        """裁决单条条目是否通过。"""
        raise NotImplementedError


class VoteFilter(MediaFilter):
    """评分过滤（post）：用 mediainfo.vote_average >= 阈值。"""

    filter_id = "vote"
    stage = "post"

    def accept(self, item, mediainfo, config):
        threshold = _to_float((config or {}).get("vote"))
        if threshold <= 0:
            return FilterVerdict.accept()
        vote = _to_float(getattr(mediainfo, "vote_average", None))
        if vote >= threshold:
            return FilterVerdict.accept()
        return FilterVerdict.reject(self.filter_id, f"评分 {vote} < {threshold}")


class YearFilter(MediaFilter):
    """年份过滤（pre）：item.year（或 mediainfo.year）>= 阈值年份。"""

    filter_id = "year"
    stage = "pre"

    def accept(self, item, mediainfo, config):
        threshold = _to_int((config or {}).get("year"))
        if threshold <= 0:
            return FilterVerdict.accept()
        raw_year = (item.year if item and item.year else None) \
            or (getattr(mediainfo, "year", None) if mediainfo else None)
        year = _to_int(raw_year)
        # 无有效年份信息时放行，避免误伤缺字段条目。
        if year <= 0:
            return FilterVerdict.accept()
        if year >= threshold:
            return FilterVerdict.accept()
        return FilterVerdict.reject(self.filter_id, f"年份 {year} < {threshold}")


class PopularityFilter(MediaFilter):
    """热度过滤（pre）：item.source_meta['count'] >= 阈值。"""

    filter_id = "popularity"
    stage = "pre"

    def accept(self, item, mediainfo, config):
        threshold = _to_int((config or {}).get("popularity"))
        if threshold <= 0:
            return FilterVerdict.accept()
        count = _to_int((item.source_meta or {}).get("count")) if item else 0
        if count >= threshold:
            return FilterVerdict.accept()
        return FilterVerdict.reject(self.filter_id, f"订阅人次 {count} < {threshold}")


class MediaTypeFilter(MediaFilter):
    """类型过滤（post）：config['media_type'] ∈ {all, movie, tv}。"""

    filter_id = "media_type"
    stage = "post"

    def accept(self, item, mediainfo, config):
        wanted = str((config or {}).get("media_type") or "all").strip().lower()
        if wanted not in ("movie", "tv"):
            return FilterVerdict.accept()
        mtype = getattr(mediainfo, "type", None) if mediainfo else None
        if wanted == "movie" and mtype != MediaType.MOVIE:
            return FilterVerdict.reject(self.filter_id, "非电影")
        if wanted == "tv" and mtype != MediaType.TV:
            return FilterVerdict.reject(self.filter_id, "非电视剧")
        return FilterVerdict.accept()


class FilterChain:
    """按阶段顺序执行过滤器，短路于首个拒绝。"""

    def __init__(self, filters: List[MediaFilter]):
        self._filters = filters or []

    def run(self, stage: str, item, mediainfo, config) -> FilterVerdict:
        """执行指定阶段的所有过滤器；任一拒绝立即返回该裁决。"""
        for f in self._filters:
            if f.stage != stage:
                continue
            verdict = f.accept(item, mediainfo, config)
            if not verdict.accepted:
                return verdict
        return FilterVerdict.accept()


# 内置过滤器注册表：filter_id -> 过滤器类。
BUILTIN_FILTERS: Dict[str, Type[MediaFilter]] = {
    VoteFilter.filter_id: VoteFilter,
    YearFilter.filter_id: YearFilter,
    PopularityFilter.filter_id: PopularityFilter,
    MediaTypeFilter.filter_id: MediaTypeFilter,
}


def build_filter_chain(filter_ids: List[str]) -> FilterChain:
    """按 spec 声明的 filter_ids 从内置注册表挑选实例，未知 id 跳过。"""
    filters: List[MediaFilter] = []
    for fid in filter_ids or []:
        cls = BUILTIN_FILTERS.get(fid)
        if cls is not None:
            filters.append(cls())
    return FilterChain(filters)
