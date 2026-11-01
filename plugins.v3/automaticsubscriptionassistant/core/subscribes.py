"""订阅手动管理：列出本插件订阅、批量退订、批量暂停/恢复。

读取订阅使用官方查询 SDK 的只读快照；写入依赖注入的 ``oper``，删除后由
``on_deleted`` 回调发送 ``EventType.SubscribeDeleted`` 事件，本模块可离线单测。

退订走主程序标准语义：删除订阅 + 通过回调发送 SubscribeDeleted 事件，触发其他组件清理。
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from app.sdk import queries as subscription_queries
from app.sdk.queries import (
    MAX_QUERY_PAGE_SIZE,
    QueryPageRequest,
    QuerySort,
    QuerySortDirection,
    QuerySortField,
    SubscriptionFilter,
    SubscriptionSnapshot,
)

# 允许的订阅状态：R=订阅中/恢复，P=待定，S=暂停（与主程序 subscribe 状态一致）。
VALID_STATES = ("R", "P", "S")

# 本插件订阅落地时使用的用户名（executor.add(username=...) 与此一致）。
PLUGIN_USERNAME = "自动订阅助手"

# 序列化到前端的订阅字段。媒体身份是 ``media_source`` + ``media_id`` 二元组，
# 单独的 media_id 不足以定位媒体，两者必须成对取用。
_FIELDS = ("id", "name", "year", "type", "media_source", "media_id", "season",
           "episode_group", "poster", "state", "total_episode", "lack_episode", "date",
           "last_update")


def list_subscriptions(username: Optional[str] = None, *, queries=subscription_queries) -> List[SubscriptionSnapshot]:
    """
    使用官方查询 SDK 按稳定顺序读取全部订阅，避免只读取默认第一页。

    :param username: 精确匹配的订阅用户名；None 表示不限用户名
    :param queries: 宿主查询 SDK；测试可注入隔离实现
    :return: 所有匹配订阅的只读快照，查询失败向调用方传播
    """
    filters = SubscriptionFilter(usernames=(username,) if username is not None else ())
    result = []
    page_number = 1
    while True:
        page = queries.list_subscriptions(
            filters=filters,
            page=QueryPageRequest(
                page=page_number, count=MAX_QUERY_PAGE_SIZE,
                sort=QuerySort(field=QuerySortField.ID, direction=QuerySortDirection.ASC)),
        )
        result.extend(page.items)
        if not page.items or not page.has_next:
            return result
        page_number += 1


class SubscribeManager:
    """本插件订阅的手动管理器。"""

    def __init__(self, oper, username: str = PLUGIN_USERNAME,
                 on_deleted: Optional[Callable] = None, *, queries=subscription_queries):
        """
        绑定订阅写入端口与官方查询 SDK，所有写操作均先复核快照中的归属。

        :param oper: 宿主订阅写入接口，仅用于删除和状态更新
        :param username: 本插件创建订阅时使用的用户名
        :param on_deleted: 删除成功后的事件通知回调
        :param queries: 宿主查询 SDK；测试可注入隔离实现
        """
        self.oper = oper                # SubscribeOper（注入，便于测试）
        self.queries = queries
        self.username = username
        self.on_deleted = on_deleted    # on_deleted(sid, sub)：删除成功后回调（插件侧发事件）

    def list_mine(self) -> List[dict]:
        """
        通过官方查询 SDK 列出本插件创建的订阅，映射为前端字典。

        :return: 按配置用户名精确筛选的全部订阅
        """
        subs = list_subscriptions(self.username, queries=self.queries)
        return [self._to_dict(s) for s in subs]

    def _owned(self, sid):
        """
        取属于本插件的订阅，不存在或不属于本插件时返回 None。

        ``list_mine`` 按用户名过滤后才交给前端，但订阅 ID 是自增整数、极易猜到，
        写操作若只凭 ID 就动手，任何能调到本端点的人都能改掉别人的订阅。故写路径
        一律先用同一条用户名判据复核归属。
        """
        sub = self.queries.get_subscription(sid)
        if sub is None or getattr(sub, "username", None) != self.username:
            return None
        return sub

    def delete(self, ids) -> Dict[str, Any]:
        """批量退订本插件的订阅：逐条删除并回调发事件。返回 {"ok","failed"}。

        不属于本插件的 ID 计入 failed，不会被删除。单条异常同样计入 failed。
        """
        ok = 0
        failed = 0
        ok_ids = []
        failed_ids = []
        for sid in ids or []:
            try:
                sub = self._owned(sid)
                if sub is None:
                    failed += 1
                    failed_ids.append(sid)
                    continue
                self.oper.delete(sid)
                if self.on_deleted:
                    self.on_deleted(sid, sub)
                ok += 1
                ok_ids.append(sid)
            except Exception:  # noqa: BLE001 - 单条失败不中断整体
                failed += 1
                failed_ids.append(sid)
        return {"ok": ok, "failed": failed, "ok_ids": ok_ids, "failed_ids": failed_ids}

    def set_state(self, ids, state: str) -> Dict[str, Any]:
        """批量置本插件订阅的状态（R/P/S）。非法状态抛 ValueError。返回 {"ok","failed"}。

        不属于本插件的 ID 计入 failed，不会被改动；``oper.update`` 对不存在的 ID
        只返回 None 而不抛错，故存在性也在此一并判定，避免虚报成功条数。
        """
        if state not in VALID_STATES:
            raise ValueError(f"非法订阅状态: {state}（允许 {VALID_STATES}）")
        ok = 0
        failed = 0
        ok_ids = []
        failed_ids = []
        for sid in ids or []:
            try:
                if self._owned(sid) is None:
                    failed += 1
                    failed_ids.append(sid)
                    continue
                self.oper.update(sid, {"state": state})
                ok += 1
                ok_ids.append(sid)
            except Exception:  # noqa: BLE001 - 单条失败不中断整体
                failed += 1
                failed_ids.append(sid)
        return {"ok": ok, "failed": failed, "ok_ids": ok_ids, "failed_ids": failed_ids}

    @staticmethod
    def _to_dict(sub) -> dict:
        """Subscribe 对象 → 前端 dict（缺字段安全取 None）。"""
        return {f: getattr(sub, f, None) for f in _FIELDS}
