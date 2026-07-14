"""插件仓库测试引导（自包含）。

本目录测试仍按 MoviePilot 主检出区的导入路径书写
（``from app.plugins.automaticsubscriptionassistant...`` + ``app.core`` / ``app.schemas``
/ ``app.testing`` 等），但插件仓库自身不含 ``app/``（MoviePilot 主程序）。故本 conftest：

1. 定位 MoviePilot 主检出区，把其根插到 ``sys.path[0]`` 供 ``import app.*``；
2. 复用主程序 ``app/testing`` 的共享 harness（隔离 CONFIG_DIR / 建表 / 装载网络守卫）；
3. **把插件仓库自己那份插件别名成 ``app.plugins.automaticsubscriptionassistant``**，
   确保测试测的是仓库副本（``plugins.v2/automaticsubscriptionassistant``），
   而非 MoviePilot 主检出区里同名的那份。
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# 1. 定位 MoviePilot 主检出区（提供 app.* 核心）
# ---------------------------------------------------------------------------
# 本 conftest 位于 <repo>/tests/plugins.v2/automaticsubscriptionassistant/tests/conftest.py，
# 到插件仓库根 <repo> 恰为上 4 层。
_CONFTEST = Path(__file__).resolve()
_REPO_ROOT = _CONFTEST.parents[4]

# 断言仓库副本存在，层数不对时立即暴露（而非静默测到别处）。
_PLUGIN_SRC = _REPO_ROOT / "plugins.v2" / "automaticsubscriptionassistant"
assert (_PLUGIN_SRC / "__init__.py").is_file(), (
    f"未定位到插件仓库副本：{_PLUGIN_SRC}（请核对 conftest 层数 parents[4]）"
)


def _candidate_moviepilot_roots():
    """按优先级产出 MoviePilot 检出候选路径。"""
    env = os.environ.get("MOVIEPILOT_ROOT")
    if env:
        yield Path(env)
    # 插件仓库同级目录 ../MoviePilot
    yield _REPO_ROOT.parent / "MoviePilot"
    # 兜底常量
    yield Path("/home/vscode/project/MoviePilot-v2/MoviePilot")


_MOVIEPILOT_ROOT = None
for _cand in _candidate_moviepilot_roots():
    try:
        if (_cand / "app" / "testing" / "bootstrap.py").is_file():
            _MOVIEPILOT_ROOT = _cand.resolve()
            break
    except OSError:
        continue

if _MOVIEPILOT_ROOT is None:
    pytest.skip(
        "未找到 MoviePilot 主检出区（需存在 app/testing/bootstrap.py）。"
        "请设置环境变量 MOVIEPILOT_ROOT 指向 MoviePilot 检出，"
        "或将 MoviePilot 检出置于插件仓库同级目录（../MoviePilot）。",
        allow_module_level=True,
    )

# 插到 sys.path 最前，确保 import app.* 从主检出区解析（且早于首个 import app.db）。
_MP_STR = str(_MOVIEPILOT_ROOT)
if _MP_STR in sys.path:
    sys.path.remove(_MP_STR)
sys.path.insert(0, _MP_STR)

# ---------------------------------------------------------------------------
# 2. 引导后端：隔离 CONFIG_DIR、补 sites 垫片、建表、装载网络守卫
# ---------------------------------------------------------------------------
# 必须早于首个 ``import app.db``（其在 import 期即按 CONFIG_PATH 连库）。
from app.testing.bootstrap import prepare_backend  # noqa: E402

prepare_backend()

# 复用共享 autouse 网络守卫：pytest 会识别 conftest 命名空间内 import 进来的 fixture。
try:
    from app.testing.network_guard import block_real_network  # noqa: E402,F401
except ImportError:  # 守卫缺失时不阻塞（旧版检出兼容）
    pass

# ---------------------------------------------------------------------------
# 3. 把仓库自己的插件别名成 app.plugins.automaticsubscriptionassistant
# ---------------------------------------------------------------------------
# 关键：主检出区同样含 app/plugins/automaticsubscriptionassistant；不别名会误测那份。
# 用 importlib 把仓库副本的 __init__.py 注册进 sys.modules，submodule_search_locations
# 指向仓库副本目录，使 ``from app.plugins.automaticsubscriptionassistant.core... import``
# 解析到仓库这份。
import app.plugins  # noqa: E402,F401  确保父包(来自主检出区)已加载

_ALIAS = "app.plugins.automaticsubscriptionassistant"
if _ALIAS not in sys.modules:
    _spec = importlib.util.spec_from_file_location(
        _ALIAS,
        _PLUGIN_SRC / "__init__.py",
        submodule_search_locations=[str(_PLUGIN_SRC)],
    )
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules[_ALIAS] = _mod
    _spec.loader.exec_module(_mod)

# 导入 providers 包触发 @register 注册，保证任意用例先后顺序下 registry 均已装载各源。
from app.plugins.automaticsubscriptionassistant import providers  # noqa: E402,F401


# ---------------------------------------------------------------------------
# 会话收尾：释放后台资源，避免解释器退出（尤其 coverage 下）挂起。
# ---------------------------------------------------------------------------
def _report_session_cleanup_error(name: str, err: Exception) -> None:
    """收尾清理失败只记录诊断，不覆盖原始 pytest 退出状态。"""
    sys.stderr.write(f"\npytest session cleanup failed: {name}: {err!r}\n")


def pytest_sessionfinish(session, exitstatus):
    """释放后台非 daemon 资源，避免解释器退出等待 worker 线程而挂起。"""
    try:
        from app.agent.tools.base import shutdown_blocking_executors

        shutdown_blocking_executors(cancel_futures=True)
    except Exception as err:
        _report_session_cleanup_error("agent blocking executors", err)

    try:
        from app.helper.thread import ThreadHelper
        from app.utils.singleton import Singleton

        helper = Singleton._instances.get((ThreadHelper, (), frozenset()))
        if helper:
            helper.shutdown()
    except Exception as err:
        _report_session_cleanup_error("thread helper", err)

    try:
        from app.log import LoggerManager

        LoggerManager.shutdown()
    except Exception as err:
        _report_session_cleanup_error("logger manager", err)
