"""猫眼榜单来源：解析猫眼票房/网播热度/网络电影 JSON，产出标准化条目。

数据来源为猫眼专业版（piaofang.maoyan.com）端点：
- 电影票房：``/dashboard-ajax/movie``（全网，无平台维度）。
- 网播热度：``/dashboard/webHeatData?seriesType=X&platformType=Y&showDate=2``
  —— seriesType: 电视剧=0 / 网络剧=1 / 综艺=2 / 电视剧+网络剧(合并剧集)=4；
     platformType: 全网="" / 腾讯视频=3 / 爱奇艺=2 / 优酷=1 / 乐视=4 / 芒果TV=7 / PPTV=6 / 搜狐=5。
- 网络电影：``/dashboard/webHeatNetData?showDate=YYYYMMDD&platformType=Y&dateType=0&rankType=0``
  —— 仅腾讯视频/爱奇艺/优酷有数据，各平台最新可用日期不同（先探测 calendarNet.selectMaxDate）。

「网播热度」与「网络电影」按「平台 × 媒体类型」自由组合（前端 region-media-map 控件），
值形态 ``{平台: [媒体类型, ...]}``。Cookie 通过 ``PlaywrightHelper`` 获取，失败降级空 dict。
年份由 releaseInfo（距今天数）反推，缺失或解析失败则置空。
"""
from __future__ import annotations

import random
import re
from datetime import date, timedelta
from typing import Dict, Iterator, List, Optional

from app.helper.browser import BrowserPage, PlaywrightHelper
from app.log import logger
from app.schemas.types import MediaType
from app.core.config import settings
from app.utils.http import RequestUtils

from ..core.models import FieldSpec, ProviderSpec, RankMediaItem
from ..core.provider import ProviderContext, RankProvider
from ..core.registry import register

# 猫眼专业版根地址。
MAOYAN_URL = "https://piaofang.maoyan.com"

# 网播热度媒体类型（webHeatData 的 seriesType）：
# series=电视剧+网络剧(合并剧集)，tv=电视剧，web=网络剧，variety=综艺。
SERIES_TYPE = {"series": "4", "tv": "0", "web": "1", "variety": "2"}
# 网络电影专用媒体类型标记（走 webHeatNetData，非 webHeatData）。
NET_MOVIE = "netmovie"
# 网络电影仅这三家平台有数据（webHeatNetData，platformType 与下表同套编码）。
NET_MOVIE_PLATFORMS = ("tx", "iqiyi", "youku")

# 平台：选项值 -> platformType 参数（全网为空串）。
PLATFORM_TYPE = {
    "all": "", "tx": "3", "iqiyi": "2", "mgtv": "7", "youku": "1",
    "sohu": "5", "letv": "4", "pptv": "6",
}
# 平台展示顺序（前端网格的行顺序）。
PLATFORM_ORDER = ("all", "tx", "iqiyi", "youku", "letv", "mgtv", "pptv", "sohu")
# 平台选项标签。
PLATFORM_LABELS = {
    "all": "全网", "tx": "腾讯视频", "iqiyi": "爱奇艺", "youku": "优酷",
    "letv": "乐视", "mgtv": "芒果TV", "pptv": "PPTV", "sohu": "搜狐",
}
# 媒体类型标签（网格的列）。网络电影因数据源停更已移除，见 get_spec 的 notice。
MEDIA_LABELS = {
    "series": "电视剧+网络剧", "tv": "电视剧", "web": "网络剧", "variety": "综艺",
}
MEDIA_ORDER = ("series", "tv", "web", "variety")
# 有效媒体类型集合。
_VALID_MEDIA = set(SERIES_TYPE)

# 旧配置（types/platforms）到新媒体类型的兼容映射。
_LEGACY_TYPE = {"web-heat": "tv", "web-tv": "web", "zongyi": "variety"}

# 随机 User-Agent 池，降低被风控概率。
_USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Edg/121.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Edg/121.0.0.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
]

# 默认每榜条数。
_DEFAULT_NUM = 10


@register
class MaoyanRankProvider(RankProvider):
    """猫眼榜单来源：电影票房 + 网播热度/网络电影（平台 × 类型自由组合）。"""

    provider_id = "maoyan"
    provider_name = "猫眼榜单"

    def get_spec(self) -> ProviderSpec:
        """返回本来源的元描述（选项与过滤器 schema）。"""
        platform_options = [
            {"title": PLATFORM_LABELS[k], "value": k} for k in PLATFORM_ORDER
        ]
        media_columns = [{"title": MEDIA_LABELS[k], "value": k} for k in MEDIA_ORDER]
        media_type_options = [
            {"title": "全部", "value": "all"},
            {"title": "电影", "value": "movie"},
            {"title": "电视剧", "value": "tv"},
        ]
        return ProviderSpec(
            provider_id=self.provider_id,
            provider_name=self.provider_name,
            default_cron="0 9 * * *",
            notice="网络电影因数据源已停更（优酷停于 2022、爱奇艺停于 2026-01），暂不支持，已移除。",
            options_schema=[
                FieldSpec(key="movie_box", label="电影票房榜", kind="switch", default=True),
                FieldSpec(
                    key="web_platform_map",
                    label="网播热度 平台 × 类型",
                    kind="region-media-map",
                    default={"all": ["tv"]},
                    options=platform_options,
                    columns=media_columns,
                    row_noun="platform",
                    hint="按平台分别选择要监听的网播类型（可各不相同）",
                ),
                FieldSpec(key="num", label="每榜条数", kind="number", default=_DEFAULT_NUM),
                FieldSpec(key="proxy", label="使用代理访问", kind="switch", default=False),
            ],
            filters_schema=[
                FieldSpec(key="year", label="年份≥", kind="number", default=0),
                FieldSpec(
                    key="media_type",
                    label="媒体类型",
                    kind="select",
                    default="all",
                    options=media_type_options,
                ),
            ],
        )

    def has_listening(self, options: dict) -> bool:
        """开启电影票房榜，或存在任一启用的网播平台×类型组合。"""
        options = options or {}
        return self._want_movie_box(options) or bool(self._resolve_platform_map(options))

    def fetch(self, options: dict, context: ProviderContext) -> Iterator[RankMediaItem]:
        """抓取并解析猫眼榜单，逐条产出 ``RankMediaItem``。

        电影票房（``movie_box``）独立产出；网播热度/网络电影按「平台 × 类型」映射逐个抓取。
        单条解析失败内部 try/except continue；请求/解析级异常向上抛出，由 runner 捕获。
        单次 fetch 内按 ``{类型}_{标题}`` 去重（同一片名跨平台只产一次）。
        """
        options = options or {}
        num = self._to_int(options.get("num"), _DEFAULT_NUM)
        # 可选代理：开启则本次抓取的 HTTP 请求走系统代理。
        self._proxies = settings.PROXY if bool(options.get("proxy")) else None

        cookies = self._get_cookies()
        headers = {"User-Agent": random.choice(_USER_AGENTS)}
        seen: set = set()

        # 电影票房榜（全网，无平台维度）。
        if self._want_movie_box(options):
            yield from self._fetch_movie_box(cookies, headers, num, seen)

        # 网播热度 / 网络电影：逐「平台 × 媒体类型」抓取。
        stop = getattr(context, "event", None)
        for platform, media_types in self._resolve_platform_map(options).items():
            if stop is not None and stop.is_set():
                return
            platform_type = PLATFORM_TYPE.get(platform, "")
            for media in media_types:
                if media in SERIES_TYPE:
                    yield from self._fetch_web_heat_one(
                        SERIES_TYPE[media], platform_type, cookies, headers, num, seen)
                elif media == NET_MOVIE and platform in NET_MOVIE_PLATFORMS:
                    yield from self._fetch_web_net_one(
                        platform_type, cookies, headers, num, seen)

    # ------------------------------------------------------------------ #
    # 配置归一化
    # ------------------------------------------------------------------ #
    def _want_movie_box(self, options: dict) -> bool:
        """是否抓电影票房：新字段 movie_box，或旧 types 含 movie（向后兼容）。"""
        if "movie_box" in options:
            return bool(options.get("movie_box"))
        return "movie" in self._as_list(options.get("types"))

    def _resolve_platform_map(self, options: dict) -> Dict[str, List[str]]:
        """归一化「平台 × 媒体类型」映射为 ``{platform: [media, ...]}``。

        优先新字段 ``web_platform_map``（region-media-map 产出的 dict）；缺省或非法时
        **向后兼容**回退旧字段 ``types``（web-heat/web-tv/zongyi）× ``platforms``。仅保留
        有效平台与有效媒体类型；空列表的平台剔除。
        """
        result: Dict[str, List[str]] = {}
        raw = options.get("web_platform_map")
        if isinstance(raw, dict) and raw:
            for platform, media in raw.items():
                if platform not in PLATFORM_TYPE:
                    continue
                # 条目形态兼容：新 {"on": bool, "cats": [...]}（可禁用而不丢配置）与旧 [...]。
                if isinstance(media, dict):
                    if not media.get("on", True):
                        continue  # 禁用的组合跳过（配置保留但本轮不生效）
                    media = media.get("cats", [])
                medias = [m for m in self._as_list(media) if m in _VALID_MEDIA]
                if medias:
                    result[platform] = medias
            return result
        # 向后兼容：旧 types × platforms（笛卡尔积套用）。旧「网络电影全网」不分平台，此处不映射。
        legacy_media = [_LEGACY_TYPE[t] for t in self._as_list(options.get("types")) if t in _LEGACY_TYPE]
        if legacy_media:
            for platform in (self._as_list(options.get("platforms")) or ["all"]):
                if platform in PLATFORM_TYPE:
                    result[platform] = list(legacy_media)
        return result

    # ------------------------------------------------------------------ #
    # 各端点抓取
    # ------------------------------------------------------------------ #
    def _fetch_movie_box(self, cookies: dict, headers: dict, num: int, seen: set) -> Iterator[RankMediaItem]:
        """电影票房榜：/dashboard-ajax/movie。"""
        url = f"{MAOYAN_URL}/dashboard-ajax/movie"
        payload = self._request_json(url, cookies, headers)
        data = ((payload or {}).get("movieList") or {}).get("list") or []
        for entry in data[:num]:
            try:
                info = entry.get("movieInfo") or {}
                yield from self._emit(
                    info.get("movieName"), info.get("releaseInfo"), None, MediaType.MOVIE, seen)
            except Exception as err:  # noqa: BLE001 - 单条兜底
                logger.error(f"{self.provider_name}：解析电影票房条目失败：{err}")
                continue

    def _fetch_web_heat_one(self, series_type: str, platform_type: str,
                            cookies: dict, headers: dict, num: int, seen: set) -> Iterator[RankMediaItem]:
        """网播热度单榜：/dashboard/webHeatData（单一 seriesType × platformType）。"""
        url = (f"{MAOYAN_URL}/dashboard/webHeatData"
               f"?seriesType={series_type}&platformType={platform_type}&showDate=2")
        payload = self._request_json(url, cookies, headers)
        data = ((payload or {}).get("dataList") or {}).get("list") or []
        for entry in data[:num]:
            try:
                info = entry.get("seriesInfo") or {}
                yield from self._emit(
                    info.get("name"), info.get("releaseInfo"), info.get("platformDesc"),
                    MediaType.TV, seen)
            except Exception as err:  # noqa: BLE001 - 单条兜底
                logger.error(f"{self.provider_name}：解析网播热度条目失败：{err}")
                continue

    def _fetch_web_net_one(self, platform_type: str,
                           cookies: dict, headers: dict, num: int, seen: set) -> Iterator[RankMediaItem]:
        """网络电影单平台：/dashboard/webHeatNetData（dateType=0）。

        各平台最新可用日期不同：先用今天探测，若无数据则读 ``calendarNet.selectMaxDate``
        用该日期重抓（腾讯多为昨日、爱奇艺可能滞后数月）。
        """
        base = f"{MAOYAN_URL}/dashboard/webHeatNetData"
        today = date.today().strftime("%Y%m%d")
        payload = self._request_json(
            f"{base}?showDate={today}&platformType={platform_type}&dateType=0&rankType=0",
            cookies, headers)
        data = ((payload or {}).get("dataList") or {}).get("list") or []
        if not data:
            max_date = ((payload or {}).get("calendarNet") or {}).get("selectMaxDate")
            # 新鲜度护栏：最新可用日距今超过阈值则视为“已停更”，不订阅陈旧老片
            # （实测：爱奇艺停更于 2026-01、优酷仅剩 2022 月榜；腾讯每日现行可通过）。
            if not max_date or self._too_stale(max_date):
                return
            ymd = str(max_date).replace("-", "")
            payload = self._request_json(
                f"{base}?showDate={ymd}&platformType={platform_type}&dateType=0&rankType=0",
                cookies, headers)
            data = ((payload or {}).get("dataList") or {}).get("list") or []
        for entry in data[:num]:
            try:
                yield from self._emit(
                    entry.get("movieName"), entry.get("releaseInfo"), None, MediaType.MOVIE, seen)
            except Exception as err:  # noqa: BLE001 - 单条兜底
                logger.error(f"{self.provider_name}：解析网络电影条目失败：{err}")
                continue

    def _emit(self, title, release_info, platform_desc, mtype: MediaType, seen: set) -> Iterator[RankMediaItem]:
        """构造并产出单条：空标题或本次已见（按 类型_标题）则跳过。"""
        if not title:
            return
        dedup = f"{mtype.value}_{title}"
        if dedup in seen:
            return
        seen.add(dedup)
        yield self._build_item(title, release_info, platform_desc, mtype)

    def _build_item(self, title, release_info, platform_desc, mtype: MediaType) -> RankMediaItem:
        """构造标准化条目，含年份反推与 unique_seed 生成。"""
        year = self._year_from_release_info(release_info)
        return RankMediaItem(
            title=str(title),
            year=year,
            type_hint=mtype,
            source_meta={"platformDesc": platform_desc, "releaseInfo": release_info},
            unique_seed=f"{mtype.value}_{title}_{year}",
        )

    @staticmethod
    def _year_from_release_info(release_info) -> Optional[str]:
        """由 releaseInfo（距今天数）反推年份；缺失或解析失败返回 None。"""
        if not release_info:
            return None
        try:
            days = int("".join(re.findall(r"\d", str(release_info))))
        except (ValueError, TypeError):
            return None
        if not str(release_info):
            return None
        try:
            target = date.today() - timedelta(days=days)
            return str(target.year)
        except (OverflowError, ValueError):
            return None

    def _request_json(self, url: str, cookies: dict, headers: dict) -> Optional[dict]:
        """发起请求并解析 JSON；无响应返回 None，请求/解析异常向上抛。"""
        proxies = getattr(self, "_proxies", None)
        if cookies:
            response = RequestUtils(proxies=proxies).get_res(url, cookies=cookies, headers=headers)
        else:
            response = RequestUtils(proxies=proxies).get_res(url, headers=headers)
        if not response:
            logger.warn(f"{self.provider_name}：请求无响应，跳过：{url}")
            return None
        return response.json()

    @staticmethod
    def _get_cookies() -> dict:
        """通过 MoviePilot 浏览器适配层获取猫眼 Cookie，失败降级空 dict。"""
        def handler(page: BrowserPage) -> dict:
            return {c["name"]: c["value"] for c in page.context.cookies()}

        try:
            return PlaywrightHelper().action(
                url=MAOYAN_URL, callback=handler, headless=True) or {}
        except Exception as err:  # noqa: BLE001 - 浏览器不可用时降级
            logger.warn(f"{MaoyanRankProvider.provider_name}：获取 Cookie 失败，降级无 Cookie 请求：{err}")
            return {}

    @staticmethod
    def _too_stale(max_date, max_age_days: int = 30) -> bool:
        """最新可用日是否过旧（距今超过 max_age_days 天）；解析失败按“过旧”处理。"""
        try:
            d = date.fromisoformat(str(max_date).strip())
        except (ValueError, TypeError):
            return True
        return (date.today() - d).days > max_age_days

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
