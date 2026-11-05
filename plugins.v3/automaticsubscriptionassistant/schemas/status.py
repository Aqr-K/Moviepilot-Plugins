"""落地状态契约。"""

from enum import Enum


class SubscribeStatus(str, Enum):
    """单条媒体经过统一落地管线后的最终状态。"""

    SUBSCRIBED = "subscribed"  # 已订阅
    MEDIA_EXISTS = "media_exists"  # 媒体库已存在
    SUBSCRIPTION_EXISTS = "subscription_exists"  # 订阅已存在
    BLACKLISTED = "blacklisted"  # 用户主动忽略
    FILTERED = "filtered"  # 被过滤（附 reason）
    UNRECOGNIZED = "unrecognized"  # 未识别
    ALREADY_HANDLED = "already_handled"  # 已处理（去重键命中）
    ERROR = "error"  # 异常
