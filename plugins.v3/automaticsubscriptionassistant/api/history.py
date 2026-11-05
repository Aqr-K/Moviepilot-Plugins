"""history HTTP 端点；使用入口提供的服务，不直接拥有数据库连接。"""

from typing import Any

from app.schemas.types import MediaType
from app.sdk.config import settings
from app.sdk.logging import logger

from ..core.config import ProviderConfig
from ..core.executor import SubscribeExecutor
from ..core.filters import build_filter_chain
from ..core.provider import ProviderContext
from ..core.registry import registry
from ..core.supplement import HistorySupplementService
from ..schemas import RankMediaItem


class HistoryApiMixin:
    def api_history(
        self,
        provider: str | None = None,
        status: str | None = None,
        mtype: str | None = None,
        keyword: str | None = None,
        year_min: str | None = None,
        year_max: str | None = None,
        page: int = 1,
        count: int = 50,
    ) -> dict[str, Any]:
        """按来源/状态/媒体类型/关键词/发行年份范围过滤并分页查询历史记录（按时间倒序）。

        provider/status/mtype 支持逗号分隔多值；单值向后兼容。year_min/year_max 为发行年份闭区间。
        """
        store = self._history_store()
        records, total = store.query(
            provider=provider,
            status=status,
            mtype=mtype,
            keyword=keyword,
            year_min=year_min,
            year_max=year_max,
            page=page,
            count=count,
        )
        return {"list": records, "total": total, "page": page, "count": len(records)}

    def api_history_uniques(
        self,
        provider: str | None = None,
        status: str | None = None,
        mtype: str | None = None,
        keyword: str | None = None,
        year_min: str | None = None,
        year_max: str | None = None,
    ) -> dict[str, Any]:
        """按同一套筛选条件返回全部历史的身份键，供前端「选全部」一次取齐。

        只回身份键、不回整行记录：全选要的就是键集合，拉整行既浪费带宽又会被单页上限截断。
        """
        uniques = self._history_store().uniques(
            provider=provider,
            status=status,
            mtype=mtype,
            keyword=keyword,
            year_min=year_min,
            year_max=year_max,
        )
        return {"uniques": uniques, "total": len(uniques)}

    def api_delete_history(self, unique: str, apikey: str) -> dict[str, Any]:
        """删除一条历史（apikey 鉴权，供后端/脚本调用）。"""
        if apikey != settings.API_TOKEN:
            return {"code": 1, "message": "API密钥错误"}
        return self._delete_history(unique)

    def api_delete_history_post(self, request: dict | None = None) -> dict[str, Any]:
        """删除一条历史（bear 鉴权，前端调用，body={"unique": ...}）。"""
        unique = (request or {}).get("unique") if isinstance(request, dict) else None
        if not unique:
            return {"code": 1, "message": "缺少 unique"}
        return self._delete_history(unique)

    def _delete_history(self, unique: str) -> dict[str, Any]:
        """删除历史的共用实现。"""
        store = self._history_store()
        removed = store.delete(unique)
        if removed:
            return {"code": 0, "message": "删除成功"}
        return {"code": 1, "message": "未找到该记录"}

    def api_history_batch_delete(self, request: dict | None = None) -> dict[str, Any]:
        """批量删除历史（bear 鉴权，body={"uniques":[...]}）。"""
        uniques = (request or {}).get("uniques") if isinstance(request, dict) else None
        if not isinstance(uniques, list) or not uniques:
            return {"code": 1, "message": "缺少 uniques 列表"}
        store = self._history_store()
        removed = store.delete_many(uniques)
        return {"code": 0, "message": f"已删除 {removed} 条", "removed": removed}

    def api_history_recognize(self, request: dict | None = None) -> dict[str, Any]:
        """重新识别一条历史记录（供『异常/未识别』项手动再跑一次识别 + 订阅）。

        从历史记录还原候选（RankMediaItem），复用订阅落地管线单条处理：识别成功则订阅
        并以新身份键记录，仍失败则记为新的异常。body={"unique": ...}。同步执行，返回最新状态。
        """
        if not self._database_ready:
            return {"code": 1, "message": "数据库未就绪，无法创建订阅"}
        unique = (request or {}).get("unique") if isinstance(request, dict) else None
        if not unique:
            return {"code": 1, "message": "缺少 unique"}
        store = self._history_store()
        rec = store.get(unique)
        if rec is None:
            return {"code": 1, "message": "未找到该记录"}
        provider = registry.get(rec.get("provider"))
        if provider is None:
            return {"code": 1, "message": f"来源不可用: {rec.get('provider')}"}
        try:
            spec = provider.get_spec()
            pconf = ProviderConfig(
                self._settings.provider_raw(provider.provider_id), spec
            )
            # 还原候选：类型中文串 → MediaType 枚举；优先恢复 v3 通用身份，旧 ID
            # 字段同时保留，供旧历史与兼容识别链使用。
            type_val = rec.get("type")
            try:
                type_hint = MediaType(type_val) if type_val else None
            except ValueError:
                type_hint = None
            item = RankMediaItem(
                title=rec.get("title") or "",
                music_type=rec.get("music_type"), artists=list(rec.get("artists") or []), album=rec.get("album"),
                year=rec.get("year"),
                type_hint=type_hint,
                douban_id=rec.get("doubanid"),
                tmdb_id=rec.get("tmdbid"),
                bangumi_id=rec.get("bangumiid"),
                season=rec.get("season"),
                poster=rec.get("poster"),
                media_source=rec.get("media_source"),
                media_id=rec.get("media_id"),
                episode_group=rec.get("episode_group"),
            )
            if isinstance(rec.get("source_item"), dict):
                item = RankMediaItem.from_dict(rec["source_item"])
                if item.season is None and rec.get("season") is not None:
                    item.season = rec["season"]
            context = ProviderContext(
                chain=self.chain,
                downloadchain=self._downloadchain,
                subscribechain=self._subscribechain,
                logger=logger,
                event=self._event,
                proxy=bool(pconf.option("proxy")),
                get_data=self.get_data,
                save_data=self.save_data,
                blacklist=self.blacklist_store(),
            )
            # 先处理再移除旧键；存储或识别异常时仍保留原候选供重试。
            filter_chain = build_filter_chain([f.key for f in spec.filters_schema])
            executor = SubscribeExecutor(
                context, self._settings.global_config, self._build_subscribed_index()
            )
            outcome = executor.process(
                item, provider, filter_chain, store, pconf.filters
            )
            store.flush()
            new_season = getattr(outcome.mediainfo, "season", None)
            new_unique = executor._identity(outcome.item, outcome.mediainfo, new_season)
            if new_unique != unique and store.get(new_unique) is not None:
                store.delete(unique)
        except Exception as exc:  # noqa: BLE001 - 端点兜底，不影响插件本体
            logger.error(f"{self.plugin_name}：重新识别失败: {exc}")
            return {"code": 1, "message": f"重新识别失败: {exc}"}
        return {
            "code": 0,
            "status": outcome.status.value,
            "reason": getattr(outcome, "reason", None),
            "message": "重新识别完成",
        }

    def api_history_supplement(self, request: dict | None = None) -> dict[str, Any]:
        """从历史补充媒体定义和订阅参数，重新识别并尝试新增。"""
        if not self._database_ready:
            return {"code": 1, "message": "数据库未就绪，无法创建订阅"}
        try:
            context = ProviderContext(
                chain=self.chain,
                downloadchain=self._downloadchain,
                subscribechain=self._subscribechain,
                logger=logger,
                event=self._event,
                get_data=self.get_data,
                save_data=self.save_data,
                blacklist=self.blacklist_store(),
            )
            return HistorySupplementService(
                context, self._settings.global_config, self._history_store()
            ).submit(request)
        except ValueError as exc:
            return {"code": 1, "message": str(exc)}
        except Exception as exc:  # noqa: BLE001 - 不影响自动来源任务
            logger.error(f"{self.plugin_name}：补充编辑订阅失败: {exc}")
            return {"code": 1, "message": "创建订阅失败，请查看日志后重试"}
