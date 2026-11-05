"""版本化建库与事务边界。引擎、文件与 PostgreSQL schema 的所有权属于宿主。"""

from configparser import ConfigParser
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from threading import RLock

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect

MIGRATIONS = Path(__file__).resolve().parent / "migrations"
# Alembic context 是进程全局代理；运行迁移与 StaticPool 单连接事务不能交叉。
DATABASE_LOCK = RLock()


class DatabaseCompatibilityError(RuntimeError):
    """库版本或结构与当前插件不兼容，禁止继续执行自动订阅。"""


def migration_config(connection=None):
    config = Config()
    config.file_config = ConfigParser(interpolation=None)
    config.set_main_option("script_location", str(MIGRATIONS))
    if connection is not None:
        config.attributes["connection"] = connection
    return config


@lru_cache(maxsize=1)
def migration_heads():
    """缓存随包迁移树的头版本，不缓存数据库是否健康。"""
    return tuple(ScriptDirectory.from_config(migration_config()).get_heads())


def ensure_schema(engine):
    """使用同一受管连接执行升级；每次初始化核对版本，不永久缓存 engine。"""
    with DATABASE_LOCK, engine.begin() as connection:
        config = migration_config(connection)
        scripts = ScriptDirectory.from_config(config)
        current = MigrationContext.configure(connection).get_current_heads()
        known = {script.revision for script in scripts.walk_revisions()}
        if any(revision not in known for revision in current):
            raise DatabaseCompatibilityError(
                f"数据库版本 {current} 高于或不属于当前插件，禁止自动降级"
            )
        command.upgrade(config, "head")
        # 版本表被保留但数据表丢失，不能把空库误当成健康库继续订阅。
        from ..db.models import MODELS

        inspector = inspect(connection)
        for model in MODELS:
            table = model.__table__
            if not inspector.has_table(table.name):
                raise DatabaseCompatibilityError(
                    f"数据库缺少表 {table.name}，请恢复完整备份"
                )
            columns = {column["name"] for column in inspector.get_columns(table.name)}
            if not set(table.columns.keys()) <= columns:
                raise DatabaseCompatibilityError(
                    f"数据库表 {table.name} 不完整，请恢复完整备份"
                )
            primary = (
                inspector.get_pk_constraint(table.name).get("constrained_columns") or []
            )
            if set(primary) != {column.name for column in table.primary_key}:
                raise DatabaseCompatibilityError(f"数据库表 {table.name} 主键不完整")
            unique_sets = {
                tuple(index["column_names"])
                for index in inspector.get_indexes(table.name)
                if index["unique"]
            }
            unique_sets.update(
                tuple(constraint["column_names"])
                for constraint in inspector.get_unique_constraints(table.name)
            )
            required = (
                {("unique",)}
                if table.name == "subscribe_history"
                else {("fingerprint",)}
                if table.name == "subscription_blacklist"
                else set()
            )
            if not required <= unique_sets:
                raise DatabaseCompatibilityError(
                    f"数据库表 {table.name} 唯一约束缺失，禁止继续写入"
                )


class DatabaseSession:
    """每次操作拥有一个短事务；不 dispose、不删除数据库。"""

    def __init__(self, session_factory):
        self.session_factory = session_factory
        self.ready = False

    @contextmanager
    def session(self):
        with DATABASE_LOCK:
            session = self.session_factory()
            try:
                if not self.ready:
                    ensure_schema(session.get_bind())
                    self.ready = True
                current = MigrationContext.configure(
                    session.connection()
                ).get_current_heads()
                if current != migration_heads():
                    raise DatabaseCompatibilityError("数据库版本已变化，请重新加载插件")
                yield session
                session.commit()
            except Exception:
                self.ready = False
                session.rollback()
                raise
            finally:
                session.close()
