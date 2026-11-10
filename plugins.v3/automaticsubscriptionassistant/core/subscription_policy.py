"""来源与榜单规则的自动订阅设置：白名单校验和逐媒体类型覆盖。"""

from copy import deepcopy

from app.schemas.subscribe import Subscribe

MEDIA_TYPES = ("电影", "电视剧", "音乐")
COMMON_FIELDS = {
    "include",
    "exclude",
    "sites",
    "downloader",
    "save_path",
    "filter_groups",
    "search_interval",
    "best_version",
}
VIDEO_FIELDS = {"quality", "resolution", "effect", "search_imdbid"}
MUSIC_FIELDS = {
    "audio_quality",
    "audio_format",
    "min_bitrate",
    "min_bit_depth",
    "min_sample_rate",
}


def normalize_subscription_policy(raw):
    """只保存可用于自动创建的参数；不允许身份、归属、总集数和交互开关。"""
    if raw is None:
        return {"enabled": False, "configs": {}}
    if not isinstance(raw, dict) or set(raw) - {"enabled", "configs"}:
        raise TypeError("订阅规则配置格式无效")
    enabled = raw.get("enabled", False)
    configs = raw.get("configs", {})
    if not isinstance(enabled, bool) or not isinstance(configs, dict):
        raise TypeError("订阅规则开关或媒体类型配置无效")
    if set(configs) - set(MEDIA_TYPES):
        raise ValueError("订阅规则含不支持的媒体类型")
    result = {}
    for media_type, options in configs.items():
        allowed = COMMON_FIELDS | (
            MUSIC_FIELDS if media_type == "音乐" else VIDEO_FIELDS
        )
        if media_type == "电视剧":
            allowed |= {"best_version_full"}
        if not isinstance(options, dict) or set(options) - allowed:
            raise ValueError(f"{media_type}订阅规则含不支持的字段")
        for key, value in options.items():
            if key in {"best_version", "best_version_full", "search_imdbid"}:
                if value is not None and (
                    not isinstance(value, (bool, int)) or value not in (0, 1)
                ):
                    raise ValueError(f"{key} 必须为开关值")
            elif key in {
                "search_interval",
                "min_bitrate",
                "min_bit_depth",
                "min_sample_rate",
            }:
                if value is not None and (
                    isinstance(value, bool) or not isinstance(value, int) or value < 1
                ):
                    raise ValueError(f"{key} 必须为正整数")
            elif key == "sites":
                if not isinstance(value, list) or any(
                    type(v) is not int or v <= 0 for v in value
                ):
                    raise ValueError("订阅站点必须为有效的站点 ID 列表")
            elif key == "filter_groups":
                if (
                    not isinstance(value, list)
                    or len(value) > 100
                    or any(
                        not isinstance(v, str) or not v.strip() or len(v) > 200
                        for v in value
                    )
                ):
                    raise ValueError("过滤规则组必须为名称列表")
            elif value is not None and (
                not isinstance(value, str) or len(value) > 4096
            ):
                raise ValueError(f"{key} 必须为文本")
        validated = Subscribe(type=media_type, **options)
        if options.get("best_version_full") and not options.get("best_version"):
            raise ValueError("全集洗版需要同时开启洗版订阅")
        result[media_type] = {key: deepcopy(getattr(validated, key)) for key in options}
    return {"enabled": enabled, "configs": result}


def subscription_options(item, mediainfo, filter_chain, source_policy):
    """选择首条同时通过两阶段筛选的规则级设置，按实际识别类型兜底。"""
    media_type = getattr(mediainfo.type, "value", mediainfo.type)
    for match in (item.source_meta or {}).get("matches", []):
        filters = match.get("filters") or {}
        if not filter_chain.run_rule("post", item, mediainfo, filters).accepted:
            continue
        policy = normalize_subscription_policy(match.get("subscription"))
        if policy["enabled"] and media_type in policy["configs"]:
            return deepcopy(policy["configs"][media_type])
    policy = normalize_subscription_policy(source_policy)
    if policy["enabled"]:
        return deepcopy(policy["configs"].get(media_type, {}))
    return {}
