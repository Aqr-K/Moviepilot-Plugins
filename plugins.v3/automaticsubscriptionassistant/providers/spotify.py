"""Spotify 公开全球周榜：单曲与专辑，不将艺术家榜当作可订阅实体。"""

from ..core.registry import register
from ..core.rules import RuleRankProvider
from ..schemas import ProviderSpec
from .music_common import music_item, music_options
from .ranking_http import limit_of, request_json, selected, stopped

ENDPOINT = "https://charts-spotify-com-service.spotify.com/public/v0/charts"
CHARTS = {
    "REGIONAL_GLOBAL_WEEKLY": "全球热门歌曲周榜",
    "ALBUM_GLOBAL_WEEKLY": "全球热门专辑周榜",
}


@register
class SpotifyRankProvider(RuleRankProvider):
    provider_id = "spotify"
    provider_name = "Spotify 音乐榜单"

    def _source_spec(self):
        return ProviderSpec(
            self.provider_id,
            self.provider_name,
            "30 9 * * *",
            options_schema=music_options(
                CHARTS, ["REGIONAL_GLOBAL_WEEKLY"], maximum=50
            ),
            notice="公开全球周榜每榜最多 50 条；歌曲与专辑按各自类型交给宿主音乐识别。",
        )


    def _fetch_options(self, options, context, payload=None):
        charts = selected(options, "charts", CHARTS, ["REGIONAL_GLOBAL_WEEKLY"])
        if not charts or stopped(context):
            return
        if payload is None:
            payload = request_json(ENDPOINT, context)
        views = payload.get("chartEntryViewResponses")
        if not isinstance(views, list):
            raise TypeError("Spotify 响应缺少公开榜单")
        found, seen = set(), set()
        for view in views:
            metadata = (view.get("displayChart") or {}).get("chartMetadata") or {}
            chart = metadata.get("alias")
            if chart not in charts:
                continue
            found.add(chart)
            if metadata.get("entityType") != (
                "ALBUM" if chart == "ALBUM_GLOBAL_WEEKLY" else "TRACK"
            ):
                raise ValueError("Spotify 榜单与实体类型不一致")
            kind = "album" if metadata.get("entityType") == "ALBUM" else "recording"
            if metadata.get("entityType") not in {"TRACK", "ALBUM"}:
                raise ValueError("Spotify 榜单实体类型不支持订阅")
            for row in (view.get("entries") or [])[: limit_of(options, 50)]:
                if stopped(context):
                    return
                if row.get("missingRequiredFields"):
                    continue
                data = (
                    row.get("albumMetadata" if kind == "album" else "trackMetadata")
                    or {}
                )
                uri = data.get("albumUri" if kind == "album" else "trackUri") or ""
                prefix = "spotify:album:" if kind == "album" else "spotify:track:"
                if not uri.startswith(prefix):
                    continue
                identity = uri[len(prefix) :]
                item = music_item(
                    "spotify",
                    identity,
                    data.get("albumName" if kind == "album" else "trackName"),
                    [artist.get("name", "") for artist in data.get("artists", [])],
                    music_type=kind,
                    year=data.get("releaseDate"),
                    poster=data.get("displayImageUri"),
                    chart=chart,
                    rank=(row.get("chartEntryData") or {}).get("currentRank"),
                )
                if item and item.unique_seed not in seen:
                    seen.add(item.unique_seed)
                    yield item
        missing = set(charts) - found
        if missing:
            raise RuntimeError(
                "Spotify 公开接口未提供所选榜单：" + ", ".join(sorted(missing))
            )
