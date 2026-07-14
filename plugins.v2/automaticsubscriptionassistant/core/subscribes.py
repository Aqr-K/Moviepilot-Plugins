"""订阅手动管理：列出本插件订阅、批量退订、批量暂停/恢复。

与订阅落地（executor/runner）解耦：只依赖注入的 ``oper``（SubscribeOper 鸭子类型）与
``on_deleted`` 回调（由插件侧发 ``EventType.SubscribeDeleted`` 事件），本模块可离线单测。

退订走主程序标准语义：删除订阅 + 通过回调发送 SubscribeDeleted 事件，触发其他组件清理。
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional

# 允许的订阅状态：R=订阅中/恢复，P=待定，S=暂停（与主程序 subscribe 状态一致）。
VALID_STATES = ("R", "P", "S")

# 本插件订阅落地时使用的用户名（executor.add(username=...) 与此一致）。
PLUGIN_USERNAME = "自动订阅助手"

# 序列化到前端的订阅字段。
_FIELDS = ("id", "name", "year", "type", "tmdbid", "doubanid", "bangumiid", "season",
           "poster", "state", "total_episode", "lack_episode", "date", "last_update")


class SubscribeManager:
    """本插件订阅的手动管理器。"""

    def __init__(self, oper, username: str = PLUGIN_USERNAME,
                 on_deleted: Optional[Callable] = None):
        self.oper = oper                # SubscribeOper（注入，便于测试）
        self.username = username
        self.on_deleted = on_deleted    # on_deleted(sid, sub)：删除成功后回调（插件侧发事件）

    def list_mine(self) -> List[dict]:
        """列出本插件创建的订阅（按 username 过滤），映射为前端 dict。"""
        subs = self.oper.list_by_username(self.username) or []
        return [self._to_dict(s) for s in subs]

    def delete(self, ids) -> Dict[str, int]:
        """批量退订：逐条删除并回调发事件。返回 {"ok","failed"}。单条异常计入 failed。"""
        ok = 0
        failed = 0
        for sid in ids or []:
            try:
                sub = self.oper.get(sid)
                if sub is None:
                    failed += 1
                    continue
                self.oper.delete(sid)
                if self.on_deleted:
                    self.on_deleted(sid, sub)
                ok += 1
            except Exception:  # noqa: BLE001 - 单条失败不中断整体
                failed += 1
        return {"ok": ok, "failed": failed}

    def set_state(self, ids, state: str) -> Dict[str, int]:
        """批量置状态（R/P/S）。非法状态抛 ValueError。返回 {"ok","failed"}。"""
        if state not in VALID_STATES:
            raise ValueError(f"非法订阅状态: {state}（允许 {VALID_STATES}）")
        ok = 0
        failed = 0
        for sid in ids or []:
            try:
                self.oper.update(sid, {"state": state})
                ok += 1
            except Exception:  # noqa: BLE001 - 单条失败不中断整体
                failed += 1
        return {"ok": ok, "failed": failed}

    @staticmethod
    def _to_dict(sub) -> dict:
        """Subscribe 对象 → 前端 dict（缺字段安全取 None）。"""
        return {f: getattr(sub, f, None) for f in _FIELDS}
