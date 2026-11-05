"""将旧 KV 忽略规则一次性接管到 SQL，保留可验证的归档和事务内检查点。"""

import json
from copy import deepcopy
from hashlib import sha256

from ..db.models import DatabaseState
from ..db.oper.blacklist import BlacklistOper
from ..schemas.blacklist import validate_rule
from .lifecycle import DatabaseSession

KEY = "subscription_blacklist"
BACKUP_KEY = "subscription_blacklist_migrated_backup"
CHECKPOINT = "blacklist_kv_migration"


def migrate_blacklist_from_kv(session_factory, get_data, save_data, del_data):
    rows = deepcopy(get_data(KEY))
    if rows is None:
        return
    if not isinstance(rows, list):
        raise TypeError("黑名单迁移源不是列表，已保留")
    signature = sha256(
        json.dumps(rows, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    backup = get_data(BACKUP_KEY)
    archived = deepcopy(backup) if isinstance(backup, list) else []
    for row in rows:
        if row not in archived:
            archived.append(row)
    if save_data(BACKUP_KEY, archived) is False or get_data(BACKUP_KEY) != archived:
        raise RuntimeError("黑名单迁移备份校验失败，源数据已保留")
    database = DatabaseSession(session_factory)
    with database.session() as session:
        checkpoint = session.get(DatabaseState, CHECKPOINT)
        if checkpoint is not None and checkpoint.value != signature:
            raise RuntimeError("黑名单迁移源在接管后发生变化，请检查原始备份")
        if checkpoint is None:
            oper = BlacklistOper(session)
            for row in rows:
                validate_rule(row)
                oper.insert(row)
            session.add(DatabaseState(key=CHECKPOINT, value=signature))
        if get_data(KEY) != rows:
            raise RuntimeError("迁移期间黑名单发生变化，源数据已保留")
    if get_data(KEY) != rows:
        raise RuntimeError("迁移期间黑名单发生变化，源数据已保留")
    if del_data(KEY) is False or get_data(KEY) is not None:
        raise RuntimeError("黑名单迁移收尾失败，下次启动继续校验")
