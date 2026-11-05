"""新榜单来源、音乐身份与宿主原生音乐落地管线，测试不请求网络。"""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from app.plugins.automaticsubscriptionassistant.core.config import GlobalConfig
from app.plugins.automaticsubscriptionassistant.core.dedup import build_subscribed_index
from app.plugins.automaticsubscriptionassistant.core.executor import SubscribeExecutor
from app.plugins.automaticsubscriptionassistant.core.filters import FilterChain
from app.plugins.automaticsubscriptionassistant.providers import (
    anilist,
    applemusic,
    netease,
    qqmusic,
    spotify,
)
from app.plugins.automaticsubscriptionassistant.providers.music_catalogs import (
    NETEASE_CHARTS,
    QQ_CHARTS,
)
from app.plugins.automaticsubscriptionassistant.providers.music_common import music_item
from app.plugins.automaticsubscriptionassistant.schemas import (
    RankMediaItem,
    SubscribeStatus,
)
from app.schemas.types import MediaType
from app.sdk.media import MetaMusic, MusicInfo
from test_executor import _make_ctx, _make_store


def song(kind="recording", source="spotify", identity="origin-id", artists=None):
    return music_item(
        source,
        identity,
        "Song 2",
        artists or ["Artist"],
        music_type=kind,
        album="Album",
    )


def recognized(kind="recording", artist="Artist"):
    return MusicInfo(
        media_source="musicbrainz",
        media_id="canonical-id",
        music_type=kind,
        title="Song 2",
        artists=[artist],
        album="Album",
        year=2026,
    )


@pytest.mark.parametrize("kind", ["recording", "album"])
def test_music_reaches_native_pipeline_with_type_and_artist(kind):
    ctx = _make_ctx()
    history, _ = _make_store()
    item = song(kind)
    ctx.chain.recognize_media.return_value = recognized(kind)
    ctx.downloadchain.get_no_exists_info.return_value = (False, {})
    ctx.subscribechain.exists.return_value = False
    ctx.subscribechain.add.return_value = (77, "")
    executor = SubscribeExecutor(ctx, GlobalConfig({}))
    outcome = executor.process(
        item, SimpleNamespace(provider_id="spotify"), FilterChain([]), history, {}
    )
    assert outcome.status == SubscribeStatus.SUBSCRIBED
    meta = ctx.chain.recognize_media.call_args.kwargs["meta"]
    assert isinstance(meta, MetaMusic)
    assert meta.artists == ["Artist"] and meta.music_type == kind
    assert "media_source" not in ctx.chain.recognize_media.call_args.kwargs
    params = ctx.subscribechain.add.call_args.kwargs
    assert params["mtype"] == MediaType.MUSIC
    assert params["music_type"] == kind
    assert (
        params["media_source"] == "musicbrainz" and params["media_id"] == "canonical-id"
    )
    assert params["season"] is None
    row = history.get(f"musicbrainz:music:{kind}:canonical-id")
    assert row["artists"] == ["Artist"] and row["type"] == "音乐"
    assert history.is_handled(item.candidate_key())
    assert (
        executor.process(
            item, SimpleNamespace(provider_id="spotify"), FilterChain([]), history, {}
        ).status
        == SubscribeStatus.ALREADY_HANDLED
    )
    ctx.subscribechain.add.assert_called_once()


@pytest.mark.parametrize(
    "wrong", [recognized("album"), recognized(artist="Different Artist")]
)
def test_music_rejects_wrong_entity_or_cover_artist(wrong):
    ctx = _make_ctx()
    history, _ = _make_store()
    ctx.chain.recognize_media.return_value = wrong
    result = SubscribeExecutor(ctx, GlobalConfig({})).process(
        song(), SimpleNamespace(provider_id="spotify"), FilterChain([]), history, {}
    )
    assert result.status == SubscribeStatus.UNRECOGNIZED
    ctx.subscribechain.add.assert_not_called()


def test_music_keys_do_not_mix_artist_album_or_film():
    first = song()
    second = song("album")
    assert first.identity() != second.identity()
    assert (
        song(artists=["Artist A"]).candidate_key()
        != song(artists=["Artist B"]).candidate_key()
    )
    assert (
        first.identity()
        != RankMediaItem(
            title=first.title,
            type_hint=MediaType.MOVIE,
            media_source="spotify",
            media_id=first.media_id,
        ).identity()
    )
    assert RankMediaItem.from_dict(first.to_dict()) == first
    index = build_subscribed_index(
        [
            SimpleNamespace(
                media_source="spotify",
                media_id=first.media_id,
                type="音乐",
                music_type="recording",
            )
        ]
    )
    assert index.contains(first) and not index.contains(second)


def test_music_blacklist_blocks_original_and_canonical_id():
    ctx = _make_ctx()
    history, _ = _make_store()
    item = song()
    ctx.blacklist.add(item)
    result = SubscribeExecutor(ctx, GlobalConfig({})).process(
        item, SimpleNamespace(provider_id="spotify"), FilterChain([]), history, {}
    )
    assert result.status == SubscribeStatus.BLACKLISTED
    ctx.chain.recognize_media.assert_not_called()
    assert not ctx.blacklist.match(song("album"))


def test_music_name_blacklist_distinguishes_artists():
    ctx = _make_ctx()
    ctx.blacklist.add(
        {"title": "Song", "type": "音乐", "music_type": "recording", "artists": ["A"]}
    )
    assert ctx.blacklist.match(
        {"title": "Song", "type": "音乐", "music_type": "recording", "artists": ["A"]}
    )
    assert not ctx.blacklist.match(
        {"title": "Song", "type": "音乐", "music_type": "recording", "artists": ["B"]}
    )


def test_anilist_pages_with_ids_formats_and_no_forced_first_season(monkeypatch):
    calls = []

    def request(url, ctx, **kwargs):
        variables = deepcopy(kwargs["payload"]["variables"])
        calls.append(variables)
        return {
            "data": {
                "Page": {
                    "pageInfo": {"hasNextPage": variables["page"] == 1},
                    "media": [
                        {
                            "id": variables["page"],
                            "title": {"native": "作品 第二季"},
                            "format": "TV",
                            "averageScore": 85,
                            "startDate": {"year": 2026},
                        },
                    ],
                }
            }
        }

    monkeypatch.setattr(anilist, "request_json", request)
    rows = list(
        anilist.AniListRankProvider().fetch(
            {"rules":[{"sort":"TRENDING_DESC", "limit":51}]}, _make_ctx()
        )
    )
    assert [row.media_id for row in rows] == ["1", "2"]
    assert all(row.media_source == "anilist" and row.season is None for row in rows)
    assert calls[0]["sort"] == ["TRENDING_DESC"] and calls[1]["page"] == 2
    assert rows[0].source_meta["vote"] == 8.5


def test_anilist_graphql_errors_are_not_empty_success(monkeypatch):
    monkeypatch.setattr(
        anilist,
        "request_json",
        lambda *a, **k: {"errors": [{"message": "rate limited"}]},
    )
    with pytest.raises(RuntimeError, match="rate limited"):
        list(anilist.AniListRankProvider().fetch({"rules":[{"sort":"TRENDING_DESC"}]}, _make_ctx()))


def test_spotify_parses_track_and_album_and_excludes_artist(monkeypatch):
    views = []
    for alias, entity, key, uri in [
        ("REGIONAL_GLOBAL_WEEKLY", "TRACK", "track", "spotify:track:same"),
        ("ALBUM_GLOBAL_WEEKLY", "ALBUM", "album", "spotify:album:same"),
    ]:
        views.append(
            {
                "displayChart": {
                    "chartMetadata": {"alias": alias, "entityType": entity}
                },
                "entries": [
                    {
                        f"{key}Metadata": {
                            f"{key}Name": "Title",
                            f"{key}Uri": uri,
                            "artists": [{"name": "Artist"}],
                        }
                    }
                ],
            }
        )
    monkeypatch.setattr(
        spotify, "request_json", lambda *a, **k: {"chartEntryViewResponses": views}
    )
    rows = list(
        spotify.SpotifyRankProvider().fetch(
            {"rules":[{"chart":chart} for chart in spotify.CHARTS]}, _make_ctx()
        )
    )
    assert [row.music_type for row in rows] == ["recording", "album"]
    assert len({row.identity() for row in rows}) == 2
    assert all("ARTIST" not in choice for choice in spotify.CHARTS)


def test_spotify_missing_selected_chart_is_failure(monkeypatch):
    monkeypatch.setattr(
        spotify, "request_json", lambda *a, **k: {"chartEntryViewResponses": []}
    )
    with pytest.raises(RuntimeError, match="未提供"):
        list(spotify.SpotifyRankProvider().fetch({}, _make_ctx()))


@pytest.mark.parametrize("chart", ["apple-songs", "itunes-songs", "itunes-albums"])
def test_apple_both_feed_formats_and_bounded_count(monkeypatch, chart):
    calls = []

    def request(url, *a, **kwargs):
        calls.append(url)
        if chart == "apple-songs":
            return {
                "feed": {
                    "results": [
                        {
                            "id": "1",
                            "name": "Song",
                            "artistName": "Artist",
                            "artworkUrl100": "cover",
                        }
                    ]
                }
            }
        return {
            "feed": {
                "entry": [
                    {
                        "id": {"attributes": {"im:id": "1"}},
                        "im:name": {"label": "Song"},
                        "im:artist": {"label": "Artist"},
                        "im:image": [{"label": "cover"}],
                    }
                ]
            }
        }

    monkeypatch.setattr(applemusic, "request_json", request)
    rows = list(
        applemusic.AppleMusicRankProvider().fetch(
            {"rules":[{"country":"us", "chart":chart, "limit":30}]}, _make_ctx()
        )
    )
    assert len(rows) == 1 and rows[0].poster == "cover"
    assert rows[0].music_type == ("album" if chart == "itunes-albums" else "recording")
    if chart == "apple-songs":
        assert "/50/songs.json" in calls[0] and "page=" not in calls[0]


def test_netease_uses_fixed_id_and_preserves_artist_album(monkeypatch):
    request = MagicMock(
        return_value={
            "code": 200,
            "result": {
                "tracks": [
                    {
                        "id": 9,
                        "name": "Song",
                        "artists": [{"name": "A"}],
                        "album": {"name": "Album", "picUrl": "cover"},
                    }
                ]
            },
        }
    )
    monkeypatch.setattr(netease, "request_json", request)
    rows = list(
        netease.NeteaseRankProvider().fetch({"rules":[{"chart":"3778678"}]}, _make_ctx())
    )
    assert len(NETEASE_CHARTS) == 65 and rows[0].album == "Album"
    assert request.call_args.kwargs["params"] == {"id": "3778678"}
    assert rows[0].artists == ["A"]


def test_qq_uses_required_referer_detail_request_and_metadata(monkeypatch):
    request = MagicMock(
        return_value={
            "code": 0,
            "req_1": {
                "code": 0,
                "data": {
                    "data": {
                        "song": [
                            {
                                "songId": 9,
                                "title": "Song",
                                "singerName": "fallback",
                                "cover": "p",
                            }
                        ]
                    },
                    "songInfoList": [
                        {
                            "id": 9,
                            "singer": [{"name": "A"}, {"name": "B"}],
                            "album": {"title": "Album"},
                        }
                    ],
                },
            },
        }
    )
    monkeypatch.setattr(qqmusic, "request_json", request)
    rows = list(
        qqmusic.QQMusicRankProvider().fetch(
            {"rules":[{"chart":"26", "limit":20}]}, _make_ctx()
        )
    )
    kwargs = request.call_args.kwargs
    assert kwargs["headers"]["Referer"] == "https://y.qq.com/"
    assert kwargs["payload"]["req_1"]["param"] == {
        "topId": 26,
        "offset": 0,
        "num": 20,
        "period": "",
    }
    assert rows[0].artists == ["A", "B"] and "201" not in QQ_CHARTS


@pytest.mark.parametrize(
    "provider",
    [
        anilist.AniListRankProvider,
        spotify.SpotifyRankProvider,
        netease.NeteaseRankProvider,
        qqmusic.QQMusicRankProvider,
    ],
)
def test_new_provider_validates_charts_and_empty_list_disables(provider):
    instance = provider()
    assert instance.has_listening({"rules": []}) is False
    with pytest.raises(ValueError):
        list(instance.fetch({"rules":[{"sort":"not-a-real-sort", "chart":"not-a-real-chart"}]}, _make_ctx()))


def test_manual_music_supplement_keeps_artists_and_uses_canonical_identity():
    from app.plugins.automaticsubscriptionassistant.core.supplement import (
        HistorySupplementService,
    )
    from app.plugins.automaticsubscriptionassistant.schemas import HistoryRecord

    ctx = _make_ctx()
    history, _ = _make_store()
    history.record(
        HistoryRecord(
            unique="original", provider="spotify", title="Song", status="unrecognized"
        )
    )
    ctx.chain.recognize_media.return_value = recognized()
    ctx.downloadchain.get_no_exists_info.return_value = (False, {})
    ctx.subscribechain.exists.return_value = False
    ctx.subscribechain.add.return_value = (77, "")
    result = HistorySupplementService(ctx, GlobalConfig({}), history).submit(
        {
            "unique": "original",
            "media": {
                "title": "Song 2",
                "type": "音乐",
                "music_type": "recording",
                "artists": ["Artist"],
                "media_source": "musicbrainz",
                "media_id": "canonical-id",
            },
            "subscription": {},
        }
    )
    assert result["created"] is True
    assert ctx.chain.recognize_media.call_args.kwargs["media_source"] == "musicbrainz"


def test_music_source_provenance_uses_entity_type():
    from app.plugins.automaticsubscriptionassistant.core.subscribes import (
        SubscribeManager,
    )

    base = {"media_source": "musicbrainz", "media_id": "same", "type": "音乐"}
    assert SubscribeManager._source_key(
        {**base, "music_type": "album"}
    ) != SubscribeManager._source_key({**base, "music_type": "recording"})


def test_http_errors_close_response_and_preserve_qq_referer(monkeypatch):
    from app.plugins.automaticsubscriptionassistant.providers import ranking_http

    response = MagicMock(status_code=429)
    client = MagicMock()
    client.post_res.return_value = response
    constructor = MagicMock(return_value=client)
    monkeypatch.setattr(ranking_http, "RequestUtils", constructor)
    with pytest.raises(RuntimeError, match="429"):
        ranking_http.request_json(
            "https://u.y.qq.com/cgi-bin/musicu.fcg",
            _make_ctx(),
            payload={"test": 1},
            headers={"Referer": "https://y.qq.com/"},
        )
    assert constructor.call_args.kwargs["headers"]["Referer"] == "https://y.qq.com/"
    response.close.assert_called_once()


def test_anilist_next_season_rolls_year_and_movie_keeps_movie_type(monkeypatch):
    from datetime import datetime, timezone

    class Clock:
        @staticmethod
        def now(tz):
            return datetime(2026, 11, 4, tzinfo=timezone.utc)

    request = MagicMock(
        return_value={
            "data": {
                "Page": {
                    "media": [
                        {"id": 1, "title": {"english": "Anime Film"}, "format": "MOVIE"}
                    ],
                    "pageInfo": {"hasNextPage": False},
                }
            }
        }
    )
    from app.plugins.automaticsubscriptionassistant.core import rules
    monkeypatch.setattr(rules, "datetime", Clock)
    monkeypatch.setattr(anilist, "request_json", request)
    rows = list(
        anilist.AniListRankProvider().fetch({"rules":[{"time":"next"}]}, _make_ctx())
    )
    variables = request.call_args.kwargs["payload"]["variables"]
    assert (variables["season"], variables["seasonYear"]) == ("WINTER", 2027)
    assert rows[0].type_hint == MediaType.MOVIE
