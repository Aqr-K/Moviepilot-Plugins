"""黑名单 SQL 操作；只使用调用方事务，禁止全表快照覆盖。"""

import json
from copy import deepcopy
from hashlib import sha256

from ...schemas.blacklist import validate_rule
from ..models import SubscriptionBlacklist


def fingerprint(row):
    payload = {key: row[key] for key in ("type", "season", "aliases")}
    return sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


class BlacklistOper:
    def __init__(self, session):
        self.session = session

    def list(self):
        rows = self.session.query(SubscriptionBlacklist).all()
        return sorted(
            (deepcopy(row.payload) for row in rows),
            key=lambda row: (row["time"], row["id"]),
            reverse=True,
        )

    def insert(self, row):
        validate_rule(row)
        identity = fingerprint(row)
        existing = (
            self.session.query(SubscriptionBlacklist)
            .filter_by(fingerprint=identity)
            .one_or_none()
        )
        if existing is not None:
            return deepcopy(existing.payload)
        existing = self.session.get(SubscriptionBlacklist, row["id"])
        if existing is not None:
            raise ValueError("黑名单 ID 冲突，原始规则已保留")
        self.session.add(
            SubscriptionBlacklist(
                id=row["id"], fingerprint=identity, payload=deepcopy(row)
            )
        )
        self.session.flush()
        return row

    def delete(self, ids):
        return (
            self.session.query(SubscriptionBlacklist)
            .filter(SubscriptionBlacklist.id.in_(tuple(ids)))
            .delete(synchronize_session=False)
        )
