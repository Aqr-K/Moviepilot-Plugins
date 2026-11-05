"""苹果音乐榜单：逐地区选择热播、歌曲和专辑榜单。"""

from ..core.registry import register
from ..core.rules import RuleRankProvider
from ..schemas import FieldSpec, ProviderSpec
from .music_common import music_item
from .ranking_http import limit_of, request_json, stopped

CHARTS = {
    "apple-songs": "Apple Music 热播歌曲",
    "itunes-songs": "iTunes 热门歌曲",
    "itunes-albums": "iTunes 热门专辑",
}
COUNTRIES = {
    "us": "United States",
    "gb": "United Kingdom",
    "cn": "Mainland China",
    "hk": "Hong Kong",
    "tw": "Taiwan",
    "jp": "Japan",
    "kr": "South Korea",
    "au": "Australia",
    "ca": "Canada",
    "de": "Germany",
    "fr": "France",
}


@register
class AppleMusicRankProvider(RuleRankProvider):
    provider_id = "applemusic"
    provider_name = "苹果音乐榜单"

    def _source_spec(self):
        return ProviderSpec(
            self.provider_id,
            self.provider_name,
            "45 9 * * *",
            options_schema=[
                FieldSpec("proxy", "使用代理访问", "switch", default=False)
            ],
        )

    def _fetch_options(self, options, context):
        seen = set()
        limit = limit_of(options)
        country, chart = options["country"], options["chart"]
        if stopped(context):
            return
        if chart == "apple-songs":
            size = next(size for size in (10, 25, 50, 100) if size >= limit)
            payload = request_json(
                f"https://rss.applemarketingtools.com/api/v2/{country}/music/most-played/{size}/songs.json",
                context,
            )
            rows = (payload.get("feed") or {}).get("results")
        else:
            name = "topalbums" if chart == "itunes-albums" else "topsongs"
            payload = request_json(
                f"https://itunes.apple.com/{country}/rss/{name}/limit={limit}/json",
                context,
            )
            rows = (payload.get("feed") or {}).get("entry")
        if not isinstance(rows, list):
            raise TypeError("Apple 音乐榜单响应缺少条目列表")
        for rank, row in enumerate(rows[:limit], 1):
            if stopped(context):
                return
            if chart == "apple-songs":
                item = music_item(
                    "applemusic",
                    row.get("id"),
                    row.get("name"),
                    [row.get("artistName", "")],
                    year=row.get("releaseDate"),
                    poster=row.get("artworkUrl100"),
                    chart=f"{country}:{chart}",
                    rank=rank,
                )
            else:
                identity = ((row.get("id") or {}).get("attributes") or {}).get("im:id")
                images = row.get("im:image") or []
                item = music_item(
                    "applemusic",
                    identity,
                    (row.get("im:name") or {}).get("label"),
                    [(row.get("im:artist") or {}).get("label", "")],
                    music_type="album" if chart == "itunes-albums" else "recording",
                    album=((row.get("im:collection") or {}).get("im:name") or {}).get(
                        "label"
                    ),
                    year=(row.get("im:releaseDate") or {}).get("label"),
                    poster=images[-1].get("label") if images else None,
                    chart=f"{country}:{chart}",
                    rank=rank,
                )
            if item and item.unique_seed not in seen:
                seen.add(item.unique_seed)
                yield item
