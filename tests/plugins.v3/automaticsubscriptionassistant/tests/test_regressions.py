"""错季、跨轮去重、失败缓存和迁移的行为回归。"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.schemas.types import MediaType
from app.plugins.automaticsubscriptionassistant.core.config import GlobalConfig
from app.plugins.automaticsubscriptionassistant.core.dedup import SubscribedIndex
from app.plugins.automaticsubscriptionassistant.core.filters import FilterChain, build_filter_chain
from app.plugins.automaticsubscriptionassistant.core.history import HistoryStore
from app.plugins.automaticsubscriptionassistant.core.migration import migrate_history_from_kv
from app.plugins.automaticsubscriptionassistant.core.models import HistoryRecord, RankMediaItem, SubscribeStatus
from app.plugins.automaticsubscriptionassistant.providers.netflix import NetflixRankProvider
from app.plugins.automaticsubscriptionassistant.providers.popular import PopularRankProvider
from test_executor import _exec, _make_ctx, _make_store, _mediainfo, _PROVIDER


def _ready_context(season=None):
    """构造媒体库缺失且尚无活动订阅的识别上下文。"""
    ctx = _make_ctx()
    ctx.chain.recognize_media.return_value = _mediainfo(mtype=MediaType.TV, season=season)
    ctx.downloadchain.get_no_exists_info.return_value = (False, {})
    ctx.subscribechain.exists.return_value = False
    ctx.subscribechain.add.return_value = (77, "")
    return ctx


def test_title_season_reaches_checks_and_subscription():
    """后端只返回整剧信息时，标题中的第三季仍贯穿检查和订阅。"""
    ctx = _ready_context()
    store, _ = _make_store()
    item = RankMediaItem(title="测试剧 第三季", douban_id="123", type_hint=MediaType.TV)
    result = _exec(ctx).process(item, _PROVIDER, FilterChain([]), store, {})
    assert result.status == SubscribeStatus.SUBSCRIBED
    assert ctx.subscribechain.add.call_args.kwargs["season"] == 3
    assert ctx.subscribechain.exists.call_args.kwargs["meta"].begin_season == 3
    assert ctx.downloadchain.get_no_exists_info.call_args.kwargs["mediainfo"].season == 3
    assert store.query()[0][0]["season"] == 3


def test_completed_subscription_is_not_readded_across_runs():
    """活动订阅已移除后，原始豆瓣候选依然命中持久成功状态。"""
    ctx = _ready_context(3)
    store, _ = _make_store()
    item = RankMediaItem(title="测试剧 第三季", douban_id="123", type_hint=MediaType.TV)
    first = _exec(ctx).process(item, _PROVIDER, FilterChain([]), store, {})
    second = _exec(ctx).process(item, _PROVIDER, FilterChain([]), HistoryStore(store._session_factory), {})
    assert first.status == SubscribeStatus.SUBSCRIBED
    assert second.status == SubscribeStatus.ALREADY_HANDLED
    ctx.subscribechain.add.assert_called_once()


def test_title_season_is_not_suppressed_by_first_season_index():
    """标题中的第二季不能被仅订阅第一季的快速索引拦截。"""
    ctx = _ready_context(2)
    store, _ = _make_store()
    index = SubscribedIndex()
    index.add_media(tmdbid=438631, mtype=MediaType.TV, season=1)
    item = RankMediaItem(title="测试剧 第二季", tmdb_id=438631, type_hint=MediaType.TV)
    assert _exec(ctx, index=index).process(item, _PROVIDER, FilterChain([]), store, {}).status == SubscribeStatus.SUBSCRIBED
    assert ctx.subscribechain.add.call_args.kwargs["season"] == 2


def test_unknown_season_requires_recognition():
    """未知季的整剧候选不应把任意单季订阅当作充分证据。"""
    index = SubscribedIndex()
    index.add_media(tmdbid=438631, mtype=MediaType.TV, season=1)
    assert not index.contains(RankMediaItem(title="测试剧", tmdb_id=438631, type_hint=MediaType.TV))


@pytest.mark.parametrize("season", [0, 2])
def test_explicit_seasons_and_specials_remain_distinct(season):
    """明确季号及特别篇不会因第一季已处理而被合并。"""
    store, _ = _make_store()
    ctx = _ready_context(1)
    for number in (1, season):
        item = RankMediaItem(title="测试剧", tmdb_id=438631, type_hint=MediaType.TV, season=number)
        _exec(ctx).process(item, _PROVIDER, FilterChain([]), store, {})
    assert ctx.subscribechain.add.call_count == 2


def test_ambiguous_series_does_not_default_to_first_season():
    """整剧有多个季且未明确目标时，不静默创建第一季订阅。"""
    ctx = _ready_context()
    ctx.chain.recognize_media.return_value.seasons = {1: [1], 2: [1]}
    store, _ = _make_store()
    result = _exec(ctx).process(RankMediaItem(title="测试剧", tmdb_id=438631, type_hint=MediaType.TV),
                                _PROVIDER, FilterChain([]), store, {})
    assert result.status == SubscribeStatus.UNRECOGNIZED
    ctx.subscribechain.add.assert_not_called()


@pytest.mark.parametrize("status", ["filtered", "media_exists", "subscription_exists"])
def test_history_keeps_resolved_season_on_short_circuits(status):
    """非创建分支同样保存已识别季号。"""
    ctx = _ready_context(3)
    ctx.downloadchain.get_no_exists_info.return_value = (status == "media_exists", {})
    ctx.subscribechain.exists.return_value = status == "subscription_exists"
    store, _ = _make_store()
    result = _exec(ctx, GlobalConfig({"exist_ok": False})).process(
        RankMediaItem(title="测试剧", douban_id="123", type_hint=MediaType.TV), _PROVIDER,
        build_filter_chain(["vote"]), store, {"vote": 10} if status == "filtered" else {})
    assert result.status.value == status
    assert store.query()[0][0]["season"] == 3


def test_exist_ok_allows_library_subscription():
    """允许已有媒体时，媒体库命中不会阻止调用新增订阅。"""
    ctx = _ready_context(1)
    ctx.downloadchain.get_no_exists_info.return_value = (True, {})
    store, _ = _make_store()
    result = _exec(ctx, GlobalConfig({"exist_ok": True})).process(
        RankMediaItem(title="测试剧", tmdb_id=438631, type_hint=MediaType.TV, season=1),
        _PROVIDER, FilterChain([]), store, {})
    assert result.status == SubscribeStatus.SUBSCRIBED
    ctx.subscribechain.add.assert_called_once()


def test_success_survives_later_filter_and_history_pruning():
    """成功事实不被其他来源的过滤结果降级，也不因展示历史修剪丢失。"""
    store, _ = _make_store()
    store.record(HistoryRecord(unique="tmdb:movie:1", provider="douban", title="A", status="subscribed", time="2020"))
    store.record(HistoryRecord(unique="tmdb:movie:1", provider="maoyan", title="A", status="filtered", time="2021"))
    assert store.get("tmdb:movie:1")["status"] == "subscribed"
    store.record(HistoryRecord(unique="tmdb:movie:2", provider="douban", title="B", status="subscribed", time="2022"))
    store.prune(1)
    assert HistoryStore(store._session_factory).is_handled("tmdb:movie:1")


def test_netflix_keeps_distinct_seasons():
    """同榜各季分别产出，跨榜同一季仍合并。"""
    provider = NetflixRankProvider()
    rows = [{"show_title": "Example", "season_title": f"Example: Season {s}"} for s in (1, 2, 1)]
    assert [i.season for i in provider._emit(rows, "TV (English)", "global", set(), None)] == [1, 2]
    entries = [{"clean_title": "Example", "title": f"Example: Season {s}"} for s in (1, 2, 1)]
    assert [i.season for i in provider._emit_rich(entries, {"kind": "tv", "scope": "global"}, set(), None)] == [1, 2]


def test_popular_keeps_distinct_seasons(monkeypatch):
    """热门统计的同剧不同季不在抓取阶段丢失。"""
    rows = [{"name": "Example", "type": "电视剧", "media_source": "themoviedb", "media_id": "1", "season": s} for s in (1, 2)]
    from app.plugins.automaticsubscriptionassistant.providers.popular import MoviePilotServerHelper
    monkeypatch.setattr(MoviePilotServerHelper, "get_subscribe_statistic", lambda **kwargs: rows)
    assert [i.season for i in PopularRankProvider()._fetch_category("tv", 10, [], None, 0)] == [1, 2]


def test_netflix_failed_rich_pages_are_retried(monkeypatch):
    """富页暂时不可达时，下次运行必须重新请求。"""
    from app.plugins.automaticsubscriptionassistant.providers import netflix
    monkeypatch.setattr(netflix, "_NETFLIX_CACHE", {})
    request = MagicMock(side_effect=RuntimeError("temporary failure"))
    monkeypatch.setattr(NetflixRankProvider, "_load_rich_page", request)
    opts = {"rich_metadata": True, "global": True, "global_media_types": ["TV (English)"]}
    assert list(NetflixRankProvider().fetch(opts, None)) == []
    assert list(NetflixRankProvider().fetch(opts, None)) == []
    assert request.call_count == 2


def test_most_popular_rich_global_uses_correct_dataset(monkeypatch):
    """史上最热无对应富页时回退同一数据集 TSV，不请求普通周榜。"""
    provider = NetflixRankProvider()
    rich = MagicMock(return_value=[])
    tsv = MagicMock(return_value=[])
    monkeypatch.setattr(provider, "_load_rich_page", rich)
    monkeypatch.setattr(provider, "_fetch_global", tsv)
    list(provider.fetch({"rich_metadata": True, "use_cache": False, "global_dataset": "most-popular",
                         "global_media_types": ["TV (English)"]}, None))
    rich.assert_not_called()
    assert tsv.call_args.args[0] == "most-popular"


def test_migration_keeps_source_when_backup_fails():
    """归档未完成时保留迁移源，尤其不能丢掉未成功导入的记录。"""
    data = {"history": [{"unique": "ok"}, {"unique": "retry"}]}
    store = MagicMock()
    store.get.return_value = None
    store.record.side_effect = [None, RuntimeError("temporary database failure")]

    def save(key, value):
        """模拟仅归档写入失败的 KV。"""
        if key == "history_migrated_backup":
            raise RuntimeError("backup unavailable")
        data[key] = value

    migrate_history_from_kv(store, data.get, save, lambda key: data.pop(key, None))
    assert "history" in data
    assert "history_migration" not in data


def test_unknown_season_candidate_does_not_freeze_future_seasons():
    """无法在来源上区分的候选每次重新识别，不能永久绑定到首次识别的季。"""
    ctx = _ready_context(1)
    store, _ = _make_store()
    item = RankMediaItem(title="测试剧", tmdb_id=438631, type_hint=MediaType.TV)
    _exec(ctx).process(item, _PROVIDER, FilterChain([]), store, {})
    ctx.chain.recognize_media.return_value = _mediainfo(mtype=MediaType.TV, season=2)
    _exec(ctx).process(item, _PROVIDER, FilterChain([]), HistoryStore(store._session_factory), {})
    assert [call.kwargs["season"] for call in ctx.subscribechain.add.call_args_list] == [1, 2]


def test_season_override_does_not_mutate_shared_recognition_result():
    """针对某季的补充不能污染宿主缓存里其他请求共享的对象。"""
    ctx = _ready_context(1)
    original = ctx.chain.recognize_media.return_value
    store, _ = _make_store()
    _exec(ctx).process(RankMediaItem(title="测试剧", tmdb_id=438631, type_hint=MediaType.TV, season=3),
                       _PROVIDER, FilterChain([]), store, {})
    assert original.season == 1
    assert ctx.subscribechain.add.call_args.kwargs["season"] == 3


def test_episode_groups_keep_separate_success_facts():
    """同剧同季的两个剧集组不能共享已处理状态。"""
    ctx = _ready_context(1)
    store, _ = _make_store()
    for group in ("group-a", "group-b"):
        item = RankMediaItem(title="测试剧", tmdb_id=438631, type_hint=MediaType.TV,
                             season=1, episode_group=group)
        _exec(ctx).process(item, _PROVIDER, FilterChain([]), store, {})
    assert ctx.subscribechain.add.call_count == 2
    assert {row["episode_group"] for row in store.query()[0]} == {"group-a", "group-b"}


def test_delete_releases_candidate_alias_even_from_another_store():
    """显式删除解除所有候选别名，其他会话不能继续使用过期内存标记。"""
    ctx = _ready_context(3)
    store, _ = _make_store()
    item = RankMediaItem(title="测试剧 第三季", douban_id="123", type_hint=MediaType.TV)
    _exec(ctx).process(item, _PROVIDER, FilterChain([]), store, {})
    HistoryStore(store._session_factory).delete(store.query()[0][0]["unique"])
    _exec(ctx).process(item, _PROVIDER, FilterChain([]), store, {})
    assert ctx.subscribechain.add.call_count == 2


def test_clear_source_releases_aliases_registered_by_other_sources():
    """清除成功记录所属来源时，其他来源指向它的别名也必须解除。"""
    store, _ = _make_store()
    store.record(HistoryRecord(unique="tmdb:movie:1", provider="douban", title="A", status="subscribed"))
    store.mark_handled("candidate:another-source", "tmdb:movie:1", "popular")
    store.clear(provider="douban")
    assert not store.is_handled("tmdb:movie:1")
    assert not store.is_handled("candidate:another-source")


def test_new_database_engines_each_have_history_schema():
    """数据库销毁重建后，新的 engine 必须真正建表。"""
    import gc
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    for _ in range(25):
        engine = create_engine("sqlite://")
        assert HistoryStore(sessionmaker(bind=engine)).count() == 0
        engine.dispose()
        del engine
        gc.collect()


def test_concurrent_sources_preserve_both_successes(tmp_path):
    """各来源用独立会话并发提交不会丢失记录或成功账本。"""
    from concurrent.futures import ThreadPoolExecutor
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(f"sqlite:///{tmp_path / 'history.db'}")
    factory = sessionmaker(bind=engine)

    def record(number):
        """模拟一个来源独立构造仓库并保存成功记录。"""
        HistoryStore(factory).record(HistoryRecord(unique=f"tmdb:movie:{number}", provider="douban",
                                                    title=str(number), status="subscribed"))

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(record, range(12)))
    assert HistoryStore(factory).count() == 12
    assert all(HistoryStore(factory).is_handled(f"tmdb:movie:{number}") for number in range(12))
    engine.dispose()


def test_migration_retries_only_failed_records_and_preserves_newer_results():
    """迁移部分失败后，旧 KV 不覆盖已在数据库中更新的结果。"""
    store, _ = _make_store()
    store.record(HistoryRecord(unique="existing", provider="douban", title="新结果", status="subscribed"))
    data = {"history": [{"unique": "existing", "title": "旧结果"}, {"unique": "retry", "title": "待迁移"}]}
    original_record = store.record

    def temporarily_unavailable(record):
        """一次暂时写入失败，保留原记录供下次启动重试。"""
        raise RuntimeError("database busy")

    store.record = temporarily_unavailable
    migrate_history_from_kv(store, data.get, lambda key, value: data.__setitem__(key, value), lambda key: data.pop(key, None))
    assert [row["unique"] for row in data["history"]] == ["retry"]
    assert "history_migration" not in data
    store.record = original_record
    migrate_history_from_kv(store, data.get, lambda key, value: data.__setitem__(key, value), lambda key: data.pop(key, None))
    assert "history" not in data
    assert store.get("existing")["title"] == "新结果"
    assert store.get("retry")["title"] == "待迁移"


def test_config_save_failure_does_not_reload_or_report_success():
    """保存端口明确失败时不应用尚未持久化的配置。"""
    from app.plugins.automaticsubscriptionassistant import AutomaticSubscriptionAssistant

    plugin = AutomaticSubscriptionAssistant.__new__(AutomaticSubscriptionAssistant)
    plugin._providers = []
    plugin.update_config = MagicMock(return_value=False)
    plugin.init_plugin = MagicMock()
    plugin._refresh_jobs = MagicMock()
    assert plugin.api_save_config({"global": {}})["code"] == 1
    plugin.init_plugin.assert_not_called()
    plugin._refresh_jobs.assert_not_called()


def test_config_save_refreshes_host_schedule():
    """自定义保存入口成功后刷新宿主任务注册。"""
    from app.plugins.automaticsubscriptionassistant import AutomaticSubscriptionAssistant

    plugin = AutomaticSubscriptionAssistant.__new__(AutomaticSubscriptionAssistant)
    plugin._providers = []
    plugin.update_config = MagicMock(return_value=True)
    plugin.init_plugin = MagicMock()
    plugin._refresh_jobs = MagicMock()
    assert plugin.api_save_config({"global": {}})["code"] == 0
    plugin._refresh_jobs.assert_called_once()


def test_retry_restores_original_source_candidate(monkeypatch):
    """重试使用原始豆瓣标题、来源和过滤元数据，并保留目标季。"""
    from threading import Event
    from app.plugins.automaticsubscriptionassistant import AutomaticSubscriptionAssistant
    from app.plugins.automaticsubscriptionassistant.core.config import PluginSettings
    from app.plugins.automaticsubscriptionassistant.providers.douban import DoubanRankProvider

    ctx = _ready_context()
    store, _ = _make_store()
    original = RankMediaItem(title="测试剧 第三季", douban_id="987", type_hint=MediaType.TV,
                             source_meta={"count": 50})
    store.record(HistoryRecord(unique="old-error", provider="douban", title="清洗后的剧名",
                               status="error", source_item=original.to_dict()))
    plugin = AutomaticSubscriptionAssistant.__new__(AutomaticSubscriptionAssistant)
    plugin._settings = PluginSettings({})
    plugin.chain = ctx.chain
    plugin._downloadchain = ctx.downloadchain
    plugin._subscribechain = ctx.subscribechain
    plugin._event = Event()
    plugin.get_data = MagicMock()
    plugin.save_data = MagicMock()
    monkeypatch.setattr(plugin, "_AutomaticSubscriptionAssistant__history_store", lambda: store)
    monkeypatch.setattr(plugin, "_AutomaticSubscriptionAssistant__build_subscribed_index", SubscribedIndex)
    monkeypatch.setattr("app.plugins.automaticsubscriptionassistant.registry.get", lambda key: DoubanRankProvider(), raising=False)
    result = plugin.api_history_recognize({"unique": "old-error"})
    assert result["code"] == 0
    assert result["status"] == "subscribed"
    assert ctx.chain.recognize_media.call_args.kwargs["media_id"] == "987"
    assert ctx.subscribechain.add.call_args.kwargs["season"] == 3
    assert store.get("old-error") is None


@pytest.mark.parametrize("value, offset", [("上映300天", -300), ("300天后上映", 300), ("距上映300天", 300)])
def test_maoyan_relative_dates_keep_direction(value, offset):
    """已上映和即将上映在跨年时使用相反的时间方向。"""
    from datetime import date, timedelta
    from app.plugins.automaticsubscriptionassistant.providers.maoyan import MaoyanRankProvider

    assert MaoyanRankProvider._year_from_release_info(value) == str((date.today() + timedelta(days=offset)).year)


def test_maoyan_absolute_and_unknown_dates():
    """绝对上映日期按日期验证，未知文案不拼接数字猜年份。"""
    from app.plugins.automaticsubscriptionassistant.providers.maoyan import MaoyanRankProvider

    assert MaoyanRankProvider._year_from_release_info("2027-02-03上映") == "2027"
    assert MaoyanRankProvider._year_from_release_info("2027-02-31上映") is None
    assert MaoyanRankProvider._year_from_release_info("总计300场") is None


def test_netflix_partial_empty_pages_are_not_cached(monkeypatch):
    """部分地区未返回条目时，不把缺项结果冻结成长期成功缓存。"""
    from app.plugins.automaticsubscriptionassistant.providers import netflix
    monkeypatch.setattr(netflix, "_NETFLIX_CACHE", {})

    def page(url, proxy):
        """日本页暂时为空，美国页正常提供同一部剧。"""
        return [] if "/japan/" in url else [{"title": "Example: Season 1", "rank": 1}]

    request = MagicMock(side_effect=page)
    monkeypatch.setattr(NetflixRankProvider, "_load_rich_page", request)
    options = {"rich_metadata": True, "global": False,
               "country_selections": {"US": ["TV"], "JP": ["TV"]}}
    assert len(list(NetflixRankProvider().fetch(options, None))) == 1
    assert len(list(NetflixRankProvider().fetch(options, None))) == 1
    assert request.call_count == 4
