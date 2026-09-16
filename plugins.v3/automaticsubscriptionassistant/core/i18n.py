"""后端 i18n：把 ``get_spec`` 产出的 zh-CN spec 按宿主语言本地化。

策略（DRY 且稳健）：
- **来源名 / 字段 label / 选项 title** 按「中文源串」翻译（单一字面量，重复串共用同一译文）；
- **多行 hint** 按 ``(provider_id, field_key)`` 翻译（避免拼接源串的脆弱匹配）；
- 缺失翻译一律回退 zh-CN 原文。

``/providers`` 与 ``/status`` 端点据前端传入的 ``lang`` 调用本模块本地化后再返回。
zh-CN 为源语言，直接返回原 spec。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

SUPPORTED = ("zh-CN", "zh-TW", "en-US")


def normalize_lang(lang: Any) -> str:
    """把宿主任意 locale 归一化为受支持的三种之一，缺省 zh-CN。"""
    if not lang:
        return "zh-CN"
    low = str(lang).strip().lower()
    if low.startswith("zh"):
        return "zh-TW" if any(t in low for t in ("tw", "hant", "hk", "mo")) else "zh-CN"
    if low.startswith("en"):
        return "en-US"
    return "zh-CN"


# 来源显示名按 provider_id 稳定键翻译（与后端硬编码的 provider_name 中文串解耦）：
# 改名 provider_name 不会破坏翻译，新增来源只需在此登记其 provider_id。zh-CN 兼作源/回退。
_PROVIDER_NAMES: Dict[str, Dict[str, str]] = {
    "douban": {"zh-CN": "豆瓣榜单", "zh-TW": "豆瓣榜單", "en-US": "Douban Rankings"},
    "maoyan": {"zh-CN": "猫眼榜单", "zh-TW": "貓眼榜單", "en-US": "Maoyan Rankings"},
    "popular": {"zh-CN": "热门媒体", "zh-TW": "熱門媒體", "en-US": "Popular Media"},
    "mikan": {"zh-CN": "Mikan 季度新番", "zh-TW": "Mikan 季度新番", "en-US": "Mikan Seasonal Anime"},
    "netflix": {"zh-CN": "奈飞榜单", "zh-TW": "奈飛榜單", "en-US": "Netflix Top 10"},
}

# 奈飞国家/地区名按 iso2 键翻译（(zh-CN, zh-TW)）；en-US 用选项自带英文名回退。
# 国名源串本身是英文（COUNTRIES=iso2->英文），故 zh-CN 也需经此本地化。
_COUNTRY_NAMES: Dict[str, tuple] = {
    "AE": ("阿联酋", "阿聯酋"), "AR": ("阿根廷", "阿根廷"), "AT": ("奥地利", "奧地利"),
    "AU": ("澳大利亚", "澳洲"), "BD": ("孟加拉国", "孟加拉"), "BE": ("比利时", "比利時"),
    "BG": ("保加利亚", "保加利亞"), "BH": ("巴林", "巴林"), "BO": ("玻利维亚", "玻利維亞"),
    "BR": ("巴西", "巴西"), "BS": ("巴哈马", "巴哈馬"), "CA": ("加拿大", "加拿大"),
    "CH": ("瑞士", "瑞士"), "CL": ("智利", "智利"), "CO": ("哥伦比亚", "哥倫比亞"),
    "CR": ("哥斯达黎加", "哥斯大黎加"), "CY": ("塞浦路斯", "賽普勒斯"), "CZ": ("捷克", "捷克"),
    "DE": ("德国", "德國"), "DK": ("丹麦", "丹麥"), "DO": ("多米尼加", "多明尼加"),
    "EC": ("厄瓜多尔", "厄瓜多"), "EE": ("爱沙尼亚", "愛沙尼亞"), "EG": ("埃及", "埃及"),
    "ES": ("西班牙", "西班牙"), "FI": ("芬兰", "芬蘭"), "FR": ("法国", "法國"),
    "GB": ("英国", "英國"), "GP": ("瓜德罗普", "瓜地洛普"), "GR": ("希腊", "希臘"),
    "GT": ("危地马拉", "瓜地馬拉"), "HK": ("香港", "香港"), "HN": ("洪都拉斯", "宏都拉斯"),
    "HR": ("克罗地亚", "克羅埃西亞"), "HU": ("匈牙利", "匈牙利"), "ID": ("印度尼西亚", "印尼"),
    "IE": ("爱尔兰", "愛爾蘭"), "IL": ("以色列", "以色列"), "IN": ("印度", "印度"),
    "IS": ("冰岛", "冰島"), "IT": ("意大利", "義大利"), "JM": ("牙买加", "牙買加"),
    "JO": ("约旦", "約旦"), "JP": ("日本", "日本"), "KE": ("肯尼亚", "肯亞"),
    "KR": ("韩国", "韓國"), "KW": ("科威特", "科威特"), "LB": ("黎巴嫩", "黎巴嫩"),
    "LK": ("斯里兰卡", "斯里蘭卡"), "LT": ("立陶宛", "立陶宛"), "LU": ("卢森堡", "盧森堡"),
    "LV": ("拉脱维亚", "拉脫維亞"), "MA": ("摩洛哥", "摩洛哥"), "MQ": ("马提尼克", "馬丁尼克"),
    "MT": ("马耳他", "馬爾他"), "MU": ("毛里求斯", "模里西斯"), "MV": ("马尔代夫", "馬爾地夫"),
    "MX": ("墨西哥", "墨西哥"), "MY": ("马来西亚", "馬來西亞"), "NC": ("新喀里多尼亚", "新喀里多尼亞"),
    "NG": ("尼日利亚", "奈及利亞"), "NI": ("尼加拉瓜", "尼加拉瓜"), "NL": ("荷兰", "荷蘭"),
    "NO": ("挪威", "挪威"), "NZ": ("新西兰", "紐西蘭"), "OM": ("阿曼", "阿曼"),
    "PA": ("巴拿马", "巴拿馬"), "PE": ("秘鲁", "秘魯"), "PH": ("菲律宾", "菲律賓"),
    "PK": ("巴基斯坦", "巴基斯坦"), "PL": ("波兰", "波蘭"), "PT": ("葡萄牙", "葡萄牙"),
    "PY": ("巴拉圭", "巴拉圭"), "QA": ("卡塔尔", "卡達"), "RE": ("留尼汪", "留尼旺"),
    "RO": ("罗马尼亚", "羅馬尼亞"), "RS": ("塞尔维亚", "塞爾維亞"), "RU": ("俄罗斯", "俄羅斯"),
    "SA": ("沙特阿拉伯", "沙烏地阿拉伯"), "SE": ("瑞典", "瑞典"), "SG": ("新加坡", "新加坡"),
    "SI": ("斯洛文尼亚", "斯洛維尼亞"), "SK": ("斯洛伐克", "斯洛伐克"), "SV": ("萨尔瓦多", "薩爾瓦多"),
    "TH": ("泰国", "泰國"), "TR": ("土耳其", "土耳其"), "TT": ("特立尼达和多巴哥", "千里達及托巴哥"),
    "TW": ("台湾", "台灣"), "UA": ("乌克兰", "烏克蘭"), "US": ("美国", "美國"),
    "UY": ("乌拉圭", "烏拉圭"), "VE": ("委内瑞拉", "委內瑞拉"), "VN": ("越南", "越南"),
    "ZA": ("南非", "南非"),
}


def _country_title(value: Any, lang: str) -> Optional[str]:
    """按 iso2 返回本地化国家名；非国家 value 或 en-US（无中文表）返回 None 交由回退。"""
    pair = _COUNTRY_NAMES.get(value)
    if not pair:
        return None
    return {"zh-CN": pair[0], "zh-TW": pair[1]}.get(lang)


# 中文源串 -> {lang: 译文}（字段 label + 选项 title；重复串共用）。
_TEXT: Dict[str, Dict[str, str]] = {
    # ---- 字段 label ----
    "热门榜单": {"zh-TW": "熱門榜單", "en-US": "Rank lists"},
    "RSSHub 地址": {"zh-TW": "RSSHub 位址", "en-US": "RSSHub base URL"},
    "自定义RSS地址": {"zh-TW": "自訂 RSS 位址", "en-US": "Custom RSS URLs"},
    "使用代理服务器": {"zh-TW": "使用代理伺服器", "en-US": "Use proxy"},
    "评分≥": {"zh-TW": "評分≥", "en-US": "Rating ≥"},
    "年份≥": {"zh-TW": "年份≥", "en-US": "Year ≥"},
    "媒体类型": {"zh-TW": "媒體類型", "en-US": "Media type"},
    "订阅类型": {"zh-TW": "訂閱類型", "en-US": "Subscription type"},
    "播出平台": {"zh-TW": "播出平台", "en-US": "Platform"},
    "每榜条数": {"zh-TW": "每榜條數", "en-US": "Items per list"},
    "订阅类别": {"zh-TW": "訂閱類別", "en-US": "Category"},
    "获取条数": {"zh-TW": "取得條數", "en-US": "Fetch count"},
    "订阅人次≥": {"zh-TW": "訂閱人次≥", "en-US": "Subscribers ≥"},
    "年份(0=当前年)": {"zh-TW": "年份(0=當前年)", "en-US": "Year (0 = current)"},
    "季度": {"zh-TW": "季度", "en-US": "Season"},
    "抓详情补 Bangumi ID/放送年(更准但更慢)": {
        "zh-TW": "抓詳情補 Bangumi ID/放送年(更準但更慢)",
        "en-US": "Fetch Bangumi ID & air year (more accurate, slower)",
    },
    "全球榜": {"zh-TW": "全球榜", "en-US": "Global list"},
    "全球数据源": {"zh-TW": "全球資料源", "en-US": "Global dataset"},
    "全球媒体类型": {"zh-TW": "全球媒體類型", "en-US": "Global media types"},
    "国家/地区 × 媒体类型": {"zh-TW": "國家/地區 × 媒體類型", "en-US": "Region × media type"},
    "每榜取前N": {"zh-TW": "每榜取前 N", "en-US": "Top N per list"},
    "使用代理访问": {"zh-TW": "使用代理存取", "en-US": "Use proxy"},
    "富元数据模式(带年份/干净剧名，更准)": {
        "zh-TW": "富元資料模式(帶年份/乾淨劇名，更準)",
        "en-US": "Rich metadata (year/clean title, more accurate)",
    },
    "并发数": {"zh-TW": "並發數", "en-US": "Concurrency"},
    "周更缓存(避免重复抓取触发风控)": {
        "zh-TW": "週更快取(避免重複抓取觸發風控)",
        "en-US": "Weekly cache (avoid rate-limiting)",
    },
    # ---- 选项 title ----
    "全部": {"zh-TW": "全部", "en-US": "All"},
    "电影": {"zh-TW": "電影", "en-US": "Movies"},
    "电视剧": {"zh-TW": "電視劇", "en-US": "TV Series"},
    "剧集": {"zh-TW": "劇集", "en-US": "TV Series"},
    "动漫": {"zh-TW": "動漫", "en-US": "Anime"},
    "电影票房榜": {"zh-TW": "電影票房榜", "en-US": "Box Office"},
    "网播热度 平台 × 类型": {"zh-TW": "網播熱度 平台 × 類型", "en-US": "Streaming heat: platform × type"},
    "电视剧+网络剧": {"zh-TW": "電視劇+網路劇", "en-US": "TV + Web series"},
    "网络剧": {"zh-TW": "網路劇", "en-US": "Web series"},
    "综艺": {"zh-TW": "綜藝", "en-US": "Variety"},
    "腾讯视频": {"zh-TW": "騰訊視頻", "en-US": "Tencent Video"},
    "芒果TV": {"zh-TW": "芒果TV", "en-US": "Mango TV"},
    "网络电影因数据源已停更（优酷停于 2022、爱奇艺停于 2026-01），暂不支持，已移除。": {
        "zh-TW": "網路電影因資料源已停更（優酷停於 2022、愛奇藝停於 2026-01），暫不支援，已移除。",
        "en-US": "Web films are no longer supported (data source stopped: Youku since 2022, iQIYI since Jan 2026); removed.",
    },
    "电影北美票房榜": {"zh-TW": "電影北美票房榜", "en-US": "Box Office (N. America)"},
    "一周口碑电影榜": {"zh-TW": "一週口碑電影榜", "en-US": "Weekly Acclaimed Films"},
    "实时热门电影": {"zh-TW": "即時熱門電影", "en-US": "Trending Films"},
    "热门综艺": {"zh-TW": "熱門綜藝", "en-US": "Popular Variety"},
    "热门电影": {"zh-TW": "熱門電影", "en-US": "Popular Films"},
    "热门电视剧": {"zh-TW": "熱門電視劇", "en-US": "Popular TV"},
    "电影TOP250": {"zh-TW": "電影 TOP250", "en-US": "Top 250 Films"},
    "电影票房": {"zh-TW": "電影票房", "en-US": "Box Office"},
    "电视剧热度": {"zh-TW": "電視劇熱度", "en-US": "TV Heat"},
    "网剧热度": {"zh-TW": "網劇熱度", "en-US": "Web Series Heat"},
    "综艺热度": {"zh-TW": "綜藝熱度", "en-US": "Variety Heat"},
    "网络电影": {"zh-TW": "網路電影", "en-US": "Web Films"},
    "全网": {"zh-TW": "全網", "en-US": "All platforms"},
    "腾讯": {"zh-TW": "騰訊", "en-US": "Tencent"},
    "爱奇艺": {"zh-TW": "愛奇藝", "en-US": "iQIYI"},
    "芒果": {"zh-TW": "芒果", "en-US": "Mango TV"},
    "优酷": {"zh-TW": "優酷", "en-US": "Youku"},
    "搜狐": {"zh-TW": "搜狐", "en-US": "Sohu"},
    "乐视": {"zh-TW": "樂視", "en-US": "LeTV"},
    "当前季度（自动）": {"zh-TW": "當前季度（自動）", "en-US": "Current season (auto)"},
    "春季": {"zh-TW": "春季", "en-US": "Spring"},
    "夏季": {"zh-TW": "夏季", "en-US": "Summer"},
    "秋季": {"zh-TW": "秋季", "en-US": "Autumn"},
    "冬季": {"zh-TW": "冬季", "en-US": "Winter"},
    "最新周榜": {"zh-TW": "最新週榜", "en-US": "Latest weekly"},
    "史上最热(不分周)": {"zh-TW": "史上最熱(不分週)", "en-US": "All-time popular"},
    "英语电影": {"zh-TW": "英語電影", "en-US": "Films (English)"},
    "非英语电影": {"zh-TW": "非英語電影", "en-US": "Films (Non-English)"},
    "英语剧集": {"zh-TW": "英語劇集", "en-US": "TV (English)"},
    "非英语剧集": {"zh-TW": "非英語劇集", "en-US": "TV (Non-English)"},
    # ---- 热门媒体 popular：字段 label（电影/剧集 各一组，按拼接后的整串登记）----
    "电影订阅": {"zh-TW": "電影訂閱", "en-US": "Movie subscription"},
    "剧集订阅": {"zh-TW": "劇集訂閱", "en-US": "TV subscription"},
    "电影风格": {"zh-TW": "電影風格", "en-US": "Movie genres"},
    "剧集风格": {"zh-TW": "劇集風格", "en-US": "TV genres"},
    "电影获取条数": {"zh-TW": "電影取得條數", "en-US": "Movie fetch count"},
    "剧集获取条数": {"zh-TW": "劇集取得條數", "en-US": "TV fetch count"},
    "电影评分下限(≥)": {"zh-TW": "電影評分下限(≥)", "en-US": "Movie rating ≥"},
    "剧集评分下限(≥)": {"zh-TW": "劇集評分下限(≥)", "en-US": "TV rating ≥"},
    "电影订阅人次(≥)": {"zh-TW": "電影訂閱人次(≥)", "en-US": "Movie subscribers ≥"},
    "剧集订阅人次(≥)": {"zh-TW": "劇集訂閱人次(≥)", "en-US": "TV subscribers ≥"},
    # ---- 热门媒体 popular：风格选项 title（TMDB genre，电影+剧集去重）----
    "动作": {"zh-TW": "動作", "en-US": "Action"},
    "冒险": {"zh-TW": "冒險", "en-US": "Adventure"},
    "动画": {"zh-TW": "動畫", "en-US": "Animation"},
    "喜剧": {"zh-TW": "喜劇", "en-US": "Comedy"},
    "犯罪": {"zh-TW": "犯罪", "en-US": "Crime"},
    "纪录片": {"zh-TW": "紀錄片", "en-US": "Documentary"},
    "剧情": {"zh-TW": "劇情", "en-US": "Drama"},
    "家庭": {"zh-TW": "家庭", "en-US": "Family"},
    "奇幻": {"zh-TW": "奇幻", "en-US": "Fantasy"},
    "历史": {"zh-TW": "歷史", "en-US": "History"},
    "恐怖": {"zh-TW": "恐怖", "en-US": "Horror"},
    "音乐": {"zh-TW": "音樂", "en-US": "Music"},
    "悬疑": {"zh-TW": "懸疑", "en-US": "Mystery"},
    "爱情": {"zh-TW": "愛情", "en-US": "Romance"},
    "科幻": {"zh-TW": "科幻", "en-US": "Science Fiction"},
    "电视电影": {"zh-TW": "電視電影", "en-US": "TV Movie"},
    "惊悚": {"zh-TW": "驚悚", "en-US": "Thriller"},
    "战争": {"zh-TW": "戰爭", "en-US": "War"},
    "西部": {"zh-TW": "西部", "en-US": "Western"},
    "动作冒险": {"zh-TW": "動作冒險", "en-US": "Action & Adventure"},
    "儿童": {"zh-TW": "兒童", "en-US": "Kids"},
    "新闻": {"zh-TW": "新聞", "en-US": "News"},
    "真人秀": {"zh-TW": "真人秀", "en-US": "Reality"},
    "科幻奇幻": {"zh-TW": "科幻奇幻", "en-US": "Sci-Fi & Fantasy"},
    "肥皂剧": {"zh-TW": "肥皂劇", "en-US": "Soap"},
    "戏剧": {"zh-TW": "戲劇", "en-US": "Talk"},
    "战争政治": {"zh-TW": "戰爭政治", "en-US": "War & Politics"},
    # ---- 热门媒体 popular：公告 notice（按整串登记）----
    "热门媒体依赖 MoviePilot 全局『订阅数据共享』：未开启时服务端订阅统计接口直接返回空、本来源无法获取任何数据。请在下方『订阅数据共享』开关处开启（等同主程序设置，即时生效、无需重启）。": {
        "zh-TW": "熱門媒體依賴 MoviePilot 全域『訂閱資料共享』：未開啟時服務端訂閱統計介面直接返回空、本來源無法取得任何資料。請在下方『訂閱資料共享』開關處開啟（等同主程式設定，即時生效、無需重啟）。",
        "en-US": "Popular Media relies on MoviePilot's global 'Subscription data sharing'. When it is off, the server's subscription-statistics API returns empty and this source cannot fetch any data. Enable it via the 'Subscription data sharing' switch below (same as the main app setting; effective immediately, no restart).",
    },
}

# (provider_id, field_key) -> {lang: hint 译文}（多行 hint 按键翻译，回退 zh-CN 原文）。
_HINTS: Dict[Any, Dict[str, str]] = {
    ("douban", "rsshub_base"): {
        "zh-TW": "內建榜單的 RSSHub 基址；rsshub.app 被牆/SNI 封鎖時可改為自建實例（如 https://rsshub.你的網域）",
        "en-US": "RSSHub base URL for built-in lists; if rsshub.app is blocked, use your own instance (e.g. https://rsshub.yourdomain)",
    },
    ("douban", "rss_addrs"): {
        "zh-TW": "每行一個完整 RSS 位址（覆蓋上面的基址，可對接任意來源）",
        "en-US": "One full RSS URL per line (overrides the base above; any source)",
    },
    ("maoyan", "web_platform_map"): {
        "zh-TW": "依平台分別選擇要監聽的網播類型（可各不相同）；網路電影僅騰訊視頻/愛奇藝/優酷有資料",
        "en-US": "Choose streaming types per platform; web films only on Tencent / iQIYI / Youku",
    },
    ("netflix", "country_selections"): {
        "zh-TW": "依地區分別選擇要監聽的媒體類型（可各不相同）",
        "en-US": "Choose media types per region independently",
    },
    ("netflix", "rich_metadata"): {
        "zh-TW": "改抓 Tudum 榜單頁內嵌 GraphQL，帶年份/乾淨劇名/videoId，識別更準；全球非英語兩類無富頁會回退 TSV",
        "en-US": "Scrapes Tudum list-page GraphQL (year/clean title/videoId, more accurate); global non-English falls back to TSV",
    },
    ("netflix", "max_workers"): {
        "zh-TW": "富元資料模式下多地區/多類型榜單頁並發抓取的執行緒數",
        "en-US": "Thread count for concurrent list-page fetches in rich mode",
    },
    ("netflix", "use_cache"): {
        "zh-TW": "Netflix Top10 為固定 7 天週期，同一刷新週內重複抓取只會拿到相同內容、可能觸發風控。開啟後按資料 week 快取條目，下次刷新≈week+9天，跨執行生效、行程重啟後首次執行重抓",
        "en-US": "Netflix Top10 refreshes weekly; repeated fetches in the same week return identical data and may trigger rate-limiting. When on, caches entries by data week (next refresh ≈ week+9d), survives restarts",
    },
    ("popular", "movie_genres"): {
        "zh-TW": "留空=全部；僅開啟電影訂閱時生效",
        "en-US": "Empty = all; effective only when Movie subscription is on",
    },
    ("popular", "tv_genres"): {
        "zh-TW": "留空=全部；僅開啟劇集訂閱時生效",
        "en-US": "Empty = all; effective only when TV subscription is on",
    },
    ("popular", "movie_min_rating"): {
        "zh-TW": "0=不限；下推服務端按評分過濾",
        "en-US": "0 = no limit; pushed to the server to filter by rating",
    },
    ("popular", "tv_min_rating"): {
        "zh-TW": "0=不限；下推服務端按評分過濾",
        "en-US": "0 = no limit; pushed to the server to filter by rating",
    },
    ("popular", "movie_popularity"): {
        "zh-TW": "0=不限；按統計訂閱人次過濾",
        "en-US": "0 = no limit; filtered locally by subscriber count",
    },
    ("popular", "tv_popularity"): {
        "zh-TW": "0=不限；按統計訂閱人次過濾",
        "en-US": "0 = no limit; filtered locally by subscriber count",
    },
}


def localize_provider_name(provider_id: str, fallback: str, lang: Any) -> str:
    """按 provider_id 稳定键返回来源显示名（与硬编码 provider_name 解耦）。

    未登记的 provider_id 回退传入的 ``fallback``（即后端 provider_name）。
    """
    names = _PROVIDER_NAMES.get(provider_id or "")
    if not names:
        return fallback
    lang = normalize_lang(lang)
    return names.get(lang) or names.get("zh-CN") or fallback


def localize_spec(spec: Dict[str, Any], lang: Any) -> Dict[str, Any]:
    """本地化单个 ProviderSpec dict（provider_name + 各字段 label/hint + 选项/列 title）。

    不改动任何 value/default/key，仅替换展示文本；返回新 dict，不修改入参。
    """
    lang = normalize_lang(lang)
    # 不因 zh-CN 提前返回：国家/地区名源串是英文，zh-CN 也需经 _country_title 本地化。
    out = dict(spec)
    pid = out.get("provider_id")
    out["provider_name"] = localize_provider_name(pid, out.get("provider_name", ""), lang)
    if out.get("notice"):
        out["notice"] = _TEXT.get(out["notice"], {}).get(lang, out["notice"])

    for schema_key in ("options_schema", "filters_schema"):
        fields: List[Dict[str, Any]] = out.get(schema_key) or []
        localized_fields = []
        for field in fields:
            nf = dict(field)
            label = nf.get("label")
            if label:
                nf["label"] = _TEXT.get(label, {}).get(lang, label)
            hint_override = _HINTS.get((pid, nf.get("key")), {}).get(lang)
            if hint_override:
                nf["hint"] = hint_override
            for axis in ("options", "columns"):
                axis_items = nf.get(axis)
                if axis_items:
                    nf[axis] = [
                        {**it, "title": _country_title(it.get("value"), lang)
                         or _TEXT.get(it.get("title", ""), {}).get(lang, it.get("title", ""))}
                        for it in axis_items
                    ]
            localized_fields.append(nf)
        out[schema_key] = localized_fields
    return out
