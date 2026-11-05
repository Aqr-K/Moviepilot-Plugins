"""AniList GraphQL 动画榜单；不推测或强制将作品季号设为第一季。"""

from app.schemas.types import MediaType

from ..core.registry import register
from ..core.rules import RuleRankProvider, quarter
from ..schemas import FieldSpec, ProviderSpec, RankMediaItem
from .ranking_http import limit_of, request_json, stopped

ENDPOINT = "https://graphql.anilist.co"
FORMATS = {
    "TV": "电视动画",
    "TV_SHORT": "短篇电视动画",
    "MOVIE": "动画电影",
    "OVA": "OVA",
    "ONA": "网络动画",
    "SPECIAL": "特别篇",
}
QUERY = """query ($page:Int!, $perPage:Int!, $sort:[MediaSort], $season:MediaSeason,
  $seasonYear:Int, $formats:[MediaFormat], $statuses:[MediaStatus], $genres:[String],
  $tags:[String], $country:CountryCode, $minimumScore:Int) {
  Page(page:$page,perPage:$perPage) { pageInfo { hasNextPage }
    media(type:ANIME,sort:$sort,season:$season,seasonYear:$seasonYear,
      format_in:$formats,status_in:$statuses,genre_in:$genres,tag_in:$tags,
      countryOfOrigin:$country,averageScore_greater:$minimumScore,isAdult:false) {
      id title { romaji english native } format startDate { year } averageScore
      popularity episodes coverImage { large } siteUrl
    }
  }
}"""


@register
class AniListRankProvider(RuleRankProvider):
    provider_id = "anilist"
    provider_name = "AniList 动画榜单"

    def _source_spec(self):
        return ProviderSpec(
            self.provider_id,
            self.provider_name,
            "15 8 * * *",
            options_schema=[
                FieldSpec("proxy", "使用代理访问", "switch", default=False)
            ],
        )

    def _fetch_options(self, options, context):
        limit = limit_of(options, 500)
        variables = {
            "page": 1,
            "perPage": min(limit, 50),
            "formats": options["formats"],
            "sort": [options["sort"]],
        }
        time = options["time"]
        if time in {"current", "next"}:
            year, season = quarter(time == "next")
            variables.update(
                season=["WINTER", "SPRING", "SUMMER", "FALL"][season], seasonYear=year
            )
        elif time == "fixed":
            variables["seasonYear"] = options["year"]
            if options["season"] != "ALL":
                variables["season"] = options["season"]
        for option, variable in [
            ("statuses", "statuses"),
            ("genres", "genres"),
            ("country", "country"),
        ]:
            if options.get(option):
                variables[variable] = options[option]
        tags = list(
            dict.fromkeys(
                t.strip() for t in options.get("tags", "").split(",") if t.strip()
            )
        )
        if tags:
            variables["tags"] = tags
        if options.get("minimum_score", 0) > 0:
            # AniList 整数百分制；用 > ceil(阈值)-1 表达 >=。
            from math import ceil

            variables["minimumScore"] = ceil(options["minimum_score"] * 10) - 1
        count = 0
        while count < limit and not stopped(context):
            payload = request_json(
                ENDPOINT, context, payload={"query": QUERY, "variables": variables}
            )
            if payload.get("errors"):
                raise RuntimeError(
                    "AniList GraphQL 错误："
                    + "; ".join(
                        str(e.get("message", "请求失败")) for e in payload["errors"]
                    )
                )
            page = (payload.get("data") or {}).get("Page")
            if not isinstance(page, dict) or not isinstance(page.get("media"), list):
                raise TypeError("AniList 榜单响应缺少 Page.media")
            for row in page["media"]:
                if count >= limit or stopped(context):
                    break
                count += 1
                if not isinstance(row, dict) or not row.get("id"):
                    continue
                titles = row.get("title") or {}
                title = (
                    titles.get("native")
                    or titles.get("romaji")
                    or titles.get("english")
                )
                if not title or row.get("format") not in FORMATS:
                    continue
                yield RankMediaItem(
                    title=title,
                    type_hint=MediaType.MOVIE
                    if row["format"] == "MOVIE"
                    else MediaType.TV,
                    media_source="anilist",
                    media_id=str(row["id"]),
                    unique_seed=str(row["id"]),
                    year=str(row["startDate"]["year"])
                    if (row.get("startDate") or {}).get("year")
                    else None,
                    poster=(row.get("coverImage") or {}).get("large"),
                    source_meta={
                        "chart": options["sort"],
                        "vote": float(row.get("averageScore") or 0) / 10,
                        "count": row.get("popularity"),
                        "format": row.get("format"),
                    },
                )
            if not (page.get("pageInfo") or {}).get("hasNextPage") or not page["media"]:
                break
            variables["page"] += 1
