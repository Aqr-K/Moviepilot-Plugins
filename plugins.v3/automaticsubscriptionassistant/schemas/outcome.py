"""筛选与订阅落地结果契约。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .media import RankMediaItem
from .status import SubscribeStatus

if TYPE_CHECKING:
    from app.sdk.media import MediaInfo


@dataclass
class FilterVerdict:
    """过滤器裁决结果。"""

    accepted: bool
    filter_id: str | None = None
    reason: str | None = None

    @classmethod
    def accept(cls) -> FilterVerdict:
        """构造一个通过裁决。"""
        return cls(True)

    @classmethod
    def reject(cls, filter_id: str, reason: str) -> FilterVerdict:
        """构造一个拒绝裁决，携带来源过滤器与原因。"""
        return cls(False, filter_id=filter_id, reason=reason)


@dataclass
class SubscribeOutcome:
    """统一落地管线（executor）对单条条目的处理结果。"""

    status: SubscribeStatus
    item: RankMediaItem
    mediainfo: MediaInfo | None = None
    reason: str | None = None
    subscribe_id: int | None = None
    message: str | None = None
