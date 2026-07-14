"""奈飞(Netflix) Top10 榜单来源：抓取官方 Tudum Top10 TSV，产出标准化条目。

数据来源为 Netflix 官方 Tudum Top10 公开数据集（GET，无鉴权），三个制表符分隔 TSV：

* ``most-popular``（``.../top10/data/most-popular.tsv``）：全球·史上最热·不分周。
  列：``category  rank  show_title  season_title  hours_viewed_first_91_days
  runtime  views_first_91_days``。
* ``all-weeks-global``（``.../top10/data/all-weeks-global.tsv``）：全球·每周·近 5 年历史。
  列：``week  category  weekly_rank  show_title  season_title  weekly_hours_viewed
  runtime  weekly_views  cumulative_weeks_in_top_10``。
* ``all-weeks-countries``（``.../top10/data/all-weeks-countries.tsv``）：94 国·每周·近 5 年
  （无观看时长）。列：``country_name  country_iso2  week  category  weekly_rank
  show_title  season_title  cumulative_weeks_in_top_10``。**约 30MB**，每次运行整表
  下载后在内存过滤最新周（``max(week)``，ISO 日期字典序即时序）再按国家/类型筛选。

首行为表头，``season_title`` 对电影为 ``N/A``、对剧集为季名（如 ``Wednesday: Season 1``）。
全球 category 有 4 种（``Films (English)`` / ``Films (Non-English)`` / ``TV (English)`` /
``TV (Non-English)``）；国家 category 有 2 种（``Films`` / ``TV``）。category 以 ``Films``
开头映射 ``MediaType.MOVIE``，否则 ``MediaType.TV``；剧集从 ``season_title`` 正则
``Season\\s*(\\d+)`` 抽季号（抽不到 None）。

**Netflix 数据无外部 id、无年份**：``year=None``、无 tmdb/douban/bangumi id，executor 只能
退化为「标题 + 类型」名称识别（命中率中等，冷门/多译名条目可能识别失败，见 README 已知限制）。
``unique_seed = f"{type_value}_{show_title}"``（``type_value`` 为 ``movie``/``tv``），单次
fetch 内按 ``unique_seed`` 去重（同一片名在全球 + 多国重复只产一次）。

**富元数据模式（``rich_metadata`` 开）**：改抓 Netflix Tudum Top10 **榜单页**（HTML），页面
SSR 内嵌 ``netflix.reactContext.models.graphql = JSON.parse('<单引号 JS 串>')``，比 TSV 多带
**年份**（``top10Video.releaseYear``）、**干净剧名**（``top10Video.parentShow.title``，识别更准）、
Netflix 数字 id（``videoId``）等，可显著提升识别命中率。榜单页 URL：全球英语
``/tudum/top10/films``（英语电影）与 ``/tudum/top10/tv``（英语剧集）；国家
``/tudum/top10/{slug}/{films|tv}``（``slug`` = 国家英文名小写、空格转连字符，由 ``COUNTRIES``
的 name 生成）。**多国家/多类型抓取用 ``concurrent.futures.ThreadPoolExecutor`` 并发**
（``max_workers`` 可调），单页失败仅告警跳过、响应 ``context.event`` 退出信号。**全球非英语
两类（``Films (Non-English)`` / ``TV (Non-English)``）无稳定 SSR 富页**（实测候选均回退英语电影），
富模式下这 2 类**回退现有 TSV 逻辑**（title-only）并记日志说明。全球榜与国家榜仍互不冲突、
可同时启用，产出后按同一 ``unique_seed`` 去重。

**按周（week）两级缓存（``use_cache`` 开，默认开）**：Netflix Top10 为固定 7 天周期，数据带
``week``/``weekEndDate``（周日结束日，如 ``2025-11-16``），每周数据在**次周周二**发布。同一 7 天
刷新周期内重复抓取只会拿到相同内容，无谓请求可能触发 Netflix 风控。故按「与结果相关选项」的
hash 为键做两级缓存：**L1** 为**模块级**字典（进程内快、跨 run 存活，因为每次运行都会 new 一个
provider 实例，实例级缓存无效）；**L2** 为**持久化插件 KV**（经 ``ProviderContext.get_data/save_data``
落 DB，键 ``netflix_cache``，**抗进程重启**）。查缓存先 L1，未命中查 L2（命中则回填 L1）；抓取完整
时同时写 L1 + L2。失效时间 ≈ ``week + 9 天``（周日结束周 + 9 天≈次周二下次发布）；若拿到的仍是旧
``week``（发布边界）则取 ``now + 12h`` 短重查；无法解析 week（如 most-popular 不分周）则兜底 6 天 TTL。
命中缓存直接产出旧条目、跳过全部网络抓取；配置变则键变、自动重抓。中途收到 ``context.event`` 退出信号
（结果不完整）时**不写缓存**。**KV 读写失败仅告警、降级为仅 L1（内存），不影响抓取**（防污染）；
``context`` 无 ``get_data``/``save_data``（如测试手动构造）或为 None 时仅走 L1、进程重启后必重抓。
"""
from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterator, List, Optional

from app.core.config import settings
from app.log import logger
from app.schemas.types import MediaType
from app.utils.http import RequestUtils

from ..core.models import FieldSpec, ProviderSpec, RankMediaItem
from ..core.provider import ProviderContext, RankProvider
from ..core.registry import register

# 三个官方 Top10 TSV 地址（GET，无鉴权）。
MOST_POPULAR_URL = "https://www.netflix.com/tudum/top10/data/most-popular.tsv"
ALL_WEEKS_GLOBAL_URL = "https://www.netflix.com/tudum/top10/data/all-weeks-global.tsv"
ALL_WEEKS_COUNTRIES_URL = "https://www.netflix.com/tudum/top10/data/all-weeks-countries.tsv"

# 全球榜 category（4 种，value=数据集内精确 category 串，label 中文）。
GLOBAL_CATEGORIES = [
    {"title": "英语电影", "value": "Films (English)"},
    {"title": "非英语电影", "value": "Films (Non-English)"},
    {"title": "英语剧集", "value": "TV (English)"},
    {"title": "非英语剧集", "value": "TV (Non-English)"},
]

# 国家榜 category（2 种，数据集内仅 Films / TV）。
COUNTRY_CATEGORIES = [
    {"title": "电影", "value": "Films"},
    {"title": "剧集", "value": "TV"},
]

# 94 个上榜国家/地区：iso2 -> 英文国名（由 all-weeks-countries.tsv 实测提取）。
COUNTRIES = {
    "AE": "United Arab Emirates",
    "AR": "Argentina",
    "AT": "Austria",
    "AU": "Australia",
    "BD": "Bangladesh",
    "BE": "Belgium",
    "BG": "Bulgaria",
    "BH": "Bahrain",
    "BO": "Bolivia",
    "BR": "Brazil",
    "BS": "Bahamas",
    "CA": "Canada",
    "CH": "Switzerland",
    "CL": "Chile",
    "CO": "Colombia",
    "CR": "Costa Rica",
    "CY": "Cyprus",
    "CZ": "Czech Republic",
    "DE": "Germany",
    "DK": "Denmark",
    "DO": "Dominican Republic",
    "EC": "Ecuador",
    "EE": "Estonia",
    "EG": "Egypt",
    "ES": "Spain",
    "FI": "Finland",
    "FR": "France",
    "GB": "United Kingdom",
    "GP": "Guadeloupe",
    "GR": "Greece",
    "GT": "Guatemala",
    "HK": "Hong Kong",
    "HN": "Honduras",
    "HR": "Croatia",
    "HU": "Hungary",
    "ID": "Indonesia",
    "IE": "Ireland",
    "IL": "Israel",
    "IN": "India",
    "IS": "Iceland",
    "IT": "Italy",
    "JM": "Jamaica",
    "JO": "Jordan",
    "JP": "Japan",
    "KE": "Kenya",
    "KR": "South Korea",
    "KW": "Kuwait",
    "LB": "Lebanon",
    "LK": "Sri Lanka",
    "LT": "Lithuania",
    "LU": "Luxembourg",
    "LV": "Latvia",
    "MA": "Morocco",
    "MQ": "Martinique",
    "MT": "Malta",
    "MU": "Mauritius",
    "MV": "Maldives",
    "MX": "Mexico",
    "MY": "Malaysia",
    "NC": "New Caledonia",
    "NG": "Nigeria",
    "NI": "Nicaragua",
    "NL": "Netherlands",
    "NO": "Norway",
    "NZ": "New Zealand",
    "OM": "Oman",
    "PA": "Panama",
    "PE": "Peru",
    "PH": "Philippines",
    "PK": "Pakistan",
    "PL": "Poland",
    "PT": "Portugal",
    "PY": "Paraguay",
    "QA": "Qatar",
    "RE": "Réunion",
    "RO": "Romania",
    "RS": "Serbia",
    "RU": "Russia",
    "SA": "Saudi Arabia",
    "SE": "Sweden",
    "SG": "Singapore",
    "SI": "Slovenia",
    "SK": "Slovakia",
    "SV": "El Salvador",
    "TH": "Thailand",
    "TR": "Turkey",
    "TT": "Trinidad and Tobago",
    "TW": "Taiwan",
    "UA": "Ukraine",
    "US": "United States",
    "UY": "Uruguay",
    "VE": "Venezuela",
    "VN": "Vietnam",
    "ZA": "South Africa",
}

# 全球数据源标识。
DATASET_WEEKLY = "all-weeks-global"
DATASET_POPULAR = "most-popular"

# HTTP 超时（秒），国家表约 30MB 故给足。
_REQUEST_TIMEOUT = 120
# 每榜默认取前 N。
_DEFAULT_LIMIT = 10
# 排名解析失败时的兜底（排到末尾）。
_RANK_FALLBACK = 10 ** 6

# 从 season_title 抽季号（"Wednesday: Season 1" -> 1；Part/Limited Series 等抽不到 None）。
_SEASON_PATTERN = re.compile(r"Season\s*(\d+)", re.IGNORECASE)

# ==================== 富元数据模式（Tudum 榜单页内嵌 GraphQL）====================
# Tudum Top10 榜单页基址：全球 /films、/tv；国家 /{slug}/films、/{slug}/tv。
_TUDUM_TOP10_BASE = "https://www.netflix.com/tudum/top10"
# 富页需带浏览器 UA 才返回内嵌 SSR HTML。
_RICH_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
)
# 富页 HTTP 超时（秒），单页 HTML 体积中等（数百 KB）。
_RICH_TIMEOUT = 30
# 默认并发抓取线程数。
_DEFAULT_MAX_WORKERS = 5
# 页面内嵌 GraphQL 存储起始标记：`...reactContext.models.graphql = JSON.parse('<单引号JS串>')`。
_GRAPHQL_MARKER = "reactContext.models.graphql = JSON.parse('"
# 单引号 JS 字符串字面量转义解码：\\ \' \" \n \t \uXXXX \xXX 等（单次左→右扫描）。
_JS_UNESCAPE = re.compile(r"\\(u[0-9a-fA-F]{4}|x[0-9a-fA-F]{2}|.)", re.DOTALL)
_JS_SIMPLE_ESCAPES = {
    "n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v",
    "0": "\0", "\\": "\\", "'": "'", '"': '"', "/": "/", "`": "`",
    "\n": "", "\r": "",
}
# 全球英语 category -> 富页路径后缀（仅英语两类有稳定内嵌富页）。
_GLOBAL_ENGLISH_RICH = {
    "Films (English)": "films",
    "TV (English)": "tv",
}
# 全球非英语 category（无稳定富页；富模式下回退 TSV title-only）。
_GLOBAL_NON_ENGLISH = ("Films (Non-English)", "TV (Non-English)")
# 国家 category -> 富页路径后缀。
_COUNTRY_RICH = {
    "Films": "films",
    "TV": "tv",
}

# ==================== 按周（week）缓存（避免同一刷新周内重复抓取触发风控）====================
# 两级缓存：L1 模块级 dict（进程内快、跨 run 存活；run_provider 每次 new 一个实例，实例级无效），
# L2 持久化插件 KV（落 DB、跨进程重启存活，经 ProviderContext.get_data/save_data 读写）。
# L1: cache_key(选项 hash) -> {"items": [RankMediaItem...], "week": str|None, "valid_until": float, "fetched_ts": float}。
_NETFLIX_CACHE: dict = {}
_CACHE_LOCK = threading.Lock()
# L2 插件 KV 键：值为 {cache_key: {"items": [RankMediaItem.to_dict()...], "week", "valid_until", "fetched_ts"}}。
_CACHE_DATA_KEY = "netflix_cache"
# 周日结束周 + 9 天 = 次周二（下一周数据的发布日）。全部按 UTC 计算，与系统/settings.TZ 无关。
_PUBLISH_LAG_DAYS = 9
# Netflix 官方于【周二】发布上一周榜单，但不暴露确切时刻/时区（TSV 无 Last-Modified/ETag，
# cache-control: no-store）。据观测取周二 12:00 UTC 作发布锚点：失效点定在「次周二 12:00 UTC」，
# 而非周日 00:00 UTC，避免周二凌晨在发布前就过早重抓；实际发布更晚时由下方 12h 短重查兜底。
_PUBLISH_HOUR_UTC = 12
# 处于发布边界（拿到的还是旧 week，base 已过）时的短重查间隔。
_MIN_RECHECK_SECONDS = 12 * 3600
# 无法解析 week（如 most-popular 不分周）时的兜底 TTL。
_FALLBACK_TTL_SECONDS = 6 * 24 * 3600


@register
class NetflixRankProvider(RankProvider):
    """奈飞 Top10 榜单来源：把官方 TSV 榜单映射为标准化 ``RankMediaItem``。

    全球榜与国家榜相互独立、可同时启用：全球按 ``global_dataset`` 取 most-popular（史上最热·
    不分周）或 all-weeks-global（周榜·只取最新周），按所选 4 类 category 各取前 ``limit``；
    国家榜取 all-weeks-countries（只取最新周），对每个所选 iso2 × 每个所选 category（Films/TV）
    各取前 ``limit``。二者合并后按 ``unique_seed`` 去重。Netflix 无外部 id、无年份，识别退化为
    标题 + 类型名称识别（见 README 已知限制）。

    开启 ``rich_metadata`` 则改走富元数据模式：并发抓 Tudum 榜单页内嵌 GraphQL，带年份/干净剧名/
    videoId 显著提升识别；全球非英语两类无稳定富页，回退现有 TSV title-only（见 ``_fetch_rich``）。
    """

    provider_id = "netflix"
    provider_name = "奈飞榜单"

    def get_spec(self) -> ProviderSpec:
        """返回本来源的元描述（选项与过滤器 schema）。

        媒体类型已由全球/国家的 category 选择区分、Netflix 无年份数据，故 ``filters_schema``
        为空（不提供年份/类型过滤）。
        """
        return ProviderSpec(
            provider_id=self.provider_id,
            provider_name=self.provider_name,
            # 榜单每周更新一次，默认每周三上午抓一次。
            default_cron="0 11 * * 3",
            options_schema=[
                FieldSpec(key="global", label="全球榜", kind="switch", default=True),
                FieldSpec(
                    key="global_dataset",
                    label="全球数据源",
                    kind="select",
                    default=DATASET_WEEKLY,
                    options=[
                        {"title": "最新周榜", "value": DATASET_WEEKLY},
                        {"title": "史上最热(不分周)", "value": DATASET_POPULAR},
                    ],
                ),
                FieldSpec(
                    key="global_media_types",
                    label="全球媒体类型",
                    kind="multi-select",
                    default=[c["value"] for c in GLOBAL_CATEGORIES],
                    options=list(GLOBAL_CATEGORIES),
                ),
                FieldSpec(
                    key="country_selections",
                    label="国家/地区 × 媒体类型",
                    kind="region-media-map",
                    default={},
                    options=[
                        {"title": name, "value": iso2}
                        for iso2, name in COUNTRIES.items()
                    ],
                    columns=list(COUNTRY_CATEGORIES),
                    hint="按地区分别选择要监听的媒体类型（可各不相同）",
                ),
                FieldSpec(key="limit", label="每榜取前N", kind="number", default=_DEFAULT_LIMIT),
                FieldSpec(key="proxy", label="使用代理访问", kind="switch", default=False),
                FieldSpec(
                    key="rich_metadata",
                    label="富元数据模式(带年份/干净剧名，更准)",
                    kind="switch",
                    default=False,
                    hint="改抓 Tudum 榜单页内嵌 GraphQL，带年份/干净剧名/videoId，识别更准；"
                         "全球非英语两类无富页会回退 TSV",
                ),
                FieldSpec(
                    key="max_workers",
                    label="并发数",
                    kind="number",
                    default=_DEFAULT_MAX_WORKERS,
                    advanced=True,
                    hint="富元数据模式下多国家/多类型榜单页并发抓取的线程数",
                ),
                FieldSpec(
                    key="use_cache",
                    label="周更缓存(避免重复抓取触发风控)",
                    kind="switch",
                    default=True,
                    advanced=True,
                    hint="Netflix Top10 为固定 7 天周期，同一刷新周内重复抓取只会拿到相同内容、"
                         "无谓请求可能触发风控。开启后按数据 week 缓存条目，下次刷新≈week+9天"
                         "（次周二发布），跨运行生效、进程重启后首次运行重抓",
                ),
            ],
            filters_schema=[],
        )

    def has_listening(self, options: dict) -> bool:
        """全球榜开启且选了媒体类型，或存在任一启用的国家×媒体类型组合。"""
        options = options or {}
        global_has = bool(options.get("global", True)) and bool(self._as_list(options.get("global_media_types")))
        return global_has or bool(self._resolve_country_selections(options))

    def fetch(self, options: dict, context: ProviderContext) -> Iterator[RankMediaItem]:
        """抓取奈飞 Top10 榜单，逐条产出 ``RankMediaItem``（带按周缓存）。

        全球榜（``global`` 为真且 ``global_media_types`` 非空）与国家榜（``countries`` 非空且
        ``country_media_types`` 非空）分别独立产出、可同时启用。单条解析失败 try/except
        continue，响应 ``context.event`` 退出信号；整表抓取失败向上抛出（由 runner 捕获）。
        单次 fetch 内按 ``unique_seed`` 去重。

        ``rich_metadata`` 为真时改走富元数据模式（``_fetch_rich``：并发抓 Tudum 榜单页内嵌
        GraphQL，带年份/干净剧名/videoId；全球非英语两类无富页回退 TSV title-only）；为假时
        完全走现有 TSV 逻辑（``_collect``，保持不变）。

        **按周两级缓存（``use_cache`` 默认开）**：Netflix Top10 固定 7 天周期，同一刷新周内重复抓取只会
        拿到相同内容、可能触发风控。查缓存先 **L1**（模块级内存 dict）命中未过期→直接产出旧条目、跳过
        全部网络；L1 未命中查 **L2**（持久化插件 KV，抗重启）命中→**回填 L1** 后产出；都未命中才实际
        抓取并按 ``max(week) + 9 天``（边界短重查 12h、无 week 兜底 6 天 TTL）记失效时间**同时写 L1 + L2**
        （键由与结果相关的选项 hash 生成，配置变则自动重抓）。中途收到退出信号（结果不完整）时**不写缓存**。
        L2 KV 读写失败仅告警、降级为仅 L1；``context`` 无 KV / 为 None 时仅 L1、进程重启后首次运行必重抓。
        """
        options = options or {}
        use_cache = bool(options.get("use_cache", True))
        key = self._cache_key(options)
        now = self._now_ts()

        # 命中未过期缓存：跳过全部网络抓取，直接产出缓存条目。
        if use_cache:
            # L1：模块级内存缓存（进程内快）。
            with _CACHE_LOCK:
                entry = _NETFLIX_CACHE.get(key)
                hit = entry if (entry and now < entry["valid_until"]) else None
                cached_items = list(hit["items"]) if hit else None
                cached_week = hit["week"] if hit else None
                cached_vu = hit["valid_until"] if hit else None
            if cached_items is not None:
                logger.info(
                    f"{self.provider_name}：命中周更缓存 L1(内存)（week={cached_week}，"
                    f"下次刷新≈{self._format_ts(cached_vu)}），跳过网络抓取"
                )
                yield from cached_items
                return

            # L2：持久化插件 KV（抗重启）。命中则回填 L1 后产出。
            persisted = self._load_persistent(context, key, now)
            if persisted is not None:
                p_items, p_week, p_valid_until = persisted
                with _CACHE_LOCK:
                    _NETFLIX_CACHE[key] = {
                        "items": p_items,
                        "week": p_week,
                        "valid_until": p_valid_until,
                        "fetched_ts": now,
                    }
                logger.info(
                    f"{self.provider_name}：命中持久化缓存 L2(KV)（week={p_week}，"
                    f"下次刷新≈{self._format_ts(p_valid_until)}），回填内存并跳过网络抓取"
                )
                yield from p_items
                return

        # 未命中：执行实际抓取，收集为完整列表。
        items = self._collect(options, context)

        # 中途收到退出信号（结果不完整）-> 不写缓存；仅开启缓存且抓取完整时才写 L1 + L2。
        if use_cache and not self._should_stop(context):
            week = self._latest_week(items)
            valid_until = self._valid_until(week, now)
            with _CACHE_LOCK:
                _NETFLIX_CACHE[key] = {
                    "items": items,
                    "week": week,
                    "valid_until": valid_until,
                    "fetched_ts": now,
                }
            # L2 持久化（失败仅告警、不影响抓取产出）。
            self._save_persistent(context, key, items, week, valid_until, now)
            logger.info(
                f"{self.provider_name}：已缓存本次抓取（week={week}，"
                f"下次刷新≈{self._format_ts(valid_until)}）"
            )
        yield from items

    def _collect(
        self, options: dict, context: Optional[ProviderContext]
    ) -> List[RankMediaItem]:
        """实际抓取主体（原 fetch 逻辑），把逐条产出收集为完整列表供缓存。

        ``rich_metadata`` 为真走富模式；否则全球榜 + 国家榜（互不冲突、可同时启用），单次内
        ``seen`` 去重。响应 ``context.event`` 退出信号（子抓取会提前返回，此时列表不完整）。
        """
        proxy = bool(options.get("proxy", False))
        limit = self._to_int(options.get("limit"), _DEFAULT_LIMIT)
        seen: set = set()

        # 富元数据模式：并发抓榜单页内嵌 GraphQL（非英语全球回退 TSV），与下方 TSV 逻辑互斥。
        if bool(options.get("rich_metadata", False)):
            return list(self._fetch_rich(options, limit, proxy, seen, context))

        items: List[RankMediaItem] = []
        # 全球榜。
        if bool(options.get("global", True)):
            global_cats = self._as_list(options.get("global_media_types"))
            if global_cats:
                dataset = str(options.get("global_dataset") or DATASET_WEEKLY).strip()
                items.extend(
                    self._fetch_global(dataset, global_cats, limit, proxy, seen, context)
                )

        # 国家榜（与全球榜互不冲突，可同时启用）。逐区「地区 × 媒体类型」映射。
        selections = self._resolve_country_selections(options)
        if selections:
            items.extend(
                self._fetch_countries(selections, limit, proxy, seen, context)
            )
        return items

    # ==================== 按周缓存辅助 ====================

    @staticmethod
    def _now_ts() -> float:
        """当前 epoch 秒（抽成方法供测试 monkeypatch 控制“现在”）。"""
        return time.time()

    @classmethod
    def _resolve_country_selections(cls, options: dict) -> Dict[str, List[str]]:
        """归一化「地区 × 媒体类型」映射为 ``{iso2: [category, ...]}``。

        优先读新字段 ``country_selections``（前端 region-media-map 产出的 dict）；缺省或非法时
        **向后兼容**回退旧字段 ``countries`` × ``country_media_types``（笛卡尔积套用到所有国家）。
        仅保留有效 iso2 与有效类型（Films/TV），媒体类型为空的地区剔除。
        """
        valid_cats = {c["value"] for c in COUNTRY_CATEGORIES}
        result: Dict[str, List[str]] = {}
        raw = options.get("country_selections")
        if isinstance(raw, dict) and raw:
            for iso2, cats in raw.items():
                if iso2 not in COUNTRIES:
                    continue
                # 条目形态兼容：新 {"on": bool, "cats": [...]}（可禁用而不丢配置）与旧 [...]。
                if isinstance(cats, dict):
                    if not cats.get("on", True):
                        continue  # 禁用的组合跳过（配置保留但本轮不生效）
                    cats = cats.get("cats", [])
                cats_list = [c for c in cls._as_list(cats) if c in valid_cats]
                if cats_list:
                    result[iso2] = cats_list
            return result
        # 向后兼容：旧的 countries + country_media_types 统一套用。
        countries = [c for c in cls._as_list(options.get("countries")) if c in COUNTRIES]
        country_cats = [c for c in cls._as_list(options.get("country_media_types")) if c in valid_cats]
        if countries and country_cats:
            for iso2 in countries:
                result[iso2] = list(country_cats)
        return result

    @classmethod
    def _cache_key(cls, options: dict) -> str:
        """由「与结果相关的选项」生成稳定缓存键（``json.dumps(sort_keys=True)``）。

        仅纳入影响产出的选项（``rich_metadata``/``global``/``global_dataset``/多选类去重排序/
        ``limit``/``proxy``）；``max_workers``（仅并发度）与 ``use_cache``（控制开关）不入键。
        任一相关配置变化 → 键变 → 自动重抓。
        """
        options = options or {}
        payload = {
            "rich_metadata": bool(options.get("rich_metadata", False)),
            "global": bool(options.get("global", True)),
            "global_dataset": str(options.get("global_dataset") or DATASET_WEEKLY).strip(),
            "global_media_types": sorted(cls._as_list(options.get("global_media_types"))),
            "country_selections": {
                iso2: sorted(cats)
                for iso2, cats in cls._resolve_country_selections(options).items()
            },
            "limit": cls._to_int(options.get("limit"), _DEFAULT_LIMIT),
            "proxy": bool(options.get("proxy", False)),
        }
        return json.dumps(payload, sort_keys=True, ensure_ascii=False)

    @classmethod
    def _valid_until(cls, week_str: Optional[str], now: float) -> float:
        """由数据 ``week``（``YYYY-MM-DD`` 周日结束日）算缓存失效 epoch。

        全部按 **UTC** 计算（与系统/settings.TZ 无关，确定性）：``base`` = 数据 ``week``（周日）
        + 9 天 = 次周二，再锚到当天 ``_PUBLISH_HOUR_UTC``:00 UTC（估计发布时刻），返回
        ``max(base, now + 12h)``——若 base 已过（在发布前重抓到旧 week）则退化为 ``now`` 起 12h
        短重查，直到新周出现（故绝不会永久遗漏，最多晚 ~12h）。解析失败（如 most-popular 不分周、
        无 week）→ ``now + 6 天`` 兜底 TTL。
        """
        if week_str:
            try:
                day = datetime.strptime(str(week_str).strip(), "%Y-%m-%d")
                base_dt = (day.replace(tzinfo=timezone.utc)
                           + timedelta(days=_PUBLISH_LAG_DAYS)).replace(
                    hour=_PUBLISH_HOUR_UTC, minute=0, second=0, microsecond=0)
                return max(base_dt.timestamp(), now + _MIN_RECHECK_SECONDS)
            except (ValueError, TypeError):
                pass
        return now + _FALLBACK_TTL_SECONDS

    @staticmethod
    def _latest_week(items: List[RankMediaItem]) -> Optional[str]:
        """从产出条目 ``source_meta['week']`` 取 ``max``（忽略空）；无任何 week 返回 None。"""
        weeks = [w for w in (i.source_meta.get("week") for i in items) if w]
        return max(weeks) if weeks else None

    @staticmethod
    def _format_ts(ts: Optional[float]) -> str:
        """把 epoch 秒格式化为可读时间（仅用于日志），非法值原样返回。"""
        try:
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
        except (ValueError, TypeError, OSError, OverflowError):
            return str(ts)

    def _load_persistent(
        self, context: Optional[ProviderContext], key: str, now: float
    ) -> Optional[tuple]:
        """从持久化插件 KV（L2）读取未过期缓存并反序列化为条目列表。

        ``context`` 有 ``get_data`` 时读 ``get_data(_CACHE_DATA_KEY) or {}``，取该 ``key`` 的
        entry；若 ``entry and now < entry["valid_until"]`` 则反序列化
        ``[RankMediaItem.from_dict(x) for x in entry["items"]]``，返回
        ``(items, entry["week"], entry["valid_until"])``；否则 None。``context`` 无 KV / 为 None → None。
        **KV 读或反序列化失败仅告警、返回 None（降级为仅 L1），不影响抓取**（防污染）。
        """
        get_data = getattr(context, "get_data", None) if context is not None else None
        if not callable(get_data):
            return None
        try:
            store = get_data(_CACHE_DATA_KEY) or {}
            entry = store.get(key)
            if not entry or now >= entry.get("valid_until", 0):
                return None
            items = [RankMediaItem.from_dict(x) for x in entry.get("items", [])]
            return items, entry.get("week"), entry.get("valid_until")
        except Exception as err:  # noqa: BLE001 - KV 读失败降级为仅 L1，不影响抓取
            logger.warning(f"{self.provider_name}：读取持久化缓存(KV)失败，降级为仅内存缓存：{err}")
            return None

    def _save_persistent(
        self,
        context: Optional[ProviderContext],
        key: str,
        items: List[RankMediaItem],
        week: Optional[str],
        valid_until: float,
        now: float,
    ) -> None:
        """把本次抓取序列化写入持久化插件 KV（L2）；剔除已过期条目防无限增长。

        ``context`` 有 ``save_data`` 时读 store、剔除 ``valid_until < now`` 的过期条目，写入
        ``store[key] = {"items": [it.to_dict()...], "week", "valid_until", "fetched_ts": now}`` 后
        ``save_data(_CACHE_DATA_KEY, store)``。**KV 读/写失败仅告警、不影响抓取产出**（防污染）；
        ``context`` 无 KV / 为 None 时直接返回（仅 L1）。
        """
        save_data = getattr(context, "save_data", None) if context is not None else None
        if not callable(save_data):
            return
        get_data = getattr(context, "get_data", None) if context is not None else None
        try:
            store = (get_data(_CACHE_DATA_KEY) or {}) if callable(get_data) else {}
            # 剔除已过期条目，防 store 无限增长。
            store = {
                k: v for k, v in store.items()
                if isinstance(v, dict) and now < v.get("valid_until", 0)
            }
            store[key] = {
                "items": [it.to_dict() for it in items],
                "week": week,
                "valid_until": valid_until,
                "fetched_ts": now,
            }
            save_data(_CACHE_DATA_KEY, store)
        except Exception as err:  # noqa: BLE001 - KV 写失败仅告警，不影响抓取产出
            logger.warning(f"{self.provider_name}：写入持久化缓存(KV)失败，仅内存缓存生效：{err}")

    def _fetch_global(
        self,
        dataset: str,
        categories: List[str],
        limit: int,
        proxy: bool,
        seen: set,
        context: Optional[ProviderContext],
    ) -> Iterator[RankMediaItem]:
        """全球榜：按数据源取对应 TSV（周榜只取最新周），每个 category 按 rank 升序取前 limit。"""
        url = MOST_POPULAR_URL if dataset == DATASET_POPULAR else ALL_WEEKS_GLOBAL_URL
        rows = self._load_tsv(url, proxy)
        if dataset != DATASET_POPULAR:
            rows = self._latest_week_rows(rows)
        logger.info(f"{self.provider_name}：全球榜({dataset}) 共 {len(rows)} 行")
        for category in categories:
            if self._should_stop(context):
                return
            cat_rows = sorted(
                (r for r in rows if r.get("category") == category),
                key=self._row_rank,
            )[:limit]
            yield from self._emit(cat_rows, category, "global", seen, context)

    def _fetch_countries(
        self,
        selections: Dict[str, List[str]],
        limit: int,
        proxy: bool,
        seen: set,
        context: Optional[ProviderContext],
    ) -> Iterator[RankMediaItem]:
        """国家榜：取 all-weeks-countries 最新周，对每个「地区 × 其所选类型」按 weekly_rank 升序取前 limit。"""
        rows = self._latest_week_rows(self._load_tsv(ALL_WEEKS_COUNTRIES_URL, proxy))
        logger.info(f"{self.provider_name}：国家榜最新周 共 {len(rows)} 行，筛选 {len(selections)} 国")
        for iso2, categories in selections.items():
            if self._should_stop(context):
                return
            country_rows = [r for r in rows if r.get("country_iso2") == iso2]
            for category in categories:
                cat_rows = sorted(
                    (r for r in country_rows if r.get("category") == category),
                    key=self._row_rank,
                )[:limit]
                yield from self._emit(cat_rows, category, iso2, seen, context)

    def _emit(
        self,
        rows: List[dict],
        category: str,
        scope: str,
        seen: set,
        context: Optional[ProviderContext],
    ) -> Iterator[RankMediaItem]:
        """把候选行逐条构造为 ``RankMediaItem``：按 unique_seed 去重、单条兜底、响应退出信号。"""
        for row in rows:
            if self._should_stop(context):
                return
            try:
                item = self._build_item(row, category, scope)
            except Exception as err:  # noqa: BLE001 - 单条兜底，不影响整源
                logger.error(f"{self.provider_name}：解析榜单条目失败：{err}")
                continue
            if not item.title:
                continue
            if item.unique_seed in seen:
                continue
            seen.add(item.unique_seed)
            yield item

    @classmethod
    def _build_item(cls, row: dict, category: str, scope: str) -> RankMediaItem:
        """把单行 dict 构造为 ``RankMediaItem``（无 id/无年份，退化名称识别）。"""
        show_title = str(row.get("show_title") or "").strip()
        is_movie = category.startswith("Films")
        mtype = MediaType.MOVIE if is_movie else MediaType.TV
        type_value = "movie" if is_movie else "tv"
        season = None if is_movie else cls._extract_season(row.get("season_title"))

        source_meta = {
            "scope": scope,
            "category": category,
            "rank": cls._row_rank(row),
        }
        week = row.get("week")
        if week:
            source_meta["week"] = week
        country_name = row.get("country_name")
        if country_name:
            source_meta["country_name"] = country_name

        return RankMediaItem(
            title=show_title,
            year=None,
            type_hint=mtype,
            season=season,
            source_meta=source_meta,
            unique_seed=f"{type_value}_{show_title}",
        )

    # ==================== 富元数据模式 ====================

    def _fetch_rich(
        self,
        options: dict,
        limit: int,
        proxy: bool,
        seen: set,
        context: Optional[ProviderContext],
    ) -> Iterator[RankMediaItem]:
        """富元数据模式：并发抓 Tudum 榜单页内嵌 GraphQL；全球非英语两类无富页回退 TSV。

        组装「富页任务」（全球英语各 1 页、每所选国家 × 每所选类型各 1 页），用
        ``ThreadPoolExecutor(max_workers)`` 并发抓取；随后对全球非英语两类（若选中且开了全球榜）
        回退现有 TSV title-only 逻辑补上。全局 ``seen`` 去重贯穿两条路径。
        """
        max_workers = max(1, self._to_int(options.get("max_workers"), _DEFAULT_MAX_WORKERS))
        global_on = bool(options.get("global", True))
        global_cats = self._as_list(options.get("global_media_types")) if global_on else []
        selections = self._resolve_country_selections(options)

        # 富页任务（全球英语 + 国家榜）。
        tasks = self._build_rich_tasks(global_cats, selections)
        if tasks:
            yield from self._run_rich_tasks(tasks, max_workers, limit, proxy, seen, context)

        # 全球非英语无稳定富页 -> 回退现有 TSV（title-only），记日志说明。
        non_english = [c for c in global_cats if c in _GLOBAL_NON_ENGLISH]
        if non_english and not self._should_stop(context):
            logger.info(
                f"{self.provider_name}：富模式下全球非英语（{'/'.join(non_english)}）"
                f"无内嵌富页，回退 TSV title-only"
            )
            dataset = str(options.get("global_dataset") or DATASET_WEEKLY).strip()
            yield from self._fetch_global(dataset, non_english, limit, proxy, seen, context)

    @classmethod
    def _build_rich_tasks(
        cls,
        global_cats: List[str],
        selections: Dict[str, List[str]],
    ) -> List[Dict]:
        """组装富页任务列表，每项 ``{url, kind, scope, category}``。

        全球英语两类各 1 页（``/tudum/top10/{films|tv}``）；每个所选地区 × 其所选类型各 1 页
        （``/tudum/top10/{slug}/{films|tv}``，``slug`` 由 ``COUNTRIES`` name 生成）。
        """
        tasks: List[Dict] = []
        for cat in global_cats:
            suffix = _GLOBAL_ENGLISH_RICH.get(cat)
            if suffix:
                tasks.append({
                    "url": f"{_TUDUM_TOP10_BASE}/{suffix}",
                    "kind": suffix,
                    "scope": "global",
                    "category": cat,
                })
        for iso2, country_cats in selections.items():
            name = COUNTRIES.get(iso2)
            if not name:
                continue
            slug = cls._country_slug(name)
            for cat in country_cats:
                suffix = _COUNTRY_RICH.get(cat)
                if not suffix:
                    continue
                tasks.append({
                    "url": f"{_TUDUM_TOP10_BASE}/{slug}/{suffix}",
                    "kind": suffix,
                    "scope": iso2,
                    "category": cat,
                })
        return tasks

    def _run_rich_tasks(
        self,
        tasks: List[Dict],
        max_workers: int,
        limit: int,
        proxy: bool,
        seen: set,
        context: Optional[ProviderContext],
    ) -> Iterator[RankMediaItem]:
        """用 ThreadPoolExecutor 并发抓所有富页任务；单页失败仅告警跳过，响应退出信号。

        用 ``as_completed`` 收集，结果按提交顺序（``tasks`` 序）产出以保证确定性；每页内按
        rank 升序取前 ``limit`` 再逐条构造。提交/收集时检查 ``context.event``，set 则停止。
        """
        results: Dict[int, List[dict]] = {}
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures: Dict = {}
            for idx, task in enumerate(tasks):
                if self._should_stop(context):
                    break
                futures[executor.submit(self._load_rich_page, task["url"], proxy)] = idx
            for future in as_completed(futures):
                idx = futures[future]
                if self._should_stop(context):
                    continue
                try:
                    results[idx] = future.result()
                except Exception as err:  # noqa: BLE001 - 单页失败仅跳过，不影响其余
                    logger.warning(
                        f"{self.provider_name}：富页 {tasks[idx]['url']} 抓取失败，跳过：{err}"
                    )

        # 按提交顺序产出（确定性）；每页内按 rank 升序取前 limit。
        for idx, task in enumerate(tasks):
            if self._should_stop(context):
                return
            entries = results.get(idx)
            if not entries:
                continue
            top = sorted(entries, key=lambda e: e.get("rank") or _RANK_FALLBACK)[:limit]
            yield from self._emit_rich(top, task, seen, context)

    def _emit_rich(
        self,
        entries: List[dict],
        task: Dict,
        seen: set,
        context: Optional[ProviderContext],
    ) -> Iterator[RankMediaItem]:
        """把富页候选条目逐条构造为 ``RankMediaItem``：按 unique_seed 去重、单条兜底、响应退出。"""
        for entry in entries:
            if self._should_stop(context):
                return
            try:
                item = self._build_rich_item(entry, task["kind"], task["scope"])
            except Exception as err:  # noqa: BLE001 - 单条兜底，不影响整源
                logger.error(f"{self.provider_name}：解析富页条目失败：{err}")
                continue
            if not item.title:
                continue
            if item.unique_seed in seen:
                continue
            seen.add(item.unique_seed)
            yield item

    @classmethod
    def _build_rich_item(cls, entry: dict, kind: str, scope: str) -> RankMediaItem:
        """把富页条目构造为 ``RankMediaItem``：优先用干净剧名，带年份/videoId/rank。

        ``title = clean_title or title``（优先 ``parentShow.title`` 干净剧名，识别更准）；
        ``year`` 来自 ``releaseYear``；``type_hint`` 由页面类型（films→MOVIE / tv→TV）判定；
        剧集季号从完整 ``title`` 抽（"X: Season N"）。``source_meta`` 带 videoId/rank/scope/category。
        """
        title = str(entry.get("title") or "").strip()
        clean = str(entry.get("clean_title") or "").strip()
        title_used = clean or title
        is_movie = kind == "films"
        mtype = MediaType.MOVIE if is_movie else MediaType.TV
        type_value = "movie" if is_movie else "tv"
        season = None if is_movie else cls._extract_season(title)
        year_val = entry.get("year")
        year = str(year_val) if year_val else None

        source_meta: dict = {
            "scope": scope,
            "category": entry.get("category"),
            "rank": entry.get("rank"),
            "video_id": entry.get("video_id"),
            "source": "rich",
        }
        week = entry.get("week")
        if week:
            source_meta["week"] = week

        return RankMediaItem(
            title=title_used,
            year=year,
            type_hint=mtype,
            season=season,
            source_meta=source_meta,
            unique_seed=f"{type_value}_{title_used}",
        )

    def _load_rich_page(self, url: str, proxy: bool) -> List[dict]:
        """抓取 Tudum 榜单页 HTML，提取并解码内嵌 GraphQL，返回该页 top10 条目列表。

        每条 ``{rank, title, clean_title, year, video_id, category, week}``。响应为空/请求失败/
        解码失败均抛异常（由上层按源/按任务兜底：``_run_rich_tasks`` 仅告警跳过该页）。
        """
        ret = RequestUtils(
            ua=_RICH_UA,
            proxies=settings.PROXY if proxy else None,
            timeout=_RICH_TIMEOUT,
        ).get_res(url)
        if ret is None or not getattr(ret, "text", None):
            raise RuntimeError(f"{self.provider_name}：获取 {url} 失败或响应为空")
        store = self._decode_graphql(ret.text)
        return self._parse_rich_store(store)

    @classmethod
    def _decode_graphql(cls, html: str) -> dict:
        """定位 ``reactContext.models.graphql = JSON.parse('<单引号JS串>')``，解码后 json.loads。

        返回归一化 store（``data`` 字段内的实体字典）。找不到标记或字符串未闭合时抛异常。
        """
        raw = cls._extract_graphql_literal(html)
        text = cls._decode_js_string(raw)
        data = json.loads(text)
        if isinstance(data, dict):
            store = data.get("data", data)
            return store if isinstance(store, dict) else {}
        return {}

    @staticmethod
    def _extract_graphql_literal(html: str) -> str:
        """从 HTML 定位 GraphQL 单引号 JS 串字面量的原始文本（不含首尾引号）。

        ``reactContext.models.graphql`` 的 JSON.parse 赋值位于页面 **尾部**（前面基本是页面骨架，
        用不上），故用 ``rfind`` **从末尾倒序定位**标记：比正向 find 少扫大半文档，且当页面偶有
        多个同名赋值时稳取最后（生效）的那个。定位后再从标记后逐字符正向扫描到首个**未转义**的
        单引号（``\\`` 后一字符整体跳过）。找不到标记或未闭合时抛 ``RuntimeError``。
        """
        start = html.rfind(_GRAPHQL_MARKER)
        if start == -1:
            raise RuntimeError("页面未找到内嵌 GraphQL 数据（reactContext.models.graphql）")
        body = start + len(_GRAPHQL_MARKER)
        i = body
        n = len(html)
        while i < n:
            ch = html[i]
            if ch == "\\":
                i += 2
                continue
            if ch == "'":
                return html[body:i]
            i += 1
        raise RuntimeError("内嵌 GraphQL 单引号字符串未正确闭合")

    @classmethod
    def _decode_js_string(cls, raw: str) -> str:
        """解码单引号 JS 字符串字面量的转义（``\\\\`` ``\\'`` ``\\"`` ``\\n`` ``\\uXXXX`` ``\\xXX`` 等）。

        单次左→右扫描替换（不递归），正确还原 CJK/重音字符：``\\\\uXXXX`` 先降为 ``\\uXXXX`` 交由
        ``json.loads`` 再解析，裸 ``\\uXXXX`` 直接转为对应字符。
        """
        return _JS_UNESCAPE.sub(cls._js_unescape_sub, raw)

    @staticmethod
    def _js_unescape_sub(match: "re.Match") -> str:
        """``_JS_UNESCAPE`` 的替换回调：处理 ``\\uXXXX`` / ``\\xXX`` / 简单转义 / 其余原样去斜杠。"""
        seq = match.group(1)
        head = seq[0]
        if head in ("u", "x"):
            try:
                return chr(int(seq[1:], 16))
            except ValueError:  # pragma: no cover - 正则已保证十六进制格式
                return seq
        return _JS_SIMPLE_ESCAPES.get(seq, seq)

    @classmethod
    def _parse_rich_store(cls, store: dict) -> List[dict]:
        """遍历归一化 store，取所有含 ``top10Video`` 的条目，按 videoId 去重后组装。

        同一 videoId 在 store 内可能出现多次（不同榜单列表引用同一视频），按 videoId 去重只留一条。
        """
        entries: List[dict] = []
        seen_ids: set = set()
        for obj in (store or {}).values():
            if not isinstance(obj, dict):
                continue
            video = obj.get("top10Video")
            top10 = obj.get("top10")
            if not isinstance(video, dict) or not isinstance(top10, dict):
                continue
            video_id = video.get("videoId")
            dedup = video_id if video_id is not None else video.get("title")
            if dedup in seen_ids:
                continue
            seen_ids.add(dedup)
            parent = video.get("parentShow")
            clean = parent.get("title") if isinstance(parent, dict) else None
            entries.append({
                "rank": cls._to_optional_int(top10.get("weeklyRank")),
                "title": video.get("title"),
                "clean_title": clean,
                "year": cls._to_optional_int(video.get("releaseYear")),
                "video_id": video_id,
                "category": top10.get("category"),
                "week": top10.get("weekEndDate"),
            })
        return entries

    @staticmethod
    def _country_slug(name: str) -> str:
        """国家英文名 -> Tudum slug：小写、空格转连字符（``South Korea`` -> ``south-korea``）。"""
        return re.sub(r"\s+", "-", str(name).strip().lower())

    @staticmethod
    def _to_optional_int(value) -> Optional[int]:
        """安全转 int，失败/为空返回 None（供富页 rank/year 用）。"""
        try:
            return int(value)
        except (ValueError, TypeError):
            return None

    def _load_tsv(self, url: str, proxy: bool) -> List[dict]:
        """GET TSV 并解析为行 dict 列表；响应为空/请求失败时抛出（整源失败，由 runner 捕获）。"""
        ret = RequestUtils(
            proxies=settings.PROXY if proxy else None,
            timeout=_REQUEST_TIMEOUT,
        ).get_res(url)
        if ret is None or not getattr(ret, "content", None):
            raise RuntimeError(f"{self.provider_name}：获取 {url} 失败或响应为空")
        # Netflix TSV 响应头 Content-Type 不带 charset，requests 会把 encoding 兜底成
        # ISO-8859-1，导致 .text 用 Latin-1 误解码 UTF-8 字节（如剧名『Å』U+00C5 被拆成
        # 『Ã』U+00C3 + U+0085 NEL，进而在下游按行切分时撕裂行、污染 week 列）。
        # 故强制按 UTF-8 从原始字节解码，兼修剧名乱码。
        text = ret.content.decode("utf-8", errors="replace")
        return self._parse_tsv(text)

    @staticmethod
    def _parse_tsv(text: str) -> List[dict]:
        """解析制表符分隔文本：首行表头，其余 ``dict(zip(header, cols))``，跳过空行、去 '\\r'。

        用 ``split("\\n")`` 而非 ``splitlines()``：后者会在 U+0085(NEL)/U+2028 等 Unicode 行
        边界处额外断行，一旦剧名含此类字符（或上游误解码引入）便会把数据行撕成碎片、污染 week 列。
        """
        lines = text.split("\n")
        if not lines:
            return []
        header = lines[0].strip("\r").split("\t")
        rows: List[dict] = []
        for line in lines[1:]:
            line = line.strip("\r")
            if not line.strip():
                continue
            rows.append(dict(zip(header, line.split("\t"))))
        return rows

    @staticmethod
    def _latest_week_rows(rows: List[dict]) -> List[dict]:
        """只保留最新周的行（``max(week)``，ISO 日期字典序即时序）；无 week 列时原样返回。"""
        weeks = [w for w in (r.get("week") for r in rows) if w]
        if not weeks:
            return rows
        latest = max(weeks)
        return [r for r in rows if r.get("week") == latest]

    @classmethod
    def _extract_season(cls, season_title) -> Optional[int]:
        """从 season_title 抽季号：``Season\\s*(\\d+)``；``N/A``/无匹配返回 None。"""
        value = str(season_title or "").strip()
        if not value or value == "N/A":
            return None
        match = _SEASON_PATTERN.search(value)
        return int(match.group(1)) if match else None

    @classmethod
    def _row_rank(cls, row: dict) -> int:
        """行排名：兼容 most-popular 的 ``rank`` 与周榜的 ``weekly_rank``，非法排末尾。"""
        return cls._to_int(row.get("rank") or row.get("weekly_rank"), _RANK_FALLBACK)

    @staticmethod
    def _should_stop(context: Optional[ProviderContext]) -> bool:
        """是否收到退出信号（``context.event`` 被 set）。"""
        return (
            context is not None
            and getattr(context, "event", None) is not None
            and context.event.is_set()
        )

    @staticmethod
    def _to_int(value, default: int) -> int:
        """安全转 int，失败回退默认值。"""
        try:
            return int(float(value))
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _as_list(value) -> List[str]:
        """把多选值统一成字符串列表（兼容逗号分隔字符串）。"""
        if isinstance(value, list):
            return [str(v).strip() for v in value if str(v).strip()]
        if isinstance(value, str):
            return [v.strip() for v in value.split(",") if v.strip()]
        return []
