"""宿主和插件共用的迁移入口；PostgreSQL 必须复用宿主限定 schema 的连接。"""

from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool


def migrate(connection):
    if (
        connection.dialect.name == "sqlite"
        and not connection.connection.driver_connection.in_transaction
    ):
        connection.exec_driver_sql("BEGIN")
    context.configure(connection=connection, target_metadata=None)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    raise RuntimeError("本插件迁移包含存量数据转换，必须在线执行")
connection = context.config.attributes.get("connection")
if connection is not None:
    migrate(connection)
else:
    url = context.config.get_main_option("sqlalchemy.url") or ""
    if not url.startswith("sqlite:"):
        raise RuntimeError("非 SQLite 迁移必须传入宿主的插件专属连接")
    engine = create_engine(url, poolclass=NullPool)
    try:
        with engine.begin() as connection:
            migrate(connection)
    finally:
        engine.dispose()
