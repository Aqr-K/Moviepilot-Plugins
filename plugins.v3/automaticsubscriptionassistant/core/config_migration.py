"""一次性配置升级：旧榜单选项转换为独立规则，写入前保留完整原件。"""

from __future__ import annotations

import json
import os
import tempfile
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

from .rules import normalize_rules


def _list(value):
    if value is None:
        return []
    if isinstance(value, str):
        value = value.split(",")
    if not isinstance(value, list):
        raise TypeError("多选项必须为列表或逗号分隔文本")
    return list(dict.fromkeys(str(v).strip() for v in value if str(v).strip()))


def _bool(value):
    if isinstance(value, str):
        return value.strip().lower() in {"true", "on", "yes", "1"}
    return bool(value)


def _matrix(raw):
    if not isinstance(raw, dict):
        raise TypeError("地区/平台组合必须为对象")
    for key, value in raw.items():
        on = True
        if isinstance(value, dict):
            if set(value) - {"on", "cats"}:
                raise ValueError("组合含无法识别的字段")
            on, value = _bool(value.get("on", True)), value.get("cats", [])
        yield key, _list(value), on


def _convert(pid, options, filters):
    """缺省值依据旧版实际执行语义；显式空选择和禁用项均保留。"""
    entries = []
    common = {}
    allowed_filters = {
        "douban": {"vote", "year", "media_type"},
        "maoyan": {"year", "media_type"},
        "mikan": {"year"},
    }
    if set(filters) - allowed_filters.get(pid, set()):
        raise ValueError("含无法等价迁移的筛选字段")
    if "year" in filters:
        common["min_year"] = filters["year"]
    for key in ("vote", "media_type"):
        if key in filters:
            common[key] = filters[key]

    def add(name, **values):
        entries.append({"name": name, "on": True, **common, **values})

    if pid == "douban":
        from ..providers.douban import DOUBAN_RANK_LABELS

        keys = {"ranks", "rss_addrs"}
        for chart in _list(options.get("ranks")):
            add(DOUBAN_RANK_LABELS.get(chart, chart), chart=chart)
        urls = options.get("rss_addrs") or ""
        if not isinstance(urls, str):
            raise ValueError("自定义 RSS 地址必须为文本")
        for index, url in enumerate(
            dict.fromkeys(u.strip() for u in urls.splitlines() if u.strip()), 1
        ):
            add(f"自定义 RSS {index}", chart="custom", url=url)
    elif pid == "maoyan":
        from ..providers.maoyan import MEDIA_LABELS, PLATFORM_LABELS

        keys = {"movie_box", "web_platform_map", "num", "types", "platforms"}
        types = _list(options.get("types"))
        if set(types) - {"movie", "web-heat", "web-tv", "zongyi"}:
            raise ValueError("存在已停用或无法识别的猫眼类型")
        if _bool(options.get("movie_box", "movie" in types)):
            add("电影票房", chart="movie-box", limit=options.get("num", 10))
        if "web_platform_map" in options:
            matrix = options["web_platform_map"]
        else:
            old_types = {"web-heat": "tv", "web-tv": "web", "zongyi": "variety"}
            cats = [old_types[t] for t in types if t in old_types]
            matrix = {p: cats for p in (_list(options.get("platforms")) or ["all"])}
        for platform, cats, on in _matrix(matrix):
            if platform not in PLATFORM_LABELS:
                raise ValueError(f"无法识别猫眼平台：{platform}")
            for cat in cats:
                add(
                    f"{PLATFORM_LABELS[platform]} · {MEDIA_LABELS.get(cat, cat)}",
                    chart="web-heat",
                    platform=platform,
                    media=cat,
                    on=on,
                    limit=options.get("num", 10),
                )
    elif pid == "netflix":
        from ..providers.netflix import COUNTRIES, DATASET_POPULAR, DATASET_WEEKLY

        keys = {
            "global",
            "global_dataset",
            "global_media_types",
            "country_selections",
            "countries",
            "country_media_types",
            "limit",
        }
        dataset = options.get("global_dataset") or DATASET_WEEKLY
        if dataset not in {DATASET_WEEKLY, DATASET_POPULAR}:
            raise ValueError("无法识别奈飞全球数据源")
        categories = _list(options.get("global_media_types"))
        if categories:
            add(
                "全球史上最热" if dataset == DATASET_POPULAR else "全球周榜",
                dataset="most-popular" if dataset == DATASET_POPULAR else "weekly",
                categories=categories,
                on=_bool(options.get("global", True)),
                limit=options.get("limit", 10),
            )
        matrix = options.get("country_selections")
        if matrix is None:
            matrix = {
                p: _list(options.get("country_media_types"))
                for p in _list(options.get("countries"))
            }
        for country, cats, on in _matrix(matrix):
            if country not in COUNTRIES:
                raise ValueError(f"无法识别奈飞地区：{country}")
            if cats:
                add(
                    f"{COUNTRIES[country]} 周榜",
                    dataset="country",
                    country=country,
                    categories=cats,
                    on=on,
                    limit=options.get("limit", 10),
                )
    elif pid == "mikan":
        keys = {"year", "season"}
        # 年份与季度在旧版中分别自动跟随日历，不能迁成一次性的当前年月。
        year, season = options.get("year", 0), options.get("season", "当前")
        add("季度新番", time="fixed", year=year, season=season)
    elif pid == "popular":
        keys = {"categories", "page_cnt"}
        for category, label in [("movie", "热门电影"), ("tv", "热门剧集")]:
            keys |= {
                f"{category}_{key}"
                for key in ("enabled", "genres", "page_cnt", "min_rating", "popularity")
            }
            on = _bool(
                options.get(
                    f"{category}_enabled",
                    category in _list(options["categories"])
                    if "categories" in options
                    else True,
                )
            )
            genres = _list(options.get(f"{category}_genres"))
            # 旧版获取条数针对每个风格；拆成单风格规则以保留这一范围。
            for genre in genres or [None]:
                add(
                    label if genre is None else f"{label} · {genre}",
                    category=category,
                    genres=[] if genre is None else [genre],
                    on=on,
                    limit=options.get(
                        f"{category}_page_cnt", options.get("page_cnt", 30)
                    ),
                    min_rating=options.get(f"{category}_min_rating", 0),
                    popularity=options.get(f"{category}_popularity", 0),
                )
    elif pid in {"spotify", "netease", "qqmusic"}:
        from ..providers.music_catalogs import NETEASE_CHARTS, QQ_CHARTS
        from ..providers.spotify import CHARTS

        keys = {"charts", "limit"}
        catalog, defaults = {
            "spotify": (CHARTS, ["REGIONAL_GLOBAL_WEEKLY"]),
            "netease": (NETEASE_CHARTS, ["3778678", "3779629"]),
            "qqmusic": (QQ_CHARTS, ["26", "27"]),
        }[pid]
        for chart in _list(options.get("charts", defaults)):
            add(catalog.get(chart, chart), chart=chart, limit=options.get("limit", 20))
    elif pid == "anilist":
        from ..providers.anilist import FORMATS

        keys = {"charts", "formats", "limit"}
        charts = {
            "trending": ("趋势", "TRENDING_DESC", "all"),
            "popular": ("人气", "POPULARITY_DESC", "all"),
            "top": ("评分", "SCORE_DESC", "all"),
            "favourites": ("收藏", "FAVOURITES_DESC", "all"),
            "season": ("本季新番", "POPULARITY_DESC", "current"),
            "next-season": ("下季新番", "POPULARITY_DESC", "next"),
        }
        for chart in _list(options.get("charts")):
            if chart not in charts:
                raise ValueError(f"无法识别 AniList 榜单：{chart}")
            name, sort, time = charts[chart]
            add(
                name,
                sort=sort,
                time=time,
                formats=_list(options.get("formats", list(FORMATS))),
                limit=options.get("limit", 20),
            )
    elif pid == "applemusic":
        keys = {"country", "countries", "charts", "chart_selections", "limit"}
        matrix = options.get("chart_selections")
        if matrix is None:
            countries = _list(options.get("countries", [options.get("country", "us")]))
            matrix = {
                country: _list(options.get("charts", ["apple-songs"]))
                for country in countries
            }
        for country, cats, on in _matrix(matrix):
            for chart in cats:
                add(
                    f"{country} · {chart}",
                    country=country,
                    chart=chart,
                    on=on,
                    limit=options.get("limit", 20),
                )
    else:
        raise ValueError(f"来源 {pid} 尚无配置迁移器")
    return entries, keys


def migrate_config(raw, providers):
    """纯转换、全量校验后返回副本；已有 rules（含空列表）绝不覆盖。"""
    if not isinstance(raw, dict):
        raise TypeError("插件配置必须为对象")
    result, changed = deepcopy(raw), []
    configs = result.get("providers", {})
    if not isinstance(configs, dict):
        raise TypeError("来源配置必须为对象")
    for provider in providers:
        pid = provider.provider_id
        if pid not in configs:
            continue
        source = configs[pid]
        if not isinstance(source, dict) or not isinstance(
            source.get("options", {}), dict
        ):
            raise TypeError(f"{provider.provider_name}：来源配置格式无效")
        options = source.get("options", {})
        if "rules" in options:
            continue
        filters = source.get("filters", {})
        if not isinstance(filters, dict):
            raise TypeError(f"{provider.provider_name}：筛选配置格式无效")
        try:
            entries, keys = _convert(pid, options, filters)
            spec = provider.get_spec()
            shared = {f.key for f in spec.options_schema if f.key != "rules"}
            if set(options) - keys - shared:
                raise ValueError(
                    "含无法识别的旧选项："
                    + "、".join(sorted(set(options) - keys - shared))
                )
            rules, seen = [], {}
            for entry in entries:
                rule = normalize_rules(spec.options_schema[0], [entry])[0]
                if rule["id"] in seen:
                    seen[rule["id"]]["on"] |= rule["on"]
                else:
                    seen[rule["id"]] = rule
                    rules.append(rule)
            normalize_rules(spec.options_schema[0], rules)
            provider.validate_options({"rules": rules})
            source["options"] = {
                key: deepcopy(value) for key, value in options.items() if key in shared
            }
            source["options"]["rules"] = rules
            source["filters"] = {}
        except (ValueError, TypeError) as exc:
            raise ValueError(
                f"{provider.provider_name} 配置自动迁移失败：{exc}"
            ) from exc
        changed.append(pid)
    return result, changed


def backup_config(raw, directory: Path) -> Path:
    """内容寻址的原始 JSON，原子落盘并校验；失败时调用方不得覆盖用户配置。"""
    payload = json.dumps(raw, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    digest = sha256(payload.encode()).hexdigest()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"before-rules-{digest}.json"
    if not target.exists():
        fd, name = tempfile.mkstemp(prefix=".config-", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, target)
        finally:
            if os.path.exists(name):
                os.unlink(name)
    if target.read_text(encoding="utf-8") != payload:
        raise OSError("旧配置备份校验失败")
    return target
