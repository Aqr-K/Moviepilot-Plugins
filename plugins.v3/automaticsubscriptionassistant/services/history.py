"""历史服务：统一事务、回滚和竞争重试，SQL 由 HistoryOper 承担。"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy.exc import IntegrityError

from ..database.lifecycle import DatabaseSession
from ..db.oper.history import HistoryOper
from ..schemas.history import HistoryRecord


class HistoryStore:
    def __init__(self, session_factory):
        self._database = DatabaseSession(session_factory)
        self._session_factory = session_factory

    def _session(self):
        return self._database.session()

    def _call(self, name, *args, **kwargs):
        for attempt in range(2):
            try:
                with self._session() as session:
                    return getattr(HistoryOper(session), name)(*args, **kwargs)
            except IntegrityError:
                if attempt or name not in {"record", "mark_handled"}:
                    raise

    def is_handled(self, key: str) -> bool:
        return self._call("is_handled", key)

    def mark_handled(
        self, key: str, canonical: str | None = None, provider: str = ""
    ) -> None:
        return self._call("mark_handled", key, canonical, provider)

    def providers_for(self, keys: Iterable[str]) -> dict[str, str]:
        return self._call("providers_for", keys)

    def merge_matches(self, keys, matches):
        return self._call("merge_matches", keys, matches)

    def record(self, rec: HistoryRecord) -> None:
        return self._call("record", rec)

    def flush(self) -> None:
        # 每次写入已独立提交，无需再创建空事务。
        return None

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
        return self._call(
            "query", provider, status, mtype, keyword, year_min, year_max, page, count
        )

    def uniques(
        self,
        provider: str | None = None,
        status: str | None = None,
        mtype: str | None = None,
        keyword: str | None = None,
        year_min=None,
        year_max=None,
    ) -> list[str]:
        return self._call(
            "uniques", provider, status, mtype, keyword, year_min, year_max
        )

    def get(self, unique: str) -> dict | None:
        return self._call("get", unique)

    def delete(self, unique: str) -> bool:
        return self._call("delete", unique)

    def delete_many(self, uniques) -> int:
        return self._call("delete_many", uniques)

    def clear(self, provider: str | None = None) -> None:
        return self._call("clear", provider)

    def stats(self) -> dict:
        return self._call("stats")

    def count(self) -> int:
        return self._call("count")

    def prune(self, keep: int) -> int:
        return self._call("prune", keep)

    def values(self) -> list[dict]:
        return self._call("values")
