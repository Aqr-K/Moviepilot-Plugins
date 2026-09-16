"""历史存储：读写插件自有表 ``subscribe_history``。

每个操作各自开事务、按行读写，写入即提交。历史记录曾整体存放在插件 KV 的单个值里，
那种形态下每个调用方都持有一份全量快照、落盘时整体覆盖，两个来源同时运行或用户在
运行期间删记录，后提交者会把先提交者的改动整体抹掉；按行读写不再有这个问题，查询与
分页也交给 SQL，不必把全表载入内存。

筛选与排序全部下推 SQL：``time`` 是 ``"%Y-%m-%d %H:%M:%S"`` 文本、字典序即时间序，
可直接排序；发行年份区间比较 ``year_num`` 整数列，不对文本列做 CAST。
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from .tables import Base, SubscribeHistory

if TYPE_CHECKING:
    from .models import HistoryRecord

# 历史记录在迁移前所用的插件 KV 键，仅存量迁移时读取。
HISTORY_KEY = "history"

# 「已处理」正向终态：命中即可跨渠道/跨运行跳过识别。被过滤/未识别/异常者不入此集合，
# 仍可被其他渠道或下一轮重试（避免漏订）。取值为 SubscribeStatus.value。
HANDLED_STATUSES = frozenset({"subscribed", "media_exists", "subscription_exists"})

# 单次查询允许返回的最大条数，挡住超大 count 造成的巨型响应。
MAX_PAGE_SIZE = 500

# 已确保建过表的 engine，避免每次构造都往数据库发一轮存在性检查。
_PREPARED_ENGINES: set = set()


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


def ensure_schema(engine) -> None:
    """按需建表，可重复调用。

    宿主在 ``init_plugin`` 之后才按 ``get_database_models()`` 建表，而插件在
    ``init_plugin`` 期间就可能读写历史，故存储层自带这道幂等兜底。

    :param engine: 插件自有库的 engine
    """
    key = id(engine)
    if key in _PREPARED_ENGINES:
        return
    Base.metadata.create_all(engine, checkfirst=True)
    _PREPARED_ENGINES.add(key)


class HistoryStore:
    """历史记录仓库。"""

    def __init__(self, session_factory):
        """
        :param session_factory: 无参可调用，每次返回一个新的 SQLAlchemy 会话
        """
        self._session_factory = session_factory
        # 本实例内显式标记过的身份键。正向终态本身由记录的 status 表达，此集合只覆盖
        # 「标记了但还没落一条记录」的调用顺序，不承担持久化职责。
        self._marked: set = set()
        self._schema_ready = False

    @contextmanager
    def _session(self):
        """开一个会话，正常结束即提交，异常回滚，最后必定关闭。"""
        session = self._session_factory()
        if not self._schema_ready:
            ensure_schema(session.get_bind())
            self._schema_ready = True
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def is_handled(self, key: str) -> bool:
        """去重键是否已处理过（正向终态）。"""
        if not key:
            return False
        if key in self._marked:
            return True
        with self._session() as session:
            return bool(session.query(
                session.query(SubscribeHistory)
                .filter(SubscribeHistory.unique == key,
                        SubscribeHistory.status.in_(tuple(HANDLED_STATUSES)))
                .exists()
            ).scalar())

    def mark_handled(self, key: str) -> None:
        """标记去重键为已处理（由 executor 对正向终态显式调用）。"""
        if key:
            self._marked.add(key)

    def record(self, rec: "HistoryRecord") -> None:
        """写入一条记录：同 unique（媒体身份键）覆盖旧的，跨渠道自动合并为一条。

        注意：本方法**不**影响是否「已处理」的判定——那取决于记录的 ``status``，
        以便被过滤/未识别的条目照常留一条但仍可被其他渠道重试。
        """
        values = rec.to_dict()
        values["year_num"] = _to_int(values.get("year"))
        try:
            with self._session() as session:
                self._upsert(session, values)
        except IntegrityError:
            # 另一个并发写入抢先插入了同一 unique，改按更新重试一次。
            with self._session() as session:
                self._upsert(session, values)

    @staticmethod
    def _upsert(session, values: dict) -> None:
        """按 unique 插入或更新一行。"""
        row = (session.query(SubscribeHistory)
               .filter(SubscribeHistory.unique == values["unique"])
               .one_or_none())
        if row is None:
            session.add(SubscribeHistory(**values))
            return
        for field, value in values.items():
            setattr(row, field, value)

    def flush(self) -> None:
        """兼容旧调用点的空操作：写入在 ``record()`` 内即已提交。"""

    def query(self, provider: Optional[str] = None, status: Optional[str] = None,
              mtype: Optional[str] = None, keyword: Optional[str] = None,
              year_min=None, year_max=None,
              page: int = 1, count: int = 50) -> Tuple[List[dict], int]:
        """按 provider/status/type/关键词/发行年份范围 过滤并分页（按 time 倒序），返回(切片, 总数)。

        provider/status/mtype 支持逗号分隔多值（如 ``"douban,maoyan"``）；单值向后兼容。
        year_min/year_max 为发行年份闭区间（留空不约束），解析不出年份的记录在有区间
        约束时不入选。keyword 对标题做不区分大小写的子串匹配。
        """
        page = max(_to_int(page) or 1, 1)
        count = min(max(_to_int(count) or 1, 1), MAX_PAGE_SIZE)
        with self._session() as session:
            query = self._filtered(session, provider, status, mtype, keyword,
                                   year_min, year_max)
            total = query.count()
            rows = (query.order_by(SubscribeHistory.time.desc(),
                                   SubscribeHistory.id.desc())
                    .offset((page - 1) * count).limit(count).all())
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

    def uniques(self, provider: Optional[str] = None, status: Optional[str] = None,
                mtype: Optional[str] = None, keyword: Optional[str] = None,
                year_min=None, year_max=None) -> List[str]:
        """按同一套筛选条件取全部身份键，供「选全部」一次取齐。

        只取一列，不受分页上限约束：前端全选要的是键集合，拉整行记录既浪费又会被
        单页上限截断。
        """
        with self._session() as session:
            query = self._filtered(session, provider, status, mtype, keyword,
                                   year_min, year_max)
            return [row.unique for row in
                    query.with_entities(SubscribeHistory.unique).all()]

    def get(self, unique: str) -> Optional[dict]:
        """按 unique 取一条记录（未找到返回 None），供「重新识别」还原候选。"""
        if not unique:
            return None
        with self._session() as session:
            row = (session.query(SubscribeHistory)
                   .filter(SubscribeHistory.unique == unique).one_or_none())
            return row.to_dict() if row is not None else None

    def delete(self, unique: str) -> bool:
        """删除指定 unique 的记录。"""
        if not unique:
            return False
        self._marked.discard(unique)
        with self._session() as session:
            removed = (session.query(SubscribeHistory)
                       .filter(SubscribeHistory.unique == unique)
                       .delete(synchronize_session=False))
        return bool(removed)

    def delete_many(self, uniques) -> int:
        """批量删除多条记录。返回实际删除条数。"""
        targets = {u for u in (uniques or []) if u}
        if not targets:
            return 0
        self._marked -= targets
        with self._session() as session:
            return (session.query(SubscribeHistory)
                    .filter(SubscribeHistory.unique.in_(tuple(targets)))
                    .delete(synchronize_session=False))

    def clear(self, provider: Optional[str] = None) -> None:
        """清空全部或某来源的历史。"""
        self._marked = set()
        with self._session() as session:
            query = session.query(SubscribeHistory)
            if provider is not None:
                query = query.filter(SubscribeHistory.provider == provider)
            query.delete(synchronize_session=False)

    def stats(self) -> dict:
        """统计各 provider / 各 status 计数。"""
        with self._session() as session:
            by_provider = {
                (p or "unknown"): n for p, n in
                session.query(SubscribeHistory.provider,
                              func.count(SubscribeHistory.id))
                .group_by(SubscribeHistory.provider).all()
            }
            by_status = {
                (s or "unknown"): n for s, n in
                session.query(SubscribeHistory.status,
                              func.count(SubscribeHistory.id))
                .group_by(SubscribeHistory.status).all()
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
            kept = [row.id for row in
                    session.query(SubscribeHistory.id)
                    .order_by(SubscribeHistory.time.desc(),
                              SubscribeHistory.id.desc())
                    .limit(keep).all()]
            if not kept:
                return 0
            return (session.query(SubscribeHistory)
                    .filter(SubscribeHistory.id.notin_(tuple(kept)))
                    .delete(synchronize_session=False))

    def values(self) -> List[dict]:
        """全部记录（按 time 倒序），供导出与存量比对。"""
        with self._session() as session:
            rows = (session.query(SubscribeHistory)
                    .order_by(SubscribeHistory.time.desc(),
                              SubscribeHistory.id.desc()).all())
            return [r.to_dict() for r in rows]
