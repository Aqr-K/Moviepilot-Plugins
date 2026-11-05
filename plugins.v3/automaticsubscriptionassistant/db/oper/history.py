"""历史 SQL 操作；事务由服务层拥有，本层不提交、不建表。"""

from __future__ import annotations

from collections.abc import Iterable
from copy import deepcopy
from contextlib import contextmanager
from typing import TYPE_CHECKING

from sqlalchemy import func

from ..models import SubscribeHandled, SubscribeHistory

if TYPE_CHECKING:
    from ...schemas.history import HistoryRecord

HISTORY_KEY = "history"
HANDLED_STATUSES = frozenset({"subscribed", "media_exists", "subscription_exists"})
MAX_PAGE_SIZE = 500


def _multi(value) -> set | None:
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


def _to_int(value) -> int | None:
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


class HistoryOper:
    """使用调用方会话处理历史与成功账本。"""

    def __init__(self, session):
        """绑定会话，不取得其生命周期所有权。"""
        self.session = session

    @contextmanager
    def _session(self):
        """复用已由服务层开启的事务。"""
        yield self.session

    def is_handled(self, key: str) -> bool:
        """去重键是否已处理过（正向终态）。"""
        if not key:
            return False
        with self._session() as session:
            if session.get(SubscribeHandled, key) is not None:
                return True
            return bool(
                session.query(
                    session.query(SubscribeHistory)
                    .filter(
                        SubscribeHistory.unique == key,
                        SubscribeHistory.status.in_(tuple(HANDLED_STATUSES)),
                    )
                    .exists()
                ).scalar()
            )

    def mark_handled(
        self, key: str, canonical: str | None = None, provider: str = ""
    ) -> None:
        """持久登记精确候选到规范身份的别名，兼容旧的单键调用。"""
        if not key:
            return
        with self._session() as session:
            self._remember(session, key, canonical or key, provider)

    def providers_for(self, keys: Iterable[str]) -> dict[str, str]:
        """批量返回规范身份的首次榜单归属，兼容旧历史并保留修剪后的来源。

        :param keys: 与订阅类型、季号、剧集组一致的强身份键
        :return: 找到可信成功记录的身份到 provider ID 映射
        """
        targets = list(dict.fromkeys(key for key in keys if key))
        if not targets:
            return {}
        result = {}
        with self._session() as session:
            # 分批限制绑定参数数量；来源查询不受历史列表的最大页数影响。
            for start in range(0, len(targets), MAX_PAGE_SIZE):
                batch = targets[start : start + MAX_PAGE_SIZE]
                for key, provider in (
                    session.query(SubscribeHandled.key, SubscribeHandled.provider)
                    .filter(SubscribeHandled.key.in_(batch))
                    .all()
                ):
                    if provider:
                        result[key] = provider
                missing = [key for key in batch if key not in result]
                if missing:
                    for key, provider in (
                        session.query(
                            SubscribeHistory.unique, SubscribeHistory.provider
                        )
                        .filter(
                            SubscribeHistory.unique.in_(missing),
                            SubscribeHistory.status.in_(tuple(HANDLED_STATUSES)),
                        )
                        .all()
                    ):
                        if provider:
                            result[key] = provider
        return result

    @staticmethod
    def _remember(session, key: str, canonical: str, provider: str) -> None:
        """在当前事务内登记成功事实，重复登记保留首次归属。"""
        if session.get(SubscribeHandled, key) is None:
            session.add(
                SubscribeHandled(key=key, canonical=canonical, provider=provider)
            )

    def merge_matches(self, keys, matches):
        """补充命中轨迹，不改变成功状态、首次归属或历史时间。"""
        targets = set(keys)
        targets.update(row.canonical for row in self.session.query(SubscribeHandled).filter(SubscribeHandled.key.in_(list(keys))).all())
        rows = self.session.query(SubscribeHistory).filter(SubscribeHistory.unique.in_(list(targets))).all()
        for row in rows:
            source = deepcopy(row.source_item or {})
            meta = source.setdefault('source_meta', {})
            merged = {(m.get('provider', row.provider), m.get('id')):m for m in meta.get('matches', [])}
            for match in matches:
                merged[(match.get('provider', row.provider), match.get('id'))] = deepcopy(match)
            meta['matches'] = list(merged.values())[-1000:]
            row.source_item = source

    def record(self, rec: HistoryRecord) -> None:
        """写入一条记录：同 unique（媒体身份键）覆盖旧的，跨渠道自动合并为一条。

        正向终态与候选别名在同一事务内写入独立账本；已有成功记录不降级。
        被过滤、未识别和异常不新增成功事实，仍可由其他来源或下一轮重试。
        """
        values = rec.to_dict()
        values["year_num"] = _to_int(values.get("year"))
        with self._session() as session:
            self._upsert(session, values)

    @classmethod
    def _upsert(cls, session, values: dict) -> None:
        """按 unique 插入或更新一行。"""
        row = (
            session.query(SubscribeHistory)
            .filter(SubscribeHistory.unique == values["unique"])
            .one_or_none()
        )
        positive = values["status"] in HANDLED_STATUSES
        if positive:
            cls._remember(
                session, values["unique"], values["unique"], values["provider"]
            )
            if values.get("candidate_key"):
                cls._remember(
                    session,
                    values["candidate_key"],
                    values["unique"],
                    values["provider"],
                )
        if row is None:
            session.add(SubscribeHistory(**values))
            return
        if row.status in HANDLED_STATUSES:
            # 成功事实与首次归属不被后续来源的过滤、异常或预去重结果覆盖。
            return
        for field, value in values.items():
            setattr(row, field, value)

    def flush(self) -> None:
        """兼容旧调用点的空操作：提交由外层服务负责。"""

    def query(
        self,
        provider: str | None = None,
        status: str | None = None,
        mtype: str | None = None,
        keyword: str | None = None,
        year_min=None,
        year_max=None,
        page: int = 1,
        count: int = 50,
    ) -> tuple[list[dict], int]:
        """按 provider/status/type/关键词/发行年份范围 过滤并分页（按 time 倒序），返回(切片, 总数)。

        provider/status/mtype 支持逗号分隔多值（如 ``"douban,maoyan"``）；单值向后兼容。
        year_min/year_max 为发行年份闭区间（留空不约束），解析不出年份的记录在有区间
        约束时不入选。keyword 对标题做不区分大小写的子串匹配。
        """
        page = max(_to_int(page) or 1, 1)
        count = min(max(_to_int(count) or 1, 1), MAX_PAGE_SIZE)
        with self._session() as session:
            query = self._filtered(
                session, provider, status, mtype, keyword, year_min, year_max
            )
            total = query.count()
            rows = (
                query.order_by(SubscribeHistory.time.desc(), SubscribeHistory.id.desc())
                .offset((page - 1) * count)
                .limit(count)
                .all()
            )
            return [r.to_dict() for r in rows], total

    @staticmethod
    def _filtered(session, provider, status, mtype, keyword, year_min, year_max):
        """按各筛选条件组装查询。"""
        query = session.query(SubscribeHistory)
        providers = _multi(provider)
        if providers is not None:
            query = query.filter(SubscribeHistory.provider.in_(tuple(providers)))
        statuses = _multi(status)
        if statuses is not None:
            query = query.filter(SubscribeHistory.status.in_(tuple(statuses)))
        mtypes = _multi(mtype)
        if mtypes is not None:
            query = query.filter(SubscribeHistory.type.in_(tuple(mtypes)))
        kw = (keyword or "").strip().lower()
        if kw:
            # 两端都转小写再匹配，不依赖各数据库 LIKE 默认的大小写敏感性。
            query = query.filter(func.lower(SubscribeHistory.title).like(f"%{kw}%"))
        ymin = _to_int(year_min)
        ymax = _to_int(year_max)
        if ymin is not None or ymax is not None:
            query = query.filter(SubscribeHistory.year_num.isnot(None))
            if ymin is not None:
                query = query.filter(SubscribeHistory.year_num >= ymin)
            if ymax is not None:
                query = query.filter(SubscribeHistory.year_num <= ymax)
        return query

    def uniques(
        self,
        provider: str | None = None,
        status: str | None = None,
        mtype: str | None = None,
        keyword: str | None = None,
        year_min=None,
        year_max=None,
    ) -> list[str]:
        """按同一套筛选条件取全部身份键，供「选全部」一次取齐。

        只取一列，不受分页上限约束：前端全选要的是键集合，拉整行记录既浪费又会被
        单页上限截断。
        """
        with self._session() as session:
            query = self._filtered(
                session, provider, status, mtype, keyword, year_min, year_max
            )
            return [
                row.unique for row in query.with_entities(SubscribeHistory.unique).all()
            ]

    def get(self, unique: str) -> dict | None:
        """按 unique 取一条记录（未找到返回 None），供「重新识别」还原候选。"""
        if not unique:
            return None
        with self._session() as session:
            row = (
                session.query(SubscribeHistory)
                .filter(SubscribeHistory.unique == unique)
                .one_or_none()
            )
            return row.to_dict() if row is not None else None

    def delete(self, unique: str) -> bool:
        """删除指定 unique 的记录。"""
        if not unique:
            return False
        with self._session() as session:
            session.query(SubscribeHandled).filter(
                SubscribeHandled.canonical == unique
            ).delete(synchronize_session=False)
            removed = (
                session.query(SubscribeHistory)
                .filter(SubscribeHistory.unique == unique)
                .delete(synchronize_session=False)
            )
        return bool(removed)

    def delete_many(self, uniques) -> int:
        """批量删除多条记录。返回实际删除条数。"""
        targets = {u for u in (uniques or []) if u}
        if not targets:
            return 0
        with self._session() as session:
            session.query(SubscribeHandled).filter(
                SubscribeHandled.canonical.in_(tuple(targets))
            ).delete(synchronize_session=False)
            return (
                session.query(SubscribeHistory)
                .filter(SubscribeHistory.unique.in_(tuple(targets)))
                .delete(synchronize_session=False)
            )

    def clear(self, provider: str | None = None) -> None:
        """清空全部或某来源的历史。"""
        with self._session() as session:
            query = session.query(SubscribeHistory)
            handled = session.query(SubscribeHandled)
            if provider is not None:
                query = query.filter(SubscribeHistory.provider == provider)
                targets = {row.unique for row in query.all()}
                targets.update(
                    row.canonical
                    for row in handled.filter(
                        SubscribeHandled.provider == provider
                    ).all()
                )
                handled = handled.filter(SubscribeHandled.canonical.in_(tuple(targets)))
            handled.delete(synchronize_session=False)
            query.delete(synchronize_session=False)

    def stats(self) -> dict:
        """统计各 provider / 各 status 计数。"""
        with self._session() as session:
            by_provider = {
                (p or "unknown"): n
                for p, n in session.query(
                    SubscribeHistory.provider, func.count(SubscribeHistory.id)
                )
                .group_by(SubscribeHistory.provider)
                .all()
            }
            by_status = {
                (s or "unknown"): n
                for s, n in session.query(
                    SubscribeHistory.status, func.count(SubscribeHistory.id)
                )
                .group_by(SubscribeHistory.status)
                .all()
            }
            total = session.query(func.count(SubscribeHistory.id)).scalar() or 0
        return {"total": total, "by_provider": by_provider, "by_status": by_status}

    def count(self) -> int:
        """历史记录总数。"""
        with self._session() as session:
            return session.query(func.count(SubscribeHistory.id)).scalar() or 0

    def prune(self, keep: int) -> int:
        """只保留最近 ``keep`` 条历史，删除更早的记录。返回删除条数。

        ``keep`` 非正数时不做任何删除。

        :param keep: 保留条数
        """
        keep = _to_int(keep) or 0
        if keep <= 0:
            return 0
        with self._session() as session:
            # 修剪只影响展示记录；把旧版本尚未迁入账本的成功事实一起保留下来。
            for row in (
                session.query(SubscribeHistory)
                .filter(SubscribeHistory.status.in_(tuple(HANDLED_STATUSES)))
                .all()
            ):
                self._remember(session, row.unique, row.unique, row.provider)
                if row.candidate_key:
                    self._remember(session, row.candidate_key, row.unique, row.provider)
            kept = [
                row.id
                for row in session.query(SubscribeHistory.id)
                .order_by(SubscribeHistory.time.desc(), SubscribeHistory.id.desc())
                .limit(keep)
                .all()
            ]
            if not kept:
                return 0
            return (
                session.query(SubscribeHistory)
                .filter(SubscribeHistory.id.notin_(tuple(kept)))
                .delete(synchronize_session=False)
            )

    def values(self) -> list[dict]:
        """全部记录（按 time 倒序），供导出与存量比对。"""
        with self._session() as session:
            rows = (
                session.query(SubscribeHistory)
                .order_by(SubscribeHistory.time.desc(), SubscribeHistory.id.desc())
                .all()
            )
            return [r.to_dict() for r in rows]
