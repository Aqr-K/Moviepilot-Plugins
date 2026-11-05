"""苹果音乐统一规则：逐条地区/榜单、独立数量和严格参数校验。"""

from copy import deepcopy
from unittest.mock import MagicMock

import pytest
from app.plugins.automaticsubscriptionassistant.core.config import build_defaults
from app.plugins.automaticsubscriptionassistant.core.i18n import localize_spec
from app.plugins.automaticsubscriptionassistant.providers import applemusic
from test_executor import _make_ctx


def response_for(url):
    if "applemarketingtools" in url:
        return {
            "feed": {
                "results": [{"id": "song", "name": "Song", "artistName": "Artist"}]
            }
        }
    return {
        "feed": {
            "entry": [
                {
                    "id": {"attributes": {"im:id": "album"}},
                    "im:name": {"label": "Album"},
                    "im:artist": {"label": "Artist"},
                }
            ]
        }
    }


def test_spec_uses_only_rule_list_and_independent_defaults():
    provider = applemusic.AppleMusicRankProvider()
    spec = provider.get_spec()
    assert [f.key for f in spec.options_schema] == ["rules", "proxy"]
    field = spec.options_schema[0]
    assert field.kind == "rule-list"
    assert {f.key for f in field.fields} == {"country", "chart", "limit"}
    defaults = build_defaults([spec])["providers"]["applemusic"]["options"]["rules"]
    defaults[0]["chart"] = "itunes-albums"
    assert provider.rules({})[0]["chart"] == "apple-songs"


def test_fetch_only_enabled_pairs_with_independent_limits(monkeypatch):
    request = MagicMock(side_effect=lambda url, context: response_for(url))
    monkeypatch.setattr(applemusic, "request_json", request)
    options = {
        "rules": [
            {
                "name": "US albums",
                "country": "us",
                "chart": "itunes-albums",
                "limit": 15,
            },
            {"name": "JP songs", "country": "jp", "chart": "apple-songs", "limit": 30},
            {"name": "GB off", "country": "gb", "chart": "itunes-songs", "on": False},
        ]
    }
    original = deepcopy(options)
    rows = list(applemusic.AppleMusicRankProvider().fetch(options, _make_ctx()))
    assert [call.args[0] for call in request.call_args_list] == [
        "https://itunes.apple.com/us/rss/topalbums/limit=15/json",
        "https://rss.applemarketingtools.com/api/v2/jp/music/most-played/50/songs.json",
    ]
    assert [row.source_meta["chart"] for row in rows] == [
        "us:itunes-albums",
        "jp:apple-songs",
    ]
    assert [row.music_type for row in rows] == ["album", "recording"]
    assert options == original


@pytest.mark.parametrize(
    "entries", [[], [{"country": "us", "chart": "apple-songs", "on": False}]]
)
def test_empty_or_disabled_rules_do_not_listen_or_fetch(monkeypatch, entries):
    request = MagicMock()
    monkeypatch.setattr(applemusic, "request_json", request)
    provider = applemusic.AppleMusicRankProvider()
    assert not provider.has_listening({"rules": entries})
    assert list(provider.fetch({"rules": entries}, _make_ctx())) == []
    request.assert_not_called()


@pytest.mark.parametrize(
    "entries",
    [
        None,
        {},
        [{"country": "xx"}],
        [{"chart": "invalid"}],
        [{"on": "false"}],
        [{"limit": -1}],
        [{"limit": 1.5}],
        [{"chart": None}],
    ],
)
def test_invalid_rules_fail_before_network(monkeypatch, entries):
    request = MagicMock()
    monkeypatch.setattr(applemusic, "request_json", request)
    with pytest.raises((TypeError, ValueError)):
        list(applemusic.AppleMusicRankProvider().fetch({"rules": entries}, _make_ctx()))
    request.assert_not_called()


def test_cross_region_duplicates_keep_all_rule_matches(monkeypatch):
    request = MagicMock(side_effect=lambda url, context: response_for(url))
    monkeypatch.setattr(applemusic, "request_json", request)
    rows = list(
        applemusic.AppleMusicRankProvider().fetch(
            {
                "rules": [
                    {"name": "US", "country": "us", "chart": "apple-songs"},
                    {"name": "JP", "country": "jp", "chart": "apple-songs"},
                ]
            },
            _make_ctx(),
        )
    )
    assert len(rows) == 1 and len(rows[0].source_meta["matches"]) == 2
    assert {m["name"] for m in rows[0].source_meta["matches"]} == {"US", "JP"}


@pytest.mark.parametrize(
    "lang,title", [("zh-CN", "美国"), ("zh-TW", "美國"), ("en-US", "United States")]
)
def test_nested_region_localization_preserves_values(lang, title):
    original = applemusic.AppleMusicRankProvider().get_spec().to_dict()
    before = deepcopy(original)
    spec = localize_spec(original, lang)
    country = next(
        f for f in spec["options_schema"][0]["fields"] if f["key"] == "country"
    )
    assert next(o for o in country["options"] if o["value"] == "us")["title"] == title
    assert original == before
