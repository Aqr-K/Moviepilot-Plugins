"""
校验插件使用官方公开 SDK，并登记当前 SDK 尚未覆盖的宿主依赖。
"""
import ast
import importlib
from pathlib import Path


_PLUGIN_ROOT = Path(__file__).resolve().parents[4] / "plugins.v3" / "automaticsubscriptionassistant"
# 这些调用在当前 SDK 中没有公开替代，具体用途与迁移限制见插件架构文档。
_INTERNAL_IMPORTS = {
    "__init__.py": {
        "app.chain.download": {"DownloadChain"},
        "app.chain.subscribe": {"SubscribeChain"},
        "app.db.oper.subscribe": {"SubscribeOper"},
    },
    "providers/popular.py": {"app.adapters.external.server": {"MoviePilotServerHelper"}},
}
_SCHEMA_IMPORTS = {
    "app.schemas.types": {"EventType", "MediaType", "MediaSource"},
    "app.schemas.event": {"ConfigChangeEventData"},
    "app.schemas.subscribe": {"Subscribe"},
}


def test_host_imports_use_available_public_sdk():
    """
    新增宿主依赖须使用真实公开 SDK；缺口仅允许已说明的精确路径和符号。
    """
    found_internal = {}
    for path in _PLUGIN_ROOT.rglob("*.py"):
        relative = path.relative_to(_PLUGIN_ROOT).as_posix()
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                assert not any(alias.name == "app" or alias.name.startswith("app.") for alias in node.names), relative
            if not isinstance(node, ast.ImportFrom) or node.level or not node.module:
                continue
            module_name = node.module
            if module_name != "app" and not module_name.startswith("app."):
                continue
            names = {alias.name for alias in node.names}
            if module_name == "app.sdk" or module_name.startswith("app.sdk."):
                assert not any(part.startswith("_") for part in module_name.split(".")), module_name
                module = importlib.import_module(module_name)
                assert all(hasattr(module, name) for name in names), (relative, module_name, names)
            elif module_name in _SCHEMA_IMPORTS:
                assert names <= _SCHEMA_IMPORTS[module_name], (relative, module_name, names)
            else:
                expected = _INTERNAL_IMPORTS.get(relative, {}).get(module_name, set())
                assert names == expected, (relative, module_name, names)
                found_internal.setdefault(relative, {})[module_name] = names
    assert found_internal == _INTERNAL_IMPORTS
