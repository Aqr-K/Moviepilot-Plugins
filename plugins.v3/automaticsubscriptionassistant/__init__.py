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
from app.chain.download import DownloadChain
from app.chain.subscribe import SubscribeChain
from app.db.oper.subscribe import SubscribeOper
from app.schemas.types import EventType, MediaType
from app.sdk.config import settings
from app.sdk.events import eventmanager
from app.sdk.logging import logger
from app.sdk.media import MetaInfo
from app.sdk.plugin import _PluginBase
from app.sdk.scheduler import update_plugin_job
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from .api.blacklist import BlacklistApiMixin
from .api.configuration import ConfigurationApiMixin
from .api.history import HistoryApiMixin
from .api.overview import OverviewApiMixin
from .api.providers import ProvidersApiMixin
from .api.routes import RoutesApiMixin
from .api.subscriptions import SubscriptionsApiMixin
from .core.config import PluginSettings, ProviderConfig, build_defaults
from .core.dedup import SubscribedIndex, build_subscribed_index
from .core.provider import ProviderContext
from .core.registry import registry
from .core.runner import ProviderRunner
from .core.subscribes import SubscribeManager, list_subscriptions
from .database.backup import DatabaseBackup
from .database.blacklist import migrate_blacklist_from_kv
from .database.legacy import migrate_history_from_kv
from .database.lifecycle import MIGRATIONS, ensure_schema
from .db.models import MODELS
from .schemas.blacklist import media_snapshot
from .services.blacklist import BLACKLIST_LOCK, BlacklistStore
from .services.history import HistoryStore
from .services.notifications import format_run_result

# 导入 providers 包会触发各来源类的 @register 注册。providers 由并行流程提供，
# 未就绪或单个来源导入异常时不应影响插件本体加载，故此处包裹兜底。
try:  # pragma: no cover - 依赖运行期 providers 包
    from . import providers as _providers  # noqa: F401
except Exception as _exc:  # noqa: BLE001
    logger.error(f"自动订阅助手：来源模块加载失败，暂无可用来源: {_exc}")


class AutomaticSubscriptionAssistant(
    RoutesApiMixin,
    ConfigurationApiMixin,
    HistoryApiMixin,
    OverviewApiMixin,
    ProvidersApiMixin,
    SubscriptionsApiMixin,
    BlacklistApiMixin,
    _PluginBase,
):
    """多来源榜单自动订阅助手（Vue 联邦渲染）。"""

    # 插件名称
    plugin_name = "自动订阅助手"
    # 插件描述
    plugin_desc = "聚合影视、动画及音乐榜单，按来源独立调度、过滤和通知，支持历史、黑名单与自动订阅。"
    # 插件图标
    plugin_icon = "https://raw.githubusercontent.com/Aqr-K/MoviePilot-Plugins/main/icons/Auto_Subscribe_Assistant.png"
    # 插件版本
    plugin_version = "3.4.0"
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
        self._database_ready = False
        self._database_error = "数据库尚未初始化"
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

        # 宿主在 init_plugin 之后才运行迁移；读取去重/忽略规则前必须先准备好库。
        self._database_ready = False
        self._database_error = ""
        try:
            with BLACKLIST_LOCK:
                handle = self.get_database()
                backup = DatabaseBackup(
                    handle.engine,
                    handle.plugin_id,
                    self.get_data_path() / "database-backups",
                )
                backup.before_upgrade()
                ensure_schema(handle.engine)
                result = migrate_history_from_kv(
                    self._history_store(),
                    self.get_data,
                    self.save_data,
                    self.del_data,
                    logger,
                )
                if result.error:
                    raise RuntimeError(result.summary())
                migrate_blacklist_from_kv(
                    handle.session, self.get_data, self.save_data, self.del_data
                )
            self._database_ready = True
        except Exception as exc:  # noqa: BLE001 - 数据未准备好时禁止调度或复位一次性开关
            self._database_error = str(exc)
            self._event.set()
            logger.error(f"{self.plugin_name}：数据库初始化失败，自动任务已停止: {exc}")
            return

        # 清空历史（一次性）。
        if clear:
            try:
                self._history_store().clear()
                logger.info(f"{self.plugin_name}：已清空全部历史记录")
            except Exception as exc:  # noqa: BLE001
                logger.error(f"{self.plugin_name}：清空历史失败: {exc}")

        # 立即运行一次（一次性）：3 秒后 date 任务跑所有启用来源。
        if onlyonce:
            logger.info(
                f"{self.plugin_name}：立即运行一次，将在 3 秒后执行所有启用来源"
            )
            self._schedule_once(self._run_enabled_once)

        # 复位一次性开关并持久化，避免下次加载重复触发。
        if onlyonce or clear:
            self._reset_oneshot_flags(reset_onlyonce=onlyonce, reset_clear=clear)

    def get_state(self) -> bool:
        """插件是否处于生效状态：总开关开启且至少一个来源启用。"""
        gcfg = self._settings.global_config
        if not self._database_ready or not gcfg.enabled:
            return False
        return any(
            self._provider_config(provider).enabled for provider in self._providers
        )

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """本插件不注册远程命令。"""
        return []

    def get_database_models(self) -> List[type]:
        """声明插件自有的历史、成功账本、黑名单与迁移状态表。"""
        return list(MODELS)

    def get_database_migrations(self):
        """向宿主声明完整迁移树；禁止由 create_all 代替版本升级。"""
        return MIGRATIONS

    def blacklist_store(self):
        """生产忽略规则只读写当前插件实例的 SQL 库。"""
        return BlacklistStore(self.get_database().session)

    def _history_store(self) -> HistoryStore:
        """构造绑定插件自有库的历史仓库。"""
        return HistoryStore(self.get_database().session)

    @staticmethod
    def get_render_mode() -> Tuple[str, str]:
        """使用 Vue 联邦组件渲染，产物位于 frontend/dist/assets。"""
        return "vue", "frontend/dist/assets"

    def get_form(self) -> Tuple[Optional[List[dict]], Dict[str, Any]]:
        """Vue 模式：表单为 None，第二项返回由 spec 反射生成的完整默认配置。"""
        defaults = build_defaults([provider.get_spec() for provider in self._providers])
        return None, defaults

    def get_sidebar_nav(self):
        """仅向管理员显示插件侧栏入口，默认进入订阅历史。"""
        return [
            {
                "nav_key": "main",
                "title": self.plugin_name,
                "icon": "mdi-rss",
                "section": "subscribe",
                "permission": "admin",
                "order": 30,
            }
        ]

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
        由前端 Dashboard 组件经 /dashboard 接口读取概览数据。"""
        if key not in ("", "overview"):
            return None
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
        if not self._database_ready or not self._settings.global_config.enabled:
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
                logger.error(
                    f"{spec.provider_name} 的 cron 表达式非法（{cron}）: {exc}"
                )
                if pconf.notify:
                    self.systemmessage.put(
                        f"{spec.provider_name} 的定时表达式非法：{cron}",
                        title=self.plugin_name,
                    )
                continue
            services.append(
                {
                    "id": f"{self.plugin_config_prefix}{spec.provider_id}",
                    "name": f"{spec.provider_name}订阅",
                    "trigger": trigger,
                    "func": self.run_provider,
                    "func_kwargs": {"provider_id": spec.provider_id},
                }
            )
        return services

    def stop_service(self):
        """置退出信号并关闭调度器。

        退出信号与最后的订阅提交共用锁，避免停止后继续添加。
        关闭不等待在途抓取任务：``stop_service`` 经 ``init_plugin`` 同步跑在保存配置的请求
        线程上，而一次性任务可能正卡在几分钟的抓取里。在途任务已经通过上面 set 的退出
        信号被要求收尾，无须再阻塞调用方等它跑完。
        """
        self._database_ready = False
        try:
            with BLACKLIST_LOCK:
                if self._event:
                    self._event.set()
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._scheduler.shutdown(wait=False)
                self._scheduler = None
        except Exception as exc:  # noqa: BLE001
            logger.error(f"{self.plugin_name}：停止服务异常: {exc}")

    # ------------------------------------------------------------------ #
    # 运行
    # ------------------------------------------------------------------ #
    def run_provider(
        self, provider_id: str, subscribed_index: Optional[SubscribedIndex] = None
    ):
        """执行单个来源：装配上下文 + 历史 + Runner 并运行，整源异常兜底提示。

        ``subscribed_index`` 为已订阅强标识索引（识别前预去重快速路径）；
        由「运行全部」传入以在多来源间共享（跨渠道去重），单来源手动运行则自建预加载索引。
        """
        if not self._database_ready or self._event.is_set():
            logger.warning(f"{self.plugin_name}：数据库未就绪或插件已停止，本次不运行")
            return
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
            subscribed_index = self._build_subscribed_index()

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
            blacklist=self.blacklist_store(),
        )
        history = self._history_store()
        errors = []
        stats = {}
        runner = ProviderRunner(
            context,
            self._settings.global_config,
            history,
            on_error=lambda _provider, error: errors.append(str(error)),
            on_progress=lambda n: self._run_progress(provider_id, n),
            subscribed_index=subscribed_index,
        )
        self._run_start(provider_id, spec.provider_name)
        try:
            stats = runner.run(provider, pconf)
            logger.info(f"{spec.provider_name} 运行完成，统计: {stats}")
        except Exception as exc:  # noqa: BLE001 - 整源兜底
            errors.append(str(exc))
            logger.error(f"{spec.provider_name} 运行失败: {exc}")
        finally:
            self._run_end(provider_id)
            if pconf.notify and not context.event.is_set():
                try:
                    self.systemmessage.put(
                        format_run_result(
                            spec.provider_name, stats, errors[-1] if errors else None
                        ),
                        title=self.plugin_name,
                    )
                except Exception as exc:  # noqa: BLE001 - 通知失败不改变本轮运行结果
                    logger.warning(f"{spec.provider_name} 运行通知发送失败: {exc}")

    def _run_enabled_once(self):
        """立即运行：依次执行所有启用来源，结束后复位 onlyonce。

        构建**一个**已订阅索引贯穿所有来源，实现跨渠道去重（一个媒体在任一来源订阅后，
        后续来源命中即跳过识别）。
        """
        # 开跑时就认定本轮的退出信号。``init_plugin`` 会换上一个全新的 Event，若每轮
        # 循环都重读实例属性，重载恰好发生在两个来源之间时，这里会读到那个尚未置位的新
        # 信号，本轮就再也停不下来了。
        event = self._event
        subscribed_index = self._build_subscribed_index()
        for provider in self._providers:
            if event is not None and event.is_set():
                break
            if not self._provider_config(provider).enabled:
                continue
            self.run_provider(provider.provider_id, subscribed_index=subscribed_index)
        self._reset_oneshot_flags(reset_onlyonce=True, reset_clear=False)

    def _build_subscribed_index(self) -> SubscribedIndex:
        """
        通过官方查询 SDK 预加载当前全部订阅的强标识索引。

        :return: 订阅索引；查询失败时返回空索引，由宿主 exists() 继续兜底
        """
        try:
            subscriptions = list_subscriptions()
            index = build_subscribed_index(subscriptions)
            logger.info(
                f"{self.plugin_name}：预加载已订阅 {len(subscriptions or [])} 条用于预去重"
            )
            return index
        except Exception as exc:  # noqa: BLE001 - 预加载失败不应阻断运行，退化为无快速路径
            logger.warning(
                f"{self.plugin_name}：预加载已订阅失败，本轮跳过预去重快速路径: {exc}"
            )
            return SubscribedIndex()

    # ------------------------------------------------------------------ #
    # 运行态（供概览「处理中」实时展示；多来源可能并发，锁保护）
    # ------------------------------------------------------------------ #
    def _run_start(self, provider_id: str, name: str) -> None:
        """标记某来源开始运行（processed 归零）。"""
        with self._run_lock:
            self._run_state[provider_id] = {
                "provider_id": provider_id,
                "name": name,
                "processed": 0,
                "started": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }

    def _run_progress(self, provider_id: str, processed: int) -> None:
        """更新某来源已处理条数。"""
        with self._run_lock:
            st = self._run_state.get(provider_id)
            if st is not None:
                st["processed"] = processed

    def _run_end(self, provider_id: str) -> None:
        """某来源运行结束，移出运行态。"""
        with self._run_lock:
            self._run_state.pop(provider_id, None)

    # ------------------------------------------------------------------ #
    # 调度与配置辅助
    # ------------------------------------------------------------------ #
    def _schedule_once(self, func, **kwargs):
        """3 秒后触发一次 date 任务（懒创建 BackgroundScheduler）。

        同一目标的重复触发按 ``job_id`` 合并：连点「立即运行」或重复调 /run 时，
        新的一次顶掉尚未开跑的那次，避免同一来源被并发跑出多个 runner 互相覆盖历史。
        """
        try:
            if not self._scheduler:
                self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            run_date = datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(
                seconds=3
            )
            job_id = (
                f"{self.plugin_config_prefix}once_{getattr(func, '__name__', 'task')}"
            )
            provider_id = (kwargs or {}).get("provider_id")
            if provider_id:
                job_id = f"{job_id}_{provider_id}"
            self._scheduler.add_job(
                func=func,
                trigger="date",
                run_date=run_date,
                kwargs=kwargs or {},
                id=job_id,
                replace_existing=True,
                max_instances=1,
                coalesce=True,
                misfire_grace_time=60,
            )
            if not self._scheduler.running:
                self._scheduler.start()
        except Exception as exc:  # noqa: BLE001
            logger.error(f"{self.plugin_name}：调度一次性任务失败: {exc}")

    def _reset_oneshot_flags(self, reset_onlyonce: bool, reset_clear: bool):
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

    def _provider_config(self, provider) -> ProviderConfig:
        """构造某来源的 ProviderConfig（带 spec 默认回退）。"""
        spec = provider.get_spec()
        return ProviderConfig(self._settings.provider_raw(spec.provider_id), spec)

    def _refresh_jobs(self) -> None:
        """自定义保存入口同样刷新宿主定时任务，移除旧 cron 与停用来源。"""
        update_plugin_job(self.__class__.__name__)

    # ------------------------------------------------------------------ #
    # 订阅手动管理
    # ------------------------------------------------------------------ #
    def _subscribe_manager(self) -> SubscribeManager:
        """
        构造订阅管理器，退订回调发送主程序标准 SubscribeDeleted 事件。

        :return: 通过 SDK 快照查询并复核归属的订阅管理器
        """

        def _on_deleted(sid, sub):
            """
            将删除前的 SDK 订阅快照转成事件数据并通知宿主。
            """
            try:
                info = sub.model_dump(mode="json")
            except Exception:  # noqa: BLE001 - 快照失败退化为最小负载
                info = {
                    "media_source": getattr(sub, "media_source", None),
                    "media_id": getattr(sub, "media_id", None),
                }
            eventmanager.send_event(
                EventType.SubscribeDeleted,
                {"subscribe_id": sid, "subscribe_info": info},
            )

        # 用配置里的用户名，与 executor 落地订阅时所用的一致；两边若分叉，管理页会
        # 按另一个名字去查，列表恒空且无法退订。
        return SubscribeManager(
            SubscribeOper(),
            username=self._settings.global_config.username,
            on_deleted=_on_deleted,
            source_lookup=lambda keys: self._history_store().providers_for(keys),
        )

    def blacklist_resolve_media(self, media):
        """仅识别整剧身份，补充跨季忽略别名；不触发订阅。"""
        snapshot = media_snapshot(media)
        meta = MetaInfo(snapshot["title"])
        meta.type = MediaType(snapshot["type"])
        if snapshot["year"]:
            meta.year = snapshot["year"]
        source = media.get("media_source")
        media_id = media.get("media_id")
        if not source or not media_id:
            source, media_id = next(iter(snapshot["ids"].items()))
            if source == "tmdb":
                source = "themoviedb"
        return self.chain.recognize_media(
            meta=meta,
            media_source=source,
            media_id=media_id,
            mtype=MediaType(snapshot["type"]),
        )

    def blacklist_history_store(self):
        """供黑名单入口复用版本对应的历史仓库。"""
        return self._history_store()

    def blacklist_subscribe_manager(self):
        """黑名单写操作沿用本插件订阅的归属检查。"""
        return self._subscribe_manager()
