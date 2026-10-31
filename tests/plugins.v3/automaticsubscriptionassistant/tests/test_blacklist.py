"""黑名单持久化、跨源/季身份与完整订阅管线的行为验证。"""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.schemas.types import MediaType
from app.plugins.automaticsubscriptionassistant import AutomaticSubscriptionAssistant
from app.plugins.automaticsubscriptionassistant.core.blacklist import BlacklistApiMixin, BlacklistStore
from app.plugins.automaticsubscriptionassistant.core.filters import FilterChain
from app.plugins.automaticsubscriptionassistant.core.models import RankMediaItem, SubscribeStatus
from test_executor import _exec, _make_ctx, _make_store, _mediainfo, _PROVIDER


@pytest.fixture
def backing():
    data = {}
    return data


def store_for(backing):
    return BlacklistStore(lambda key: deepcopy(backing.get(key)),
                          lambda key, value: backing.__setitem__(key, deepcopy(value)))


def tv(**kwargs):
    return {"title": "测试剧", "type": "电视剧", "tmdbid": "42", **kwargs}


@pytest.mark.parametrize("season", [0, 1, 3])
def test_all_seasons_block_survives_reopen(backing, season):
    store_for(backing).add(tv(season=2))
    reopened = store_for(backing)
    assert reopened.match(tv(season=season))
    assert not reopened.match(tv(type="电影", season=season))
    assert not reopened.match(tv(tmdbid="43", season=season))


@pytest.mark.parametrize("season", [0, 2])
def test_single_season_does_not_block_other_or_unknown_seasons(backing, season):
    store = store_for(backing)
    store.add(tv(), season=season)
    assert store.match(tv(season=season))
    assert not store.match(tv(season=season + 1))
    assert not store.match(tv())


def test_tmdb_all_seasons_accepts_different_douban_subjects(backing):
    store = store_for(backing)
    store.add(tv(doubanid="season-one"))
    assert store.match(tv(doubanid="season-two", season=2))


def test_unknown_tmdb_type_requires_recognition(backing):
    store = store_for(backing)
    store.add(tv())
    assert not store.match(tv(type=""))
    # 豆瓣 subject 的命名空间自身不区分电影/剧集，可在识别前按该 ID 命中。
    store.add(tv(tmdbid=None, doubanid="123"))
    assert store.match({"doubanid": "123"})


def test_source_aliases_and_generic_media_identity(backing):
    store = store_for(backing)
    store.add(tv(), aliases=[{"title": "测试剧 第二季", "type_hint": "电视剧", "douban_id": "123"}])
    assert store.match({"douban_id": "123", "type_hint": MediaType.TV, "season": 2})
    assert store.match({"media_source": "themoviedb", "media_id": "42", "type": "电视剧"})
    assert not store.match({"media_source": "themoviedb", "media_id": "42", "type": "电影"})


def test_manual_title_rule_requires_exact_title_type_and_optional_year(backing):
    store = store_for(backing)
    store.add({"title": " The Show ", "type": "电视剧", "year": "2026"})
    assert store.match({"title": "the show", "type": "电视剧", "year": "2026", "tmdbid": "8"})
    assert not store.match({"title": "The Show Again", "type": "电视剧", "year": "2026"})
    assert not store.match({"title": "The Show", "type": "电视剧", "year": "2025"})
    assert not store.match({"title": "The Show", "type": "电影", "year": "2026"})


@pytest.mark.parametrize("season", [-1, 1.5, True, "", "1.0"])
def test_invalid_seasons_rejected(backing, season):
    with pytest.raises(ValueError):
        store_for(backing).add(tv(), season=season)


def test_stale_store_cannot_erase_rules_and_repeated_add_is_idempotent(backing):
    first, second = store_for(backing), store_for(backing)
    row = first.add(tv())
    second.add(tv(title="另一部剧", tmdbid="43"))
    assert first.add(tv())["id"] == row["id"]
    assert len(second.list()) == 2
    first.delete([row["id"]])
    assert len(second.list()) == 1


def ready_context(backing, season=2):
    ctx = _make_ctx()
    ctx.get_data = lambda key: deepcopy(backing.get(key))
    ctx.save_data = lambda key, value: backing.__setitem__(key, deepcopy(value))
    ctx.chain.recognize_media.return_value = _mediainfo(mtype=MediaType.TV, season=season)
    ctx.downloadchain.get_no_exists_info.return_value = (False, {})
    ctx.subscribechain.exists.return_value = False
    ctx.subscribechain.add.return_value = (77, "")
    return ctx


def test_precheck_blocks_before_recognition_and_is_reversible(backing):
    ctx = ready_context(backing)
    history, _ = _make_store()
    row = store_for(backing).add(tv(tmdbid=None, doubanid="123"), season=2)
    item = RankMediaItem(title="测试剧 第二季", douban_id="123", type_hint=MediaType.TV)
    result = _exec(ctx).process(item, _PROVIDER, FilterChain([]), history, {})
    assert result.status == SubscribeStatus.BLACKLISTED
    ctx.chain.recognize_media.assert_not_called()
    ctx.subscribechain.add.assert_not_called()
    assert history.query()[0][0]["status"] == "blacklisted"
    store_for(backing).delete([row["id"]])
    result = _exec(ctx).process(item, _PROVIDER, FilterChain([]), history, {})
    assert result.status == SubscribeStatus.SUBSCRIBED


def test_postcheck_blocks_canonical_identity_from_different_source(backing):
    ctx = ready_context(backing)
    history, _ = _make_store()
    store_for(backing).add(tv(tmdbid="438631"), season=2)
    result = _exec(ctx).process(RankMediaItem(title="测试剧 第二季", douban_id="123", type_hint=MediaType.TV),
                                _PROVIDER, FilterChain([]), history, {})
    assert result.status == SubscribeStatus.BLACKLISTED
    ctx.chain.recognize_media.assert_called_once()
    ctx.subscribechain.add.assert_not_called()


def test_rule_added_during_pipeline_is_checked_again_before_add(backing):
    ctx = ready_context(backing)
    history, _ = _make_store()

    def add_rule(**_):
        store_for(backing).add(tv(tmdbid="438631"))
        return False

    ctx.subscribechain.exists.side_effect = add_rule
    result = _exec(ctx).process(RankMediaItem(title="测试剧 第二季", douban_id="123", type_hint=MediaType.TV),
                                _PROVIDER, FilterChain([]), history, {})
    assert result.status == SubscribeStatus.BLACKLISTED
    ctx.subscribechain.add.assert_not_called()


class Api(BlacklistApiMixin):
    def __init__(self, backing):
        self.get_data = lambda key: deepcopy(backing.get(key))
        self.save_data = lambda key, value: backing.__setitem__(key, deepcopy(value))
        self.manager = MagicMock()
        self.manager.list_mine.return_value = [{"id": 1, "name": "测试剧", "type": "电视剧", "tmdbid": "42", "season": 2}]
        self.manager.delete.return_value = {"ok": 1, "failed": 0, "ok_ids": [1], "failed_ids": []}
        self.history = MagicMock()

    def blacklist_subscribe_manager(self):
        return self.manager

    def blacklist_history_store(self):
        return self.history


def test_api_add_from_history_keeps_source_snapshot_and_clear_does_not_remove_rule(backing):
    api = Api(backing)
    api.history.get.return_value = tv(season=2, source_item={"douban_id": "123"})
    assert api.api_blacklist_add({"kind": "history", "unique": "old", "scope": "season"})["code"] == 0
    api.history.clear()
    assert api.blacklist_store().match({"douban_id": "123", "season": 2})
    assert len(api.api_blacklist()["list"]) == 1


def test_unsubscribe_only_after_rule_is_saved(backing):
    api = Api(backing)

    def delete(ids):
        assert api.blacklist_store().match(tv(season=2))
        return {"ok": 1}

    api.manager.delete.side_effect = delete
    result = api.api_subscribes_block({"ids": [1, 99], "scope": "season"})
    assert result["ok_ids"] == [1]
    assert result["failed_ids"] == [99]
    api.manager.delete.assert_called_once_with([1])


def test_failed_persistence_does_not_unsubscribe(backing):
    api = Api(backing)
    api.save_data = lambda *_: False
    result = api.api_subscribes_block({"ids": [1]})
    assert result["failed_ids"] == [1]
    assert "黑名单保存失败" in result["message"]
    api.manager.delete.assert_not_called()


def test_failed_unsubscribe_keeps_rule_for_next_run(backing):
    api = Api(backing)
    api.manager.delete.return_value = {"ok": 0}
    result = api.api_subscribes_block({"ids": [1]})
    assert result["failed_ids"] == [1]
    assert api.blacklist_store().match(tv(season=2))


def test_manual_and_delete_api_validate_and_report_failures(backing):
    api = Api(backing)
    assert api.api_blacklist_add({"kind": "manual", "media": tv(), "scope": "season"})["code"] == 1
    assert api.api_blacklist_add({"kind": "manual", "media": tv(media_source="tmdb")})["code"] == 1
    assert api.api_blacklist_delete({"ids": []})["code"] == 1
    result = api.api_blacklist_add({"media": tv()})
    assert result["code"] == 0
    assert api.api_blacklist_delete({"ids": [result["item"]["id"]]})["removed"] == 1


def test_blacklist_routes_require_bearer_auth_and_sidebar_declares_entry():
    plugin = AutomaticSubscriptionAssistant.__new__(AutomaticSubscriptionAssistant)
    endpoints = [route for route in plugin.get_api() if "blacklist" in route["path"] or route["path"] == "/subscribes/block"]
    assert len(endpoints) == 4
    assert all(route["auth"] == "bear" for route in endpoints)
    assert plugin.get_sidebar_nav()[0]["nav_key"] == "blacklist"


def test_manual_douban_all_seasons_resolves_canonical_show_before_saving(backing):
    api = Api(backing)
    api.blacklist_resolve_media = MagicMock(return_value=tv())
    result = api.api_blacklist_add({"media": {"title": "测试剧 第二季", "type": "电视剧", "media_source": "douban", "media_id": "123"}})
    assert result["code"] == 0
    api.blacklist_resolve_media.assert_called_once()
    assert api.blacklist_store().match(tv(season=3, doubanid="456"))


def test_manual_douban_all_seasons_does_not_claim_whole_show_if_resolution_fails(backing):
    api = Api(backing)
    api.blacklist_resolve_media = MagicMock(return_value=None)
    result = api.api_blacklist_add({"media": {"title": "测试剧", "type": "电视剧", "doubanid": "123"}})
    assert result["code"] == 1
    assert "整剧身份" in result["message"]
    assert not api.blacklist_store().list()


def test_single_season_douban_rule_does_not_require_whole_show_recognition(backing):
    api = Api(backing)
    api.blacklist_resolve_media = MagicMock()
    result = api.api_blacklist_add({"scope": "season", "media": {"title": "测试剧", "type": "电视剧", "doubanid": "123", "season": 2}})
    assert result["code"] == 0
    api.blacklist_resolve_media.assert_not_called()


def test_host_recognition_helper_only_recognizes_without_subscribing():
    plugin = AutomaticSubscriptionAssistant.__new__(AutomaticSubscriptionAssistant)
    recognized = _mediainfo(mtype=MediaType.TV, season=2)
    plugin.chain = SimpleNamespace(recognize_media=MagicMock(return_value=recognized))
    result = plugin.blacklist_resolve_media({"title": "测试剧 第二季", "type": "电视剧", "media_source": "douban", "media_id": "123"})
    assert result is recognized
    args = plugin.chain.recognize_media.call_args.kwargs
    assert args["mtype"] == MediaType.TV
    # v3 使用通用身份；v2 使用兼容 ID 参数。
    assert args.get("media_id", args.get("doubanid")) == "123"


def test_movie_is_blocked_after_source_identity_conversion(backing):
    ctx = ready_context(backing)
    ctx.chain.recognize_media.return_value = _mediainfo(mtype=MediaType.MOVIE)
    history, _ = _make_store()
    store_for(backing).add({"title": "沙丘", "type": "电影", "tmdbid": "438631"})
    result = _exec(ctx).process(RankMediaItem(title="沙丘", douban_id="123", type_hint=MediaType.MOVIE),
                                _PROVIDER, FilterChain([]), history, {})
    assert result.status == SubscribeStatus.BLACKLISTED
    ctx.subscribechain.add.assert_not_called()
    assert history.query()[0][0]["season"] is None


def test_whole_show_block_does_not_require_resolving_an_ambiguous_season(backing):
    ctx = ready_context(backing, season=None)
    ctx.chain.recognize_media.return_value.seasons = {1: [1], 2: [1]}
    history, _ = _make_store()
    store_for(backing).add(tv(tmdbid="438631"))
    result = _exec(ctx).process(RankMediaItem(title="测试剧", douban_id="123", type_hint=MediaType.TV),
                                _PROVIDER, FilterChain([]), history, {})
    assert result.status == SubscribeStatus.BLACKLISTED
    ctx.subscribechain.add.assert_not_called()
