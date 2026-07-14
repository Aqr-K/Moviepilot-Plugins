"""core/executor.py 单元测试：统一落地管线全部 SubscribeStatus 路径 + 预去重快速路径。

用 MagicMock 造 ProviderContext 的三条链，真实 HistoryStore（闭包 KV）断言历史与去重集合。
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.core.context import MediaInfo
from app.schemas.types import MediaType

from app.plugins.automaticsubscriptionassistant.core.config import GlobalConfig
from app.plugins.automaticsubscriptionassistant.core.dedup import SubscribedIndex
from app.plugins.automaticsubscriptionassistant.core.executor import SubscribeExecutor
from app.plugins.automaticsubscriptionassistant.core.filters import FilterChain, build_filter_chain
from app.plugins.automaticsubscriptionassistant.core.history import HISTORY_KEY, HistoryStore
from app.plugins.automaticsubscriptionassistant.core.models import RankMediaItem, SubscribeStatus
from app.plugins.automaticsubscriptionassistant.core.provider import ProviderContext

_PROVIDER = SimpleNamespace(provider_id="douban")


def _make_store(initial=None):
    kv = {HISTORY_KEY: list(initial or [])}
    return HistoryStore(lambda k: kv.get(k), lambda k, v: kv.__setitem__(k, v),
                        lambda k: kv.pop(k, None)), kv


def _make_ctx():
    return ProviderContext(chain=MagicMock(), downloadchain=MagicMock(),
                           subscribechain=MagicMock(), logger=MagicMock())


def _mediainfo(mtype=MediaType.MOVIE, tmdb_id=438631, douban_id="123",
               year="2021", season=1, vote_average=8.0, genre_ids=None):
    mi = MediaInfo()
    mi.type = mtype
    mi.title = "沙丘"
    mi.tmdb_id = tmdb_id
    mi.douban_id = douban_id
    mi.year = year
    mi.season = season
    mi.vote_average = vote_average
    mi.genre_ids = genre_ids or []
    return mi


def _exec(ctx, gcfg=None, index=None):
    return SubscribeExecutor(ctx, gcfg or GlobalConfig({}), index)


def test_already_handled():
    # 历史中已有正向终态（身份键 douban:D）→ 短路，不识别、不记新历史。
    store, _ = _make_store([{"unique": "douban:D", "status": "subscribed"}])
    ctx = _make_ctx()
    item = RankMediaItem(title="X", douban_id="D", unique_seed="seed")
    outcome = _exec(ctx).process(item, _PROVIDER, FilterChain([]), store, {})
    assert outcome.status == SubscribeStatus.ALREADY_HANDLED
    assert store.query()[1] == 1
    ctx.chain.recognize_media.assert_not_called()


def test_filtered_pre():
    store, _ = _make_store()
    ctx = _make_ctx()
    item = RankMediaItem(title="X", year="2000", unique_seed="s")
    chain = build_filter_chain(["year"])
    outcome = _exec(ctx).process(item, _PROVIDER, chain, store, {"year": 2020})
    assert outcome.status == SubscribeStatus.FILTERED
    assert "年份" in outcome.reason
    # pre 阶段短路，不触发识别；记录一条 filtered，但**不**标记已处理（可被其他渠道重试）。
    ctx.chain.recognize_media.assert_not_called()
    assert store.is_handled(item.identity()) is False
    assert store.query()[0][0]["status"] == "filtered"


def test_unrecognized():
    store, _ = _make_store()
    ctx = _make_ctx()
    ctx.chain.recognize_media.return_value = None
    item = RankMediaItem(title="X", unique_seed="s")  # 无 id -> 纯标题识别分支
    outcome = _exec(ctx).process(item, _PROVIDER, FilterChain([]), store, {})
    assert outcome.status == SubscribeStatus.UNRECOGNIZED
    ctx.chain.recognize_media.assert_called_once()
    assert store.query()[0][0]["status"] == "unrecognized"
    assert store.is_handled(item.identity()) is False  # 未识别不标记，可重试


def test_filtered_post():
    store, _ = _make_store()
    ctx = _make_ctx()
    mi = _mediainfo(mtype=MediaType.TV)
    ctx.chain.recognize_media.return_value = mi
    item = RankMediaItem(title="X", douban_id="123", unique_seed="s")
    chain = build_filter_chain(["media_type"])
    outcome = _exec(ctx).process(item, _PROVIDER, chain, store, {"media_type": "movie"})
    assert outcome.status == SubscribeStatus.FILTERED
    assert outcome.reason == "非电影"
    assert outcome.mediainfo is mi
    # douban 识别分支
    assert ctx.chain.recognize_media.call_args.kwargs.get("doubanid") == "123"
    assert store.query()[0][0]["status"] == "filtered"


def test_media_exists():
    store, _ = _make_store()
    ctx = _make_ctx()
    ctx.chain.recognize_media.return_value = _mediainfo(mtype=MediaType.MOVIE)
    ctx.downloadchain.get_no_exists_info.return_value = (True, {})  # True=已完整存在
    item = RankMediaItem(title="X", douban_id="123", unique_seed="s")
    outcome = _exec(ctx).process(item, _PROVIDER, FilterChain([]), store, {})
    assert outcome.status == SubscribeStatus.MEDIA_EXISTS
    ctx.subscribechain.exists.assert_not_called()
    rec = store.query()[0][0]
    assert rec["status"] == "media_exists"
    assert rec["unique"] == "tmdb:movie:438631"
    assert store.is_handled("tmdb:movie:438631") is True  # 正向终态标记已处理


def test_subscription_exists():
    store, _ = _make_store()
    ctx = _make_ctx()
    ctx.chain.recognize_media.return_value = _mediainfo(mtype=MediaType.MOVIE)
    ctx.downloadchain.get_no_exists_info.return_value = (False, {})
    ctx.subscribechain.exists.return_value = True
    item = RankMediaItem(title="X", bangumi_id=42, unique_seed="s")  # bangumi 识别分支
    outcome = _exec(ctx).process(item, _PROVIDER, FilterChain([]), store, {})
    assert outcome.status == SubscribeStatus.SUBSCRIPTION_EXISTS
    assert ctx.chain.recognize_media.call_args.kwargs.get("bangumiid") == 42
    ctx.subscribechain.add.assert_not_called()
    assert store.query()[0][0]["status"] == "subscription_exists"


def test_subscribed_movie():
    store, _ = _make_store()
    ctx = _make_ctx()
    ctx.chain.recognize_media.return_value = _mediainfo(
        mtype=MediaType.MOVIE, tmdb_id=438631, douban_id="123", year="2021")
    ctx.downloadchain.get_no_exists_info.return_value = (False, {})
    ctx.subscribechain.exists.return_value = False
    ctx.subscribechain.add.return_value = (777, "")
    item = RankMediaItem(title="沙丘", tmdb_id=438631, type_hint=MediaType.MOVIE, unique_seed="s")
    outcome = _exec(ctx).process(item, _PROVIDER, FilterChain([]), store, {})

    assert outcome.status == SubscribeStatus.SUBSCRIBED
    assert outcome.subscribe_id == 777
    # tmdb 识别分支
    assert ctx.chain.recognize_media.call_args.kwargs.get("tmdbid") == 438631
    # add 关键参数
    add_kwargs = ctx.subscribechain.add.call_args.kwargs
    assert add_kwargs["title"] == "沙丘"
    assert add_kwargs["year"] == "2021"
    assert add_kwargs["mtype"] == MediaType.MOVIE
    assert add_kwargs["tmdbid"] == 438631
    assert add_kwargs["doubanid"] == "123"
    assert add_kwargs["season"] is None       # 电影 season 传 None
    assert add_kwargs["exist_ok"] is True
    assert add_kwargs["username"] == "自动订阅助手"
    # 历史落地（unique 为媒体身份键）
    rec = store.query()[0][0]
    assert rec["status"] == "subscribed"
    assert rec["tmdbid"] == 438631
    assert rec["type"] == "电影"
    assert rec["unique"] == "tmdb:movie:438631"
    assert store.is_handled("tmdb:movie:438631") is True


def test_subscribed_tv_uses_item_season():
    store, _ = _make_store()
    ctx = _make_ctx()
    ctx.chain.recognize_media.return_value = _mediainfo(mtype=MediaType.TV, season=9)
    ctx.downloadchain.get_no_exists_info.return_value = (False, {})
    ctx.subscribechain.exists.return_value = False
    ctx.subscribechain.add.return_value = (10, "")
    item = RankMediaItem(title="剧", tmdb_id=1, type_hint=MediaType.TV, season=2, unique_seed="s")
    _exec(ctx).process(item, _PROVIDER, FilterChain([]), store, {})
    # item.season 优先于 mediainfo.season
    assert ctx.subscribechain.add.call_args.kwargs["season"] == 2
    rec = store.query()[0][0]
    assert rec["season"] == 2
    # 身份键用识别后的 tmdb（438631）+ 条目季（2）
    assert rec["unique"] == "tmdb:tv:438631:s2"


def test_subscribed_tv_falls_back_to_mediainfo_season():
    store, _ = _make_store()
    ctx = _make_ctx()
    ctx.chain.recognize_media.return_value = _mediainfo(mtype=MediaType.TV, season=5)
    ctx.downloadchain.get_no_exists_info.return_value = (False, {})
    ctx.subscribechain.exists.return_value = False
    ctx.subscribechain.add.return_value = (11, "")
    item = RankMediaItem(title="剧", tmdb_id=1, type_hint=MediaType.TV, season=None, unique_seed="s")
    _exec(ctx).process(item, _PROVIDER, FilterChain([]), store, {})
    assert ctx.subscribechain.add.call_args.kwargs["season"] == 5


def test_error_when_add_fails():
    store, _ = _make_store()
    ctx = _make_ctx()
    ctx.chain.recognize_media.return_value = _mediainfo(mtype=MediaType.MOVIE)
    ctx.downloadchain.get_no_exists_info.return_value = (False, {})
    ctx.subscribechain.exists.return_value = False
    ctx.subscribechain.add.return_value = (None, "boom")
    item = RankMediaItem(title="X", tmdb_id=1, type_hint=MediaType.MOVIE, unique_seed="s")
    outcome = _exec(ctx).process(item, _PROVIDER, FilterChain([]), store, {})
    assert outcome.status == SubscribeStatus.ERROR
    assert outcome.reason == "boom"
    rec = store.query()[0][0]
    assert rec["status"] == "error"
    assert rec["reason"] == "boom"
    assert store.is_handled(rec["unique"]) is False  # 异常不标记，可重试


def test_error_on_exception():
    store, _ = _make_store()
    ctx = _make_ctx()
    ctx.chain.recognize_media.side_effect = RuntimeError("kaboom")
    item = RankMediaItem(title="X", douban_id="1", unique_seed="s")
    outcome = _exec(ctx).process(item, _PROVIDER, FilterChain([]), store, {})
    assert outcome.status == SubscribeStatus.ERROR
    assert "kaboom" in outcome.reason
    # 异常路径记历史但不标记已处理（可被后续重试）
    assert store.is_handled("douban:1") is False
    assert store.query()[0][0]["status"] == "error"


# --------------------------------------------------------------------------- #
# 预去重快速路径（SubscribedIndex）
# --------------------------------------------------------------------------- #
def test_prededup_fast_path_skips_recognition():
    # 索引预加载已订阅（豆瓣 D9）→ 命中即跳过识别，仅记一条 subscription_exists。
    store, _ = _make_store()
    ctx = _make_ctx()
    index = SubscribedIndex()
    index.add_media(doubanid="D9")
    item = RankMediaItem(title="X", douban_id="D9", unique_seed="s")
    outcome = _exec(ctx, index=index).process(item, _PROVIDER, FilterChain([]), store, {})
    assert outcome.status == SubscribeStatus.SUBSCRIPTION_EXISTS
    ctx.chain.recognize_media.assert_not_called()          # 关键：未触发识别
    rec = store.query()[0][0]
    assert rec["status"] == "subscription_exists"
    assert rec["unique"] == "douban:D9"
    assert store.is_handled("douban:D9") is True


def test_prededup_same_media_recorded_once():
    # 两个渠道命中同一已订阅媒体（同 douban）→ 只留一条记录（身份键合并，避免膨胀）。
    store, _ = _make_store()
    ctx = _make_ctx()
    index = SubscribedIndex()
    index.add_media(doubanid="D9")
    ex = _exec(ctx, index=index)
    a = RankMediaItem(title="A", douban_id="D9", unique_seed="a")
    b = RankMediaItem(title="B", douban_id="D9", unique_seed="b")
    ex.process(a, SimpleNamespace(provider_id="douban"), FilterChain([]), store, {})
    ex.process(b, SimpleNamespace(provider_id="maoyan"), FilterChain([]), store, {})
    _, total = store.query()
    assert total == 1  # 合并为一条


def test_subscribe_registers_index_for_cross_channel():
    # 渠道 A 订阅成功后写入索引 → 渠道 B 命中同一媒体（同 tmdbid）跳过识别。
    store, _ = _make_store()
    ctx = _make_ctx()
    ctx.chain.recognize_media.return_value = _mediainfo(
        mtype=MediaType.MOVIE, tmdb_id=438631, douban_id="123")
    ctx.downloadchain.get_no_exists_info.return_value = (False, {})
    ctx.subscribechain.exists.return_value = False
    ctx.subscribechain.add.return_value = (1, "")
    ex = _exec(ctx)  # 共享自建空索引
    a = RankMediaItem(title="沙丘", tmdb_id=438631, type_hint=MediaType.MOVIE, unique_seed="a")
    b = RankMediaItem(title="沙丘", tmdb_id=438631, type_hint=MediaType.MOVIE, unique_seed="b")
    out_a = ex.process(a, SimpleNamespace(provider_id="douban"), FilterChain([]), store, {})
    out_b = ex.process(b, SimpleNamespace(provider_id="maoyan"), FilterChain([]), store, {})
    assert out_a.status == SubscribeStatus.SUBSCRIBED
    assert out_b.status == SubscribeStatus.SUBSCRIPTION_EXISTS
    # 识别只发生一次（渠道 A），渠道 B 走快速路径
    ctx.chain.recognize_media.assert_called_once()
    # add 只调用一次
    ctx.subscribechain.add.assert_called_once()
    # 合并为一条记录（subscribed 优先，B 未覆盖）
    records, total = store.query()
    assert total == 1
    assert records[0]["status"] == "subscribed"


def test_prededup_tv_different_season_not_skipped():
    # 已订阅 tmdbid=1 第 1 季；来了第 2 季 → 不应被跳过（不同季，需订阅）。
    store, _ = _make_store()
    ctx = _make_ctx()
    ctx.chain.recognize_media.return_value = _mediainfo(mtype=MediaType.TV, tmdb_id=1, season=2)
    ctx.downloadchain.get_no_exists_info.return_value = (False, {})
    ctx.subscribechain.exists.return_value = False
    ctx.subscribechain.add.return_value = (5, "")
    index = SubscribedIndex()
    index.add_media(tmdbid=1, mtype=MediaType.TV, season=1)
    item = RankMediaItem(title="剧", tmdb_id=1, type_hint=MediaType.TV, season=2, unique_seed="s")
    outcome = _exec(ctx, index=index).process(item, _PROVIDER, FilterChain([]), store, {})
    assert outcome.status == SubscribeStatus.SUBSCRIBED
    ctx.chain.recognize_media.assert_called_once()  # 未被快速路径拦截
