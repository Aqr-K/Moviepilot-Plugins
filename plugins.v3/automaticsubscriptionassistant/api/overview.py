"""overview HTTP 端点；使用入口提供的服务，不直接拥有数据库连接。"""

from typing import Any

from app.sdk.logging import logger

from ..core.config import ProviderConfig
from ..core.i18n import localize_provider_name


class OverviewApiMixin:
    def api_status(self, lang: str | None = None) -> dict[str, Any]:
        """返回总开关、各来源启用状态与历史统计（来源名按 lang 本地化）。"""
        providers = []
        for provider in self._providers:
            spec = provider.get_spec()
            pconf = ProviderConfig(self._settings.provider_raw(spec.provider_id), spec)
            providers.append(
                {
                    "provider_id": spec.provider_id,
                    "provider_name": localize_provider_name(
                        spec.provider_id, spec.provider_name, lang
                    ),
                    "enabled": pconf.enabled,
                    "notify": pconf.notify,
                    "cron": pconf.cron,
                }
            )
        with self._run_lock:
            running = list(self._run_state.values())
        return {
            "enabled": self._settings.global_config.enabled,
            "providers": providers,
            "stats": self._history_store().stats() if self._database_ready else None,
            "running": running,
            "database": {"ready": self._database_ready, "error": self._database_error},
        }

    def api_dashboard(self, lang: str | None = None) -> dict[str, Any]:
        """提供只读概览；历史条数为当前保留量，不冒充累计订阅或执行次数。"""
        try:
            status = self.api_status(lang=lang)
            subscriptions = self._subscribe_manager().list_mine()
            recent, _ = self._history_store().query(
                status="subscribed", page=1, count=5
            )
            return {
                "code": 0,
                **status,
                "counts": {
                    "history": status["stats"]["total"],
                    "subscriptions": len(subscriptions),
                    "paused": sum(row.get("state") == "S" for row in subscriptions),
                    "blacklist": len(self.blacklist_store().list()),
                },
                "recent": recent,
            }
        except Exception as exc:  # noqa: BLE001 - 单个组件失败不影响宿主仪表盘
            logger.error(f"{self.plugin_name}：读取仪表盘概览失败: {exc}")
            return {"code": 1, "message": "读取仪表盘概览失败，请稍后重试"}
