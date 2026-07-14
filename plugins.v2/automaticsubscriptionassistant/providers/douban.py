"""豆瓣榜单来源：解析 RSSHub 豆瓣 RSS，产出标准化条目。

数据来源为 RSSHub 的豆瓣榜单 RSS（内置榜单路由 + 用户自定义地址）。RSSHub 基址可自定义，
部分地区 rsshub.app 被 SNI 黑名单封锁时，可对接用户自建的 RSSHub 实例（``rsshub_base`` 选项）。
抓取逻辑移植自参考插件 ``doubanrankplus``，纯函数化后由统一落地管线消费。
豆瓣评分、季号等信息在 executor 识别（recognize_media(doubanid=...)）后由 MediaInfo 提供，
故 VoteFilter 归属 post 阶段。原插件的 70 分钟限流退避窗口本次未移植（见 README）。
"""
from __future__ import annotations

import re
import xml.dom.minidom
from typing import Iterator, List

from app.core.config import settings
from app.log import logger
from app.schemas.types import MediaType
from app.utils.dom import DomUtils
from app.utils.http import RequestUtils

from ..core.models import FieldSpec, ProviderSpec, RankMediaItem
from ..core.provider import ProviderContext, RankProvider
from ..core.registry import register

# 默认 RSSHub 基址；部分地区 rsshub.app 被 SNI 黑名单封锁，可在配置里改为自建实例。
DEFAULT_RSSHUB_BASE = "https://rsshub.app"

# 内置榜单路由：key 为 select 选项值，value 为 RSSHub 相对路由（与基址拼接成完整地址）。
DOUBAN_ADDRESS = {
    "movie-ustop": "/douban/movie/ustop",
    "movie-weekly": "/douban/movie/weekly",
    "movie-real-time": "/douban/movie/weekly/movie_real_time_hotest",
    "show-domestic": "/douban/movie/weekly/show_domestic",
    "movie-hot-gaia": "/douban/movie/weekly/movie_hot_gaia",
    "tv-hot": "/douban/movie/weekly/tv_hot",
    "movie-top250": "/douban/list/movie_top250",
}

# 榜单选项的中文标签。
DOUBAN_RANK_LABELS = {
    "movie-ustop": "电影北美票房榜",
    "movie-weekly": "一周口碑电影榜",
    "movie-real-time": "实时热门电影",
    "show-domestic": "热门综艺",
    "movie-hot-gaia": "热门电影",
    "tv-hot": "热门电视剧",
    "movie-top250": "电影TOP250",
}

# HTTP 请求超时（秒），对齐参考插件。
_REQUEST_TIMEOUT = 240
# 年份正则：匹配 1900-2099 的四位独立数字。
_YEAR_PATTERN = re.compile(r"\b(19\d{2}|20\d{2})\b")
# 豆瓣ID正则：从详情链接提取数字段。
_DOUBAN_ID_PATTERN = re.compile(r"/(\d+)/")


@register
class DoubanRankProvider(RankProvider):
    """豆瓣榜单来源：解析 RSS item 为标准化 ``RankMediaItem``。"""

    provider_id = "douban"
    provider_name = "豆瓣榜单"

    def get_spec(self) -> ProviderSpec:
        """返回本来源的元描述（选项与过滤器 schema）。"""
        rank_options = [
            {"title": DOUBAN_RANK_LABELS[key], "value": key}
            for key in DOUBAN_ADDRESS
        ]
        media_type_options = [
            {"title": "全部", "value": "all"},
            {"title": "电影", "value": "movie"},
            {"title": "电视剧", "value": "tv"},
        ]
        return ProviderSpec(
            provider_id=self.provider_id,
            provider_name=self.provider_name,
            default_cron="0 8 * * *",
            options_schema=[
                FieldSpec(
                    key="ranks",
                    label="热门榜单",
                    kind="multi-select",
                    default=["movie-hot-gaia", "tv-hot"],
                    options=rank_options,
                ),
                FieldSpec(
                    key="rsshub_base",
                    label="RSSHub 地址",
                    kind="text",
                    default=DEFAULT_RSSHUB_BASE,
                    hint="内置榜单的 RSSHub 基址；rsshub.app 被墙/SNI 封锁时可改为自建实例（如 https://rsshub.你的域名）",
                    advanced=True,
                ),
                FieldSpec(
                    key="rss_addrs",
                    label="自定义RSS地址",
                    kind="textarea",
                    default="",
                    hint="每行一个完整 RSS 地址（覆盖上面的基址，可对接任意源）",
                    advanced=True,
                ),
                FieldSpec(
                    key="proxy",
                    label="使用代理服务器",
                    kind="switch",
                    default=False,
                ),
            ],
            filters_schema=[
                FieldSpec(key="vote", label="评分≥", kind="float", default=0),
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
        """选了任一内置榜单，或填了任一自定义 RSS 地址。"""
        options = options or {}
        ranks = [r for r in self._as_list(options.get("ranks")) if r in DOUBAN_ADDRESS]
        custom = [ln for ln in str(options.get("rss_addrs") or "").splitlines() if ln.strip()]
        return bool(ranks) or bool(custom)

    def fetch(self, options: dict, context: ProviderContext) -> Iterator[RankMediaItem]:
        """抓取并解析豆瓣 RSS，逐条产出 ``RankMediaItem``。

        单条 item 解析失败内部 try/except continue；请求/解析级异常向上抛出，由 runner 捕获。
        """
        options = options or {}
        ranks = self._as_list(options.get("ranks"))
        custom_addrs = [
            line.strip()
            for line in str(options.get("rss_addrs") or "").splitlines()
            if line.strip()
        ]
        proxy = bool(options.get("proxy"))
        base = self._normalize_base(options.get("rsshub_base"))
        addr_list = custom_addrs + [
            f"{base}{DOUBAN_ADDRESS[rank]}" for rank in ranks if rank in DOUBAN_ADDRESS
        ]
        if not addr_list:
            logger.warn(f"{self.provider_name}：未配置任何榜单地址")
            return
        for addr in addr_list:
            yield from self._fetch_addr(addr, proxy)

    @staticmethod
    def _normalize_base(raw) -> str:
        """规整 RSSHub 基址：空则用默认，去尾部斜杠，无 scheme 时补 https://。"""
        base = str(raw or "").strip()
        if not base:
            return DEFAULT_RSSHUB_BASE
        base = base.rstrip("/")
        if not re.match(r"^https?://", base):
            base = f"https://{base}"
        return base

    def _fetch_addr(self, addr: str, proxy: bool) -> Iterator[RankMediaItem]:
        """抓取单个 RSS 地址并解析其中的 item。"""
        proxies = settings.PROXY if proxy else None
        ret = RequestUtils(timeout=_REQUEST_TIMEOUT, proxies=proxies).get_res(addr)
        if not ret:
            logger.warn(f"{self.provider_name}：RSS 地址无返回，跳过：{addr}")
            return
        root = xml.dom.minidom.parseString(ret.text).documentElement
        if root is None:
            return
        items = root.getElementsByTagName("item")
        logger.info(f"{self.provider_name}：{addr} 共 {len(items)} 条数据")
        for item in items:
            try:
                media_item = self._parse_item(item)
            except Exception as err:  # noqa: BLE001 - 单条解析失败不影响其余条目
                logger.error(f"{self.provider_name}：解析 RSS 条目失败：{err}")
                continue
            if media_item is not None:
                yield media_item

    def _parse_item(self, item) -> RankMediaItem | None:
        """将单个 RSS item DOM 节点解析为 ``RankMediaItem``。"""
        title = DomUtils.tag_value(item, "title", default="")
        link = DomUtils.tag_value(item, "link", default="")
        if not title and not link:
            return None

        douban_id = self._parse_douban_id(str(link or ""))
        year = self._parse_year(item)
        type_hint = self._parse_type(item)

        return RankMediaItem(
            title=str(title),
            year=year,
            type_hint=type_hint,
            douban_id=douban_id,
            poster=self._parse_poster(item),
            source_meta={"link": str(link)},
            unique_seed=f"{title}_{year}_(DB:{douban_id})",
        )

    @staticmethod
    def _parse_douban_id(link: str) -> str | None:
        """从详情链接提取豆瓣ID（需为纯数字）。"""
        found = _DOUBAN_ID_PATTERN.findall(link)
        if found and str(found[0]).isdigit():
            return str(found[0])
        return None

    @staticmethod
    def _parse_year(item) -> str | None:
        """优先取 year 标签，缺失则从 description 中回退解析四位年份。"""
        year = DomUtils.tag_value(item, "year", default="")
        if year:
            return str(year)
        description = str(DomUtils.tag_value(item, "description", default="") or "")
        # 移除“评价数...”片段与 <img> 标签，避免误匹配其中的数字。
        description = re.sub(r"评价数.*?<br>", "", description)
        description = re.sub(r"<img.*?>", "", description)
        found_year = _YEAR_PATTERN.findall(description)
        return found_year[0] if found_year else None

    @staticmethod
    def _parse_type(item) -> MediaType | None:
        """解析类型标签：movie->MOVIE，其它非空->TV，空->None。"""
        type_str = str(DomUtils.tag_value(item, "type", default="") or "")
        if type_str == "movie":
            return MediaType.MOVIE
        if type_str:
            return MediaType.TV
        return None

    @staticmethod
    def _parse_poster(item) -> str | None:
        """尝试从 description 的 <img src=...> 提取海报地址（可选）。"""
        description = str(DomUtils.tag_value(item, "description", default="") or "")
        found = re.findall(r"<img[^>]+src=\"([^\"]+)\"", description)
        return found[0] if found else None

    @staticmethod
    def _as_list(value) -> List[str]:
        """把多选值统一成字符串列表（兼容逗号分隔字符串）。"""
        if isinstance(value, list):
            return [str(v).strip() for v in value if str(v).strip()]
        if isinstance(value, str):
            return [v.strip() for v in value.split(",") if v.strip()]
        return []
