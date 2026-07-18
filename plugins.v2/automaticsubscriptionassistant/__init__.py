"""自动订阅助手插件入口。

聚合豆瓣榜单 / 猫眼榜单 / 热门媒体等多来源，抓取榜单后按用户配置的过滤器
组合筛选，统一走 MoviePilot 订阅落地管线自动订阅。

本文件仅负责与 MoviePilot 插件框架对接（元数据、配置装载、定时服务注册、
API 端点），真正的抓取 / 过滤 / 落地逻辑均在 ``core`` 与 ``providers`` 中实现。
"""
from datetime import datetime, timedelta
from threading import Event, Lock
from typing import Any, Dict, List, Optional, Tuple

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.chain.download import DownloadChain
from app.chain.subscribe import SubscribeChain
from app.core.config import settings
from app.core.event import eventmanager
from app.db.subscribe_oper import SubscribeOper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.event import ConfigChangeEventData
from app.schemas.types import EventType, MediaType

from .core.config import PluginSettings, ProviderConfig, build_defaults
from .core.dedup import SubscribedIndex, build_subscribed_index
from .core.executor import SubscribeExecutor
from .core.filters import build_filter_chain
from .core.history import HistoryStore
from .core.i18n import localize_provider_name, localize_spec
from .core.models import RankMediaItem
from .core.provider import ProviderContext
from .core.registry import registry
from .core.runner import ProviderRunner
from .core.subscribes import SubscribeManager

# 导入 providers 包会触发各来源类的 @register 注册。providers 由并行流程提供，
# 未就绪或单个来源导入异常时不应影响插件本体加载，故此处包裹兜底。
try:  # pragma: no cover - 依赖运行期 providers 包
    from . import providers as _providers  # noqa: F401
except Exception as _exc:  # noqa: BLE001
    logger.error(f"自动订阅助手：来源模块加载失败，暂无可用来源: {_exc}")


class AutomaticSubscriptionAssistant(_PluginBase):
    """多来源榜单自动订阅助手（Vue 联邦渲染）。"""

    # 插件名称
    plugin_name = "自动订阅助手"
    # 插件描述
    plugin_desc = "统一聚合豆瓣榜单/猫眼榜单/热门媒体等来源，可组合过滤后自动订阅。"
    # 插件图标
    plugin_icon = "https://raw.githubusercontent.com/Aqr-K/MoviePilot-Plugins/main/icons/Auto_Subscribe_Assistant.png"
    # 插件版本
    plugin_version = "0.2.12"
    # 插件作者
    plugin_author = "Aqr-K"
    # 作者主页
    author_url = "https://github.com/Aqr-K"
    # 插件配置项 ID 前缀
    plugin_config_prefix = "automaticsubscriptionassistant_"
    # 加载顺序
    plugin_order = 25
    # 可使用的用户级别
    auth_level = 1

    def __init__(self):
        super().__init__()
        # 运行期状态（真正的赋值在 init_plugin 中完成）。
        self._enabled: bool = False
        self._config: Dict[str, Any] = {}
        self._settings: PluginSettings = PluginSettings({})
        self._providers: list = []
        self._downloadchain: Optional[DownloadChain] = None
        self._subscribechain: Optional[SubscribeChain] = None
        self._event: Event = Event()
        self._scheduler: Optional[BackgroundScheduler] = None
        # 运行态：provider_id -> {provider_id, name, processed, started}，供概览「处理中」实时展示。
        # 多来源可能并发运行，读写用锁保护。
        self._run_state: Dict[str, dict] = {}
        self._run_lock: Lock = Lock()
        # 连通性测试防抖：provider_id -> 上次测试时间；短时间内高频触发直接拒绝。
        self._test_last: Dict[str, datetime] = {}
        self._test_lock: Lock = Lock()

    # ------------------------------------------------------------------ #
    # 生命周期
    # ------------------------------------------------------------------ #
    def init_plugin(self, config: dict = None):
        """装载配置、构建依赖链、处理一次性开关（立即运行 / 清空历史）。"""
        self._config = config or {}
        self._settings = PluginSettings(self._config)
        self._downloadchain = DownloadChain()
        self._subscribechain = SubscribeChain()
        self._providers = registry.create_all()

        gcfg = self._settings.global_config
        self._enabled = gcfg.enabled

        # 停止历史遗留任务，避免重复调度。
        self.stop_service()
        # stop_service 会 set 退出信号，此处重置以便本轮任务正常运行。
        self._event = Event()

        onlyonce = gcfg.onlyonce
        clear = gcfg.clear

        # 清空历史（一次性）。
        if clear:
            try:
                self.save_data("history", [])
                logger.info(f"{self.plugin_name}：已清空全部历史记录")
            except Exception as exc:  # noqa: BLE001
                logger.error(f"{self.plugin_name}：清空历史失败: {exc}")

        # 立即运行一次（一次性）：3 秒后 date 任务跑所有启用来源。
        if onlyonce:
            logger.info(f"{self.plugin_name}：立即运行一次，将在 3 秒后执行所有启用来源")
            self.__schedule_once(self.__run_enabled_once)

        # 复位一次性开关并持久化，避免下次加载重复触发。
        if onlyonce or clear:
            self.__reset_oneshot_flags(reset_onlyonce=onlyonce, reset_clear=clear)

    def get_state(self) -> bool:
        """插件是否处于生效状态：总开关开启且至少一个来源启用。"""
        gcfg = self._settings.global_config
        if not gcfg.enabled:
            return False
        return any(self.__provider_config(provider).enabled for provider in self._providers)

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """本插件不注册远程命令。"""
        return []

    @staticmethod
    def get_render_mode() -> Tuple[str, str]:
        """使用 Vue 联邦组件渲染，产物位于 frontend/dist/assets。"""
        return "vue", "frontend/dist/assets"

    def get_form(self) -> Tuple[Optional[List[dict]], Dict[str, Any]]:
        """Vue 模式：表单为 None，第二项返回由 spec 反射生成的完整默认配置。"""
        defaults = build_defaults([provider.get_spec() for provider in self._providers])
        return None, defaults

    def get_page(self) -> Optional[List[dict]]:
        """Vue 模式无需 Vuetify 详情页，历史由前端 Page 组件经 API 渲染。"""
        return None

    def get_dashboard_meta(self) -> Optional[List[Dict[str, str]]]:
        """声明可用的仪表盘部件（供宿主仪表盘「添加组件」列出）。"""
        return [{"key": "overview", "name": "自动订阅助手 · 订阅概览"}]

    def get_dashboard(
        self, key: str = "", **kwargs
    ) -> Optional[Tuple[Dict[str, Any], Dict[str, Any], Optional[List[dict]]]]:
        """Vue 模式仪表盘：返回列宽配置 + 全局属性；元素为 None，
        由前端 Dashboard 组件经 /status、/history 接口自绘真实统计。"""
        cols = {"cols": 12, "md": 6}
        attrs = {
            "border": True,
            "title": "自动订阅助手",
            "subtitle": "订阅概览",
            # 前端 Dashboard 组件据此设置自动刷新间隔（秒）；0 表示仅手动刷新。
            "refresh": 300,
        }
        return cols, attrs, None

    def get_service(self) -> List[Dict[str, Any]]:
        """为每个启用且 cron 合法的来源注册独立的 cron 定时服务。"""
        services: List[Dict[str, Any]] = []
        if not self._settings.global_config.enabled:
            return services
        for provider in self._providers:
            spec = provider.get_spec()
            pconf = ProviderConfig(self._settings.provider_raw(spec.provider_id), spec)
            if not pconf.enabled:
                continue
            cron = (pconf.cron or "").strip()
            if not cron:
                continue
            try:
                trigger = CronTrigger.from_crontab(cron)
            except Exception as exc:  # noqa: BLE001 - cron 非法则跳过该源
                logger.error(f"{spec.provider_name} 的 cron 表达式非法（{cron}）: {exc}")
                self.systemmessage.put(
                    f"{spec.provider_name} 的定时表达式非法：{cron}", title=self.plugin_name)
                continue
            services.append({
                "id": f"{self.plugin_config_prefix}{spec.provider_id}",
                "name": f"{spec.provider_name}订阅",
                "trigger": trigger,
                "func": self.run_provider,
                "func_kwargs": {"provider_id": spec.provider_id},
            })
        return services

    def stop_service(self):
        """置退出信号并关闭调度器。"""
        try:
            if self._event:
                self._event.set()
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._scheduler.shutdown()
                self._scheduler = None
        except Exception as exc:  # noqa: BLE001
            logger.error(f"{self.plugin_name}：停止服务异常: {exc}")

    # ------------------------------------------------------------------ #
    # 运行
    # ------------------------------------------------------------------ #
    def run_provider(self, provider_id: str, subscribed_index: Optional[SubscribedIndex] = None):
        """执行单个来源：装配上下文 + 历史 + Runner 并运行，整源异常兜底提示。

        ``subscribed_index`` 为已订阅强标识索引（识别前预去重快速路径）；
        由「运行全部」传入以在多来源间共享（跨渠道去重），单来源手动运行则自建预加载索引。
        """
        provider = registry.get(provider_id)
        if provider is None:
            logger.error(f"{self.plugin_name}：未知来源 {provider_id}")
            return
        spec = provider.get_spec()
        pconf = ProviderConfig(self._settings.provider_raw(provider_id), spec)
        # 代理开关：来源 options 声明了 proxy 才生效，否则默认不走代理。
        proxy = bool(pconf.option("proxy"))
        # 单来源手动运行：自建预加载索引（仍与已订阅去重）。
        if subscribed_index is None:
            subscribed_index = self.__build_subscribed_index()

        context = ProviderContext(
            chain=self.chain,
            downloadchain=self._downloadchain,
            subscribechain=self._subscribechain,
            logger=logger,
            event=self._event,
            proxy=proxy,
            # 注入插件 KV 读写，供 provider 持久化缓存（如奈飞两级缓存的 L2，抗重启）。
            get_data=self.get_data,
            save_data=self.save_data,
        )
        history = HistoryStore(self.get_data, self.save_data, self.del_data)
        runner = ProviderRunner(
            context, self._settings.global_config, history,
            on_error=self.__on_provider_error,
            on_progress=lambda n: self.__run_progress(provider_id, n),
            subscribed_index=subscribed_index)
        self.__run_start(provider_id, spec.provider_name)
        try:
            stats = runner.run(provider, pconf)
            logger.info(f"{spec.provider_name} 运行完成，统计: {stats}")
            if self._settings.global_config.notify and stats:
                summary = "，".join(f"{k}:{v}" for k, v in stats.items())
                self.systemmessage.put(
                    f"{spec.provider_name} 运行完成（{summary}）", title=self.plugin_name)
        except Exception as exc:  # noqa: BLE001 - 整源兜底
            logger.error(f"{spec.provider_name} 运行失败: {exc}")
            self.systemmessage.put(f"{spec.provider_name}运行失败: {exc}", title=self.plugin_name)
        finally:
            self.__run_end(provider_id)

    def __run_enabled_once(self):
        """立即运行：依次执行所有启用来源，结束后复位 onlyonce。

        构建**一个**已订阅索引贯穿所有来源，实现跨渠道去重（一个媒体在任一来源订阅后，
        后续来源命中即跳过识别）。
        """
        subscribed_index = self.__build_subscribed_index()
        for provider in self._providers:
            if self._event and self._event.is_set():
                break
            if not self.__provider_config(provider).enabled:
                continue
            self.run_provider(provider.provider_id, subscribed_index=subscribed_index)
        self.__reset_oneshot_flags(reset_onlyonce=True, reset_clear=False)

    def __build_subscribed_index(self) -> SubscribedIndex:
        """预加载当前全部订阅为强标识索引；失败兜底空索引（exists() 仍兜底，安全）。"""
        try:
            subscriptions = SubscribeOper().list()
            index = build_subscribed_index(subscriptions)
            logger.info(f"{self.plugin_name}：预加载已订阅 {len(subscriptions or [])} 条用于预去重")
            return index
        except Exception as exc:  # noqa: BLE001 - 预加载失败不应阻断运行，退化为无快速路径
            logger.warning(f"{self.plugin_name}：预加载已订阅失败，本轮跳过预去重快速路径: {exc}")
            return SubscribedIndex()

    def __on_provider_error(self, provider, error: Exception):
        """Runner 整源失败回调：系统 toast 提示。"""
        try:
            self.systemmessage.put(
                f"{provider.provider_name}运行失败: {error}", title=self.plugin_name)
        except Exception:  # noqa: BLE001 - 回调不得影响主流程
            pass

    # ------------------------------------------------------------------ #
    # 运行态（供概览「处理中」实时展示；多来源可能并发，锁保护）
    # ------------------------------------------------------------------ #
    def __run_start(self, provider_id: str, name: str) -> None:
        """标记某来源开始运行（processed 归零）。"""
        with self._run_lock:
            self._run_state[provider_id] = {
                "provider_id": provider_id, "name": name, "processed": 0,
                "started": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }

    def __run_progress(self, provider_id: str, processed: int) -> None:
        """更新某来源已处理条数。"""
        with self._run_lock:
            st = self._run_state.get(provider_id)
            if st is not None:
                st["processed"] = processed

    def __run_end(self, provider_id: str) -> None:
        """某来源运行结束，移出运行态。"""
        with self._run_lock:
            self._run_state.pop(provider_id, None)

    # ------------------------------------------------------------------ #
    # 调度与配置辅助
    # ------------------------------------------------------------------ #
    def __schedule_once(self, func, **kwargs):
        """3 秒后触发一次 date 任务（懒创建 BackgroundScheduler）。"""
        try:
            if not self._scheduler:
                self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            run_date = datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3)
            self._scheduler.add_job(func=func, trigger="date", run_date=run_date, kwargs=kwargs or {})
            if not self._scheduler.running:
                self._scheduler.start()
        except Exception as exc:  # noqa: BLE001
            logger.error(f"{self.plugin_name}：调度一次性任务失败: {exc}")

    def __reset_oneshot_flags(self, reset_onlyonce: bool, reset_clear: bool):
        """复位 onlyonce / clear 并持久化，读取最新配置避免并发覆盖。"""
        try:
            cfg = dict(self.get_config() or self._config or {})
            global_conf = dict(cfg.get("global") or {})
            if reset_onlyonce:
                global_conf["onlyonce"] = False
            if reset_clear:
                global_conf["clear"] = False
            cfg["global"] = global_conf
            self._config = cfg
            self._settings = PluginSettings(cfg)
            self.update_config(cfg)
        except Exception as exc:  # noqa: BLE001
            logger.error(f"{self.plugin_name}：复位一次性开关失败: {exc}")

    def __provider_config(self, provider) -> ProviderConfig:
        """构造某来源的 ProviderConfig（带 spec 默认回退）。"""
        spec = provider.get_spec()
        return ProviderConfig(self._settings.provider_raw(spec.provider_id), spec)

    # ------------------------------------------------------------------ #
    # API
    # ------------------------------------------------------------------ #
    def get_api(self) -> List[Dict[str, Any]]:
        """注册插件 API 端点（读取类走 bear，删除类可用 apikey）。"""
        return [
            {
                "path": "/providers", "endpoint": self.api_providers, "methods": ["GET"],
                "auth": "bear", "summary": "来源列表", "description": "返回所有来源的元描述 spec",
            },
            {
                "path": "/config", "endpoint": self.api_get_config, "methods": ["GET"],
                "auth": "bear", "summary": "读取配置", "description": "返回当前配置（缺省时返回反射默认）",
            },
            {
                "path": "/config", "endpoint": self.api_save_config, "methods": ["POST"],
                "auth": "bear", "summary": "保存配置", "description": "保存完整配置并重载调度",
            },
            {
                "path": "/history", "endpoint": self.api_history, "methods": ["GET"],
                "auth": "bear", "summary": "历史记录", "description": "按来源/状态过滤并分页查询历史",
            },
            {
                "path": "/history", "endpoint": self.api_delete_history, "methods": ["DELETE"],
                "auth": "apikey", "summary": "删除历史", "description": "按 unique 删除一条历史（apikey 鉴权）",
            },
            {
                "path": "/history/delete", "endpoint": self.api_delete_history_post, "methods": ["POST"],
                "auth": "bear", "summary": "删除历史（前端）", "description": "按 unique 删除一条历史（前端调用）",
            },
            {
                "path": "/status", "endpoint": self.api_status, "methods": ["GET"],
                "auth": "bear", "summary": "运行状态", "description": "各来源启用状态与历史统计",
            },
            {
                "path": "/run", "endpoint": self.api_run, "methods": ["POST"],
                "auth": "bear", "summary": "立即运行", "description": "触发指定来源在 3 秒后运行一次",
            },
            {
                "path": "/providers/test", "endpoint": self.api_test_provider, "methods": ["POST"],
                "auth": "bear", "summary": "连通性测试", "description": "抓取来源前几条验证连通（不订阅、不写历史），带最小间隔防抖",
            },
            {
                "path": "/history/batch-delete", "endpoint": self.api_history_batch_delete, "methods": ["POST"],
                "auth": "bear", "summary": "批量删除历史", "description": "按 unique 列表批量删除历史记录",
            },
            {
                "path": "/history/recognize", "endpoint": self.api_history_recognize, "methods": ["POST"],
                "auth": "bear", "summary": "重新识别", "description": "按 unique 对一条历史记录重新识别并尝试订阅",
            },
            {
                "path": "/subscribes", "endpoint": self.api_subscribes, "methods": ["GET"],
                "auth": "bear", "summary": "订阅列表", "description": "列出本插件创建的订阅",
            },
            {
                "path": "/subscribes/delete", "endpoint": self.api_subscribes_delete, "methods": ["POST"],
                "auth": "bear", "summary": "批量退订", "description": "按订阅ID列表批量退订（发删除事件）",
            },
            {
                "path": "/subscribes/state", "endpoint": self.api_subscribes_state, "methods": ["POST"],
                "auth": "bear", "summary": "批量暂停/恢复", "description": "按订阅ID列表批量置状态（S暂停/R恢复）",
            },
            {
                "path": "/system/share", "endpoint": self.api_get_share, "methods": ["GET"],
                "auth": "bear", "summary": "读取订阅数据共享",
                "description": "读取 MoviePilot 全局『订阅数据共享』(SUBSCRIBE_STATISTIC_SHARE) 状态（热门媒体依赖）",
            },
            {
                "path": "/system/share", "endpoint": self.api_set_share, "methods": ["POST"],
                "auth": "bear", "summary": "设置订阅数据共享",
                "description": "开/关 MoviePilot 全局『订阅数据共享』并持久化（改内存+落 app.env，无需重启）",
            },
        ]

    def api_providers(self, lang: str = None) -> Dict[str, Any]:
        """返回所有来源的 spec 元描述，供前端动态渲染配置表单（按 lang 本地化标签）。"""
        specs = [provider.get_spec().to_dict() for provider in self._providers]
        return {"providers": [localize_spec(spec, lang) for spec in specs]}

    def api_get_config(self) -> Dict[str, Any]:
        """返回当前配置；未保存过时回退为反射生成的默认配置。"""
        config = self.get_config()
        if not config:
            config = build_defaults([provider.get_spec() for provider in self._providers])
        return {"config": config}

    def api_save_config(self, request: dict = None) -> Dict[str, Any]:
        """保存完整配置并重载：update_config 持久化 + init_plugin 重建调度。"""
        if not isinstance(request, dict):
            return {"code": 1, "message": "请求体必须为配置对象"}
        # 状态检测兜底：启用了却无任何可监听内容的来源，保存时自动关闭其开关（与前端一致，防绕过前端直接保存）。
        self._auto_disable_empty_providers(request)
        try:
            self.update_config(request)
            # 重新装载：重建 settings/链/调度，并处理其中的一次性开关。
            self.init_plugin(request)
            return {"code": 0, "message": "保存成功"}
        except Exception as exc:  # noqa: BLE001
            logger.error(f"{self.plugin_name}：保存配置失败: {exc}")
            return {"code": 1, "message": f"保存失败: {exc}"}

    def _auto_disable_empty_providers(self, request: dict) -> None:
        """状态检测兜底：遍历各来源，已启用却无任何可监听内容者（``provider.has_listening`` 为假）
        自动关闭其开关。与前端保存时的即时判断一致，防止直接调 API 保存绕过前端。Mikan 等始终有
        监听的来源默认 ``has_listening`` 返回 True，不受影响。"""
        providers_cfg = request.get("providers")
        if not isinstance(providers_cfg, dict):
            return
        for provider in self._providers:
            pconf = providers_cfg.get(provider.provider_id)
            if not isinstance(pconf, dict) or not pconf.get("enabled"):
                continue
            options = pconf.get("options") if isinstance(pconf.get("options"), dict) else {}
            try:
                if not provider.has_listening(options):
                    pconf["enabled"] = False
                    logger.info(f"{self.plugin_name}：{provider.provider_name} 未配置任何可监听内容，"
                                f"保存时已自动关闭该来源开关。")
            except Exception as exc:  # noqa: BLE001 - 单源检测失败不影响保存
                logger.warning(f"{self.plugin_name}：{provider.provider_name} 监听状态检测失败（跳过）: {exc}")

    def api_history(self, provider: str = None, status: str = None, mtype: str = None,
                    keyword: str = None, year_min: str = None, year_max: str = None,
                    page: int = 1, count: int = 50) -> Dict[str, Any]:
        """按来源/状态/媒体类型/关键词/发行年份范围过滤并分页查询历史记录（按时间倒序）。

        provider/status/mtype 支持逗号分隔多值；单值向后兼容。year_min/year_max 为发行年份闭区间。
        """
        store = HistoryStore(self.get_data, self.save_data, self.del_data)
        records, total = store.query(provider=provider, status=status, mtype=mtype,
                                     keyword=keyword, year_min=year_min, year_max=year_max,
                                     page=page, count=count)
        return {"list": records, "total": total, "page": page, "count": count}

    def api_delete_history(self, unique: str, apikey: str) -> Dict[str, Any]:
        """删除一条历史（apikey 鉴权，供后端/脚本调用）。"""
        if apikey != settings.API_TOKEN:
            return {"code": 1, "message": "API密钥错误"}
        return self.__delete_history(unique)

    def api_delete_history_post(self, request: dict = None) -> Dict[str, Any]:
        """删除一条历史（bear 鉴权，前端调用，body={"unique": ...}）。"""
        unique = (request or {}).get("unique") if isinstance(request, dict) else None
        if not unique:
            return {"code": 1, "message": "缺少 unique"}
        return self.__delete_history(unique)

    def api_status(self, lang: str = None) -> Dict[str, Any]:
        """返回总开关、各来源启用状态与历史统计（来源名按 lang 本地化）。"""
        store = HistoryStore(self.get_data, self.save_data, self.del_data)
        providers = []
        for provider in self._providers:
            spec = provider.get_spec()
            pconf = ProviderConfig(self._settings.provider_raw(spec.provider_id), spec)
            providers.append({
                "provider_id": spec.provider_id,
                "provider_name": localize_provider_name(spec.provider_id, spec.provider_name, lang),
                "enabled": pconf.enabled,
                "cron": pconf.cron,
            })
        with self._run_lock:
            running = list(self._run_state.values())
        return {
            "enabled": self._settings.global_config.enabled,
            "providers": providers,
            "stats": store.stats(),
            "running": running,
        }

    def api_run(self, request: dict = None, provider_id: str = None) -> Dict[str, Any]:
        """触发指定来源在 3 秒后运行一次（provider_id 支持 body 或 query）。"""
        pid = provider_id or ((request or {}).get("provider_id") if isinstance(request, dict) else None)
        if not pid:
            return {"code": 1, "message": "缺少 provider_id"}
        provider = registry.get(pid)
        if provider is None:
            return {"code": 1, "message": f"未知来源: {pid}"}
        self.__schedule_once(self.run_provider, provider_id=pid)
        return {"code": 0, "message": f"{provider.provider_name} 已触发，将在 3 秒后运行"}

    def api_test_provider(self, request: dict = None, provider_id: str = None) -> Dict[str, Any]:
        """连通性测试：抓取该来源前几条以验证可达，**绝不进入订阅管线、绝不订阅、绝不写历史**。

        服务端防抖：同一来源两次测试的最小间隔 2 秒，短时间高频触发直接拒绝（防止绕过前端疯狂点击）。
        """
        pid = provider_id or ((request or {}).get("provider_id") if isinstance(request, dict) else None)
        if not pid:
            return {"code": 1, "message": "缺少 provider_id"}
        provider = registry.get(pid)
        if provider is None:
            return {"code": 1, "message": f"未知来源: {pid}"}
        # 防抖：同一来源 2 秒内重复测试直接拒绝。
        now = datetime.now()
        with self._test_lock:
            last = self._test_last.get(pid)
            if last is not None and (now - last).total_seconds() < 2.0:
                return {"code": 1, "throttled": True, "message": "操作过于频繁，请稍后再试"}
            self._test_last[pid] = now
        spec = provider.get_spec()
        pconf = ProviderConfig(self._settings.provider_raw(pid), spec)
        context = ProviderContext(
            chain=self.chain,
            downloadchain=self._downloadchain,
            subscribechain=self._subscribechain,
            logger=logger,
            event=self._event,
            proxy=bool(pconf.option("proxy")),
            get_data=self.get_data,
            save_data=self.save_data,
        )
        # 连通性测试用「spec 默认值兜底 + 用户已存配置覆盖」的完整 options：
        # 避免未细配的来源（如热门/奈飞的启用开关、类别未落库）被判为「已连通但无条目」。
        test_options = {f.key: f.default for f in (spec.options_schema or [])}
        test_options.update(pconf.options or {})
        # 连通性测试强制关缓存（须盖过用户已存的 use_cache=True）：既不读缓存（真实走网络验证连通、
        # 而非产出旧的缓存条目），也不写缓存（不产生持久化副作用、不污染正常运行的缓存周期）。
        test_options["use_cache"] = False
        try:
            count = 0
            sample = None
            # 仅消费前几条即 break：验证连通与产出，不遍历全部、不调用任何订阅/历史逻辑。
            for item in provider.fetch(test_options, context):
                count += 1
                if sample is None:
                    sample = getattr(item, "title", None)
                if count >= 3:
                    break
        except Exception as exc:  # noqa: BLE001 - 测试失败即返回失败，不影响插件本体
            logger.warning(f"{self.plugin_name}：{spec.provider_name} 连通性测试失败: {exc}")
            return {"code": 0, "ok": False, "message": f"连通失败：{exc}"}
        if count > 0:
            return {"code": 0, "ok": True, "count": count, "sample": sample,
                    "message": f"连通正常，取到示例：{sample}"}
        return {"code": 0, "ok": False, "count": 0, "message": "已连通但未取到条目（可能暂无数据或配置为空）"}

    def api_get_share(self) -> Dict[str, Any]:
        """读取 MoviePilot 全局『订阅数据共享』(SUBSCRIBE_STATISTIC_SHARE) 当前状态。

        热门媒体来源依赖该主程序开关：关闭时服务端订阅统计接口直接返回空、本来源无法获取数据。
        """
        return {"code": 0, "enabled": bool(settings.SUBSCRIBE_STATISTIC_SHARE)}

    def api_set_share(self, request: dict = None) -> Dict[str, Any]:
        """开/关 MoviePilot 全局『订阅数据共享』并持久化（改内存 + 落 app.env，无需重启）。

        经官方 settings.update_setting 写入，success 三态——True 已更新 / None 值未变 / False 失败
        （该键被真实 OS 环境变量占用时拒写）；仅真正变更时广播 ConfigChanged 事件。body={"enabled": bool}。
        """
        if not isinstance(request, dict) or "enabled" not in request:
            return {"code": 1, "message": "缺少 enabled"}
        enabled = bool(request.get("enabled"))
        try:
            success, message = settings.update_setting("SUBSCRIBE_STATISTIC_SHARE", enabled)
        except Exception as exc:  # noqa: BLE001 - 写设置失败即返回失败，不影响插件本体
            logger.error(f"{self.plugin_name}：设置订阅数据共享失败: {exc}")
            return {"code": 1, "enabled": bool(settings.SUBSCRIBE_STATISTIC_SHARE), "message": f"设置失败: {exc}"}
        if success is False:
            # 被真实 OS 环境变量占用等原因拒写：如实回传当前值与原因，前端据此提示手动配置。
            return {"code": 1, "enabled": bool(settings.SUBSCRIBE_STATISTIC_SHARE),
                    "message": message or "无法修改：该设置可能由系统环境变量锁定，请手动在 MoviePilot 配置中调整"}
        if success:
            # 仅在值真正发生变化时广播（None 表示已是目标值、无需广播）；广播失败不影响已成功的写入。
            try:
                eventmanager.send_event(
                    etype=EventType.ConfigChanged,
                    data=ConfigChangeEventData(
                        key="SUBSCRIBE_STATISTIC_SHARE", value=enabled, change_type="update"),
                )
            except Exception as exc:  # noqa: BLE001 - 广播失败仅告警，设置本身已成功
                logger.warning(f"{self.plugin_name}：广播配置变更事件失败（不影响设置）: {exc}")
        return {"code": 0, "enabled": bool(settings.SUBSCRIBE_STATISTIC_SHARE), "message": "已更新"}

    def __delete_history(self, unique: str) -> Dict[str, Any]:
        """删除历史的共用实现。"""
        store = HistoryStore(self.get_data, self.save_data, self.del_data)
        removed = store.delete(unique)
        if removed:
            return {"code": 0, "message": "删除成功"}
        return {"code": 1, "message": "未找到该记录"}

    def api_history_batch_delete(self, request: dict = None) -> Dict[str, Any]:
        """批量删除历史（bear 鉴权，body={"uniques":[...]}）。"""
        uniques = (request or {}).get("uniques") if isinstance(request, dict) else None
        if not isinstance(uniques, list) or not uniques:
            return {"code": 1, "message": "缺少 uniques 列表"}
        store = HistoryStore(self.get_data, self.save_data, self.del_data)
        removed = store.delete_many(uniques)
        return {"code": 0, "message": f"已删除 {removed} 条", "removed": removed}

    def api_history_recognize(self, request: dict = None) -> Dict[str, Any]:
        """重新识别一条历史记录（供『异常/未识别』项手动再跑一次识别 + 订阅）。

        从历史记录还原候选（RankMediaItem），复用订阅落地管线单条处理：识别成功则订阅
        并以新身份键记录，仍失败则记为新的异常。body={"unique": ...}。同步执行，返回最新状态。
        """
        unique = (request or {}).get("unique") if isinstance(request, dict) else None
        if not unique:
            return {"code": 1, "message": "缺少 unique"}
        store = HistoryStore(self.get_data, self.save_data, self.del_data)
        rec = store.get(unique)
        if rec is None:
            return {"code": 1, "message": "未找到该记录"}
        provider = registry.get(rec.get("provider"))
        if provider is None:
            return {"code": 1, "message": f"来源不可用: {rec.get('provider')}"}
        try:
            spec = provider.get_spec()
            pconf = ProviderConfig(self._settings.provider_raw(provider.provider_id), spec)
            # 还原候选：类型中文串 → MediaType 枚举；tmdb/douban/bangumi id 供按优先级识别。
            type_val = rec.get("type")
            try:
                type_hint = MediaType(type_val) if type_val else None
            except ValueError:
                type_hint = None
            item = RankMediaItem(
                title=rec.get("title") or "",
                year=rec.get("year"),
                type_hint=type_hint,
                douban_id=rec.get("doubanid"),
                tmdb_id=rec.get("tmdbid"),
                bangumi_id=rec.get("bangumiid"),
                season=rec.get("season"),
                poster=rec.get("poster"),
            )
            context = ProviderContext(
                chain=self.chain,
                downloadchain=self._downloadchain,
                subscribechain=self._subscribechain,
                logger=logger,
                event=self._event,
                proxy=bool(pconf.option("proxy")),
                get_data=self.get_data,
                save_data=self.save_data,
            )
            # 先删旧记录：识别成功后身份键可能由标题回退键升级为强标识键，避免残留孤儿记录。
            store.delete(unique)
            filter_chain = build_filter_chain([f.key for f in spec.filters_schema])
            executor = SubscribeExecutor(context, self._settings.global_config,
                                         self.__build_subscribed_index())
            outcome = executor.process(item, provider, filter_chain, store, pconf.filters)
            store.flush()
        except Exception as exc:  # noqa: BLE001 - 端点兜底，不影响插件本体
            logger.error(f"{self.plugin_name}：重新识别失败: {exc}")
            return {"code": 1, "message": f"重新识别失败: {exc}"}
        return {"code": 0, "status": outcome.status.value,
                "reason": getattr(outcome, "reason", None), "message": "重新识别完成"}

    # ------------------------------------------------------------------ #
    # 订阅手动管理
    # ------------------------------------------------------------------ #
    def __subscribe_manager(self) -> SubscribeManager:
        """构造订阅管理器：退订回调发送主程序标准 SubscribeDeleted 事件。"""
        def _on_deleted(sid, sub):
            try:
                info = {c.name: sub.__dict__.get(c.name) for c in sub.__table__.columns}
            except Exception:  # noqa: BLE001 - 快照失败退化为最小负载
                info = {"tmdbid": getattr(sub, "tmdbid", None), "doubanid": getattr(sub, "doubanid", None)}
            eventmanager.send_event(
                EventType.SubscribeDeleted,
                {"subscribe_id": sid, "subscribe_info": info})
        return SubscribeManager(SubscribeOper(), on_deleted=_on_deleted)

    def api_subscribes(self) -> Dict[str, Any]:
        """列出本插件创建的订阅。"""
        try:
            rows = self.__subscribe_manager().list_mine()
            return {"list": rows, "total": len(rows)}
        except Exception as exc:  # noqa: BLE001
            logger.error(f"{self.plugin_name}：读取订阅列表失败: {exc}")
            return {"list": [], "total": 0, "message": f"读取失败: {exc}"}

    def api_subscribes_delete(self, request: dict = None) -> Dict[str, Any]:
        """批量退订（body={"ids":[...]}）。"""
        ids = (request or {}).get("ids") if isinstance(request, dict) else None
        if not isinstance(ids, list) or not ids:
            return {"code": 1, "message": "缺少 ids 列表"}
        try:
            res = self.__subscribe_manager().delete(ids)
            return {"code": 0, "message": f"已退订 {res['ok']} 个" + (f"，{res['failed']} 个失败" if res["failed"] else ""), **res}
        except Exception as exc:  # noqa: BLE001
            logger.error(f"{self.plugin_name}：批量退订失败: {exc}")
            return {"code": 1, "message": f"退订失败: {exc}"}

    def api_subscribes_state(self, request: dict = None) -> Dict[str, Any]:
        """批量暂停/恢复（body={"ids":[...],"state":"S|R"}）。"""
        body = request if isinstance(request, dict) else {}
        ids = body.get("ids")
        state = body.get("state")
        if not isinstance(ids, list) or not ids:
            return {"code": 1, "message": "缺少 ids 列表"}
        try:
            res = self.__subscribe_manager().set_state(ids, state)
            label = "暂停" if state == "S" else "恢复"
            return {"code": 0, "message": f"已{label} {res['ok']} 个" + (f"，{res['failed']} 个失败" if res["failed"] else ""), **res}
        except ValueError as exc:
            return {"code": 1, "message": str(exc)}
        except Exception as exc:  # noqa: BLE001
            logger.error(f"{self.plugin_name}：批量置状态失败: {exc}")
            return {"code": 1, "message": f"操作失败: {exc}"}
