"""来源规则的公开契约、独立请求、筛选 OR 与持久命中轨迹。"""

from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from app.plugins.automaticsubscriptionassistant.core import rules
from app.plugins.automaticsubscriptionassistant.core.config import (
    GlobalConfig,
    ProviderConfig,
    build_defaults,
)
from app.plugins.automaticsubscriptionassistant.core.filters import build_filter_chain
from app.plugins.automaticsubscriptionassistant.core.i18n import localize_spec
from app.plugins.automaticsubscriptionassistant.core.registry import registry
from app.plugins.automaticsubscriptionassistant.core.runner import ProviderRunner
from app.plugins.automaticsubscriptionassistant.providers import (
    anilist,
    mikan,
    netflix,
    popular,
)
from app.plugins.automaticsubscriptionassistant.schemas import RankMediaItem
from app.schemas.types import MediaType
from test_executor import _make_ctx
from test_runner import _movie_ctx, _store

RULE_PROVIDERS = registry.ids()


@pytest.mark.parametrize("pid", RULE_PROVIDERS)
def test_rule_contract_defaults_serialization_and_empty_disables(pid, monkeypatch):
    monkeypatch.setattr(popular.settings, "SUBSCRIBE_STATISTIC_SHARE", True)
    provider = registry.get(pid)
    spec = provider.get_spec()
    assert spec.options_schema[0].kind == "rule-list"
    assert spec.options_schema[0].fields
    defaults = build_defaults([spec])["providers"][pid]
    parsed = ProviderConfig(defaults, spec).option("rules")
    assert isinstance(parsed, list) and provider.has_listening(defaults["options"])
    assert not provider.has_listening({"rules": []})
    assert list(provider.fetch({"rules": []}, _make_ctx())) == []
    assert spec.to_dict()["options_schema"][0]["fields"]
    parsed.clear()
    assert spec.options_schema[0].default


@pytest.mark.parametrize(
    "bad",
    [
        None,
        {},
        "x",
        [{"on": "false"}],
        [{"sort": "BOGUS"}],
        [{"formats": []}],
        [{"limit": -1}],
        [{"limit": True}],
        [{"limit": "nan"}],
        [{"limit": 1.5}],
        [{"statuses": ["invalid"]}],
        [{"name": "x" * 81}],
    ],
)
def test_invalid_rules_fail_before_network(bad, monkeypatch):
    request = MagicMock()
    monkeypatch.setattr(anilist, "request_json", request)
    with pytest.raises((ValueError, TypeError)):
        list(anilist.AniListRankProvider().fetch({"rules": bad}, _make_ctx()))
    request.assert_not_called()


def test_duplicate_conditions_not_evaded_by_name_id_enabled_or_order():
    provider = anilist.AniListRankProvider()
    with pytest.raises(ValueError, match="重复规则"):
        provider.rules(
            {
                "rules": [
                    {"id": "a", "name": "A", "formats": ["TV", "MOVIE"]},
                    {"id": "b", "name": "B", "on": False, "formats": ["MOVIE", "TV"]},
                ]
            }
        )


def test_anilist_independent_combinations_and_upstream_filters(monkeypatch):
    calls = []

    def request(url, ctx, **kwargs):
        calls.append(deepcopy(kwargs["payload"]["variables"]))
        return {"data": {"Page": {"media": [], "pageInfo": {"hasNextPage": False}}}}

    monkeypatch.setattr(anilist, "request_json", request)
    list(
        anilist.AniListRankProvider().fetch(
            {
                "rules": [
                    {
                        "name": "season tv",
                        "time": "current",
                        "formats": ["TV"],
                        "limit": 15,
                    },
                    {
                        "name": "year film",
                        "time": "fixed",
                        "year": 2025,
                        "season": "ALL",
                        "formats": ["MOVIE"],
                        "sort": "SCORE_DESC",
                        "limit": 30,
                        "statuses": ["FINISHED"],
                        "genres": ["Action"],
                        "tags": "Time Travel, Time Travel",
                        "country": "JP",
                        "minimum_score": 8.5,
                    },
                ]
            },
            _make_ctx(),
        )
    )
    assert len(calls) == 2
    assert calls[0]["formats"] == ["TV"] and calls[0]["perPage"] == 15
    assert "season" in calls[0]
    assert calls[1]["formats"] == ["MOVIE"] and calls[1]["seasonYear"] == 2025
    assert "season" not in calls[1] and calls[1]["sort"] == ["SCORE_DESC"]
    assert calls[1]["minimumScore"] == 84 and calls[1]["tags"] == ["Time Travel"]
    assert calls[1]["genres"] == ["Action"] and calls[1]["country"] == "JP"


def test_mikan_multiple_quarters_cross_year_and_disabled(monkeypatch):
    class Clock:
        @staticmethod
        def now(tz):
            return datetime(2027, 1, 8, tzinfo=timezone.utc)

    monkeypatch.setattr(rules, "datetime", Clock)
    calls = []
    monkeypatch.setattr(
        mikan.MikanApi, "season", lambda self, y, s: calls.append((y, s)) or []
    )
    list(
        mikan.MikanRankProvider().fetch(
            {
                "rules": [
                    {"time": "current"},
                    {"time": "previous"},
                    {"time": "next"},
                    {"time": "fixed", "year": 2024, "season": "夏"},
                    {"time": "fixed", "year": 2023, "season": "春", "on": False},
                ]
            },
            _make_ctx(),
        )
    )
    assert calls == [(2027, "冬"), (2026, "秋"), (2027, "春"), (2024, "夏")]


def test_popular_independent_thresholds_and_no_cartesian_product(monkeypatch):
    monkeypatch.setattr(popular.settings, "SUBSCRIBE_STATISTIC_SHARE", True)
    calls = []

    def category(self, cat, count, genres, rating, popularity):
        calls.append((cat, count, genres, rating, popularity))
        return iter(
            [
                RankMediaItem(
                    title=str(i),
                    media_source="themoviedb",
                    media_id=str(i),
                    type_hint=MediaType.MOVIE,
                )
                for i in range(5)
            ]
        )

    monkeypatch.setattr(popular.PopularRankProvider, "_fetch_category", category)
    rows = list(
        popular.PopularRankProvider().fetch(
            {
                "rules": [
                    {
                        "category": "movie",
                        "genres": ["28"],
                        "limit": 2,
                        "min_rating": 7,
                        "popularity": 15,
                    },
                    {
                        "category": "tv",
                        "genres": ["16"],
                        "limit": 3,
                        "min_rating": 8,
                        "popularity": 30,
                    },
                ]
            },
            _make_ctx(),
        )
    )
    assert calls == [("movie", 2, [28], 7, 15), ("tv", 3, [16], 8, 30)]
    assert len(rows) == 3 and len(rows[0].source_meta["matches"]) == 2
    with pytest.raises(ValueError):
        popular.PopularRankProvider().rules(
            {"rules": [{"category": "tv", "genres": ["28"]}]}
        )


def test_netflix_both_global_datasets_and_country_are_independent(monkeypatch):
    calls = []

    def fetch(self, opts, ctx):
        calls.append(opts)
        yield RankMediaItem(title="Film", type_hint=MediaType.MOVIE, unique_seed="film")

    monkeypatch.setattr(netflix.NetflixRankProvider, "_fetch_options", fetch)
    rows = list(
        netflix.NetflixRankProvider().fetch(
            {
                "rules": [
                    {
                        "name": "weekly",
                        "dataset": "weekly",
                        "categories": ["Films (English)"],
                    },
                    {
                        "name": "popular",
                        "dataset": "most-popular",
                        "categories": ["TV (English)"],
                    },
                    {
                        "name": "JP films",
                        "dataset": "country",
                        "country": "JP",
                        "categories": ["Films"],
                    },
                ],
            },
            _make_ctx(),
        )
    )
    assert len(calls) == 3 and len(rows) == 1
    assert (
        calls[0]["global_dataset"] == netflix.DATASET_WEEKLY
        and calls[0]["country_selections"] == {}
    )
    assert calls[1]["global_dataset"] == netflix.DATASET_POPULAR and calls[1][
        "global_media_types"
    ] == ["TV (English)"]
    assert calls[2]["global"] is False and list(calls[2]["country_selections"]) == [
        "JP"
    ]
    assert len(rows[0].source_meta["matches"]) == 3


def test_partial_rule_failure_keeps_other_results_and_reports_error():
    item = RankMediaItem(title="Film", type_hint=MediaType.MOVIE)

    def fail():
        raise RuntimeError("not available")

    iterator = rules.merge_jobs(
        [
            ({"id": "a", "name": "good"}, lambda: iter([item])),
            ({"id": "b", "name": "bad"}, fail),
        ],
        _make_ctx(),
    )
    assert next(iterator).title == "Film"
    with pytest.raises(RuntimeError, match="not available"):
        next(iterator)
    assert item.source_meta == {}  # 未修改缓存/调用方对象


def test_rules_must_pass_both_filter_stages_in_same_branch():
    chain = build_filter_chain(["year", "vote"])
    item = RankMediaItem(
        title="Film",
        year="2020",
        source_meta={
            "matches": [
                {"name": "new films", "filters": {"year": 2025, "vote": 0}},
                {"name": "high score", "filters": {"year": 0, "vote": 9}},
            ]
        },
    )
    assert chain.run("pre", item, None, {}).accepted
    assert not chain.run("post", item, SimpleNamespace(vote_average=8), {}).accepted
    assert chain.run("post", item, SimpleNamespace(vote_average=9), {}).accepted


def test_runner_subscribes_once_and_keeps_matches_on_later_handled_run(monkeypatch):
    provider = anilist.AniListRankProvider()
    item = RankMediaItem(
        title="Film", year="2020", type_hint=MediaType.MOVIE, tmdb_id=1
    )
    monkeypatch.setattr(provider, "_fetch_options", lambda opts, ctx: iter([item]))
    ctx = _movie_ctx()
    history, _ = _store()
    cfg = ProviderConfig(
        {
            "filters": {"year": 2090},
            "options": {
                "rules": [
                    {"id": "trend", "name": "Trending"},
                    {"id": "rated", "name": "Rated", "sort": "SCORE_DESC"},
                ]
            },
        },
        provider.get_spec(),
    )
    runner = ProviderRunner(ctx, GlobalConfig({}), history)
    assert runner.run(provider, cfg) == {"subscribed": 1}
    saved = history.values()[0]
    assert len(saved["source_item"]["source_meta"]["matches"]) == 2
    cfg.options["rules"].append(
        {"id": "fav", "name": "Favourites", "sort": "FAVOURITES_DESC"}
    )
    assert runner.run(provider, cfg) in (
        {"already_handled": 1},
        {"subscription_exists": 1},
    )
    ctx.subscribechain.add.assert_called_once()
    saved = history.values()[0]
    assert {m["name"] for m in saved["source_item"]["source_meta"]["matches"]} == {
        "Trending",
        "Rated",
        "Favourites",
    }
    assert saved["status"] == "subscribed"


def test_nested_localization_preserves_rule_values_and_conditions():
    spec = anilist.AniListRankProvider().get_spec().to_dict()
    before = deepcopy(spec)
    en = localize_spec(spec, "en-US")
    fields = {f["key"]: f for f in en["options_schema"][0]["fields"]}
    assert fields["sort"]["label"] == "Rank by"
    assert fields["time"]["options"][1]["title"] == "Current season"
    assert fields["year"]["visible_when"] == {"time": ["fixed"]}
    assert spec == before


def test_qq_selection_uses_official_groups_and_spotify_has_no_region():
    qq = registry.get("qqmusic").get_spec().options_schema[0]
    options = next(f for f in qq.fields if f.key == "chart").options
    assert {v["group"] for v in options} >= {"巅峰榜", "地区榜", "特色榜", "全球榜"}
    sp = registry.get("spotify").get_spec().options_schema[0]
    assert {f.key for f in sp.fields} == {"chart", "limit"}


def test_invalid_api_rules_are_rejected_before_configuration_write():
    from app.plugins.automaticsubscriptionassistant.api.configuration import (
        ConfigurationApiMixin,
    )

    api = ConfigurationApiMixin()
    api._providers = [anilist.AniListRankProvider()]
    api.update_config = MagicMock()
    result = api.api_save_config(
        {
            "providers": {
                "anilist": {"enabled": True, "options": {"rules": [{"limit": -1}]}}
            }
        }
    )
    assert result["code"] == 1
    api.update_config.assert_not_called()


def test_stop_during_collection_discards_candidates_before_subscription():
    from threading import Event

    ctx = _make_ctx()
    ctx.event = Event()

    def fetch():
        yield RankMediaItem(title="First")
        ctx.event.set()
        yield RankMediaItem(title="Second")

    assert list(rules.merge_jobs([({"id": "a", "name": "rule"}, fetch)], ctx)) == []


def test_spotify_requests_public_payload_once_for_multiple_cards(monkeypatch):
    from app.plugins.automaticsubscriptionassistant.providers import spotify

    request = MagicMock(
        return_value={
            "chartEntryViewResponses": [
                {
                    "displayChart": {
                        "chartMetadata": {
                            "alias": "REGIONAL_GLOBAL_WEEKLY",
                            "entityType": "TRACK",
                        }
                    },
                    "entries": [
                        {
                            "trackMetadata": {
                                "trackName": "Song",
                                "trackUri": "spotify:track:one",
                                "artists": [{"name": "Artist"}],
                            }
                        }
                    ],
                }
            ]
        }
    )
    monkeypatch.setattr(spotify, "request_json", request)
    rows = list(
        spotify.SpotifyRankProvider().fetch(
            {
                "rules": [
                    {"id": "one", "chart": "REGIONAL_GLOBAL_WEEKLY", "limit": 1},
                    {"id": "two", "chart": "REGIONAL_GLOBAL_WEEKLY", "limit": 2},
                ]
            },
            _make_ctx(),
        )
    )
    request.assert_called_once()
    assert len(rows) == 1 and len(rows[0].source_meta["matches"]) == 2


@pytest.mark.parametrize(
    "pid,old_options",
    [
        ("anilist", {"charts": ["popular"]}),
        ("mikan", {"year": 2025, "season": "夏"}),
        ("douban", {"ranks": []}),
        ("popular", {"movie_enabled": False}),
        ("spotify", {"charts": []}),
        ("netease", {"charts": ["3778678"]}),
        ("qqmusic", {"charts": ["26"]}),
        ("netflix", {"global": False}),
    ],
)
def test_previous_flat_configuration_does_not_start_default_subscriptions(
    pid, old_options
):
    provider = registry.get(pid)
    with pytest.raises(ValueError, match="重新设置"):
        list(provider.fetch(old_options, _make_ctx()))


def test_new_rule_configuration_survives_save_and_reload_without_matrix_fields():
    from app.plugins.automaticsubscriptionassistant.api.configuration import (
        ConfigurationApiMixin,
    )

    api = ConfigurationApiMixin()
    api._providers = registry.create_all()
    api._database_ready = True
    api.init_plugin = MagicMock()
    api._refresh_jobs = MagicMock()
    saved = {}

    def persist(value):
        saved.clear()
        saved.update(deepcopy(value))
        return True

    api.update_config = persist
    api.get_config = lambda: deepcopy(saved)
    request = {
        "providers": {
            "applemusic": {
                "enabled": True,
                "notify": False,
                "options": {
                    "rules": [
                        {
                            "id": "rule-http-test",
                            "name": "HTTP album",
                            "on": True,
                            "country": "jp",
                            "chart": "itunes-albums",
                            "limit": 15,
                        },
                    ]
                },
                "filters": {},
            }
        }
    }
    assert api.api_save_config(request)["code"] == 0
    loaded = api.api_get_config()["config"]
    assert (
        loaded["providers"]["applemusic"]["options"]
        == request["providers"]["applemusic"]["options"]
    )
    assert set(loaded["providers"]["applemusic"]["options"]) == {"rules"}
    assert (
        registry.get("applemusic").rules(loaded["providers"]["applemusic"]["options"])[
            0
        ]["id"]
        == "rule-http-test"
    )


@pytest.mark.parametrize('pid', RULE_PROVIDERS)
def test_all_sources_accept_wide_numeric_ranges_and_zero_limit_skips_fetch(pid, monkeypatch):
    provider = registry.get(pid)
    field = provider.get_spec().options_schema[0]
    entry = deepcopy(field.default[0])
    for spec in field.fields:
        if spec.kind in {'number', 'float'}:
            assert spec.maximum is None
            if spec.key not in {'year'}:
                entry[spec.key] = 100000
    parsed = provider.rules({'rules': [entry]})
    assert parsed
    if any(f.key == 'limit' for f in field.fields):
        entry['limit'] = 0
        monkeypatch.setattr(provider, '_fetch_options', MagicMock(side_effect=AssertionError('must not fetch')))
        assert not provider.has_listening({'rules': [entry]})
        assert list(provider.fetch({'rules': [entry]}, _make_ctx())) == []
