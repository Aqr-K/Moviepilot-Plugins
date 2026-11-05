"""插件专属 ORM 基类，不与宿主共享 MetaData。"""

from app.sdk.database import plugin_declarative_base

Base = plugin_declarative_base()
