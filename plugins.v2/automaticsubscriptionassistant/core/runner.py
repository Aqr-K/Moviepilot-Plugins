"""单来源执行编排：fetch -> 逐条 executor.process -> 汇总统计。"""
from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Dict, Optional

from .executor import SubscribeExecutor
from .filters import build_filter_chain

if TYPE_CHECKING:
    from .config import GlobalConfig, ProviderConfig
    from .dedup import SubscribedIndex
    from .history import HistoryStore
    from .provider import ProviderContext, RankProvider


class ProviderRunner:
    """跑单个来源：抓取、逐条落地、退出信号响应、结束落盘。"""

    def __init__(self, context: "ProviderContext", global_config: "GlobalConfig",
                 history: "HistoryStore", on_error: Optional[Callable] = None,
                 on_progress: Optional[Callable] = None,
                 subscribed_index: Optional["SubscribedIndex"] = None):
        self.ctx = context
        self.gcfg = global_config
        self.history = history
        self.on_error = on_error
        self.on_progress = on_progress    # on_progress(processed:int)：每处理完一条回调，供运行态展示
        # 已订阅索引可由外部传入（多来源共享 → 跨渠道去重）；缺省则 executor 自建空索引。
        self.executor = SubscribeExecutor(context, global_config, subscribed_index)

    def run(self, provider: "RankProvider", provider_config: "ProviderConfig") -> Dict[str, int]:
        """执行单源，返回各状态计数统计（按 SubscribeStatus.value 累加）。"""
        stats: Dict[str, int] = {}
        spec = provider.get_spec()
        filter_chain = build_filter_chain([f.key for f in spec.filters_schema])

        try:
            items = provider.fetch(provider_config.options, self.ctx)
        except Exception as exc:  # noqa: BLE001 - 整源抓取失败兜底
            self._report_error(provider, exc)
            return stats

        processed = 0
        try:
            for item in items:
                # 响应退出信号。
                if self.ctx.event is not None and self.ctx.event.is_set():
                    break
                try:
                    outcome = self.executor.process(
                        item, provider, filter_chain, self.history, provider_config.filters)
                except Exception as exc:  # noqa: BLE001 - 单条兜底，继续下一条
                    if self.ctx.logger:
                        self.ctx.logger.error(f"{provider.provider_name} 处理条目失败: {exc}")
                    continue
                status_key = outcome.status.value
                stats[status_key] = stats.get(status_key, 0) + 1
                processed += 1
                if self.on_progress:
                    try:
                        self.on_progress(processed)
                    except Exception:  # noqa: BLE001 - 进度回调不得影响主流程
                        pass
        finally:
            self.history.flush()
        return stats

    def _report_error(self, provider: "RankProvider", error: Exception) -> None:
        """整源失败：记日志并回调 on_error（如系统 toast）。"""
        if self.ctx.logger:
            self.ctx.logger.error(f"{provider.provider_name} 运行失败: {error}")
        if self.on_error:
            try:
                self.on_error(provider, error)
            except Exception:  # noqa: BLE001 - 错误回调本身不得抛出影响主流程
                pass
