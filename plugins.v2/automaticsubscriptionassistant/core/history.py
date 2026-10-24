"""v2 历史存储：共享锁内读取最新 KV、按身份合并并立即提交。

各运行任务不再保留全量快照，flush 不执行写入，避免旧任务覆盖另一来源或用户的删除。
成功事实与候选别名存入独立键；只有显式删除历史才清除此身份的处理状态。
"""
from __future__ import annotations

from threading import RLock
from typing import TYPE_CHECKING, List, Optional, Tuple

if TYPE_CHECKING:
    from .models import HistoryRecord

# 插件 KV 中历史记录的固定键。
HISTORY_KEY = "history"
HANDLED_KEY = "history_handled"
_KV_LOCK = RLock()

# 「已处理」正向终态：命中即可跨渠道/跨运行跳过识别。被过滤/未识别/异常者不入此集合，
# 仍可被其他渠道或下一轮重试（避免漏订）。取值为 SubscribeStatus.value。
HANDLED_STATUSES = frozenset({"subscribed", "media_exists", "subscription_exists"})


def _handled_uniques(records: List[dict]) -> set:
    """从记录集合重建已处理去重键集合（仅正向终态）。"""
    return {r.get("unique") for r in records
            if r.get("unique") and r.get("status") in HANDLED_STATUSES}


def _multi(value) -> Optional[set]:
    """逗号分隔字符串 / 列表 → 去空白后的集合；空或 None → None（表示不过滤）。

    单值（如 ``"douban"``）归一为 ``{"douban"}``，与旧的等值过滤语义一致（向后兼容）。
    """
    if value is None:
        return None
    if isinstance(value, (list, tuple, set)):
        items = [str(v).strip() for v in value]
    else:
        items = [p.strip() for p in str(value).split(",")]
    items = [p for p in items if p]
    return set(items) or None


def _to_int(value) -> Optional[int]:
    """宽松转 int：None/空串/不可解析 → None。"""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        return int(s)
    except (TypeError, ValueError):
        return None


def _year_in_range(year, ymin: Optional[int], ymax: Optional[int]) -> bool:
    """发行年份闭区间判断；无区间约束恒真；年份不可解析且有约束时判否。"""
    if ymin is None and ymax is None:
        return True
    y = _to_int(year)
    if y is None:
        return False
    if ymin is not None and y < ymin:
        return False
    if ymax is not None and y > ymax:
        return False
    return True


class HistoryStore:
    """历史记录仓库 + 去重键集合。"""

    def __init__(self, get_data, save_data, del_data):
        """保存插件 KV 端口；所有实例在操作时读取最新状态。"""
        self._get = get_data
        self._save = save_data
        self._del = del_data

    def _read(self) -> List[dict]:
        """读取当前历史副本，调用者不直接修改 KV 返回值。"""
        return [dict(row) for row in (self._get(HISTORY_KEY) or []) if isinstance(row, dict)]

    def is_handled(self, key: str) -> bool:
        """查独立成功账本，兼容旧版仅存在于历史中的正向终态。"""
        if not key:
            return False
        with _KV_LOCK:
            if key in (self._get(HANDLED_KEY) or {}):
                return True
            return any(row.get("status") in HANDLED_STATUSES
                       and key in (row.get("unique"), row.get("candidate_key"))
                       for row in self._read())

    def mark_handled(self, key: str, canonical: Optional[str] = None, provider: str = "") -> None:
        """立即保存精确候选别名和规范身份。"""
        if not key:
            return
        with _KV_LOCK:
            handled = dict(self._get(HANDLED_KEY) or {})
            handled.setdefault(key, {"canonical": canonical or key, "provider": provider})
            self._save(HANDLED_KEY, handled)

    def record(self, rec: "HistoryRecord") -> None:
        """合并最新记录并提交；首次成功记录不被后续结果覆盖。"""
        with _KV_LOCK:
            records = self._read()
            existing = next((row for row in records if row.get("unique") == rec.unique), None)
            if rec.status in HANDLED_STATUSES:
                self.mark_handled(rec.unique, provider=rec.provider)
                if rec.candidate_key:
                    self.mark_handled(rec.candidate_key, rec.unique, rec.provider)
            if existing and existing.get("status") in HANDLED_STATUSES:
                return
            records = [row for row in records if row.get("unique") != rec.unique]
            records.append(rec.to_dict())
            self._save(HISTORY_KEY, records)

    def flush(self) -> None:
        """兼容旧调用点；写入已在各操作内提交，不再覆盖全量快照。"""

    def query(self, provider: Optional[str] = None, status: Optional[str] = None,
              mtype: Optional[str] = None, keyword: Optional[str] = None,
              year_min=None, year_max=None,
              page: int = 1, count: int = 50) -> Tuple[List[dict], int]:
        """按 provider/status/type/关键词/发行年份范围 过滤并分页（按 time 倒序），返回(切片, 总数)。

        provider/status/mtype 支持逗号分隔多值（如 ``"douban,maoyan"``）；单值向后兼容。
        year_min/year_max 为发行年份闭区间（留空不约束）。
        keyword 对标题做不区分大小写的子串匹配。
        """
        kw = (keyword or "").strip().lower()
        providers = _multi(provider)
        statuses = _multi(status)
        mtypes = _multi(mtype)
        ymin = _to_int(year_min)
        ymax = _to_int(year_max)
        filtered = [
            r for r in self._read()
            if (providers is None or r.get("provider") in providers)
            and (statuses is None or r.get("status") in statuses)
            and (mtypes is None or r.get("type") in mtypes)
            and (not kw or kw in (r.get("title") or "").lower())
            and _year_in_range(r.get("year"), ymin, ymax)
        ]
        filtered.sort(key=lambda r: r.get("time") or "", reverse=True)
        total = len(filtered)
        page = max(int(page or 1), 1)
        count = max(int(count or 1), 1)
        start = (page - 1) * count
        return filtered[start:start + count], total

    def get(self, unique: str) -> Optional[dict]:
        """按 unique 取一条记录（未找到返回 None），供「重新识别」还原候选。"""
        return next((r for r in self._read() if r.get("unique") == unique), None)

    def _forget(self, targets: set) -> None:
        """在共享临界区内删除这些规范身份及其候选别名。"""
        handled = dict(self._get(HANDLED_KEY) or {})
        handled = {key: value for key, value in handled.items()
                   if key not in targets and value.get("canonical") not in targets}
        self._save(HANDLED_KEY, handled)

    def delete(self, unique: str) -> bool:
        """删除最新历史与对应成功事实，不恢复其他任务持有的旧数据。"""
        return bool(self.delete_many([unique]))

    def delete_many(self, uniques) -> int:
        """一次临界区内合并批量删除，并清除候选映射。"""
        targets = {key for key in (uniques or []) if key}
        with _KV_LOCK:
            records = self._read()
            remaining = [row for row in records if row.get("unique") not in targets]
            self._forget(targets)
            if len(remaining) != len(records):
                self._save(HISTORY_KEY, remaining)
            return len(records) - len(remaining)

    def clear(self, provider: Optional[str] = None) -> None:
        """显式清空历史同时解除对应成功状态。"""
        with _KV_LOCK:
            if provider is None:
                self._save(HISTORY_KEY, [])
                self._save(HANDLED_KEY, {})
                return
            records = self._read()
            targets = {row.get("unique") for row in records if row.get("provider") == provider}
            handled = self._get(HANDLED_KEY) or {}
            targets.update(value.get("canonical") for value in handled.values()
                           if value.get("provider") == provider)
            self._forget(targets)
            self._save(HISTORY_KEY, [row for row in records if row.get("provider") != provider])

    def stats(self) -> dict:
        """统计各 provider / 各 status 计数。"""
        by_provider: dict = {}
        by_status: dict = {}
        records = self._read()
        for r in records:
            provider = r.get("provider") or "unknown"
            status = r.get("status") or "unknown"
            by_provider[provider] = by_provider.get(provider, 0) + 1
            by_status[status] = by_status.get(status, 0) + 1
        return {"total": len(records), "by_provider": by_provider, "by_status": by_status}
