"""来源实现包：导入各 provider 模块以触发 ``@register`` 注册。

registry 单例通过导入副作用收集所有 Provider 类，供插件主体 ``registry.create_all()`` /
``registry.get()`` 使用。新增来源时在此追加一行 ``from . import <module>`` 即可。
"""
from . import douban, maoyan, popular, mikan, netflix  # noqa: F401 - 导入触发 @register 注册
