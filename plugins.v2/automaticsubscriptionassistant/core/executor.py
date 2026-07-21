"""统一订阅落地管线。

对单条 RankMediaItem 严格按序执行：预去重 -> 已处理短路 -> pre 过滤 -> 识别 ->
post 过滤 -> 媒体库查重 -> 订阅查重 -> 加订阅 -> 记历史。每步命中即短路并落历史。

预去重（``SubscribedIndex``）是叠加在 ``subscribechain.exists()`` 之上的**快速路径**：
仅当强标识命中已订阅/本轮已处理集合时才跳过识别；未命中仍照常识别 + exists() 兜底。
最坏情况只是「多识别了一条」，绝不会错订/重订/漏订。

整条处理包在 try/except，异常返回 ERROR 并记历史（非正向终态、可被后续重试）。
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from app.core.metainfo import MetaInfo
from app.log import logger
from app.schemas.types import MediaType

from .dedup import SubscribedIndex
from .models import HistoryRecord, RankMediaItem, SubscribeOutcome, SubscribeStatus, media_identity

if TYPE_CHECKING:
    from app.core.context import MediaInfo

    from .config import GlobalConfig
    from .filters import FilterChain
    from .history import HistoryStore
    from .provider import ProviderContext, RankProvider

# 历史时间格式。
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


class SubscribeExecutor:
    """把标准化条目统一落地为订阅，并沉淀历史。"""

    def __init__(self, context: "ProviderContext", global_config: "GlobalConfig",
                 subscribed_index: Optional[SubscribedIndex] = None):
        self.ctx = context
        self.gcfg = global_config
        # 已订阅强标识索引（跨渠道 + 与已订阅去重的快速路径）。缺省空索引 → 无快速路径、向后兼容。
        self.index = subscribed_index if subscribed_index is not None else SubscribedIndex()

    def process(self, item: RankMediaItem, provider: "RankProvider",
                filter_chain: "FilterChain", history: "HistoryStore",
                filters_config: dict) -> SubscribeOutcome:
        """处理单条条目，返回落地结果。异常统一转为 ERROR 结果并记历史。"""
        try:
            return self._process(item, provider, filter_chain, history, filters_config)
        except Exception as exc:  # noqa: BLE001 - 单条兜底，不应影响整源
            reason = str(exc)
            self._record(history, item.identity(), provider, item, None, None,
                         SubscribeStatus.ERROR, reason)
            return SubscribeOutcome(SubscribeStatus.ERROR, item, reason=reason)

    def _process(self, item, provider, filter_chain, history, filters_config) -> SubscribeOutcome:
        identity = item.identity()

        # 1. 预去重快速路径：强标识命中「已订阅 / 本轮已处理」→ 跳过识别。
        if self.index.contains(item):
            canonical = self.index.identity_for(item) or identity
            # 同一命中方式只记一条（身份键合并），避免记录膨胀。
            if not history.is_handled(canonical):
                self._record(history, canonical, provider, item, None, None,
                             SubscribeStatus.SUBSCRIPTION_EXISTS, "已订阅（预去重，跳过识别）")
                history.mark_handled(canonical)
            return SubscribeOutcome(SubscribeStatus.SUBSCRIPTION_EXISTS, item,
                                    reason="已订阅（预去重，跳过识别）")

        # 2. 已处理短路（本插件历史中的正向终态）：不识别、不记新历史。
        if history.is_handled(identity):
            return SubscribeOutcome(SubscribeStatus.ALREADY_HANDLED, item)

        # 3. pre 过滤（识别前）。被过滤者记录但不标记已处理 → 可被其他渠道/下一轮重试。
        verdict = filter_chain.run("pre", item, None, filters_config)
        if not verdict.accepted:
            self._record(history, identity, provider, item, None, None,
                         SubscribeStatus.FILTERED, verdict.reason)
            return SubscribeOutcome(SubscribeStatus.FILTERED, item, reason=verdict.reason)

        # 4. 识别。
        meta = MetaInfo(item.title)
        if item.year:
            meta.year = item.year
        if item.type_hint:
            meta.type = item.type_hint
        if item.season is not None:
            meta.begin_season = item.season
        mediainfo = self._recognize(item, meta)
        if mediainfo is None:
            self._record(history, identity, provider, item, None, None,
                         SubscribeStatus.UNRECOGNIZED, "未识别到媒体信息")
            return SubscribeOutcome(SubscribeStatus.UNRECOGNIZED, item, reason="未识别到媒体信息")

        # 识别成功后，用识别结果计算规范身份与订阅季（供记录合并与索引登记）。
        is_tv = mediainfo.type == MediaType.TV
        sub_season = item.season if item.season is not None else mediainfo.season
        rid = self._identity(item, mediainfo, sub_season if is_tv else None)
        logger.debug(
            f"[{provider.provider_id}] 原始 名称={item.title!r} 年份={item.year or '-'} "
            f"tmdb={item.tmdb_id or '-'} douban={item.douban_id or '-'} "
            f"bangumi={item.bangumi_id or '-'} 季={item.season if item.season is not None else '-'}"
            f" → 订阅 名称={mediainfo.title!r} 年份={mediainfo.year or '-'} "
            f"tmdb={mediainfo.tmdb_id or '-'} 季={sub_season if is_tv else '-'}"
        )

        # 5. post 过滤（识别后）。同样记录但不标记已处理。
        verdict = filter_chain.run("post", item, mediainfo, filters_config)
        if not verdict.accepted:
            self._record(history, rid, provider, item, mediainfo, None,
                         SubscribeStatus.FILTERED, verdict.reason)
            return SubscribeOutcome(SubscribeStatus.FILTERED, item, mediainfo=mediainfo, reason=verdict.reason)

        # 6. 媒体库查重：get_no_exists_info 返回 True 表示已完整存在，应跳过。
        exist_flag, _ = self.ctx.downloadchain.get_no_exists_info(meta=meta, mediainfo=mediainfo)
        if exist_flag:
            self._record(history, rid, provider, item, mediainfo, None,
                         SubscribeStatus.MEDIA_EXISTS, "媒体库已存在")
            self._mark_done(history, rid, mediainfo, sub_season if is_tv else None)
            return SubscribeOutcome(SubscribeStatus.MEDIA_EXISTS, item, mediainfo=mediainfo, reason="媒体库已存在")

        # 7. 订阅查重（保留：预去重只是快速路径，此处仍是最终安全网）。
        if self.ctx.subscribechain.exists(mediainfo=mediainfo, meta=meta):
            self._record(history, rid, provider, item, mediainfo, None,
                         SubscribeStatus.SUBSCRIPTION_EXISTS, "订阅已存在")
            self._mark_done(history, rid, mediainfo, sub_season if is_tv else None)
            return SubscribeOutcome(SubscribeStatus.SUBSCRIPTION_EXISTS, item, mediainfo=mediainfo, reason="订阅已存在")

        # 8. 加订阅。
        sid, err = self.ctx.subscribechain.add(
            title=mediainfo.title,
            year=mediainfo.year,
            mtype=mediainfo.type,
            tmdbid=mediainfo.tmdb_id,
            doubanid=mediainfo.douban_id,
            season=sub_season if is_tv else None,
            exist_ok=self.gcfg.exist_ok,
            username=self.gcfg.username,
        )
        if sid:
            self._record(history, rid, provider, item, mediainfo, sub_season,
                         SubscribeStatus.SUBSCRIBED, None, subscribe_id=sid)
            self._mark_done(history, rid, mediainfo, sub_season if is_tv else None)
            return SubscribeOutcome(SubscribeStatus.SUBSCRIBED, item, mediainfo=mediainfo,
                                    subscribe_id=sid, message=err)
        self._record(history, rid, provider, item, mediainfo, sub_season, SubscribeStatus.ERROR, err)
        return SubscribeOutcome(SubscribeStatus.ERROR, item, mediainfo=mediainfo, reason=err)

    def _mark_done(self, history, identity, mediainfo, season) -> None:
        """正向终态收尾：标记已处理并登记进已订阅索引，供本轮后续渠道跳过。"""
        history.mark_handled(identity)
        self.index.add_media(
            tmdbid=mediainfo.tmdb_id,
            doubanid=mediainfo.douban_id,
            bangumiid=getattr(mediainfo, "bangumi_id", None),
            mtype=mediainfo.type,
            season=season,
            title=mediainfo.title,
            year=mediainfo.year,
        )

    @staticmethod
    def _identity(item: RankMediaItem, mediainfo: Optional["MediaInfo"], season) -> str:
        """规范媒体身份键：识别成功用识别结果，否则回退条目自带标识。"""
        if mediainfo is not None:
            is_tv = mediainfo.type == MediaType.TV if mediainfo.type else False
            return media_identity(
                tmdb_id=mediainfo.tmdb_id, douban_id=mediainfo.douban_id,
                bangumi_id=getattr(mediainfo, "bangumi_id", None),
                is_tv=is_tv, season=season, title=mediainfo.title, year=mediainfo.year)
        return item.identity()

    def _recognize(self, item: RankMediaItem, meta) -> Optional["MediaInfo"]:
        """按 ID 优先级识别媒体：tmdb > douban > bangumi > 纯标题。"""
        if item.tmdb_id:
            return self.ctx.chain.recognize_media(meta=meta, tmdbid=item.tmdb_id, mtype=item.type_hint)
        if item.douban_id:
            return self.ctx.chain.recognize_media(meta=meta, doubanid=item.douban_id)
        if item.bangumi_id:
            return self.ctx.chain.recognize_media(meta=meta, bangumiid=item.bangumi_id)
        return self.ctx.chain.recognize_media(meta=meta)

    def _record(self, history, unique, provider, item, mediainfo, season,
                status: SubscribeStatus, reason, subscribe_id=None) -> None:
        """构造并写入一条历史记录（unique 为媒体身份键，跨渠道合并展示）。"""
        if season is None:
            season = item.season
        record = HistoryRecord(
            unique=unique,
            provider=provider.provider_id,
            title=mediainfo.title if mediainfo else item.title,
            year=mediainfo.year if mediainfo else item.year,
            # 类型标注：优先用识别结果，未识别则回退来源自带的 type_hint（榜单已知电影/剧集），
            # 确保每条历史都带类型、可按电影/剧集筛选。
            type=((mediainfo.type.value if mediainfo and mediainfo.type else None)
                  or (item.type_hint.value if item and item.type_hint else "")),
            tmdbid=mediainfo.tmdb_id if mediainfo else item.tmdb_id,
            doubanid=mediainfo.douban_id if mediainfo else item.douban_id,
            # 增存 bangumi id：供「重新识别」无损重建 mikan/番剧候选（识别链按 bangumiid 命中）。
            bangumiid=(getattr(mediainfo, "bangumi_id", None) if mediainfo else item.bangumi_id),
            poster=(mediainfo.get_poster_image() if mediainfo else item.poster),
            season=season,
            status=status.value,
            reason=reason,
            time=datetime.now().strftime(TIME_FORMAT),
        )
        history.record(record)
