"""Mikan(蜜柑计划) 季度新番来源：抓取蜜柑季度番剧列表，产出标准化条目。

数据来源为蜜柑计划（mikanani.me，备用 mikanime.tv）季度新番页面，
API 移植自 ``mikan_flutter`` 的 ``mikan.ts``。季度番剧列表页
``/Home/BangumiCoverFlowByDayOfWeek?year={year}&seasonStr={季}`` 返回按星期分组的
HTML（``div.sk-bangumi li``），每部番剧含 Mikan bangumi id、中文标题与封面。

详情页 ``/Home/Bangumi/{mikan_id}`` 的信息区实测为多个 ``p.bangumi-info``，
每条形如 ``key：value``（全角冒号），移植自 ``mikan.ts`` 的 ``parseBangumi``：实测
key 恒为 放送日期/放送开始/官方网站/Bangumi番组计划链接。据此一次详情请求解析出
``{bgm_id, year, air_date, original_title, aliases}``：

* ``bgm_id``：在 ``.bangumi-info`` 文本域内匹配 ``bgm.tv/bangumi.tv/subject/{id}``，
  缺该容器时回退整页匹配。
* ``year``：从「放送开始」值里正则抽 4 位真实放送年（覆盖配置/当前年）。
* ``air_date``：「放送开始」原值。
* ``original_title`` / ``aliases``：实测 Mikan 信息区并无「原名/别名」字段，故
  ``original_title`` 回退取详情页 ``p.bangumi-title`` 全名（通常比列表标题更完整），
  ``aliases`` 取「别名/又名」类 key（无则 ``[]``）。二者仅存入 ``source_meta``
  供历史展示/未来使用；**executor 识别仍只用主标题**（真正用别名做识别需改
  executor，属另一范畴，本次不动 executor）。

产出 ``bangumi_id``（bgm.tv subject id）时 executor 走
``recognize_media(bangumiid=)`` 识别；抓不到 bgm id 时退化为 title+year 名称识别。
封面 ``cover`` 同时落到 ``RankMediaItem.poster`` 与 ``source_meta``。
冷门番若 TMDB 名称匹配不到需注意（见 README 已知限制）。
"""
from __future__ import annotations

import re
from datetime import datetime
from time import sleep
from typing import Iterator, List, Optional, Tuple
from urllib.parse import quote

from bs4 import BeautifulSoup

from app.log import logger
from app.schemas.types import MediaType
from app.core.config import settings
from app.utils.http import RequestUtils

from ..core.models import FieldSpec, ProviderSpec, RankMediaItem
from ..core.provider import ProviderContext, RankProvider
from ..core.registry import register

# 蜜柑计划基址（主 + 备），逐个尝试。
MIKAN_URLS = ["https://mikanani.me", "https://mikanime.tv"]
# 蜜柑要求的 User-Agent。
MIKAN_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36 MikanProject/1.0.0"
)

# 季度 seasonStr 真实取值（实测确认为中文季名，春/夏/秋/冬 均返回 HTTP 200）。
MIKAN_SEASONS = ["春", "夏", "秋", "冬"]
# “当前”自动项的哨兵值：fetch 时按当前月份推导实际季度。
SEASON_AUTO = "当前"

# HTTP 超时（秒）。
_REQUEST_TIMEOUT = 30
# 逐条抓详情时的礼貌间隔（秒），避免压站。
_DETAIL_SLEEP = 0.6

# bgm.tv / bangumi.tv subject id 正则（详情页 .bangumi-info 内链接）。
_BGM_ID_PATTERN = re.compile(r"b(?:gm|angumi)\.tv/subject/(\d+)")
# 4 位年份正则（从「放送开始」等日期值里抽真实放送年）。
_YEAR_PATTERN = re.compile(r"(\d{4})")
# 详情页信息区里表示「放送开始日期」的 key（实测恒为此名，含真实放送年）。
_AIR_START_KEY = "放送开始"
# 用于回退扫描年份的日期类 key 关键词。
_DATE_KEY_HINTS = ("放送", "开播", "首播", "播出")
# 原名/译名类 key（实测 Mikan 无此字段，保留以增强健壮性/未来兼容）。
_ORIGINAL_TITLE_KEYS = ("原名", "日文名", "日语名", "罗马音", "译名")
# 别名类 key（实测 Mikan 无此字段，保留以增强健壮性/未来兼容）。
_ALIAS_KEYS = ("别名", "又名", "别称")
# 别名值的常见分隔符。
_ALIAS_SPLIT_PATTERN = re.compile(r"[、,，/／|｜]")


def _to_int(value) -> int:
    """安全转 int，失败返回 0。"""
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return 0


class MikanApi:
    """蜜柑计划轻客户端：季度番剧列表 + 详情页信息（bgm id / 放送年 / 名称）提取。"""

    def __init__(self, proxies: Optional[dict] = None) -> None:
        """``proxies`` 由调用方（``MikanRankProvider``）传入，本实例请求全程携带。"""
        self._proxies = proxies

    def _get(self, path: str) -> Optional[Tuple[str, str]]:
        """按主/备基址依次 GET ``path``，返回 ``(HTML 文本, 命中的基址)``。

        命中的基址随文本一并返回，供解析相对封面 URL 时拼对站点（走备用站也拼备用站）；
        全部基址失败返回 None。
        """
        last_err: Optional[Exception] = None
        for base in MIKAN_URLS:
            url = f"{base}{path}"
            try:
                ret = RequestUtils(ua=MIKAN_UA, timeout=_REQUEST_TIMEOUT,
                                   proxies=self._proxies).get_res(url)
            except Exception as err:  # noqa: BLE001 - 单个基址失败则尝试备用
                last_err = err
                continue
            if ret is not None and getattr(ret, "text", None):
                return ret.text, base
        if last_err is not None:
            logger.warn(f"Mikan 请求失败：{path}：{last_err}")
        return None

    def season(self, year, season_str: str) -> List[dict]:
        """GET 季度新番列表并解析，产出 ``[{mikan_id, title, cover, week}]``。"""
        path = (
            f"/Home/BangumiCoverFlowByDayOfWeek"
            f"?year={year}&seasonStr={quote(str(season_str))}"
        )
        ret = self._get(path)
        if not ret:
            return []
        html, base = ret
        return self._parse_season(html, base)

    def bangumi_detail(self, mikan_id: str) -> dict:
        """GET 详情页，一次解析 ``{bgm_id, year, air_date, original_title, aliases}``。

        详情页缺失（全部基址失败）返回 ``{}``；各字段解析不到为 None/``[]``。
        """
        ret = self._get(f"/Home/Bangumi/{mikan_id}")
        if not ret:
            return {}
        html, _base = ret
        return self._parse_detail(html)

    @staticmethod
    def _parse_season(html: str, base: str) -> List[dict]:
        """解析季度页 HTML：``div.sk-bangumi`` 内按星期分组的 ``li`` 番剧项。

        相对封面按实际命中的 ``base`` 拼绝对 URL（走备用站也拼备用站）。
        """
        soup = BeautifulSoup(html, "lxml")
        results: List[dict] = []
        seen: set = set()
        for group in soup.select("div.sk-bangumi"):
            row = group.select_one("div.row")
            week = row.get_text(strip=True) if row else str(group.get("data-dayofweek") or "")
            for li in group.select("li"):
                span = li.select_one("span[data-bangumiid]")
                if span is None:
                    continue
                mikan_id = str(span.get("data-bangumiid") or "").strip()
                if not mikan_id or mikan_id in seen:
                    continue
                anchor = li.select_one("a.an-text")
                title = ""
                if anchor is not None:
                    title = str(anchor.get("title") or anchor.get_text(strip=True) or "").strip()
                if not title:
                    continue
                seen.add(mikan_id)
                cover = str(span.get("data-src") or "").strip()
                if cover.startswith("/"):
                    cover = f"{base}{cover}"
                results.append(
                    {"mikan_id": mikan_id, "title": title, "cover": cover, "week": week}
                )
        return results

    @classmethod
    def _parse_detail(cls, html: str) -> dict:
        """解析详情页信息区，返回 ``{bgm_id, year, air_date, original_title, aliases}``。

        实测信息区为多个 ``p.bangumi-info``，每条 ``key：value``（全角冒号），逐条
        partition 成 ``more`` 字典（移植自 ``mikan.ts`` parseBangumi 的 more）：
        bgm id 在信息区文本内匹配（缺容器回退整页）；真实放送年从「放送开始」抽 4 位；
        原名/别名走可选 key（无则回退 ``p.bangumi-title`` / ``[]``）。全部字段可选。
        """
        soup = BeautifulSoup(html, "lxml")
        nodes = soup.select("p.bangumi-info") or soup.select(".bangumi-info")

        # 逐条 key：value（全角冒号）解析为字典。
        more: dict = {}
        for node in nodes:
            text = node.get_text(" ", strip=True)
            if "：" not in text:
                continue
            key, _sep, value = text.partition("：")
            key, value = key.strip(), value.strip()
            if key and value:
                more[key] = value

        # bgm/bangumi.tv subject id：优先 .bangumi-info 文本域，缺该容器时回退整页。
        if nodes:
            search_text = "\n".join(n.get_text(" ", strip=True) for n in nodes)
        else:
            search_text = html
        bgm_id: Optional[int] = None
        match = _BGM_ID_PATTERN.search(search_text)
        if match:
            bgm_id = _to_int(match.group(1)) or None

        air_date = more.get(_AIR_START_KEY) or None
        return {
            "bgm_id": bgm_id,
            "year": cls._extract_year(more, air_date),
            "air_date": air_date,
            "original_title": cls._extract_original_title(soup, more),
            "aliases": cls._extract_aliases(more),
        }

    @staticmethod
    def _extract_year(more: dict, air_date: Optional[str]) -> Optional[str]:
        """从「放送开始」等日期类值里抽 4 位真实放送年（1900-2100 合法域）。"""
        candidates: List[str] = []
        if air_date:
            candidates.append(air_date)
        for key, value in more.items():
            if value and any(hint in key for hint in _DATE_KEY_HINTS):
                candidates.append(value)
        for candidate in candidates:
            ym = _YEAR_PATTERN.search(candidate)
            if ym and 1900 <= int(ym.group(1)) <= 2100:
                return ym.group(1)
        return None

    @staticmethod
    def _extract_original_title(soup: BeautifulSoup, more: dict) -> Optional[str]:
        """原名：优先原名类 key，回退详情页 ``p.bangumi-title`` 全名；无则 None。"""
        for key in _ORIGINAL_TITLE_KEYS:
            value = more.get(key)
            if value:
                return value
        title_node = soup.select_one("p.bangumi-title")
        if title_node is not None:
            text = title_node.get_text(strip=True)
            if text:
                return text
        return None

    @staticmethod
    def _extract_aliases(more: dict) -> List[str]:
        """别名：取别名类 key 的值按常见分隔符切分；无则 ``[]``。"""
        for key in _ALIAS_KEYS:
            value = more.get(key)
            if value:
                return [a.strip() for a in _ALIAS_SPLIT_PATTERN.split(value) if a.strip()]
        return []


@register
class MikanRankProvider(RankProvider):
    """Mikan 季度新番来源：解析蜜柑季度番剧列表为标准化 ``RankMediaItem``。

    ``resolve_bangumi_id`` 为 True 时逐条抓详情，一次请求拿齐 bgm subject id +
    真实放送年 + 原名/别名：产出 ``bangumi_id`` 时 executor 走
    ``recognize_media(bangumiid=)`` 识别，抓不到 bgm id 时退化为 title+year 名称识别；
    真实放送年（解析到才）覆盖配置/当前年；``original_title``/``aliases`` 仅存
    ``source_meta``（executor 识别仍用主标题，未接入别名识别）。封面 ``cover`` 同时落到
    ``poster`` 与 ``source_meta``。番剧统一按 ``MediaType.TV`` 处理。
    """

    provider_id = "mikan"
    provider_name = "Mikan 季度新番"

    def get_spec(self) -> ProviderSpec:
        """返回本来源的元描述（选项与过滤器 schema）。"""
        season_options = [{"title": "当前季度（自动）", "value": SEASON_AUTO}] + [
            {"title": f"{s}季", "value": s} for s in MIKAN_SEASONS
        ]
        return ProviderSpec(
            provider_id=self.provider_id,
            provider_name=self.provider_name,
            # 季番每周更新，默认每周一早上抓一次。
            default_cron="0 10 * * 1",
            options_schema=[
                FieldSpec(key="year", label="年份(0=当前年)", kind="number", default=0),
                FieldSpec(
                    key="season",
                    label="季度",
                    kind="select",
                    default=SEASON_AUTO,
                    options=season_options,
                ),
                FieldSpec(
                    key="resolve_bangumi_id",
                    label="抓详情补 Bangumi ID/放送年(更准但更慢)",
                    kind="switch",
                    default=True,
                ),
                FieldSpec(key="proxy", label="使用代理访问", kind="switch", default=False),
            ],
            filters_schema=[
                FieldSpec(key="year", label="年份≥", kind="number", default=0),
            ],
        )

    def fetch(self, options: dict, context: ProviderContext) -> Iterator[RankMediaItem]:
        """抓取蜜柑季度番剧列表，逐条产出 ``RankMediaItem``。

        ``resolve_bangumi_id`` 为 True 时逐条抓详情补 bgm subject id + 真实放送年 +
        原名/别名，每条之间短暂 sleep 避免压站，并响应 ``context.event`` 退出信号；
        为 False 时不抓详情（年份用配置/当前年、无 bgm id）。单条失败 try/except
        continue，整源抓取失败向上抛出（由 runner 捕获）。
        """
        options = options or {}
        year = self._resolve_year(options.get("year"))
        season_str = self._resolve_season(options.get("season"))
        resolve_bgm = bool(options.get("resolve_bangumi_id", True))
        # 可选代理：开启则本次抓取的 HTTP 请求（季度列表 + 详情）走系统代理。
        proxies = settings.PROXY if bool(options.get("proxy")) else None

        api = MikanApi(proxies=proxies)
        entries = api.season(year, season_str)
        logger.info(
            f"{self.provider_name}：{year} 年 {season_str} 季 共 {len(entries)} 部番剧"
        )
        config_year = str(year)
        for entry in entries:
            # 响应退出信号。
            if context is not None and getattr(context, "event", None) is not None \
                    and context.event.is_set():
                break
            try:
                detail: dict = {}
                if resolve_bgm:
                    detail = self._safe_detail(api, entry)
                    sleep(_DETAIL_SLEEP)
                yield self._build_item(entry, config_year, detail)
            except Exception as err:  # noqa: BLE001 - 单条兜底，不影响其余番剧
                logger.error(f"{self.provider_name}：解析番剧条目失败：{err}")
                continue

    def _safe_detail(self, api: "MikanApi", entry: dict) -> dict:
        """抓详情补 bgm id + 放送年 + 名称，失败仅告警并返回 ``{}``（退化名称识别）。"""
        try:
            return api.bangumi_detail(entry["mikan_id"])
        except Exception as err:  # noqa: BLE001 - 单条详情失败不影响主流程
            logger.warn(
                f"{self.provider_name}：抓取详情失败"
                f"（{entry.get('title')}）：{err}"
            )
            return {}

    @staticmethod
    def _build_item(entry: dict, config_year: str, detail: dict) -> RankMediaItem:
        """把单部番剧 dict + 详情 dict 构造为 ``RankMediaItem``。

        真实放送年（``detail['year']``，解析到才）覆盖配置/当前年；封面同时落到
        ``poster`` 与 ``source_meta``；``original_title``/``aliases``/``air_date``
        存入 ``source_meta``（供历史展示/未来用，识别仍用主标题）。
        """
        detail = detail or {}
        cover = entry.get("cover")
        year = detail.get("year") or config_year
        return RankMediaItem(
            title=entry["title"],
            year=year,
            type_hint=MediaType.TV,
            bangumi_id=detail.get("bgm_id"),
            poster=cover,
            source_meta={
                "mikan_id": entry["mikan_id"],
                "week": entry.get("week"),
                "cover": cover,
                "original_title": detail.get("original_title"),
                "aliases": detail.get("aliases") or [],
                "air_date": detail.get("air_date"),
            },
            unique_seed=entry["mikan_id"],
        )

    @staticmethod
    def _resolve_year(raw) -> int:
        """解析年份：``0`` 或非法 -> 当前年。"""
        year = _to_int(raw)
        if year <= 0:
            return datetime.now().year
        return year

    @classmethod
    def _resolve_season(cls, raw) -> str:
        """解析季度：实测季名直用，``当前``/未知 -> 按当前月推导。"""
        value = str(raw or "").strip()
        if value in MIKAN_SEASONS:
            return value
        return cls._season_by_month(datetime.now().month)

    @staticmethod
    def _season_by_month(month: int) -> str:
        """按月份推导季度：1-3->冬，4-6->春，7-9->夏，10-12->秋。"""
        if month in (1, 2, 3):
            return "冬"
        if month in (4, 5, 6):
            return "春"
        if month in (7, 8, 9):
            return "夏"
        return "秋"
