"""插件库逻辑快照。仅限实例维护工具使用，不开放在线还原 HTTP 入口。"""

import json
import os
import sqlite3
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Integer, MetaData, String, Table, inspect, select

from .lifecycle import (
    DATABASE_LOCK,
    DatabaseCompatibilityError,
    ensure_schema,
    migration_config,
)

TABLES = (
    "subscribe_history",
    "subscribe_handled",
    "subscription_blacklist",
    "database_state",
)
FORMAT = "automatic-subscription-assistant/database/1"


def checksum(payload):
    return sha256(
        json.dumps(
            payload,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


class DatabaseBackup:
    """不包含宿主订阅、用户配置或 provider 缓存，不触碰宿主连接池所有权。"""

    def __init__(self, engine, instance_id: str, directory: Path):
        self.engine = engine
        self.instance_id = instance_id
        self.directory = Path(directory)

    def _snapshot(self, connection):
        # SQLAlchemy SQLite 默认的 SELECT 不会显式 BEGIN，先固定读快照。
        if connection.dialect.name == "sqlite":
            raw = connection.connection.driver_connection
            if not raw.in_transaction:
                connection.exec_driver_sql("BEGIN")
        elif connection.dialect.name == "postgresql":
            connection.exec_driver_sql(
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"
            )
        payload = {
            "format": FORMAT,
            "instance": self.instance_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "revisions": list(
                MigrationContext.configure(connection).get_current_heads()
            ),
            "tables": {},
        }
        for name in TABLES:
            if not inspect(connection).has_table(name):
                continue
            table = Table(name, MetaData(), autoload_with=connection)
            payload["tables"][name] = [
                dict(row) for row in connection.execute(select(table)).mappings()
            ]
        return {"payload": payload, "checksum": checksum(payload)}

    def export(self):
        with DATABASE_LOCK, self.engine.begin() as connection:
            return self._snapshot(connection)

    def _write(self, snapshot, label):
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        name = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%S%fZ}-{label}-{uuid4().hex[:8]}.json"
        target = self.directory / name
        # 独占创建，写完 fsync 后发布文件，崩溃时不留下看似完成的备份。
        temporary = target.with_suffix(".tmp")
        try:
            with temporary.open("x", encoding="utf-8") as stream:
                os.chmod(temporary, 0o600)
                json.dump(snapshot, stream, ensure_ascii=False, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            if json.loads(temporary.read_text()) != snapshot:
                raise RuntimeError("数据库快照回读校验失败")
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        return target

    def create(self):
        return self._write(self.export(), "manual")

    def before_upgrade(self):
        """仅在已有库即将升级时备份；失败会阻止升级，不覆盖先前备份。"""
        with DATABASE_LOCK:
            with self.engine.connect() as connection:
                scripts = ScriptDirectory.from_config(migration_config())
                current = MigrationContext.configure(connection).get_current_heads()
                known = {script.revision for script in scripts.walk_revisions()}
                if any(revision not in known for revision in current):
                    raise DatabaseCompatibilityError(
                        "数据库含当前插件不认识的版本，拒绝升级或降级"
                    )
                if current == tuple(scripts.get_heads()):
                    return None
                if not any(inspect(connection).has_table(name) for name in TABLES):
                    return None
            path = self._write(self.export(), "before-upgrade")
            if self.engine.dialect.name == "sqlite":
                self._sqlite_copy(path.with_suffix(".sqlite"))
            return path

    def _sqlite_copy(self, target):
        """SQLite 在线备份协议包含 WAL 中已提交数据，禁止只复制 plugin.db。"""
        temporary = target.with_suffix(".sqlite.tmp")
        try:
            with temporary.open("xb"):
                os.chmod(temporary, 0o600)
            destination = sqlite3.connect(temporary)
            try:
                source = self.engine.raw_connection()
                try:
                    source.driver_connection.backup(destination)
                finally:
                    source.close()
                if destination.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RuntimeError("SQLite 升级前完整备份校验失败")
            finally:
                destination.close()
            with temporary.open("rb") as stream:
                os.fsync(stream.fileno())
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)

    def restore(self, snapshot, *, stopped: bool = False, mode: str = "merge"):
        """停机维护时校验并恢复当前结构的快照；replace 需调用方明确指定。

        旧结构升级前快照保留用于人工恢复，不能绕过迁移直接覆盖当前结构。
        调用方须先停止并等待全部任务退出，其他进程亦须停止；本函数不停止宿主。
        """
        if stopped is not True:
            raise ValueError("还原前必须停止插件并等待在途任务退出")
        if mode not in {"merge", "replace"}:
            raise ValueError("无效还原方式")
        if not isinstance(snapshot, dict) or set(snapshot) != {"payload", "checksum"}:
            raise ValueError("快照格式错误")
        payload = snapshot["payload"]
        if not isinstance(payload, dict) or checksum(payload) != snapshot["checksum"]:
            raise ValueError("快照校验失败")
        if (
            payload.get("format") != FORMAT
            or payload.get("instance") != self.instance_id
        ):
            raise ValueError("快照格式或插件实例不匹配")
        head = list(ScriptDirectory.from_config(migration_config()).get_heads())
        if payload.get("revisions") != head or set(payload.get("tables", {})) != set(
            TABLES
        ):
            raise ValueError("快照数据库版本不匹配，请使用对应版本插件恢复后再升级")
        from sqlalchemy.orm import Session

        from ..db.models import (
            MODELS,
            DatabaseState,
            SubscribeHistory,
        )
        from ..db.oper.blacklist import BlacklistOper, fingerprint
        from ..db.oper.history import HistoryOper
        from ..schemas.blacklist import validate_rule
        from ..schemas.history import HistoryRecord

        for model in MODELS:
            table = model.__table__
            rows = payload["tables"][table.name]
            if not isinstance(rows, list) or any(
                not isinstance(row, dict) or set(row) != set(table.columns.keys())
                for row in rows
            ):
                raise ValueError(f"快照表 {table.name} 结构错误")
            for row in rows:
                for column in table.columns:
                    value = row[column.name]
                    if value is None:
                        if not column.nullable:
                            raise ValueError(
                                f"快照表 {table.name} 的 {column.name} 不能为空"
                            )
                    elif isinstance(column.type, Integer) and type(value) is not int:
                        raise ValueError(
                            f"快照表 {table.name} 的 {column.name} 必须为整数"
                        )
                    elif isinstance(column.type, String) and not isinstance(value, str):
                        raise ValueError(
                            f"快照表 {table.name} 的 {column.name} 必须为文本"
                        )
        for row in payload["tables"]["subscription_blacklist"]:
            validate_rule(row["payload"])
            if row["id"] != row["payload"]["id"] or row["fingerprint"] != fingerprint(
                row["payload"]
            ):
                raise ValueError("黑名单快照身份校验失败")
        with DATABASE_LOCK:
            ensure_schema(self.engine)
            self._write(self.export(), "before-restore")
            with Session(self.engine) as session, session.begin():
                if mode == "replace":
                    for model in reversed(MODELS):
                        session.query(model).delete(synchronize_session=False)
                    for model in MODELS:
                        for row in payload["tables"][model.__tablename__]:
                            # 省略序列 ID，避免 PostgreSQL 序列落后而使后续写入冲突。
                            values = {
                                k: v
                                for k, v in row.items()
                                if not (model is SubscribeHistory and k == "id")
                            }
                            session.add(model(**values))
                else:
                    history = HistoryOper(session)
                    for row in payload["tables"]["subscribe_history"]:
                        history.record(HistoryRecord.from_dict(row))
                    session.flush()
                    for row in payload["tables"]["subscribe_handled"]:
                        history._remember(
                            session, row["key"], row["canonical"], row["provider"]
                        )
                    for row in payload["tables"]["subscription_blacklist"]:
                        BlacklistOper(session).insert(row["payload"])
                    for row in payload["tables"]["database_state"]:
                        if session.get(DatabaseState, row["key"]) is None:
                            session.add(DatabaseState(**row))
