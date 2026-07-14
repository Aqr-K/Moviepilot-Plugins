"""历史存储：封装插件 KV 读写并维护去重集合。

存储 key 固定 ``'history'``，值为 ``List[dict]``。构造时从 KV 载入并重建去重集合，
写入内存后由 ``flush()`` 统一落盘，降低 KV 写频率。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional, Tuple

if TYPE_CHECKING:
    from .models import HistoryRecord

# 插件 KV 中历史记录的固定键。
HISTORY_KEY = "history"

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
        # get_data/save_data/del_data 为 _PluginBase 的绑定方法。
        self._records: List[dict] = list(get_data(HISTORY_KEY) or [])
        self._handled = _handled_uniques(self._records)
        self._save = save_data
        self._del = del_data

    def is_handled(self, key: str) -> bool:
        """去重键是否已处理过（正向终态）。"""
        return key in self._handled

    def mark_handled(self, key: str) -> None:
        """标记去重键为已处理（由 executor 对正向终态显式调用）。"""
        self._handled.add(key)

    def record(self, rec: "HistoryRecord") -> None:
        """写入一条记录：同 unique（媒体身份键）先移除旧的再追加，跨渠道自动合并为一条。

        注意：本方法**不**修改已处理集合——是否「已处理」由 executor 依据终态显式
        ``mark_handled``，以便被过滤/未识别的条目照常留一条但仍可被其他渠道重试。
        """
        self._records = [r for r in self._records if r.get("unique") != rec.unique]
        self._records.append(rec.to_dict())

    def flush(self) -> None:
        """把内存记录整体落盘。"""
        self._save(HISTORY_KEY, self._records)

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
            r for r in self._records
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
        return next((r for r in self._records if r.get("unique") == unique), None)

    def delete(self, unique: str) -> bool:
        """删除指定 unique 的记录并落盘，同时从去重集合移除。"""
        before = len(self._records)
        self._records = [r for r in self._records if r.get("unique") != unique]
        removed = len(self._records) != before
        self._handled.discard(unique)
        if removed:
            self.flush()
        return removed

    def delete_many(self, uniques) -> int:
        """批量删除多条记录，仅一次落盘。返回实际删除条数。"""
        targets = {u for u in (uniques or []) if u}
        if not targets:
            return 0
        before = len(self._records)
        self._records = [r for r in self._records if r.get("unique") not in targets]
        removed = before - len(self._records)
        self._handled -= targets
        if removed:
            self.flush()
        return removed

    def clear(self, provider: Optional[str] = None) -> None:
        """清空全部或某来源的历史，并落盘。"""
        if provider is None:
            self._records = []
            self._handled = set()
        else:
            self._records = [r for r in self._records if r.get("provider") != provider]
            self._handled = _handled_uniques(self._records)
        self.flush()

    def stats(self) -> dict:
        """统计各 provider / 各 status 计数。"""
        by_provider: dict = {}
        by_status: dict = {}
        for r in self._records:
            provider = r.get("provider") or "unknown"
            status = r.get("status") or "unknown"
            by_provider[provider] = by_provider.get(provider, 0) + 1
            by_status[status] = by_status.get(status, 0) + 1
        return {"total": len(self._records), "by_provider": by_provider, "by_status": by_status}
