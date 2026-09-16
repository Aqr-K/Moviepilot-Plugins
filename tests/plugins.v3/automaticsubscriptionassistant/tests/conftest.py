"""v3 插件仓测试引导（自包含）。

本目录测试按宿主运行时的导入路径书写
（``from app.plugins.automaticsubscriptionassistant...`` + ``app.sdk`` / ``app.schemas`` 等），
但插件仓自身不含 ``app/``（MoviePilot 主程序）。故本 conftest：

1. 定位 MoviePilot 主检出区，把其根插到 ``sys.path[0]`` 供 ``import app.*``；
2. 调用主程序 ``app.testing.bootstrap.prepare_v3_backend`` 完成共享引导——隔离 CONFIG_DIR、
   建表、装配领域依赖，并把 ``<repo>/plugins.v3`` 暴露为 ``app.plugins.*`` 的搜索路径，
   因而测到的是仓库副本而非主检出区里的同名插件。

v3 插件与旧代插件同名，同一 pytest 会话不能混跑，须与 ``tests/plugins.v2`` 分会话执行。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# 1. 定位 MoviePilot 主检出区（提供 app.* 核心）
# ---------------------------------------------------------------------------
# 本 conftest 位于 <repo>/tests/plugins.v3/automaticsubscriptionassistant/tests/conftest.py，
# 到插件仓库根 <repo> 恰为上 4 层。
_CONFTEST = Path(__file__).resolve()
_REPO_ROOT = _CONFTEST.parents[4]

# 断言仓库副本存在，层数不对时立即暴露（而非静默测到别处）。
_PLUGIN_SRC = _REPO_ROOT / "plugins.v3" / "automaticsubscriptionassistant"
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
        "未找到 MoviePilot v3 主检出区（需存在 app/testing/bootstrap.py）。"
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
# 2. 引导后端并把 plugins.v3 暴露为 app.plugins 的源
# ---------------------------------------------------------------------------
# 必须早于首个 ``import app.db``（其在 import 期即按 CONFIG_PATH 连库）。
from app.testing.bootstrap import prepare_v3_backend  # noqa: E402

prepare_v3_backend(_REPO_ROOT)

# 共享引导只把系统配置快照读进内存，不装配读取该快照的服务。识别链在解析标题时要查
# 自定义识别词，未装配则 MetaInfo 构造即抛「系统配置服务尚未配置」，订阅落地管线的用例
# 会全部停在识别前。此处按隔离库补装同步服务（不带异步执行器，本目录用例均为同步路径）。
from app.application.configuration import (  # noqa: E402
    SystemConfigService,
    configure_system_config,
)
from app.db.oper.systemconfig import SystemConfigOper  # noqa: E402

configure_system_config(SystemConfigService(repository=SystemConfigOper()))

# 复用共享 autouse 网络守卫：pytest 会识别 conftest 命名空间内 import 进来的 fixture。
try:
    from app.testing.network_guard import block_real_network  # noqa: E402,F401
except ImportError:  # 守卫缺失时不阻塞（旧版检出兼容）
    pass

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
        from app.runtime.thread import ThreadHelper
        from app.sdk.utilities import Singleton

        helper = Singleton._instances.get((ThreadHelper, (), frozenset()))
        if helper:
            helper.shutdown()
    except Exception as err:
        _report_session_cleanup_error("thread helper", err)

    try:
        from app.sdk.logging import LoggerManager

        LoggerManager.shutdown()
    except Exception as err:
        _report_session_cleanup_error("logger manager", err)
