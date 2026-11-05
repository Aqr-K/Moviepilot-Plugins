"""配置升级保留实际订阅范围，写入前备份，失败不启动自动任务。"""

import json
from copy import deepcopy
from unittest.mock import MagicMock

import pytest
import test_database_lifecycle as lifecycle_tests
from app.plugins.automaticsubscriptionassistant.api.configuration import (
    ConfigurationApiMixin,
)
from app.plugins.automaticsubscriptionassistant.core.config_migration import (
    backup_config,
    migrate_config,
)
from app.plugins.automaticsubscriptionassistant.core.registry import registry
from app.plugins.automaticsubscriptionassistant.providers.mikan import MikanRankProvider
from test_database_lifecycle import bare_plugin

database = lifecycle_tests.database


def convert(pid, options, filters=None):
    raw = {
        "global": {"enabled": True, "username": "my-user"},
        "providers": {
            pid: {
                "enabled": True,
                "notify": True,
                "cron": "1 2 * * *",
                "options": options,
                "filters": filters or {},
            }
        },
    }
    before = deepcopy(raw)
    result, changed = migrate_config(raw, registry.create_all())
    assert raw == before
    assert changed == [pid]
    assert result["global"] == raw["global"]
    new = result["providers"][pid]
    for key in ("enabled", "notify", "cron"):
        assert new[key] == raw["providers"][pid][key]
    assert new["filters"] == {}
    assert migrate_config(result, registry.create_all()) == (result, [])
    return new["options"]


def test_douban_migrates_ranks_custom_rss_and_all_filters():
    options = convert(
        "douban",
        {
            "ranks": ["tv-hot", "movie-weekly", "tv-hot"],
            "rss_addrs": " https://example.test/rss\nhttps://example.test/rss\nhttps://example.test/2 ",
            "rsshub_base": "https://my.rsshub",
            "proxy": True,
        },
        {"year": 2023, "vote": 8.2, "media_type": "tv"},
    )
    assert options["proxy"] is True and options["rsshub_base"] == "https://my.rsshub"
    rules = options["rules"]
    assert [r["chart"] for r in rules] == ["tv-hot", "movie-weekly", "custom", "custom"]
    assert rules[-1]["url"] == "https://example.test/2"
    assert all(
        (r["min_year"], r["vote"], r["media_type"]) == (2023, 8.2, "tv") for r in rules
    )


def test_maoyan_retains_disabled_platforms_and_exact_combinations():
    rules = convert(
        "maoyan",
        {
            "movie_box": False,
            "num": 8,
            "proxy": True,
            "web_platform_map": {
                "all": [],
                "tx": ["tv", "variety"],
                "iqiyi": {"on": False, "cats": ["web"]},
            },
        },
        {"year": 2024, "media_type": "tv"},
    )["rules"]
    assert {(r["platform"], r["media"], r["on"]) for r in rules} == {
        ("tx", "tv", True),
        ("tx", "variety", True),
        ("iqiyi", "web", False),
    }
    assert all(r["limit"] == 8 and r["min_year"] == 2024 for r in rules)


def test_maoyan_older_types_and_platforms_still_upgrade():
    rules = convert(
        "maoyan",
        {
            "types": ["movie", "web-heat", "zongyi"],
            "platforms": ["tx", "iqiyi"],
            "num": 3,
        },
    )["rules"]
    assert len(rules) == 5
    assert rules[0]["chart"] == "movie-box"
    assert {(r["platform"], r["media"]) for r in rules[1:]} == {
        ("tx", "tv"),
        ("tx", "variety"),
        ("iqiyi", "tv"),
        ("iqiyi", "variety"),
    }


def test_netflix_keeps_global_dataset_types_regions_and_disabled_choices():
    options = convert(
        "netflix",
        {
            "global": False,
            "global_dataset": "most-popular",
            "global_media_types": ["TV (English)"],
            "country_selections": {
                "JP": ["TV"],
                "US": {"on": False, "cats": ["Films"]},
                "GB": [],
            },
            "limit": 4,
            "rich_metadata": True,
            "max_workers": 3,
            "use_cache": False,
            "proxy": True,
        },
    )
    assert {
        k: options[k] for k in ("rich_metadata", "max_workers", "use_cache", "proxy")
    } == {"rich_metadata": True, "max_workers": 3, "use_cache": False, "proxy": True}
    assert [
        (r["dataset"], r.get("country"), r["categories"], r["on"])
        for r in options["rules"]
    ] == [
        ("most-popular", None, ["TV (English)"], False),
        ("country", "JP", ["TV"], True),
        ("country", "US", ["Films"], False),
    ]
    assert all(r["limit"] == 4 for r in options["rules"])


def test_netflix_old_region_arrays_and_explicit_empty_matrix():
    rules = convert(
        "netflix",
        {"global": False, "countries": ["JP", "US"], "country_media_types": ["TV"]},
    )["rules"]
    assert [r["country"] for r in rules] == ["JP", "US"]
    assert (
        convert(
            "netflix",
            {
                "global": False,
                "country_selections": {},
                "countries": ["JP"],
                "country_media_types": ["TV"],
            },
        )["rules"]
        == []
    )


@pytest.mark.parametrize(
    "year,season", [(0, "当前"), (0, "春"), (2025, "当前"), (2025, "夏")]
)
def test_mikan_keeps_independent_calendar_year_and_quarter(year, season):
    options = convert(
        "mikan",
        {"year": year, "season": season, "resolve_bangumi_id": False},
        {"year": 2021},
    )
    assert options["resolve_bangumi_id"] is False
    rule = options["rules"][0]
    assert (rule["time"], rule["year"], rule["season"], rule["min_year"]) == (
        "fixed",
        year,
        season,
        2021,
    )
    provider = MikanRankProvider()
    job = provider._rule_options(rule, options)
    assert (job["year"], job["season"]) == (year, season)
    assert provider._resolve_year(job["year"]) == (year or provider._resolve_year(0))
    assert provider._resolve_season(job["season"]) == (
        season if season != "当前" else provider._resolve_season("当前")
    )


def test_popular_retains_per_genre_limits_and_disabled_category():
    rules = convert(
        "popular",
        {
            "movie_enabled": True,
            "movie_genres": ["28", "16"],
            "movie_page_cnt": 15,
            "movie_min_rating": 8.1,
            "movie_popularity": 500,
            "tv_enabled": False,
            "tv_genres": [],
            "tv_page_cnt": 7,
        },
    )["rules"]
    assert [(r["category"], r["genres"], r["limit"], r["on"]) for r in rules] == [
        ("movie", ["28"], 15, True),
        ("movie", ["16"], 15, True),
        ("tv", [], 7, False),
    ]
    assert all(r["min_rating"] == 8.1 and r["popularity"] == 500 for r in rules[:2])


@pytest.mark.parametrize(
    "pid,options",
    [
        ("douban", {"ranks": [], "rss_addrs": ""}),
        ("maoyan", {"movie_box": False, "web_platform_map": {}}),
        ("netflix", {"global": False, "country_selections": {}}),
        ("spotify", {"charts": []}),
        ("netease", {"charts": []}),
        ("qqmusic", {"charts": []}),
        ("applemusic", {"chart_selections": {}}),
        ("anilist", {"charts": []}),
    ],
)
def test_explicit_empty_selection_never_activates_new_defaults(pid, options):
    assert convert(pid, options)["rules"] == []


@pytest.mark.parametrize(
    "pid,options,expected",
    [
        (
            "spotify",
            {"charts": ["ALBUM_GLOBAL_WEEKLY"], "limit": 4},
            "ALBUM_GLOBAL_WEEKLY",
        ),
        ("netease", {"charts": ["3778678"], "limit": 4}, "3778678"),
        ("qqmusic", {"charts": ["26"], "limit": 4}, "26"),
    ],
)
def test_music_list_selection(pid, options, expected):
    rule = convert(pid, options)["rules"][0]
    assert (rule["chart"], rule["limit"]) == (expected, 4)


def test_apple_matrix_and_anilist_selection():
    rules = convert(
        "applemusic",
        {
            "chart_selections": {
                "jp": ["itunes-albums"],
                "us": {"on": False, "cats": ["apple-songs"]},
            },
            "limit": 10,
        },
    )["rules"]
    assert [(r["country"], r["chart"], r["on"]) for r in rules] == [
        ("jp", "itunes-albums", True),
        ("us", "apple-songs", False),
    ]
    rule = convert("anilist", {"charts": ["popular"], "formats": ["TV"], "limit": 8})[
        "rules"
    ][0]
    assert (
        rule["sort"] == "POPULARITY_DESC"
        and rule["limit"] == 8
        and rule["formats"] == ["TV"]
    )


def test_new_rules_including_explicit_empty_remain_untouched():
    config = {
        "providers": {
            "douban": {"options": {"rules": []}},
            "mikan": {"options": {"rules": [{"time": "next", "id": "user"}]}},
        }
    }
    assert migrate_config(config, registry.create_all()) == (config, [])
    assert migrate_config({}, registry.create_all()) == ({}, [])


@pytest.mark.parametrize(
    "pid,options,filters",
    [
        ("douban", {"ranks": ["unknown"]}, {}),
        ("douban", {"ranks": ["tv-hot"], "unknown": 1}, {}),
        ("douban", {"ranks": ["tv-hot"]}, {"future_filter": 1}),
        ("douban", {"ranks": ["tv-hot"]}, {"vote": 11}),
        ("mikan", {"year": -1, "season": "夏"}, {}),
        ("maoyan", {"web_platform_map": {"tx": ["netmovie"]}}, {}),
        ("netflix", {"country_selections": {"unknown": ["TV"]}}, {}),
        ("spotify", {"charts": ["ALBUM_GLOBAL_WEEKLY"], "limit": 0}, {}),
    ],
)
def test_non_equivalent_config_rejected_without_mutating_original(
    pid, options, filters
):
    raw = {"providers": {pid: {"options": options, "filters": filters}}}
    original = deepcopy(raw)
    with pytest.raises(ValueError, match="迁移失败"):
        migrate_config(raw, registry.create_all())
    assert raw == original


def test_backup_is_exact_idempotent_and_corruption_blocks_upgrade(tmp_path):
    original = {"providers": {"douban": {"options": {"ranks": ["tv-hot"]}}}}
    path = backup_config(original, tmp_path)
    assert json.loads(path.read_text()) == original
    assert backup_config(original, tmp_path) == path
    assert len(list(tmp_path.glob("*.json"))) == 1
    assert path.stat().st_mode & 0o077 == 0
    path.write_text("corrupt")
    with pytest.raises(OSError, match="备份校验失败"):
        backup_config(original, tmp_path)


def test_startup_migrates_persists_and_exposes_upgraded_config(
    database, monkeypatch, tmp_path
):
    plugin, _ = bare_plugin(database, monkeypatch, tmp_path)
    original = {
        "global": {"enabled": True},
        "providers": {
            "douban": {
                "enabled": True,
                "cron": "0 8 * * *",
                "options": {"ranks": ["tv-hot"]},
                "filters": {"vote": 8},
            }
        },
    }
    saved = deepcopy(original)
    writes = []

    def persist(config):
        saved.clear()
        saved.update(deepcopy(config))
        writes.append(deepcopy(config))

    plugin.update_config = persist
    plugin.get_config = lambda: deepcopy(saved)
    plugin.init_plugin(original)
    assert plugin._database_ready and not plugin._event.is_set()
    assert saved["providers"]["douban"]["options"]["rules"][0]["vote"] == 8
    assert plugin.api_get_config()["config"] == saved
    assert plugin._settings.provider_raw("douban") == saved["providers"]["douban"]
    assert len(plugin.get_service()) == 1
    assert (
        json.loads(next((tmp_path / "config-backups").glob("*.json")).read_text())
        == original
    )
    plugin.init_plugin(saved)
    assert len(writes) == 1


@pytest.mark.parametrize("failure", ["backup", "write", "readback", "invalid"])
def test_startup_migration_failure_stops_jobs_and_oneshots(
    database, monkeypatch, tmp_path, failure
):
    import app.plugins.automaticsubscriptionassistant.api.configuration as api

    plugin, _ = bare_plugin(database, monkeypatch, tmp_path)
    original = {
        "global": {"enabled": True, "onlyonce": True, "clear": True},
        "providers": {"douban": {"enabled": True, "options": {"ranks": ["tv-hot"]}}},
    }
    if failure == "invalid":
        original["providers"]["douban"]["options"]["ranks"] = ["unknown"]
    before = deepcopy(original)
    plugin.update_config = MagicMock(return_value=False if failure == "write" else None)
    plugin.get_config = lambda: deepcopy(original)
    if failure == "backup":
        monkeypatch.setattr(
            api, "backup_config", MagicMock(side_effect=OSError("disk full"))
        )
    plugin.init_plugin(original)
    assert not plugin._database_ready and plugin._event.is_set()
    assert not plugin.get_state() and plugin.get_service() == []
    assert plugin.api_get_config()["code"] == 1
    plugin._schedule_once.assert_not_called()
    plugin._reset_oneshot_flags.assert_not_called()
    if failure in {"backup", "invalid"}:
        plugin.update_config.assert_not_called()
    assert original == before


def test_api_save_old_config_also_migrates_and_backs_up(tmp_path):
    api = ConfigurationApiMixin()
    api._providers = registry.create_all()
    api._database_ready = True
    api.init_plugin = MagicMock()
    api._refresh_jobs = MagicMock()
    api.get_data_path = lambda: tmp_path
    api.update_config = MagicMock()
    original = {
        "providers": {
            "douban": {
                "enabled": True,
                "options": {"ranks": ["tv-hot"]},
                "filters": {"vote": 8},
            }
        }
    }
    assert api.api_save_config(original)["code"] == 0
    saved = api.update_config.call_args.args[0]
    assert saved["providers"]["douban"]["options"]["rules"][0]["vote"] == 8
    assert (
        json.loads(next((tmp_path / "config-backups").glob("*.json")).read_text())
        == original
    )


def test_real_sdk_configuration_storage_migrates_old_release_defaults(
    database, monkeypatch, tmp_path
):
    from app.db.oper.plugininstance import PluginInstanceOper
    from app.plugins.automaticsubscriptionassistant.providers.netflix import (
        GLOBAL_CATEGORIES,
    )

    plugin, _ = bare_plugin(database, monkeypatch, tmp_path)
    plugin._plugininstance = PluginInstanceOper()
    monkeypatch.setattr(
        plugin, "__class__", type("ASAConfigMigrationTest", (type(plugin),), {})
    )
    original = {
        "global": {"enabled": False, "username": "old-user", "history_keep": 500},
        "providers": {
            "douban": {
                "enabled": False,
                "cron": "0 8 * * *",
                "options": {
                    "ranks": ["movie-hot-gaia", "tv-hot"],
                    "rsshub_base": "https://rsshub.app",
                    "rss_addrs": "",
                    "proxy": False,
                },
                "filters": {"vote": 0, "year": 0, "media_type": "all"},
            },
            "maoyan": {
                "enabled": False,
                "options": {
                    "movie_box": True,
                    "web_platform_map": {"all": ["tv"]},
                    "num": 10,
                    "proxy": False,
                },
                "filters": {"year": 0, "media_type": "all"},
            },
            "netflix": {
                "enabled": False,
                "options": {
                    "global": True,
                    "global_dataset": "all-weeks-global",
                    "global_media_types": [c["value"] for c in GLOBAL_CATEGORIES],
                    "country_selections": {},
                    "limit": 10,
                    "proxy": False,
                    "rich_metadata": False,
                    "max_workers": 6,
                    "use_cache": True,
                },
                "filters": {},
            },
            "mikan": {
                "enabled": False,
                "options": {
                    "year": 0,
                    "season": "当前",
                    "resolve_bangumi_id": True,
                    "proxy": False,
                },
                "filters": {"year": 0},
            },
            "popular": {
                "enabled": False,
                "options": {
                    "movie_enabled": True,
                    "movie_genres": [],
                    "movie_page_cnt": 30,
                    "movie_min_rating": 0,
                    "movie_popularity": 0,
                    "tv_enabled": True,
                    "tv_genres": [],
                    "tv_page_cnt": 30,
                    "tv_min_rating": 0,
                    "tv_popularity": 0,
                },
                "filters": {},
            },
        },
    }
    plugin.update_config(original)
    plugin.init_plugin(plugin.get_config())
    assert plugin._database_ready, plugin._database_error
    saved = plugin.get_config()
    assert saved["global"] == original["global"]
    assert {
        pid: len(conf["options"]["rules"]) for pid, conf in saved["providers"].items()
    } == {"douban": 2, "maoyan": 2, "netflix": 1, "mikan": 1, "popular": 2}
    assert plugin.api_get_config()["config"] == saved
    plugin.init_plugin(saved)
    assert plugin.get_config() == saved
    assert len(list((tmp_path / "config-backups").glob("*.json"))) == 1
    plugin._plugininstance.delete("ASAConfigMigrationTest")
    # 测试引导使用隔离的宿主数据库，不访问运行实例的配置。
