"""核心数据模型：状态枚举与不可变数据对象。

全部使用 dataclass + Enum，凡需序列化到前端或插件 KV 的对象均提供 ``to_dict()``。
MediaInfo / MediaType 仅用于类型注解，通过 ``TYPE_CHECKING`` 延迟导入，
使本模块可在无重依赖环境下被测试直接导入。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from app.core.context import MediaInfo
    from app.schemas.types import MediaType


def media_identity(tmdb_id: Optional[int] = None, douban_id: Optional[str] = None,
                   bangumi_id: Optional[int] = None, is_tv: bool = False,
                   season: Optional[int] = None, title: str = "", year: Optional[str] = None) -> str:
    """从最强可用标识生成稳定的「媒体身份键」，供历史记录去重（跨渠道合并展示）。

    优先级：tmdb（区分电影/剧集，剧集含季）> douban > bangumi > 名称回退。
    名称回退仅用于展示层的记录合并，**绝不**可用于跳过识别/订阅（避免同名不同作品误伤）。
    """
    if tmdb_id:
        if is_tv:
            return f"tmdb:tv:{tmdb_id}:s{season}" if season is not None else f"tmdb:tv:{tmdb_id}"
        return f"tmdb:movie:{tmdb_id}"
    if douban_id:
        return f"douban:{douban_id}"
    if bangumi_id:
        return f"bangumi:{bangumi_id}"
    return f"name:{(title or '').strip().lower()}:{year or ''}"


class SubscribeStatus(str, Enum):
    """单条媒体经过统一落地管线后的最终状态。"""

    SUBSCRIBED = "subscribed"                    # 已订阅
    MEDIA_EXISTS = "media_exists"                # 媒体库已存在
    SUBSCRIPTION_EXISTS = "subscription_exists"  # 订阅已存在
    FILTERED = "filtered"                        # 被过滤（附 reason）
    UNRECOGNIZED = "unrecognized"                # 未识别
    ALREADY_HANDLED = "already_handled"          # 已处理（去重键命中）
    ERROR = "error"                              # 异常


@dataclass
class FieldSpec:
    """前端动态渲染用的单个配置字段描述。"""

    key: str
    label: str
    kind: str  # switch|number|float|text|select|multi-select|cron|textarea|hidden|region-media-map
    default: Any = None
    options: Optional[List[Dict[str, Any]]] = None  # select / multi-select / region-media-map(行=地区) 用
    hint: str = ""
    advanced: bool = False  # 前端归入“高级选项”，默认折叠不直接显示
    # region-media-map 专用：媒体类型轴（列），如 [{"title": "电影", "value": "Films"}, ...]。
    # 值形态为 {行value: [列value, ...]}，用于「行 × 列」任意组合。
    columns: Optional[List[Dict[str, Any]]] = None
    # region-media-map 专用：行的名词标识，供前端文案（如“添加{名词}”）本地化。
    # 取值 "region"（地区，默认）或 "platform"（平台）等；缺省按“地区”。
    row_noun: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """序列化为前端可消费的 dict。"""
        return {
            "key": self.key,
            "label": self.label,
            "kind": self.kind,
            "default": self.default,
            "options": self.options,
            "hint": self.hint,
            "advanced": self.advanced,
            "columns": self.columns,
            "row_noun": self.row_noun,
        }


@dataclass
class ProviderSpec:
    """来源（Provider）的元描述：标识、默认周期与可配置字段。"""

    provider_id: str
    provider_name: str
    default_cron: str
    options_schema: List[FieldSpec] = field(default_factory=list)
    filters_schema: List[FieldSpec] = field(default_factory=list)
    # 来源级告示：前端在该来源配置区顶部以提示条展示（如某能力停更下线的说明）。
    notice: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """序列化整个来源描述，含选项与过滤器 schema。"""
        return {
            "provider_id": self.provider_id,
            "provider_name": self.provider_name,
            "default_cron": self.default_cron,
            "options_schema": [f.to_dict() for f in self.options_schema],
            "filters_schema": [f.to_dict() for f in self.filters_schema],
            "notice": self.notice,
        }


@dataclass
class RankMediaItem:
    """抓取阶段产出的标准化中间条目（可能尚未带 tmdbid）。"""

    title: str
    year: Optional[str] = None
    type_hint: Optional["MediaType"] = None
    douban_id: Optional[str] = None
    tmdb_id: Optional[int] = None
    bangumi_id: Optional[int] = None
    tvdb_id: Optional[int] = None
    imdb_id: Optional[str] = None
    season: Optional[int] = None
    poster: Optional[str] = None
    source_meta: dict = field(default_factory=dict)
    unique_seed: str = ""

    def dedup_key(self, provider_id: str) -> str:
        """返回去重键：``{provider_id}:{unique_seed}``。"""
        return f"{provider_id}:{self.unique_seed}"

    def identity(self) -> str:
        """媒体身份键（用条目自带的强标识；无强标识时回退名称）。

        与 :func:`media_identity` 一致，供历史记录去重合并。剧集是否按季由 ``type_hint`` 判定。
        """
        is_tv = bool(self.type_hint) and self.type_hint.value == "电视剧"
        return media_identity(
            tmdb_id=self.tmdb_id, douban_id=self.douban_id, bangumi_id=self.bangumi_id,
            is_tv=is_tv, season=self.season, title=self.title, year=self.year)

    def to_dict(self) -> Dict[str, Any]:
        """序列化为 JSON 安全 dict（供持久化到插件 KV，如奈飞两级缓存的 L2）。

        ``type_hint`` 为 ``MediaType`` 枚举 → 取 ``.value``（中文串）以 JSON 安全；
        ``source_meta`` 已是原始 dict、原样带出；其余字段均为原始标量。
        """
        return {
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
        }

    @classmethod
    def from_dict(cls, d: dict) -> "RankMediaItem":
        """从持久化 dict 还原；缺字段走 dataclass 安全默认。

        ``MediaType`` 运行时局部 import（本模块 TYPE_CHECKING 保护导入以便离线测试）；
        ``type_hint`` 由 ``.value`` 串还原为枚举（空则 None）。
        """
        from app.schemas.types import MediaType

        d = d or {}
        type_value = d.get("type_hint")
        return cls(
            title=d.get("title", ""),
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
        )


@dataclass
class FilterVerdict:
    """过滤器裁决结果。"""

    accepted: bool
    filter_id: Optional[str] = None
    reason: Optional[str] = None

    @classmethod
    def accept(cls) -> "FilterVerdict":
        """构造一个通过裁决。"""
        return cls(True)

    @classmethod
    def reject(cls, filter_id: str, reason: str) -> "FilterVerdict":
        """构造一个拒绝裁决，携带来源过滤器与原因。"""
        return cls(False, filter_id=filter_id, reason=reason)


@dataclass
class SubscribeOutcome:
    """统一落地管线（executor）对单条条目的处理结果。"""

    status: SubscribeStatus
    item: RankMediaItem
    mediainfo: Optional["MediaInfo"] = None
    reason: Optional[str] = None
    subscribe_id: Optional[int] = None
    message: Optional[str] = None


@dataclass
class HistoryRecord:
    """写入插件 KV 的一条历史记录。"""

    unique: str
    provider: str
    title: str
    year: Optional[str] = None
    type: Optional[str] = None      # 中文 MediaType.value 或 ''
    tmdbid: Optional[int] = None
    doubanid: Optional[str] = None
    bangumiid: Optional[int] = None
    poster: Optional[str] = None
    season: Optional[int] = None
    status: str = ""                # SubscribeStatus.value
    reason: Optional[str] = None
    time: str = ""                  # "%Y-%m-%d %H:%M:%S"

    def to_dict(self) -> Dict[str, Any]:
        """序列化为可持久化 dict。"""
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

    @classmethod
    def from_dict(cls, data: dict) -> "HistoryRecord":
        """从持久化 dict 反序列化，缺字段走安全默认。"""
        data = data or {}
        return cls(
            unique=data.get("unique", ""),
            provider=data.get("provider", ""),
            title=data.get("title", ""),
            year=data.get("year"),
            type=data.get("type"),
            tmdbid=data.get("tmdbid"),
            doubanid=data.get("doubanid"),
            bangumiid=data.get("bangumiid"),
            poster=data.get("poster"),
            season=data.get("season"),
            status=data.get("status", ""),
            reason=data.get("reason"),
            time=data.get("time", ""),
        )
