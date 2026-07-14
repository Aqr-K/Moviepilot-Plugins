"""热门媒体来源：读取 MoviePilot 服务端订阅统计，产出标准化条目。

数据来源为 ``MoviePilotServerHelper.get_subscribe_statistic``（classmethod，无需实例化，
受 ``settings.SUBSCRIBE_STATISTIC_SHARE`` 门控，关闭时返回空）。
服务端统计仅区分 movie / tv 两类（动漫混在 tv 中，官方接口不单列），故本来源只暴露这两个 category。
"""
from __future__ import annotations

from typing import Iterator, List, Optional

from app.core.config import settings
from app.helper.server import MoviePilotServerHelper
from app.log import logger
from app.schemas.types import MediaType

from ..core.models import FieldSpec, ProviderSpec, RankMediaItem
from ..core.provider import ProviderContext, RankProvider
from ..core.registry import register

# category 展示标签（电影 / 剧集）。
CATEGORY_LABELS = {"movie": "电影", "tv": "剧集"}

# 各类型的 TMDB genre 字典（id -> 中文标签），标签取自官方 zh-CN 语言包 tmdb.genreType.*。
# 电影与电视剧的 genre 轴不同（官方前端亦分两套），故分别维护；`动画(16)` 两者皆有，
# 旧「动漫」伪分类由此收编为一项风格标签。
MOVIE_GENRES = {
    28: "动作", 12: "冒险", 16: "动画", 35: "喜剧", 80: "犯罪", 99: "纪录片",
    18: "剧情", 10751: "家庭", 14: "奇幻", 36: "历史", 27: "恐怖", 10402: "音乐",
    9648: "悬疑", 10749: "爱情", 878: "科幻", 10770: "电视电影", 53: "惊悚",
    10752: "战争", 37: "西部",
}
TV_GENRES = {
    10759: "动作冒险", 16: "动画", 35: "喜剧", 80: "犯罪", 99: "纪录片", 18: "剧情",
    10751: "家庭", 10762: "儿童", 9648: "悬疑", 10763: "新闻", 10764: "真人秀",
    10765: "科幻奇幻", 10766: "肥皂剧", 10767: "戏剧", 10768: "战争政治", 37: "西部",
}

# 各 category 对应的 genre 字典（构建风格选项与日志用）。
# 每类型的配置字段 key 统一为 ``{category}_{genres|page_cnt|min_rating}``。
_CATEGORY_GENRES = {"movie": MOVIE_GENRES, "tv": TV_GENRES}

# 默认获取条数。
_DEFAULT_PAGE_CNT = 30

# 服务端订阅统计接口 /subscribe/statistic 的 stype 参数用**中文**枚举（"电影"/"电视剧"），
# 传英文 "movie"/"tv" 服务端会直接返回空列表（实测：stype=movie→[]，stype=电影→有数据）。
# 与主程序 /subscribe/popular、官方前端一致；动漫混在电视剧中，本来源不单列。
_STYPE_CN = {"movie": "电影", "tv": "电视剧"}


def _genre_options(genres: dict) -> List[dict]:
    """把 genre 字典（id->中文）转成 multi-select 选项（value 为字符串 id）。"""
    return [{"title": label, "value": str(gid)} for gid, label in genres.items()]


@register
class PopularRankProvider(RankProvider):
    """热门媒体来源：将服务端统计项映射为标准化 ``RankMediaItem``。"""

    provider_id = "popular"
    provider_name = "热门媒体"

    def get_spec(self) -> ProviderSpec:
        """返回本来源的元描述（选项 schema）。

        电影 / 剧集拆成两大组，各自独立配置「订阅开关 / 风格 / 获取条数 / 评分下限 /
        订阅人次」，字段 key 统一为
        ``{category}_{enabled|genres|page_cnt|min_rating|popularity}``。
        订阅人次过滤在 provider 内按 ``source_meta['count']`` 本地完成，故无独立 filters_schema。
        """
        options_schema = []
        # 每个类型独立一组：订阅开关 / 风格 / 获取条数 / 评分下限 / 订阅人次。
        for cat in ("movie", "tv"):
            label = CATEGORY_LABELS[cat]
            options_schema += [
                FieldSpec(key=f"{cat}_enabled", label=f"{label}订阅", kind="switch", default=True),
                FieldSpec(key=f"{cat}_genres", label=f"{label}风格", kind="multi-select",
                          default=[], options=_genre_options(_CATEGORY_GENRES[cat]),
                          hint=f"留空=全部；仅开启{label}订阅时生效"),
                FieldSpec(key=f"{cat}_page_cnt", label=f"{label}获取条数", kind="number",
                          default=_DEFAULT_PAGE_CNT),
                FieldSpec(key=f"{cat}_min_rating", label=f"{label}评分下限(≥)", kind="float",
                          default=0, hint="0=不限；下推服务端按评分过滤"),
                FieldSpec(key=f"{cat}_popularity", label=f"{label}订阅人次(≥)", kind="number",
                          default=0, hint="0=不限；按统计订阅人次过滤"),
            ]
        return ProviderSpec(
            provider_id=self.provider_id,
            provider_name=self.provider_name,
            default_cron="5 1 * * *",
            options_schema=options_schema,
            filters_schema=[],
            notice="热门媒体依赖 MoviePilot 全局『订阅数据共享』：未开启时服务端订阅统计接口直接返回空、"
                   "本来源无法获取任何数据。请在下方『订阅数据共享』开关处开启（等同主程序设置，即时生效、无需重启）。",
        )

    def has_listening(self, options: dict) -> bool:
        """电影或剧集订阅任一开启，且主程序『订阅数据共享』已开（关闭则服务端无数据、等同无监听）。"""
        options = options or {}
        if not (self._enabled("movie", options) or self._enabled("tv", options)):
            return False
        return bool(settings.SUBSCRIBE_STATISTIC_SHARE)

    def fetch(self, options: dict, context: ProviderContext) -> Iterator[RankMediaItem]:
        """按类型开关拉取服务端统计并映射，逐条产出 ``RankMediaItem``。

        电影 / 剧集由 ``{category}_enabled`` 开关独立控制（缺省两类都开）；各自独立读取
        ``{category}_genres`` / ``{category}_page_cnt`` / ``{category}_min_rating`` /
        ``{category}_popularity``。单条映射失败内部 try/except continue；请求级异常向上抛出，由 runner 捕获。
        """
        options = options or {}
        # 热门媒体读取的是 MoviePilot 官方服务端订阅统计（MoviePilotServerHelper.get_subscribe_statistic），
        # 该接口受主程序「订阅数据共享」开关门控：关闭时服务端直接返回空列表、任何配置都取不到内容。
        # 提前显式检测并给出可操作的日志，避免误判为「插件坏了/配置错了」。
        if not settings.SUBSCRIBE_STATISTIC_SHARE:
            logger.warning(
                f"{self.provider_name}：未开启 MoviePilot「订阅数据共享」(SUBSCRIBE_STATISTIC_SHARE)，"
                f"服务端订阅统计接口将返回空、无法获取热门数据。请在 MoviePilot『设定 → 订阅』中开启"
                f"「订阅数据共享」（或设置环境变量 SUBSCRIBE_STATISTIC_SHARE=true）后重启生效。"
            )
            return
        for category in ("movie", "tv"):
            if not self._enabled(category, options):
                continue
            genre_ids = self._as_int_list(options.get(f"{category}_genres"))
            # 每类型独立获取条数 / 评分下限 / 订阅人次。
            page_cnt = self._to_int(options.get(f"{category}_page_cnt"), _DEFAULT_PAGE_CNT)
            # 0/非法评分视为不限（None -> helper 不带 min_rating 参数）。
            min_rating = self._to_float(options.get(f"{category}_min_rating")) or None
            popularity = self._to_int(options.get(f"{category}_popularity"), 0)
            yield from self._fetch_category(category, page_cnt, genre_ids, min_rating, popularity)

    def _fetch_category(self, category: str, page_cnt: int, genre_ids: List[int],
                        min_rating: Optional[float], popularity: int) -> Iterator[RankMediaItem]:
        """拉取单个类型（movie/tv）的统计数据并映射为条目。

        ``category`` 与服务端 ``stype`` 同名（movie/tv）直接透传。``genre_ids`` 为空则单次拉取全部
        （无过滤基线，与主程序『热门订阅』(/subscribe/popular) 参数一致，可命中同一份进程内共享缓存
        region=subscribe_share）；多选则逐 genre 分别请求，跨 genre 按 ``unique_seed`` 去重。

        **min_rating 不再透传服务端、改本地按 ``vote`` 过滤**：评分下限一旦进入服务端查询就会改变缓存
        key，与前端无过滤基线各自请求、且拿不到前端已填充的共享缓存、更易各自打空；``popularity`` 同样
        本地按订阅人次过滤。（genre 因统计项不含风格信息只能走服务端查询，配置了风格却为空时见 _log_empty。）
        """
        seen = set()
        for gid in (genre_ids or [None]):
            # 无评分过滤基线请求（min_rating=None）：与主程序前端『热门订阅』参数一致以命中共享缓存。
            # stype 必须传中文（"电影"/"电视剧"），传英文服务端返回空。
            subs = MoviePilotServerHelper.get_subscribe_statistic(
                stype=_STYPE_CN.get(category, category), page=1, count=page_cnt,
                genre_id=gid, min_rating=None) or []
            if subs:
                logger.info(f"{self.provider_name}：{self._cat_log(category, gid)} 获取 {len(subs)} 条统计")
            else:
                self._log_empty(category, gid)
            for sub in subs:
                try:
                    media_item = self._build_item(sub, category, gid)
                except Exception as err:  # noqa: BLE001 - 单条兜底
                    logger.error(f"{self.provider_name}：映射统计项失败：{err}")
                    continue
                if media_item is None or media_item.unique_seed in seen:
                    continue
                # 评分下限本地过滤（统计项 vote 即评分；服务端过滤会改变缓存 key 故改本地）。
                if min_rating is not None and self._to_float(media_item.source_meta.get("vote")) < min_rating:
                    continue
                # 订阅人次过滤（服务端不支持 min_sub，按统计 count 本地判定）。
                if popularity > 0 and self._to_int(media_item.source_meta.get("count"), 0) < popularity:
                    continue
                seen.add(media_item.unique_seed)
                yield media_item

    def _log_empty(self, category: str, gid: Optional[int]) -> None:
        """空结果诊断：helper 的 _handle_list_response 把『连不上/非200』与『200 空数据』都压平成 []，
        这里直接发一次原始请求读 status_code 以区分，给出可操作日志。任何异常都退回通用提示、不影响抓取。"""
        detail = "服务端返回空"
        try:
            params = MoviePilotServerHelper._build_subscribe_query_params(
                page=1, count=1, stype=_STYPE_CN.get(category, category), genre_id=gid)
            res = MoviePilotServerHelper.subscribe_statistic(params)
            code = getattr(res, "status_code", None)
            if code == 200:
                detail = ("服务端返回 200 但无数据（该账号/过滤条件当前无共享统计；"
                          "若配置了『风格』筛选，可清空改用全部再试）")
            elif code is None:
                detail = "与 MoviePilot 官方服务器通信失败（连不上/超时，请检查网络与代理）"
            else:
                detail = f"服务端返回 HTTP {code}（可能被限流或服务异常）"
        except Exception:  # noqa: BLE001 - 诊断失败不影响主流程
            detail = "服务端返回空（无法进一步诊断）"
        logger.warning(
            f"{self.provider_name}：{self._cat_log(category, gid)} 获取 0 条统计——{detail}"
            f"（MP_SERVER_HOST={settings.MP_SERVER_HOST}）。"
        )

    def _build_item(self, sub: dict, category: str,
                    genre_id: Optional[int] = None) -> Optional[RankMediaItem]:
        """将单条统计 dict 映射为 ``RankMediaItem``，类型无法识别则跳过。"""
        mtype = self._map_media_type(sub.get("type"))
        if mtype is None:
            return None
        source_meta = {
            "count": sub.get("count"),
            "vote": sub.get("vote"),
            "category": category,
        }
        if genre_id is not None:
            source_meta["genre_id"] = genre_id
        name = sub.get("name")
        return RankMediaItem(
            title=str(name) if name is not None else "",
            year=self._to_str(sub.get("year")),
            type_hint=mtype,
            tmdb_id=self._to_optional_int(sub.get("tmdbid")),
            douban_id=self._to_str(sub.get("doubanid")),
            bangumi_id=self._to_optional_int(sub.get("bangumiid")),
            tvdb_id=self._to_optional_int(sub.get("tvdbid")),
            imdb_id=self._to_str(sub.get("imdbid")),
            season=self._to_optional_int(sub.get("season")),
            poster=sub.get("poster"),
            source_meta=source_meta,
            unique_seed=f"{name}:{sub.get('tmdbid')}",
        )

    @staticmethod
    def _map_media_type(raw) -> Optional[MediaType]:
        """把统计项 type 映射为 MediaType（兼容英文与中文），未知返回 None。"""
        value = str(raw or "").strip().lower()
        if value in ("movie", MediaType.MOVIE.value):
            return MediaType.MOVIE
        if value in ("tv", MediaType.TV.value):
            return MediaType.TV
        return None

    @staticmethod
    def _to_optional_int(value) -> Optional[int]:
        """安全转 int，空/非法返回 None。"""
        if value in (None, ""):
            return None
        try:
            return int(float(value))
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _to_str(value) -> Optional[str]:
        """空值返回 None，其余强转 str。"""
        if value in (None, ""):
            return None
        return str(value)

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

    @staticmethod
    def _to_float(value) -> float:
        """安全转 float，空/非法返回 0.0。"""
        try:
            return float(value)
        except (ValueError, TypeError):
            return 0.0

    @staticmethod
    def _as_int_list(value) -> List[int]:
        """把多选 genre 值统一成 int 列表（兼容字符串/逗号分隔），非法项丢弃。"""
        ints: List[int] = []
        for v in PopularRankProvider._as_list(value):
            try:
                ints.append(int(float(v)))
            except (ValueError, TypeError):
                continue
        return ints

    @staticmethod
    def _enabled(category: str, options: dict) -> bool:
        """判断某类型是否开启订阅：读 ``{category}_enabled`` 开关，缺省默认开启。"""
        key = f"{category}_enabled"
        if key in options:
            return bool(options.get(key))
        return True

    @staticmethod
    def _cat_log(category: str, genre_id: Optional[int]) -> str:
        """日志用类型标签，带上 genre 中文名（若有）。"""
        label = CATEGORY_LABELS.get(category, category)
        if genre_id is None:
            return label
        gname = _CATEGORY_GENRES.get(category, {}).get(genre_id, genre_id)
        return f"{label}·{gname}"
