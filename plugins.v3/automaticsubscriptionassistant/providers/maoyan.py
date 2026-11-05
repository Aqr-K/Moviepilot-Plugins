"""猫眼榜单来源：解析猫眼票房/网播热度 JSON，产出标准化条目。

数据来源为猫眼专业版（piaofang.maoyan.com）端点：
- 电影票房：``/dashboard-ajax/movie``（全网，无平台维度）。
- 网播热度：``/dashboard/webHeatData?seriesType=X&platformType=Y&showDate=2``
  —— seriesType: 电视剧=0 / 网络剧=1 / 综艺=2 / 电视剧+网络剧(合并剧集)=4；
     platformType: 全网="" / 腾讯视频=3 / 爱奇艺=2 / 优酷=1 / 乐视=4 / 芒果TV=7 / PPTV=6 / 搜狐=5。


配置通过统一榜单规则弹窗逐条选择票房榜，或网播平台与类型。
"""

from __future__ import annotations

import random
import re
from datetime import date, timedelta
from typing import Iterator, List, Optional

from app.schemas.types import MediaType
from app.sdk.browser import launch_browser_context
from app.sdk.config import settings
from app.sdk.logging import logger
from app.sdk.network import RequestUtils

from ..core.provider import ProviderContext
from ..core.registry import register
from ..core.rules import RuleRankProvider
from ..schemas import FieldSpec, ProviderSpec, RankMediaItem

# 猫眼专业版根地址。
MAOYAN_URL = "https://piaofang.maoyan.com"

# 网播热度媒体类型（webHeatData 的 seriesType）：
# series=电视剧+网络剧(合并剧集)，tv=电视剧，web=网络剧，variety=综艺。
SERIES_TYPE = {"series": "4", "tv": "0", "web": "1", "variety": "2"}
# 平台：选项值 -> platformType 参数（全网为空串）。
PLATFORM_TYPE = {
    "all": "",
    "tx": "3",
    "iqiyi": "2",
    "mgtv": "7",
    "youku": "1",
    "sohu": "5",
    "letv": "4",
    "pptv": "6",
}
# 平台选项标签。
PLATFORM_LABELS = {
    "all": "全网",
    "tx": "腾讯视频",
    "iqiyi": "爱奇艺",
    "youku": "优酷",
    "letv": "乐视",
    "mgtv": "芒果TV",
    "pptv": "PPTV",
    "sohu": "搜狐",
}
# 网播类型的显示名称。
MEDIA_LABELS = {
    "series": "电视剧+网络剧",
    "tv": "电视剧",
    "web": "网络剧",
    "variety": "综艺",
}
MEDIA_ORDER = ("series", "tv", "web", "variety")
# 随机 User-Agent 池，降低被风控概率。
_USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Edg/121.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Edg/121.0.0.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
]

@register
class MaoyanRankProvider(RuleRankProvider):
    """猫眼榜单来源：统一规则弹窗中的电影票房或网播热度。"""

    provider_id = "maoyan"
    provider_name = "猫眼榜单"

    def _source_spec(self) -> ProviderSpec:
        return ProviderSpec(
            self.provider_id,
            self.provider_name,
            "0 9 * * *",
            options_schema=[
                FieldSpec("proxy", "使用代理访问", "switch", default=False)
            ],
            notice="网络电影因数据源已停更，暂不支持。",
        )

    def _fetch_options(
        self, options: dict, context: ProviderContext
    ) -> Iterator[RankMediaItem]:
        self._proxies = settings.PROXY if bool(options.get("proxy")) else None
        cookies = self._get_cookies()
        headers = {"User-Agent": random.choice(_USER_AGENTS)}
        seen = set()
        if context is not None and context.event is not None and context.event.is_set():
            return
        if options["chart"] == "movie-box":
            yield from self._fetch_movie_box(cookies, headers, options["limit"], seen)
        else:
            yield from self._fetch_web_heat_one(
                SERIES_TYPE[options["media"]],
                PLATFORM_TYPE[options["platform"]],
                cookies,
                headers,
                options["limit"],
                seen,
            )

    def _fetch_movie_box(
        self, cookies: dict, headers: dict, num: int, seen: set
    ) -> Iterator[RankMediaItem]:
        """电影票房榜：/dashboard-ajax/movie。"""
        url = f"{MAOYAN_URL}/dashboard-ajax/movie"
        payload = self._request_json(url, cookies, headers)
        data = ((payload or {}).get("movieList") or {}).get("list") or []
        for entry in data[:num]:
            try:
                info = entry.get("movieInfo") or {}
                yield from self._emit(
                    info.get("movieName"),
                    info.get("releaseInfo"),
                    None,
                    MediaType.MOVIE,
                    seen,
                )
            except Exception as err:  # noqa: BLE001 - 单条兜底
                logger.error(f"{self.provider_name}：解析电影票房条目失败：{err}")
                continue

    def _fetch_web_heat_one(
        self,
        series_type: str,
        platform_type: str,
        cookies: dict,
        headers: dict,
        num: int,
        seen: set,
    ) -> Iterator[RankMediaItem]:
        """网播热度单榜：/dashboard/webHeatData（单一 seriesType × platformType）。"""
        url = (
            f"{MAOYAN_URL}/dashboard/webHeatData"
            f"?seriesType={series_type}&platformType={platform_type}&showDate=2"
        )
        payload = self._request_json(url, cookies, headers)
        data = ((payload or {}).get("dataList") or {}).get("list") or []
        for entry in data[:num]:
            try:
                info = entry.get("seriesInfo") or {}
                yield from self._emit(
                    info.get("name"),
                    info.get("releaseInfo"),
                    info.get("platformDesc"),
                    MediaType.TV,
                    seen,
                )
            except Exception as err:  # noqa: BLE001 - 单条兜底
                logger.error(f"{self.provider_name}：解析网播热度条目失败：{err}")
                continue

    def _emit(
        self, title, release_info, platform_desc, mtype: MediaType, seen: set
    ) -> Iterator[RankMediaItem]:
        """构造并产出单条：空标题或本次已见（按 类型_标题）则跳过。"""
        if not title:
            return
        dedup = f"{mtype.value}_{title}"
        if dedup in seen:
            return
        seen.add(dedup)
        yield self._build_item(title, release_info, platform_desc, mtype)

    def _build_item(
        self, title, release_info, platform_desc, mtype: MediaType
    ) -> RankMediaItem:
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
        """解析上映日期或明确的相对天数；未知格式不猜年份。"""
        value = str(release_info or "").strip()
        if not value:
            return None
        absolute = re.search(
            r"(19\d{2}|20\d{2})[-年/.](\d{1,2})[-月/.](\d{1,2})", value
        )
        if absolute:
            try:
                return str(date(*(int(part) for part in absolute.groups())).year)
            except ValueError:
                return None
        offsets = {
            "今天上映": 0,
            "今日上映": 0,
            "昨天上映": -1,
            "昨日上映": -1,
            "明天上映": 1,
            "明日上映": 1,
        }
        offset = offsets.get(value)
        if offset is None:
            past = re.fullmatch(
                r"(?:已上映|上映|已播出|播出|开播|点映)\s*(\d+)\s*天", value
            )
            future = re.fullmatch(r"(\d+)\s*天后(?:上映|开播|播出)?", value)
            until = re.fullmatch(
                r"(?:距|距离)(?:上映|开播|播出)(?:还有)?\s*(\d+)\s*天", value
            )
            if past:
                offset = -int(past.group(1))
            elif future or until:
                offset = int((future or until).group(1))
            else:
                return None
        try:
            return str((date.today() + timedelta(days=offset)).year)
        except (OverflowError, ValueError):
            return None

    def _request_json(self, url: str, cookies: dict, headers: dict) -> Optional[dict]:
        """发起请求并解析 JSON；无响应返回 None，请求/解析异常向上抛。"""
        proxies = getattr(self, "_proxies", None)
        if cookies:
            response = RequestUtils(proxies=proxies).get_res(
                url, cookies=cookies, headers=headers
            )
        else:
            response = RequestUtils(proxies=proxies).get_res(url, headers=headers)
        if not response:
            logger.warn(f"{self.provider_name}：请求无响应，跳过：{url}")
            return None
        return response.json()

    @staticmethod
    def _get_cookies() -> dict:
        """
        通过官方浏览器 SDK 获取猫眼 Cookie，结束后释放上下文及页面。

        :return: 浏览器 Cookie；启动、导航或读取失败时返回空字典
        """
        context = None
        try:
            context = launch_browser_context(
                headless=True,
                humanize=settings.CLOAKBROWSER_HUMANIZE,
                human_preset=settings.CLOAKBROWSER_HUMAN_PRESET,
            )
            page = context.new_page()
            page.goto(MAOYAN_URL, wait_until="domcontentloaded", timeout=60_000)
            try:
                page.wait_for_load_state("networkidle", timeout=15_000)
            except Exception:  # noqa: BLE001 - 长连接不应阻止读取已经取得的 Cookie
                pass
            return {cookie["name"]: cookie["value"] for cookie in context.cookies()}
        except Exception as err:  # noqa: BLE001 - 浏览器不可用时降级
            logger.warn(
                f"{MaoyanRankProvider.provider_name}：获取 Cookie 失败，降级无 Cookie 请求：{err}"
            )
            return {}
        finally:
            if context is not None:
                try:
                    context.close()
                except Exception as err:  # noqa: BLE001 - 清理失败不覆盖已经取得的 Cookie
                    logger.warning(
                        f"{MaoyanRankProvider.provider_name}：关闭浏览器上下文失败：{err}"
                    )

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
