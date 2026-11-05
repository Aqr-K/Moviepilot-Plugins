"""subscriptions HTTP 端点；使用入口提供的服务，不直接拥有数据库连接。"""

from typing import Any

from app.sdk.logging import logger

from ..core.i18n import localize_provider_name
from ..core.registry import registry


class SubscriptionsApiMixin:
    def api_subscribes(self, lang: str | None = None) -> dict[str, Any]:
        """列出本插件创建的订阅及本地化的榜单来源。"""
        try:
            rows = self._subscribe_manager().list_mine()
            for row in rows:
                provider_id = row.get("provider")
                provider = registry.get(provider_id) if provider_id else None
                name = provider.provider_name if provider is not None else provider_id
                row["provider_name"] = (
                    localize_provider_name(provider_id, name, lang)
                    if provider_id
                    else None
                )
            return {"list": rows, "total": len(rows)}
        except Exception as exc:  # noqa: BLE001
            logger.error(f"{self.plugin_name}：读取订阅列表失败: {exc}")
            return {"list": [], "total": 0, "message": f"读取失败: {exc}"}

    def api_subscribes_delete(self, request: dict | None = None) -> dict[str, Any]:
        """批量退订（body={"ids":[...]}）。"""
        ids = (request or {}).get("ids") if isinstance(request, dict) else None
        if not isinstance(ids, list) or not ids:
            return {"code": 1, "message": "缺少 ids 列表"}
        try:
            res = self._subscribe_manager().delete(ids)
            return {
                "code": 0,
                "message": f"已退订 {res['ok']} 个"
                + (f"，{res['failed']} 个失败" if res["failed"] else ""),
                **res,
            }
        except Exception as exc:  # noqa: BLE001
            logger.error(f"{self.plugin_name}：批量退订失败: {exc}")
            return {"code": 1, "message": f"退订失败: {exc}"}

    def api_subscribes_state(self, request: dict | None = None) -> dict[str, Any]:
        """批量暂停/恢复（body={"ids":[...],"state":"S|R"}）。"""
        body = request if isinstance(request, dict) else {}
        ids = body.get("ids")
        state = body.get("state")
        if not isinstance(ids, list) or not ids:
            return {"code": 1, "message": "缺少 ids 列表"}
        try:
            res = self._subscribe_manager().set_state(ids, state)
            label = "暂停" if state == "S" else "恢复"
            return {
                "code": 0,
                "message": f"已{label} {res['ok']} 个"
                + (f"，{res['failed']} 个失败" if res["failed"] else ""),
                **res,
            }
        except ValueError as exc:
            return {"code": 1, "message": str(exc)}
        except Exception as exc:  # noqa: BLE001
            logger.error(f"{self.plugin_name}：批量置状态失败: {exc}")
            return {"code": 1, "message": f"操作失败: {exc}"}
