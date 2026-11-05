"""各来源规则字段；UI、默认值与后端校验使用同一份契约。"""

from copy import deepcopy
from datetime import datetime, timezone

from ..schemas import FieldSpec


def choices(values):
    return [{"value": key, "title": title} for key, title in values.items()]


def pick(key, label, values, default, *, multiple=False, **kwargs):
    return FieldSpec(
        key,
        label,
        "multi-select" if multiple else "select",
        default,
        options=choices(values),
        required=kwargs.pop("required", True),
        **kwargs,
    )


def number(key, label, default, minimum=0, maximum=100, **kwargs):
    return FieldSpec(
        key, label, "number", default, minimum=minimum, maximum=maximum, **kwargs
    )


def rule(name, **values):
    return {"name": name, "on": True, **values}


def definition(pid):
    """返回 (规则字段, 默认规则, 预设, 来源共享字段键)。延迟导入避免注册循环。"""
    shared = {"proxy"}
    if pid == "anilist":
        from .anilist import FORMATS

        fields = [
            pick(
                "sort",
                "排行依据",
                {
                    "TRENDING_DESC": "趋势",
                    "POPULARITY_DESC": "人气",
                    "SCORE_DESC": "评分",
                    "FAVOURITES_DESC": "收藏数",
                },
                "TRENDING_DESC",
            ),
            pick(
                "time",
                "时间范围",
                {
                    "all": "不限",
                    "current": "本季",
                    "next": "下季",
                    "fixed": "指定年份与季度",
                },
                "all",
            ),
            number(
                "year",
                "年份",
                datetime.now(timezone.utc).year,
                1940,
                2200,
                visible_when={"time": ["fixed"]},
            ),
            pick(
                "season",
                "季度",
                {
                    "ALL": "全年",
                    "WINTER": "冬季",
                    "SPRING": "春季",
                    "SUMMER": "夏季",
                    "FALL": "秋季",
                },
                "ALL",
                visible_when={"time": ["fixed"]},
            ),
            pick("formats", "动画形式", FORMATS, list(FORMATS), multiple=True),
            number("limit", "获取条数", 20, 1, 500),
            pick(
                "statuses",
                "播出状态",
                {
                    "RELEASING": "连载中",
                    "FINISHED": "已完结",
                    "NOT_YET_RELEASED": "未开播",
                    "CANCELLED": "已取消",
                    "HIATUS": "暂停中",
                },
                [],
                multiple=True,
                advanced=True,
                required=False,
            ),
            FieldSpec(
                "genres",
                "题材",
                "multi-select",
                [],
                options=choices(
                    {
                        g: g
                        for g in [
                            "Action",
                            "Adventure",
                            "Comedy",
                            "Drama",
                            "Ecchi",
                            "Fantasy",
                            "Hentai",
                            "Horror",
                            "Mahou Shoujo",
                            "Mecha",
                            "Music",
                            "Mystery",
                            "Psychological",
                            "Romance",
                            "Sci-Fi",
                            "Slice of Life",
                            "Sports",
                            "Supernatural",
                            "Thriller",
                        ]
                    }
                ),
                advanced=True,
            ),
            FieldSpec(
                "tags",
                "标签",
                "text",
                "",
                hint="使用 AniList 标签原名，多个标签用英文逗号分隔",
                advanced=True,
            ),
            FieldSpec(
                "country",
                "出品国家",
                "select",
                "",
                options=choices(
                    {"": "不限", "JP": "日本", "CN": "中国", "KR": "韩国", "TW": "台湾"}
                ),
                advanced=True,
            ),
            FieldSpec(
                "minimum_score",
                "评分≥",
                "float",
                0,
                minimum=0,
                maximum=10,
                advanced=True,
            ),
        ]
        defaults = [
            rule("正在流行", sort="TRENDING_DESC"),
            rule("本季新番", sort="POPULARITY_DESC", time="current"),
        ]
        presets = defaults + [
            rule(
                "年度动画电影",
                sort="SCORE_DESC",
                time="fixed",
                season="ALL",
                formats=["MOVIE"],
            )
        ]
    elif pid == "mikan":
        fields = [
            pick(
                "time",
                "时间范围",
                {
                    "current": "本季",
                    "previous": "上季",
                    "next": "下季",
                    "fixed": "指定年份与季度",
                },
                "current",
            ),
            number(
                "year",
                "年份",
                datetime.now(timezone.utc).year,
                2000,
                2200,
                visible_when={"time": ["fixed"]},
            ),
            pick(
                "season",
                "季度",
                {s: s + "季" for s in ["冬", "春", "夏", "秋"]},
                "冬",
                visible_when={"time": ["fixed"]},
            ),
            number("min_year", "年份≥", 0, 0, 2200, advanced=True),
        ]
        defaults = [rule("本季新番")]
        presets = defaults + [
            rule("上季新番", time="previous"),
            rule("下季新番", time="next"),
        ]
        shared |= {"resolve_bangumi_id"}
    elif pid == "popular":
        from .popular import MOVIE_GENRES, TV_GENRES

        fields = [
            pick("category", "媒体类型", {"movie": "电影", "tv": "剧集"}, "movie"),
            FieldSpec(
                "genres",
                "风格",
                "multi-select",
                [],
                hint="多选时匹配任一风格，留空表示全部",
                options_by={
                    "key": "category",
                    "values": {
                        "movie": choices({str(k): v for k, v in MOVIE_GENRES.items()}),
                        "tv": choices({str(k): v for k, v in TV_GENRES.items()}),
                    },
                },
            ),
            number("limit", "获取条数", 30, 1, 500),
            FieldSpec("min_rating", "评分≥", "float", 0, minimum=0, maximum=10),
            number("popularity", "订阅人次≥", 0, 0, 100000000),
        ]
        defaults = [rule("热门电影", category="movie"), rule("热门剧集", category="tv")]
        presets = defaults + [
            rule("高分动画剧集", category="tv", genres=["16"], min_rating=8),
            rule("热门动作电影", category="movie", genres=["28"]),
        ]
    elif pid == "douban":
        from .douban import DOUBAN_RANK_LABELS

        fields = [
            pick(
                "chart",
                "榜单",
                {**DOUBAN_RANK_LABELS, "custom": "自定义 RSS"},
                "movie-hot-gaia",
            ),
            FieldSpec(
                "url",
                "RSS 地址",
                "text",
                "",
                required=True,
                visible_when={"chart": ["custom"]},
            ),
            FieldSpec("vote", "评分≥", "float", 0, minimum=0, maximum=10),
            number("min_year", "年份≥", 0, 0, 2200),
            pick(
                "media_type",
                "媒体类型",
                {"all": "全部", "movie": "电影", "tv": "电视剧"},
                "all",
            ),
        ]
        defaults = [
            rule("热门电影", chart="movie-hot-gaia"),
            rule("热门电视剧", chart="tv-hot"),
        ]
        presets = defaults + [rule("自定义 RSS", chart="custom")]
        shared |= {"rsshub_base"}
    elif pid == "applemusic":
        from .applemusic import CHARTS, COUNTRIES

        fields = [
            pick("country", "地区", COUNTRIES, "us"),
            pick("chart", "音乐榜单", CHARTS, "apple-songs"),
            number("limit", "每榜取前N", 20, 1, 100),
        ]
        defaults = [rule("美国热播歌曲", country="us", chart="apple-songs")]
        presets = defaults + [
            rule("日本热门歌曲", country="jp", chart="itunes-songs"),
            rule("美国热门专辑", country="us", chart="itunes-albums"),
        ]
    elif pid == "maoyan":
        from .maoyan import MEDIA_LABELS, PLATFORM_LABELS

        web_only = {"chart": ["web-heat"]}
        fields = [
            pick(
                "chart",
                "榜单",
                {"movie-box": "电影票房榜", "web-heat": "网播热度榜"},
                "movie-box",
            ),
            pick("platform", "平台", PLATFORM_LABELS, "all", visible_when=web_only),
            pick("media", "网播类型", MEDIA_LABELS, "tv", visible_when=web_only),
            number("limit", "每榜取前N", 10, 1, 100),
            number("min_year", "年份≥", 0, 0, 2200),
            pick(
                "media_type",
                "媒体类型",
                {"all": "全部", "movie": "电影", "tv": "电视剧"},
                "all",
                advanced=True,
            ),
        ]
        defaults = [
            rule("电影票房", chart="movie-box"),
            rule("全网电视剧", chart="web-heat", platform="all", media="tv"),
        ]
        presets = defaults + [
            rule("腾讯视频综艺", chart="web-heat", platform="tx", media="variety")
        ]
    elif pid == "netflix":
        from .netflix import COUNTRIES, COUNTRY_CATEGORIES, GLOBAL_CATEGORIES

        global_options = choices({v["value"]: v["title"] for v in GLOBAL_CATEGORIES})
        country_options = choices({v["value"]: v["title"] for v in COUNTRY_CATEGORIES})
        fields = [
            pick(
                "dataset",
                "榜单",
                {
                    "weekly": "全球最新周榜",
                    "most-popular": "全球史上最热",
                    "country": "地区周榜",
                },
                "weekly",
            ),
            pick(
                "country",
                "地区",
                COUNTRIES,
                "US",
                visible_when={"dataset": ["country"]},
            ),
            FieldSpec(
                "categories",
                "媒体类型",
                "multi-select",
                [v["value"] for v in GLOBAL_CATEGORIES],
                required=True,
                options_by={
                    "key": "dataset",
                    "values": {
                        "weekly": global_options,
                        "most-popular": global_options,
                        "country": country_options,
                    },
                },
            ),
            number("limit", "每榜取前N", 10, 1, 10),
        ]
        defaults = [rule("全球周榜")]
        presets = defaults + [
            rule("全球史上最热", dataset="most-popular"),
            rule("日本地区剧集", dataset="country", country="JP", categories=["TV"]),
        ]
        shared |= {"rich_metadata", "max_workers", "use_cache"}
    else:
        from .music_catalogs import NETEASE_CHARTS, QQ_CHARTS, QQ_GROUPS
        from .spotify import CHARTS

        catalog = (
            CHARTS
            if pid == "spotify"
            else NETEASE_CHARTS
            if pid == "netease"
            else QQ_CHARTS
        )
        options = choices(catalog)
        if pid == "qqmusic":
            for item in options:
                item["group"] = QQ_GROUPS.get(item["value"], "其他")
        if pid == "netease":
            for item in options:
                name = item["title"]
                item["group"] = (
                    "热门榜"
                    if item["value"] in {"19723756", "3779629", "2884035", "3778678"}
                    else "ACG 榜"
                    if any(s in name for s in ["ACG", "VOCALOID", "Oricon"])
                    else "地区与语言榜"
                    if any(
                        s in name
                        for s in [
                            "语",
                            "欧美",
                            "美国",
                            "日本",
                            "法国",
                            "俄罗斯",
                            "UK",
                            "Billboard",
                        ]
                    )
                    else "特色榜"
                )
        fields = [
            FieldSpec(
                "chart",
                "音乐榜单",
                "select",
                next(iter(catalog)),
                options=options,
                required=True,
            ),
            number("limit", "每榜取前N", 20, 1, 50 if pid == "spotify" else 100),
        ]
        ids = (
            ["REGIONAL_GLOBAL_WEEKLY"]
            if pid == "spotify"
            else ["3778678", "3779629"]
            if pid == "netease"
            else ["26", "27"]
        )
        defaults = [rule(catalog[key], chart=key) for key in ids]
        presets = (
            [rule(title, chart=key) for key, title in catalog.items()]
            if pid == "spotify"
            else []
        )
    return fields, deepcopy(defaults), deepcopy(presets), shared
