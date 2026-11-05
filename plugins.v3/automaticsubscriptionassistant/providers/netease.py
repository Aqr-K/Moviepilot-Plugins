"""网易云音乐固定榜单目录与官方歌单详情，只读取歌曲元数据。"""

from ..core.registry import register
from ..core.rules import RuleRankProvider
from ..schemas import ProviderSpec
from .music_catalogs import NETEASE_CHARTS
from .music_common import music_item, music_options, timestamp_year
from .ranking_http import limit_of, request_json, selected, stopped


@register
class NeteaseRankProvider(RuleRankProvider):
    provider_id = "netease"
    provider_name = "网易云音乐榜单"

    def _source_spec(self):
        return ProviderSpec(
            self.provider_id,
            self.provider_name,
            "0 10 * * *",
            options_schema=music_options(NETEASE_CHARTS, ["3778678", "3779629"]),
        )


    def _fetch_options(self, options, context):
        seen = set()
        for chart in selected(
            options, "charts", NETEASE_CHARTS, ["3778678", "3779629"]
        ):
            if stopped(context):
                return
            payload = request_json(
                "https://music.163.com/api/playlist/detail",
                context,
                params={"id": chart},
                headers={"Referer": "https://music.163.com/"},
            )
            if payload.get("code") != 200:
                raise RuntimeError(f"网易云榜单返回错误码 {payload.get('code')}")
            rows = (payload.get("result") or {}).get("tracks")
            if not isinstance(rows, list):
                raise TypeError("网易云榜单缺少歌曲列表")
            for rank, row in enumerate(rows[: limit_of(options)], 1):
                if stopped(context):
                    return
                album = row.get("album") or {}
                item = music_item(
                    "netease",
                    row.get("id"),
                    row.get("name"),
                    [artist.get("name", "") for artist in row.get("artists", [])],
                    album=album.get("name"),
                    year=timestamp_year(album.get("publishTime")),
                    poster=album.get("picUrl"),
                    isrc=row.get("isrc"),
                    chart=chart,
                    rank=rank,
                )
                if item and item.unique_seed not in seen:
                    seen.add(item.unique_seed)
                    yield item
