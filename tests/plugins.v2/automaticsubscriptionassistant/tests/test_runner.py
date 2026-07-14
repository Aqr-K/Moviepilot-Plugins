"""core/runner.py 单元测试：单源编排、退出信号、整源失败回调。"""
from __future__ import annotations

import threading
from unittest.mock import MagicMock

from app.core.context import MediaInfo
from app.schemas.types import MediaType

from app.plugins.automaticsubscriptionassistant.core.config import GlobalConfig, ProviderConfig
from app.plugins.automaticsubscriptionassistant.core.history import HISTORY_KEY, HistoryStore
from app.plugins.automaticsubscriptionassistant.core.models import (
    FieldSpec,
    ProviderSpec,
    RankMediaItem,
)
from app.plugins.automaticsubscriptionassistant.core.provider import ProviderContext, RankProvider
from app.plugins.automaticsubscriptionassistant.core.runner import ProviderRunner


class _FakeProvider(RankProvider):
    provider_id = "fake"
    provider_name = "假源"

    def __init__(self, items):
        self._items = items

    def get_spec(self):
        return ProviderSpec("fake", "假源", "0 8 * * *", [],
                            [FieldSpec("year", "", "number", 0)])

    def fetch(self, options, context):
        return iter(self._items)


class _FakeErrorProvider(_FakeProvider):
    def fetch(self, options, context):
        raise RuntimeError("fetch boom")  # 非生成器：调用即抛，模拟整源失败


def _store():
    kv = {HISTORY_KEY: []}
    return HistoryStore(lambda k: kv.get(k), lambda k, v: kv.__setitem__(k, v),
                        lambda k: kv.pop(k, None)), kv


def _movie_ctx(event=None):
    ctx = ProviderContext(MagicMock(), MagicMock(), MagicMock(), MagicMock(), event=event)

    def _recognize(*args, **kwargs):
        # 按识别请求的 tmdbid 返回对应 mediainfo，使不同条目身份键相异（贴近真实）。
        mi = MediaInfo()
        mi.type = MediaType.MOVIE
        mi.title = "t"
        mi.tmdb_id = kwargs.get("tmdbid") or 1
        mi.year = "2020"
        mi.season = 1
        mi.douban_id = None
        return mi

    ctx.chain.recognize_media.side_effect = _recognize
    ctx.downloadchain.get_no_exists_info.return_value = (False, {})
    ctx.subscribechain.exists.return_value = False
    ctx.subscribechain.add.return_value = (1, "")
    return ctx


def test_runner_happy_path_aggregates_and_flushes():
    prov = _FakeProvider([
        RankMediaItem(title="A", tmdb_id=1, unique_seed="a"),
        RankMediaItem(title="B", tmdb_id=2, unique_seed="b"),
    ])
    ctx = _movie_ctx()
    store, kv = _store()
    runner = ProviderRunner(ctx, GlobalConfig({}), store)
    stats = runner.run(prov, ProviderConfig({}, prov.get_spec()))
    assert stats == {"subscribed": 2}
    # 结束落盘
    assert len(kv[HISTORY_KEY]) == 2


def test_runner_uses_shared_index_to_skip_recognition():
    # 传入预加载的已订阅索引：命中条目跳过识别，直接判定为订阅已存在。
    from app.plugins.automaticsubscriptionassistant.core.dedup import SubscribedIndex

    index = SubscribedIndex()
    index.add_media(tmdbid=1, mtype=MediaType.MOVIE)
    prov = _FakeProvider([
        RankMediaItem(title="A", tmdb_id=1, type_hint=MediaType.MOVIE, unique_seed="a"),  # 命中 → 跳过
        RankMediaItem(title="B", tmdb_id=2, type_hint=MediaType.MOVIE, unique_seed="b"),  # 未命中 → 订阅
    ])
    ctx = _movie_ctx()
    store, _ = _store()
    runner = ProviderRunner(ctx, GlobalConfig({}), store, subscribed_index=index)
    stats = runner.run(prov, ProviderConfig({}, prov.get_spec()))
    assert stats == {"subscription_exists": 1, "subscribed": 1}
    # A 命中快速路径未识别，只有 B 触发识别
    ctx.chain.recognize_media.assert_called_once()
    assert ctx.chain.recognize_media.call_args.kwargs.get("tmdbid") == 2


def test_runner_respects_exit_event():
    ev = threading.Event()
    ev.set()
    prov = _FakeProvider([RankMediaItem(title="A", tmdb_id=1, unique_seed="a")])
    ctx = _movie_ctx(event=ev)
    store, _ = _store()
    runner = ProviderRunner(ctx, GlobalConfig({}), store)
    stats = runner.run(prov, ProviderConfig({}, prov.get_spec()))
    assert stats == {}
    ctx.chain.recognize_media.assert_not_called()


def test_runner_reports_source_error():
    errors = []
    ctx = ProviderContext(MagicMock(), MagicMock(), MagicMock(), MagicMock())
    prov = _FakeErrorProvider([])
    store, _ = _store()
    runner = ProviderRunner(ctx, GlobalConfig({}), store,
                            on_error=lambda p, e: errors.append((p, e)))
    stats = runner.run(prov, ProviderConfig({}, prov.get_spec()))
    assert stats == {}
    assert len(errors) == 1
    assert errors[0][0] is prov


def test_runner_error_callback_failure_is_swallowed():
    ctx = ProviderContext(MagicMock(), MagicMock(), MagicMock(), MagicMock())
    prov = _FakeErrorProvider([])
    store, _ = _store()

    def _bad_cb(p, e):
        raise ValueError("callback boom")

    runner = ProviderRunner(ctx, GlobalConfig({}), store, on_error=_bad_cb)
    # 回调自身抛错不得冒泡影响主流程
    assert runner.run(prov, ProviderConfig({}, prov.get_spec())) == {}
