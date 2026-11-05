"""插件业务数据契约；不依赖 ORM 或运行期存储。"""

from .history import HistoryRecord
from .identity import (
    _identity_group_suffix,
    _legacy_source_identity,
    _normalize_media_identity,
    _source_prefix,
    _source_value,
    media_identity,
)
from .media import RankMediaItem
from .outcome import FilterVerdict, SubscribeOutcome
from .provider import FieldSpec, ProviderSpec
from .status import SubscribeStatus

__all__ = [
    "FieldSpec",
    "FilterVerdict",
    "HistoryRecord",
    "ProviderSpec",
    "RankMediaItem",
    "SubscribeOutcome",
    "SubscribeStatus",
    "_identity_group_suffix",
    "_legacy_source_identity",
    "_normalize_media_identity",
    "_source_prefix",
    "_source_value",
    "media_identity",
]
