"""自动订阅规则的优先级、媒体隔离、持久化和参数边界。"""

from copy import deepcopy
from types import SimpleNamespace

import pytest
import test_config_migration as migration_tests
from app.plugins.automaticsubscriptionassistant.core.config import (
    GlobalConfig,
    ProviderConfig,
    build_defaults,
)
from app.plugins.automaticsubscriptionassistant.core.executor import SubscribeExecutor
from app.plugins.automaticsubscriptionassistant.core.filters import build_filter_chain
from app.plugins.automaticsubscriptionassistant.core.registry import registry
from app.plugins.automaticsubscriptionassistant.core.runner import ProviderRunner
from app.plugins.automaticsubscriptionassistant.core.subscription_policy import (
    normalize_subscription_policy,
    subscription_options,
)
from app.plugins.automaticsubscriptionassistant.schemas import (
    RankMediaItem,
    SubscribeStatus,
)
from app.schemas.types import MediaType
from test_config_migration import _stored_plugin
from test_executor import _make_ctx, _make_store, _mediainfo
from test_music_sources import recognized, song
from test_runner import _FakeProvider, _movie_ctx

database = migration_tests.database


def policy(options=None, media_type="电影", enabled=True):
    return {"enabled": enabled, "configs": {media_type: options or {}}}


def test_priority_is_per_recognized_type_and_not_per_field():
    source = policy({"quality": "source", "sites": [1]})
    item = RankMediaItem(
        title="Film",
        source_meta={
            "matches": [
                {"subscription": policy({"quality": "tv"}, "电视剧")},
                {"subscription": policy({"resolution": "4K"})},
                {"subscription": policy({"quality": "later"})},
            ]
        },
    )
    before = deepcopy(item.source_meta)
    result = subscription_options(item, _mediainfo(), build_filter_chain([]), source)
    assert result == {"resolution": "4K"}  # 不混入来源的 quality/sites
    result["resolution"] = "mutated"
    assert item.source_meta == before


@pytest.mark.parametrize(
    "override",
    [
        None,
        {"enabled": False, "configs": {"电影": {"quality": "off"}}},
        policy({}, "音乐"),
    ],
)
def test_absent_disabled_or_wrong_type_uses_source(override):
    item = RankMediaItem(
        title="Film", source_meta={"matches": [{"subscription": override}]}
    )
    assert subscription_options(
        item, _mediainfo(), build_filter_chain([]), policy({"sites": [2]})
    ) == {"sites": [2]}
    assert subscription_options(item, _mediainfo(), build_filter_chain([]), None) == {}


def test_explicit_empty_rule_type_can_select_host_defaults():
    item = RankMediaItem(
        title="Film", source_meta={"matches": [{"subscription": policy()}]}
    )
    assert (
        subscription_options(
            item, _mediainfo(), build_filter_chain([]), policy({"quality": "source"})
        )
        == {}
    )


def test_only_same_rule_passing_both_filter_stages_can_override():
    item = RankMediaItem(
        title="Film",
        year="2020",
        source_meta={
            "matches": [
                {
                    "filters": {"year": 2025},
                    "subscription": policy({"quality": "wrong-year"}),
                },
                {
                    "filters": {"vote": 9},
                    "subscription": policy({"quality": "wrong-vote"}),
                },
                {
                    "filters": {"year": 2010, "vote": 7},
                    "subscription": policy({"quality": "right"}),
                },
            ]
        },
    )
    assert subscription_options(
        item, _mediainfo(), build_filter_chain(["year", "vote"]), None
    ) == {"quality": "right"}
    item.source_meta["matches"].pop()
    chain = build_filter_chain(["year", "vote"])
    assert not chain.run("post", item, _mediainfo(), {}).accepted
    assert subscription_options(
        item, _mediainfo(), chain, policy({"quality": "source"})
    ) == {"quality": "source"}


@pytest.mark.parametrize(
    "options",
    [
        {"show_edit_dialog": True},
        {"username": "admin"},
        {"season": 1},
        {"media_id": "x"},
        {"total_episode": 99},
        {"best_version": "1"},
        {"quality": {}},
        {"sites": [True]},
        {"sites": ["1"]},
        {"filter_groups": [1]},
        {"search_interval": 8761},
        {"search_interval": True},
        {"search_interval": 0},
        {"search_interval": 1.5},
        {"audio_format": "FLAC"},
        {"best_version_full": 1},
    ],
)
def test_reject_interaction_identity_wrong_type_and_malformed_options(options):
    with pytest.raises(ValueError):
        normalize_subscription_policy(policy(options))


def test_normalizer_retains_explicit_flags_and_isolates_config():
    source = policy(
        {"best_version": 0, "search_imdbid": 0, "sites": [1], "filter_groups": ["HD"]}
    )
    result = normalize_subscription_policy(source)
    assert result == source
    result["configs"]["电影"]["sites"].append(2)
    assert source["configs"]["电影"]["sites"] == [1]
    assert normalize_subscription_policy(
        policy({"best_version": 1, "best_version_full": 1}, "电视剧")
    )["enabled"]


def test_runner_resets_source_policy_between_sources():
    item = RankMediaItem(title="Film", tmdb_id=1, unique_seed="1")
    provider = _FakeProvider([item])
    ctx = _movie_ctx()
    history, _ = _make_store()
    runner = ProviderRunner(ctx, GlobalConfig({}), history)
    runner.run(
        provider,
        ProviderConfig(
            {"subscription": policy({"quality": "source"})}, provider.get_spec()
        ),
    )
    assert ctx.subscribechain.add.call_args.kwargs["quality"] == "source"
    provider._items = [RankMediaItem(title="Other", tmdb_id=2, unique_seed="2")]
    runner.run(provider, ProviderConfig({}, provider.get_spec()))
    assert "quality" not in ctx.subscribechain.add.call_args.kwargs


@pytest.mark.parametrize("manual", [False, True])
def test_video_executor_passes_only_selected_options_and_manual_ignores_auto(manual):
    ctx, (history, _) = _movie_ctx(), _make_store()
    executor = SubscribeExecutor(
        ctx,
        GlobalConfig({}),
        manual=manual,
        subscribe_options={"resolution": "manual"} if manual else None,
    )
    executor.source_subscription = policy({"quality": "source"})
    item = RankMediaItem(
        title="Film",
        tmdb_id=1,
        type_hint=MediaType.MOVIE,
        source_meta={
            "matches": [
                {"subscription": policy({"resolution": "rule", "best_version": 0})}
            ]
        },
    )
    result = executor.process(
        item, SimpleNamespace(provider_id="douban"), build_filter_chain([]), history, {}
    )
    assert result.status == SubscribeStatus.SUBSCRIBED, result.reason
    params = ctx.subscribechain.add.call_args.kwargs
    assert params["resolution"] == ("manual" if manual else "rule")
    assert "quality" not in params and "show_edit_dialog" not in params
    assert params["media_id"] == "1" and params["username"] == "自动订阅助手"
    if not manual:
        assert params["best_version"] == 0


def test_music_executor_uses_music_policy_without_video_options():
    ctx, (history, _) = _make_ctx(), _make_store()
    ctx.chain.recognize_media.return_value = recognized()
    ctx.downloadchain.get_no_exists_info.return_value = (False, {})
    ctx.subscribechain.exists.return_value = False
    ctx.subscribechain.add.return_value = (12, "")
    executor = SubscribeExecutor(ctx, GlobalConfig({}))
    executor.source_subscription = {
        "enabled": True,
        "configs": {
            "电影": {"quality": "video"},
            "音乐": {"audio_format": "FLAC", "min_bit_depth": 24},
        },
    }
    result = executor.process(
        song(),
        SimpleNamespace(provider_id="spotify"),
        build_filter_chain([]),
        history,
        {},
    )
    assert result.status == SubscribeStatus.SUBSCRIBED, result.reason
    params = ctx.subscribechain.add.call_args.kwargs
    assert params["audio_format"] == "FLAC" and params["min_bit_depth"] == 24
    assert "quality" not in params and params["mtype"] == MediaType.MUSIC


def test_rule_fetch_keeps_override_on_all_matches(monkeypatch):
    provider = registry.get("anilist")
    raw = [
        {"sort": "TRENDING_DESC", "subscription": policy({"quality": "HD"})},
        {"sort": "POPULARITY_DESC", "subscription": policy({"quality": "4K"})},
    ]
    monkeypatch.setattr(
        provider,
        "_fetch_options",
        lambda *args: [
            RankMediaItem(title="Shared", media_source="anilist", media_id="1")
        ],
    )
    rows = list(provider.fetch({"rules": raw}, _make_ctx()))
    assert len(rows) == 1
    assert [m["subscription"] for m in rows[0].source_meta["matches"]] == [
        r["subscription"] for r in raw
    ]
    assert raw[0].get("id") is None


def test_save_reload_and_legacy_upgrade_preserve_policies(
    database, monkeypatch, tmp_path
):
    provider = registry.get("anilist")
    config = build_defaults([provider.get_spec()])
    config["providers"]["anilist"]["subscription"] = policy({"quality": "source"})
    config["providers"]["anilist"]["options"]["rules"][0]["subscription"] = policy(
        {"resolution": "rule"}
    )
    plugin, saved = _stored_plugin(database, monkeypatch, tmp_path, {})
    assert plugin.api_save_config(deepcopy(config))["code"] == 0
    assert saved == config
    assert plugin.api_get_config()["config"] == config
    bad = deepcopy(config)
    bad["providers"]["anilist"]["subscription"]["configs"]["电影"][
        "show_edit_dialog"
    ] = True
    assert plugin.api_save_config(bad)["code"] == 1
    assert saved == config
    legacy = {
        "providers": {
            "douban": {
                "options": {"ranks": ["movie-weekly"]},
                "subscription": policy({"sites": [1]}),
            }
        }
    }
    upgraded = plugin._upgrade_config(legacy)
    assert (
        upgraded["providers"]["douban"]["subscription"]
        == legacy["providers"]["douban"]["subscription"]
    )
    assert upgraded["providers"]["douban"]["options"]["rules"]


def test_bad_subscription_policy_isolates_only_affected_source(
    database, monkeypatch, tmp_path
):
    original = {
        "providers": {
            "anilist": {
                "options": {"rules": []},
                "subscription": policy({"show_edit_dialog": True}),
            },
            "mikan": {"options": {"rules": []}},
        }
    }
    plugin, saved = _stored_plugin(database, monkeypatch, tmp_path, original)
    assert set(plugin.api_get_config()["provider_errors"]) == {"anilist"}
    assert saved == original
