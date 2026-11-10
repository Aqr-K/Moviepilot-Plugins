"""configuration HTTP 端点；使用入口提供的服务，不直接拥有数据库连接。"""

from copy import deepcopy
from typing import Any

from app.schemas.event import ConfigChangeEventData
from app.schemas.types import EventType
from app.sdk.config import settings
from app.sdk.events import eventmanager
from app.sdk.logging import logger

from ..core.config import build_defaults
from ..core.config_migration import backup_config, migrate_config
from ..core.subscription_policy import normalize_subscription_policy


class ConfigurationApiMixin:
    def _upgrade_config(self, config):
        """仅对旧结构执行一次升级；确认备份和持久化成功后才交给运行时。"""
        if not isinstance(config, dict) or not isinstance(
            config.get("providers", {}), dict
        ):
            raise TypeError("插件或来源配置必须为对象，可在全局设置中还原默认配置")
        migrated, changed = deepcopy(config), []
        self._configuration_errors = {}
        for provider in self._providers:
            pid = provider.provider_id
            if pid not in config.get("providers", {}):
                continue
            try:
                result, updated = migrate_config(
                    {"providers": {pid: config["providers"][pid]}}, [provider]
                )
                source = result["providers"][pid]
                if "subscription" in source:
                    source["subscription"] = normalize_subscription_policy(source["subscription"])
                provider.validate_options(source.get("options", {}))
                migrated["providers"][pid] = source
                changed.extend(updated)
            except (ValueError, TypeError) as exc:
                self._configuration_errors[pid] = str(exc)
                logger.warning(
                    f"{self.plugin_name}：{provider.provider_name} 配置异常，仅暂停此来源：{exc}"
                )
        if changed or self._configuration_errors:
            path = backup_config(config, self.get_data_path() / "config-backups")
        if changed:
            if self.update_config(migrated) is False or self.get_config() != migrated:
                raise OSError("新配置写入或回读校验失败，原配置备份已保留")
            logger.info(
                f"{self.plugin_name}：已自动迁移来源配置 {', '.join(changed)}；备份：{path}"
            )
        return migrated

    def api_get_config(self) -> dict[str, Any]:
        """返回当前配置；未保存过时回退为反射生成的默认配置。"""
        config = self.get_config()
        if not config:
            config = build_defaults(
                [provider.get_spec() for provider in self._providers]
            )
        return {
            "code": 0,
            "config": config,
            "provider_errors": getattr(self, "_configuration_errors", {}),
            "warning": getattr(self, "_configuration_error", ""),
        }

    def api_reset_config(self, request: dict | None = None) -> dict[str, Any]:
        """一次性维护：备份后还原配置，来源默认全部关闭，不操作历史或黑名单。"""
        if not isinstance(request, dict) or request.get("confirmed") is not True:
            return {"code": 1, "message": "请先确认还原全部默认配置"}
        try:
            original = self.get_config()
            if original is None:
                original = getattr(self, "_config", {})
            backup_config(original, self.get_data_path() / "config-backups")
            defaults = build_defaults(
                [provider.get_spec() for provider in self._providers]
            )
            self.stop_service()
            if self.update_config(defaults) is False or self.get_config() != defaults:
                raise OSError("默认配置写入或回读失败，原配置备份已保留")
            self.init_plugin(defaults)
            self._refresh_jobs()
            return {
                "code": 0,
                "message": "已还原全部默认配置，插件与所有来源均已关闭",
                "config": defaults,
            }
        except Exception as exc:  # noqa: BLE001 - 维护失败保留备份与数据库内容
            logger.error(f"{self.plugin_name}：还原默认配置失败：{exc}")
            return {"code": 1, "message": f"还原默认配置失败：{exc}"}

    def api_save_config(self, request: dict | None = None) -> dict[str, Any]:
        """保存完整配置并重载：update_config 持久化 + init_plugin 重建调度。"""
        if not isinstance(request, dict):
            return {"code": 1, "message": "请求体必须为配置对象"}
        try:
            original = request
            if not isinstance(request.get("providers", {}), dict):
                raise TypeError("来源配置必须为对象")
            # 未修改的异常来源保留原件，允许先保存、修复其他来源。
            preserved = {}
            current = (
                self.get_config() if getattr(self, "_configuration_errors", {}) else {}
            )
            for pid in getattr(self, "_configuration_errors", {}):
                incoming = (request.get("providers") or {}).get(pid)
                if pid in (request.get("providers") or {}) and incoming == (
                    current.get("providers") or {}
                ).get(pid):
                    preserved[pid] = incoming
            candidate = deepcopy(request)
            for pid in preserved:
                candidate["providers"].pop(pid, None)
            request, migrated = migrate_config(candidate, self._providers)
            providers = request.get("providers", {})
            if not isinstance(providers, dict):
                raise TypeError("来源配置必须为对象")
            for provider in self._providers:
                if provider.provider_id in preserved:
                    continue
                raw = providers.get(provider.provider_id, {})
                if not isinstance(raw, dict) or not isinstance(
                    raw.get("options", {}), dict
                ):
                    raise TypeError("来源选项必须为对象")
                validate = getattr(provider, "validate_options", None)
                if "subscription" in raw:
                    raw["subscription"] = normalize_subscription_policy(raw["subscription"])
                if validate:
                    validate(raw.get("options", {}))
            if preserved:
                request.setdefault("providers", {}).update(preserved)
        except (ValueError, TypeError) as exc:
            return {"code": 1, "message": str(exc)}
        # 状态检测兜底：启用了却无任何可监听内容的来源，保存时自动关闭其开关（与前端一致，防绕过前端直接保存）。
        self._auto_disable_empty_providers(request)
        try:
            if migrated:
                backup_config(original, self.get_data_path() / "config-backups")
            if self.update_config(request) is False:
                return {"code": 1, "message": "配置保存失败，运行配置未变更"}
            # 重新装载：重建 settings/链/调度，并处理其中的一次性开关。
            self.init_plugin(request)
            self._refresh_jobs()
            if not self._database_ready:
                return {
                    "code": 1,
                    "message": "配置已保存，但数据库初始化失败，自动任务未启动",
                }
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
            options = (
                pconf.get("options") if isinstance(pconf.get("options"), dict) else {}
            )
            try:
                if not provider.has_listening(options):
                    pconf["enabled"] = False
                    logger.info(
                        f"{self.plugin_name}：{provider.provider_name} 未配置任何可监听内容，"
                        f"保存时已自动关闭该来源开关。"
                    )
            except Exception as exc:  # noqa: BLE001 - 单源检测失败不影响保存
                logger.warning(
                    f"{self.plugin_name}：{provider.provider_name} 监听状态检测失败（跳过）: {exc}"
                )

    def api_get_share(self) -> dict[str, Any]:
        """读取 MoviePilot 全局『订阅数据共享』(SUBSCRIBE_STATISTIC_SHARE) 当前状态。

        热门媒体来源依赖该主程序开关：关闭时服务端订阅统计接口直接返回空、本来源无法获取数据。
        """
        return {"code": 0, "enabled": bool(settings.SUBSCRIBE_STATISTIC_SHARE)}

    def api_set_share(self, request: dict | None = None) -> dict[str, Any]:
        """开/关 MoviePilot 全局『订阅数据共享』并持久化（改内存 + 落 app.env，无需重启）。

        经官方 settings.update_setting 写入，success 三态——True 已更新 / None 值未变 / False 失败
        （该键被真实 OS 环境变量占用时拒写）；仅真正变更时广播 ConfigChanged 事件。body={"enabled": bool}。
        """
        if not isinstance(request, dict) or "enabled" not in request:
            return {"code": 1, "message": "缺少 enabled"}
        enabled = bool(request.get("enabled"))
        try:
            success, message = settings.update_setting(
                "SUBSCRIBE_STATISTIC_SHARE", enabled
            )
        except Exception as exc:  # noqa: BLE001 - 写设置失败即返回失败，不影响插件本体
            logger.error(f"{self.plugin_name}：设置订阅数据共享失败: {exc}")
            return {
                "code": 1,
                "enabled": bool(settings.SUBSCRIBE_STATISTIC_SHARE),
                "message": f"设置失败: {exc}",
            }
        if success is False:
            # 被真实 OS 环境变量占用等原因拒写：如实回传当前值与原因，前端据此提示手动配置。
            return {
                "code": 1,
                "enabled": bool(settings.SUBSCRIBE_STATISTIC_SHARE),
                "message": message
                or "无法修改：该设置可能由系统环境变量锁定，请手动在 MoviePilot 配置中调整",
            }
        if success:
            # 仅在值真正发生变化时广播（None 表示已是目标值、无需广播）；广播失败不影响已成功的写入。
            try:
                eventmanager.send_event(
                    etype=EventType.ConfigChanged,
                    data=ConfigChangeEventData(
                        key="SUBSCRIBE_STATISTIC_SHARE",
                        value=enabled,
                        change_type="update",
                    ),
                )
            except Exception as exc:  # noqa: BLE001 - 广播失败仅告警，设置本身已成功
                logger.warning(
                    f"{self.plugin_name}：广播配置变更事件失败（不影响设置）: {exc}"
                )
        return {
            "code": 0,
            "enabled": bool(settings.SUBSCRIBE_STATISTIC_SHARE),
            "message": "已更新",
        }
