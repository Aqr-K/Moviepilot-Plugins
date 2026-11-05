"""腾讯音乐固定榜单目录；所有请求显式携带 QQ 音乐 Referer。"""

from ..core.registry import register
from ..core.rules import RuleRankProvider
from ..schemas import ProviderSpec
from .music_catalogs import QQ_CHARTS
from .music_common import music_item, music_options
from .ranking_http import limit_of, request_json, selected, stopped

ENDPOINT = "https://u.y.qq.com/cgi-bin/musicu.fcg"


@register
class QQMusicRankProvider(RuleRankProvider):
    provider_id = "qqmusic"
    provider_name = "腾讯音乐榜单"

    def _source_spec(self):
        return ProviderSpec(
            self.provider_id,
            self.provider_name,
            "15 10 * * *",
            options_schema=music_options(QQ_CHARTS, ["26", "27"]),
        )


    def _fetch_options(self, options, context):
        seen = set()
        for chart in selected(options, "charts", QQ_CHARTS, ["26", "27"]):
            if stopped(context):
                return
            limit = limit_of(options)
            payload = request_json(
                ENDPOINT,
                context,
                headers={
                    "Referer": "https://y.qq.com/",
                    "Content-Type": "application/json",
                },
                payload={
                    "comm": {
                        "cv": 4747474,
                        "ct": 24,
                        "format": "json",
                        "platform": "yqq.json",
                    },
                    "req_1": {
                        "module": "musicToplist.ToplistInfoServer",
                        "method": "GetDetail",
                        "param": {
                            "topId": int(chart),
                            "offset": 0,
                            "num": limit,
                            "period": "",
                        },
                    },
                },
            )
            result = payload.get("req_1") or {}
            if payload.get("code") != 0 or result.get("code") != 0:
                raise RuntimeError("腾讯音乐榜单接口返回错误")
            data = result.get("data") or {}
            rows = (data.get("data") or {}).get("song")
            if not isinstance(rows, list):
                raise TypeError("腾讯音乐榜单缺少歌曲列表")
            details = {str(row.get("id")): row for row in data.get("songInfoList", [])}
            for row in rows[:limit]:
                if stopped(context):
                    return
                identity = row.get("songId")
                detail = details.get(str(identity), {})
                album = detail.get("album") or {}
                artists = [
                    artist.get("name", "") for artist in detail.get("singer", [])
                ] or [row.get("singerName", "")]
                item = music_item(
                    "qqmusic",
                    identity,
                    detail.get("title") or row.get("title"),
                    artists,
                    album=album.get("title") or album.get("name"),
                    year=detail.get("time_public"),
                    poster=row.get("cover"),
                    chart=chart,
                    rank=row.get("rank"),
                )
                if item and item.unique_seed not in seen:
                    seen.add(item.unique_seed)
                    yield item
