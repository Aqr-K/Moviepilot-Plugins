"""providers/*.py 单元测试：仅测解析，网络/浏览器/服务端全部 mock，零真实出站。"""
from __future__ import annotations

import threading
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.schemas.types import MediaType
from app.utils.http import RequestUtils
from app.helper.browser import PlaywrightHelper
from app.helper.server import MoviePilotServerHelper

from app.plugins.automaticsubscriptionassistant.providers.douban import DoubanRankProvider
from app.plugins.automaticsubscriptionassistant.providers.maoyan import MaoyanRankProvider
from app.plugins.automaticsubscriptionassistant.providers.popular import PopularRankProvider
from app.plugins.automaticsubscriptionassistant.providers import netflix as netflix_mod
from app.plugins.automaticsubscriptionassistant.providers.netflix import NetflixRankProvider


# ===================== 豆瓣 =====================

DOUBAN_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>豆瓣热门</title>
  <item>
    <title>沙丘</title>
    <link>https://movie.douban.com/subject/1234567/</link>
    <type>movie</type>
    <year>2021</year>
  </item>
  <item>
    <title>热剧第一季</title>
    <link>https://movie.douban.com/subject/7654321/</link>
    <type>tv</type>
    <description><![CDATA[<img src="https://img.douban.com/p.jpg"> 评价数12345<br> 2019 / 美国 / 剧情]]></description>
  </item>
</channel></rss>"""


def test_douban_fetch_parses_items(monkeypatch):
    monkeypatch.setattr(RequestUtils, "get_res",
                        lambda self, url, *a, **k: SimpleNamespace(text=DOUBAN_RSS))
    items = list(DoubanRankProvider().fetch({"ranks": ["movie-hot-gaia"]}, None))
    assert len(items) == 2
    by_title = {i.title: i for i in items}

    a = by_title["沙丘"]
    assert a.year == "2021"
    assert a.douban_id == "1234567"
    assert a.type_hint == MediaType.MOVIE
    assert a.unique_seed == "沙丘_2021_(DB:1234567)"
    assert a.source_meta["link"].endswith("1234567/")

    b = by_title["热剧第一季"]
    assert b.year == "2019"            # 从 description 回退解析
    assert b.douban_id == "7654321"
    assert b.type_hint == MediaType.TV
    assert b.poster == "https://img.douban.com/p.jpg"
    assert b.dedup_key("douban") == "douban:热剧第一季_2019_(DB:7654321)"


def test_douban_no_address_yields_nothing(monkeypatch):
    called = {"n": 0}

    def _spy(self, url, *a, **k):  # 不应被调用
        called["n"] += 1
        return SimpleNamespace(text=DOUBAN_RSS)

    monkeypatch.setattr(RequestUtils, "get_res", _spy)
    items = list(DoubanRankProvider().fetch({}, None))
    assert items == []
    assert called["n"] == 0


def test_douban_empty_response_skipped(monkeypatch):
    monkeypatch.setattr(RequestUtils, "get_res", lambda self, url, *a, **k: None)
    items = list(DoubanRankProvider().fetch({"ranks": ["tv-hot"]}, None))
    assert items == []


def test_douban_base_defaults_to_rsshub_app(monkeypatch):
    """未配置 rsshub_base 时内置榜单默认走 rsshub.app（向后兼容）。"""
    seen = []
    monkeypatch.setattr(RequestUtils, "get_res",
                        lambda self, url, *a, **k: seen.append(url) or SimpleNamespace(text=DOUBAN_RSS))
    list(DoubanRankProvider().fetch({"ranks": ["tv-hot"]}, None))
    assert seen == ["https://rsshub.app/douban/movie/weekly/tv_hot"]


def test_douban_custom_rsshub_base(monkeypatch):
    """内置榜单使用自定义 RSSHub 基址（尾斜杠被规整）；自定义 rss_addrs 原样使用。"""
    seen = []
    monkeypatch.setattr(RequestUtils, "get_res",
                        lambda self, url, *a, **k: seen.append(url) or SimpleNamespace(text=DOUBAN_RSS))
    list(DoubanRankProvider().fetch(
        {"ranks": ["movie-hot-gaia"],
         "rsshub_base": "https://rsshub.mydomain.com/",
         "rss_addrs": "https://custom.example/feed"},
        None,
    ))
    assert "https://custom.example/feed" in seen
    assert "https://rsshub.mydomain.com/douban/movie/weekly/movie_hot_gaia" in seen
    assert "rsshub.app" not in " ".join(seen)


def test_douban_base_adds_scheme(monkeypatch):
    """无 scheme 的基址自动补 https://。"""
    seen = []
    monkeypatch.setattr(RequestUtils, "get_res",
                        lambda self, url, *a, **k: seen.append(url) or SimpleNamespace(text=DOUBAN_RSS))
    list(DoubanRankProvider().fetch({"ranks": ["tv-hot"], "rsshub_base": "rsshub.local:1200"}, None))
    assert seen == ["https://rsshub.local:1200/douban/movie/weekly/tv_hot"]


# ===================== 猫眼 =====================

def _maoyan_payload(url):
    if "/dashboard-ajax/movie" in url:
        return {"movieList": {"list": [
            {"movieInfo": {"movieName": "电影A", "releaseInfo": "上映50天"}},
        ]}}
    if "/dashboard/webMaoYanHotData" in url:
        return {"data": {"list": [
            {"name": "网大B", "platformDesc": "某平台"},   # 无 releaseInfo -> year None
        ]}}
    if "/dashboard/webHeatData" in url:
        return {"dataList": {"list": [
            {"seriesInfo": {"name": "剧C", "releaseInfo": "上映100天", "platformDesc": "腾讯"}},
            {"seriesInfo": {"name": "剧C", "releaseInfo": "上映100天"}},  # 同名去重
        ]}}
    return {}


def test_maoyan_fetch_parses_three_endpoints(monkeypatch):
    monkeypatch.setattr(PlaywrightHelper, "action", lambda self, *a, **k: {})  # 无 Cookie 降级
    monkeypatch.setattr(RequestUtils, "get_res",
                        lambda self, url, *a, **k: SimpleNamespace(json=lambda: _maoyan_payload(url)))

    items = list(MaoyanRankProvider().fetch(
        {"types": ["movie", "web-movie", "web-heat"], "platforms": ["all"], "num": 10}, None))
    titles = [i.title for i in items]
    assert titles.count("剧C") == 1  # 网播热度按标题去重
    by = {i.title: i for i in items}

    exp_movie_year = str((date.today() - timedelta(days=50)).year)
    mv = by["电影A"]
    assert mv.type_hint == MediaType.MOVIE
    assert mv.year == exp_movie_year
    assert mv.unique_seed == f"电影_电影A_{exp_movie_year}"

    nb = by["网大B"]
    assert nb.type_hint == MediaType.MOVIE
    assert nb.year is None          # releaseInfo 缺失 -> None
    assert nb.source_meta["platformDesc"] == "某平台"

    exp_tv_year = str((date.today() - timedelta(days=100)).year)
    tv = by["剧C"]
    assert tv.type_hint == MediaType.TV
    assert tv.year == exp_tv_year
    assert tv.source_meta["platformDesc"] == "腾讯"
    assert tv.unique_seed == f"电视剧_剧C_{exp_tv_year}"


def test_maoyan_new_platforms_build_platform_type(monkeypatch):
    """搜狐=5 / 乐视=4 / PPTV=6 的 platformType 正确拼入 webHeatData URL。"""
    from app.plugins.automaticsubscriptionassistant.providers.maoyan import PLATFORM_TYPE
    assert (PLATFORM_TYPE["sohu"], PLATFORM_TYPE["letv"], PLATFORM_TYPE["pptv"]) == ("5", "4", "6")
    assert PLATFORM_TYPE["mgtv"] == "7"  # 芒果保持 7，不与 PPTV 撞码

    seen = []
    monkeypatch.setattr(PlaywrightHelper, "action", lambda self, *a, **k: {})
    monkeypatch.setattr(RequestUtils, "get_res",
                        lambda self, url, *a, **k: seen.append(url) or SimpleNamespace(json=lambda: _maoyan_payload(url)))
    list(MaoyanRankProvider().fetch(
        {"types": ["web-heat"], "platforms": ["sohu", "letv", "pptv"], "num": 5}, None))
    heat = [u for u in seen if "/dashboard/webHeatData" in u]
    assert any("platformType=5" in u for u in heat)  # 搜狐
    assert any("platformType=4" in u for u in heat)  # 乐视
    assert any("platformType=6" in u for u in heat)  # PPTV


def test_douban_custom_address_fields_are_advanced():
    """自定义地址字段（rsshub_base / rss_addrs）标记为 advanced，前端默认隐藏。"""
    spec = DoubanRankProvider().get_spec()
    adv = {f.key for f in spec.options_schema if f.advanced}
    assert adv == {"rsshub_base", "rss_addrs"}


def test_maoyan_cookie_branch(monkeypatch):
    # action 返回非空 cookies -> 走带 Cookie 请求分支
    monkeypatch.setattr(PlaywrightHelper, "action", lambda self, *a, **k: {"uuid": "x"})
    seen = {}

    def _fake(self, url, *a, **k):
        seen["cookies"] = k.get("cookies")
        return SimpleNamespace(json=lambda: _maoyan_payload(url))

    monkeypatch.setattr(RequestUtils, "get_res", _fake)
    items = list(MaoyanRankProvider().fetch({"types": ["movie"], "num": 5}, None))
    assert len(items) == 1
    assert seen["cookies"] == {"uuid": "x"}


def test_maoyan_cookies_failure_degrades(monkeypatch):
    def _raise(self, *a, **k):
        raise RuntimeError("no browser")

    monkeypatch.setattr(PlaywrightHelper, "action", _raise)
    monkeypatch.setattr(RequestUtils, "get_res",
                        lambda self, url, *a, **k: SimpleNamespace(json=lambda: _maoyan_payload(url)))
    # 浏览器异常降级空 Cookie，仍能解析
    items = list(MaoyanRankProvider().fetch({"types": ["movie"], "num": 5}, None))
    assert len(items) == 1


def test_maoyan_year_from_release_info():
    f = MaoyanRankProvider._year_from_release_info
    assert f(None) is None
    assert f("即将上映") is None            # 无数字
    assert f("上映10天") == str((date.today() - timedelta(days=10)).year)


def test_maoyan_no_response(monkeypatch):
    monkeypatch.setattr(PlaywrightHelper, "action", lambda self, *a, **k: {})
    monkeypatch.setattr(RequestUtils, "get_res", lambda self, url, *a, **k: None)
    items = list(MaoyanRankProvider().fetch({"types": ["movie"], "num": 5}, None))
    assert items == []


# ===================== 热门媒体 =====================

def _stat_movie():
    return {"type": "movie", "name": "电影X", "tmdbid": 100, "year": 2021,
            "doubanid": "d1", "count": 500, "vote": 8.1, "poster": "pm.jpg",
            "season": None, "bangumiid": None, "tvdbid": None, "imdbid": None}


def _stat_tv():
    return {"type": "tv", "name": "剧Y", "tmdbid": 200, "year": 2020, "count": 300,
            "season": 1, "doubanid": "", "bangumiid": 10, "tvdbid": None,
            "imdbid": "tt1", "poster": "pt.jpg"}


def _stat_unknown():
    return {"type": "weird", "name": "未知Z", "tmdbid": 300}


def test_popular_fetch_maps_movie_and_tv(monkeypatch):
    calls = []

    def _fake(stype, page=1, count=30, genre_id=None, min_rating=None, **kw):
        calls.append((stype, count, genre_id, min_rating))
        if stype in ("movie", MediaType.MOVIE.value):
            return [_stat_movie()]
        return [_stat_tv(), _stat_unknown()]

    monkeypatch.setattr(MoviePilotServerHelper, "get_subscribe_statistic", _fake)

    # 两类开关均开；各自独立获取条数（movie=5, tv=7）
    items = list(PopularRankProvider().fetch(
        {"movie_enabled": True, "tv_enabled": True,
         "movie_page_cnt": 5, "tv_page_cnt": 7}, None))
    # 未知类型（type=weird）被跳过 -> movie + tv = 2
    assert len(items) == 2
    # 各类型独立 count；未选风格/评分 -> genre_id、min_rating 均为 None
    assert calls == [("movie", 5, None, None), ("tv", 7, None, None)]

    by_cat = {i.source_meta["category"]: i for i in items}
    assert "anime" not in by_cat

    movie = by_cat["movie"]
    assert movie.type_hint == MediaType.MOVIE
    assert movie.tmdb_id == 100
    assert movie.year == "2021"            # int -> str
    assert movie.douban_id == "d1"
    assert movie.source_meta["count"] == 500
    assert "anime_mode" not in movie.source_meta
    assert movie.unique_seed == "电影X:100"

    tv = by_cat["tv"]
    assert tv.type_hint == MediaType.TV
    assert "anime_mode" not in tv.source_meta
    assert tv.bangumi_id == 10
    assert tv.imdb_id == "tt1"
    assert tv.season == 1
    assert tv.douban_id is None            # 空串 -> None
    assert tv.tvdb_id is None


def test_popular_fetch_genre_fanout(monkeypatch):
    """电影多选风格 -> 逐 genre 分别请求，跨 genre 按 tmdbid 去重合并。"""
    calls = []

    def _fake(stype, page=1, count=30, genre_id=None, min_rating=None, **kw):
        calls.append((stype, genre_id))
        if genre_id == 16:
            return [_stat_movie(), {"type": "movie", "name": "动画A", "tmdbid": 101}]
        if genre_id == 878:
            return [_stat_movie(), {"type": "movie", "name": "科幻B", "tmdbid": 102}]
        return []

    monkeypatch.setattr(MoviePilotServerHelper, "get_subscribe_statistic", _fake)

    items = list(PopularRankProvider().fetch(
        {"movie_enabled": True, "tv_enabled": False,
         "movie_genres": ["16", "878"], "movie_page_cnt": 5}, None))

    # 逐 genre 各请求一次
    assert calls == [("movie", 16), ("movie", 878)]
    # 电影X(100) 在两个 genre 里都出现 -> 去重后只一条；共 3 条(100/101/102)
    assert len(items) == 3
    assert {i.unique_seed for i in items} == {"电影X:100", "动画A:101", "科幻B:102"}
    # genre_id 记入 source_meta（保留首次命中的 16）
    x = next(i for i in items if i.unique_seed == "电影X:100")
    assert x.source_meta["genre_id"] == 16


def test_popular_fetch_min_rating_passthrough(monkeypatch):
    """每类型独立 min_rating 下推服务端；0/未设视为不限（None）。"""
    calls = []

    def _fake(stype, page=1, count=30, genre_id=None, min_rating=None, **kw):
        calls.append((stype, min_rating))
        return [_stat_movie()] if stype == "movie" else [_stat_tv()]

    monkeypatch.setattr(MoviePilotServerHelper, "get_subscribe_statistic", _fake)

    # 电影设 7.5、剧集不设 -> 各自独立：movie=7.5, tv=None
    list(PopularRankProvider().fetch(
        {"movie_enabled": True, "tv_enabled": True, "movie_min_rating": 7.5}, None))
    assert calls == [("movie", 7.5), ("tv", None)]

    calls.clear()
    # 0 视为不限 -> None
    list(PopularRankProvider().fetch(
        {"movie_enabled": True, "tv_enabled": False, "movie_min_rating": 0}, None))
    assert calls == [("movie", None)]


def test_popular_spec_has_genre_and_rating_fields():
    from app.plugins.automaticsubscriptionassistant.providers.popular import (
        MOVIE_GENRES, TV_GENRES)
    spec = PopularRankProvider().get_spec()
    opts = {f.key: f for f in spec.options_schema}
    # 订阅类别改为每类型开关
    assert opts["movie_enabled"].kind == "switch" and opts["movie_enabled"].default is True
    assert opts["tv_enabled"].kind == "switch" and opts["tv_enabled"].default is True
    assert opts["movie_genres"].kind == "multi-select"
    assert opts["tv_genres"].kind == "multi-select"
    # 电影/剧集各自独立的获取条数、评分下限、订阅人次
    assert opts["movie_page_cnt"].kind == "number"
    assert opts["tv_page_cnt"].kind == "number"
    assert opts["movie_min_rating"].kind == "float"
    assert opts["tv_min_rating"].kind == "float"
    assert opts["movie_popularity"].kind == "number"
    assert opts["tv_popularity"].kind == "number"
    # 不再有共享/多选字段；popularity 移入 per-type 选项后 filters_schema 为空
    assert "page_cnt" not in opts and "min_rating" not in opts and "categories" not in opts
    assert spec.filters_schema == []
    # 选项 value 为字符串 id，分别覆盖各自 genre 字典
    assert {o["value"] for o in opts["movie_genres"].options} == {str(g) for g in MOVIE_GENRES}
    assert {o["value"] for o in opts["tv_genres"].options} == {str(g) for g in TV_GENRES}
    # 动画(16) 两套都有（旧「动漫」收编为风格标签）
    assert "16" in {o["value"] for o in opts["movie_genres"].options}
    assert "16" in {o["value"] for o in opts["tv_genres"].options}


def test_popular_enable_switches(monkeypatch):
    """{category}_enabled 开关独立控制各类型；关闭则不拉取。"""
    calls = []

    def _fake(stype, page=1, count=30, genre_id=None, min_rating=None, **kw):
        calls.append(stype)
        return [_stat_movie()] if stype == "movie" else [_stat_tv()]

    monkeypatch.setattr(MoviePilotServerHelper, "get_subscribe_statistic", _fake)

    # 仅开电影
    items = list(PopularRankProvider().fetch(
        {"movie_enabled": True, "tv_enabled": False}, None))
    assert calls == ["movie"]
    assert [i.source_meta["category"] for i in items] == ["movie"]

    # 两个都关 -> 不拉取
    calls.clear()
    assert list(PopularRankProvider().fetch(
        {"movie_enabled": False, "tv_enabled": False}, None)) == []
    assert calls == []


def test_popular_popularity_filter(monkeypatch):
    """订阅人次过滤按 source_meta['count'] 本地判定，低于阈值的条目被丢弃。"""
    def _fake(stype, page=1, count=30, genre_id=None, min_rating=None, **kw):
        # count=500 的高人次 + count=100 的低人次
        return [_stat_movie(), {"type": "movie", "name": "冷门M", "tmdbid": 199, "count": 100}]

    monkeypatch.setattr(MoviePilotServerHelper, "get_subscribe_statistic", _fake)

    items = list(PopularRankProvider().fetch(
        {"movie_enabled": True, "tv_enabled": False, "movie_popularity": 400}, None))
    # 仅保留 count>=400 的电影X(500)，冷门M(100) 被过滤
    assert {i.unique_seed for i in items} == {"电影X:100"}


def test_popular_legacy_page_cnt_fallback(monkeypatch):
    """未设开关/条数时，回退旧的 categories 多选与共享 page_cnt 键（向后兼容）。"""
    calls = []

    def _fake(stype, page=1, count=30, genre_id=None, min_rating=None, **kw):
        calls.append((stype, count))
        return []

    monkeypatch.setattr(MoviePilotServerHelper, "get_subscribe_statistic", _fake)
    list(PopularRankProvider().fetch({"categories": ["movie", "tv"], "page_cnt": 9}, None))
    assert calls == [("movie", 9), ("tv", 9)]


def test_popular_empty_statistic(monkeypatch):
    monkeypatch.setattr(MoviePilotServerHelper, "get_subscribe_statistic",
                        lambda stype, page=1, count=30, **kw: [])
    items = list(PopularRankProvider().fetch({"categories": ["movie"], "page_cnt": 5}, None))
    assert items == []


def test_popular_static_helpers():
    assert PopularRankProvider._map_media_type("movie") == MediaType.MOVIE
    assert PopularRankProvider._map_media_type("电影") == MediaType.MOVIE
    assert PopularRankProvider._map_media_type("tv") == MediaType.TV
    assert PopularRankProvider._map_media_type("电视剧") == MediaType.TV
    assert PopularRankProvider._map_media_type("xxx") is None
    assert PopularRankProvider._map_media_type(None) is None

    assert PopularRankProvider._to_optional_int(None) is None
    assert PopularRankProvider._to_optional_int("") is None
    assert PopularRankProvider._to_optional_int("5") == 5
    assert PopularRankProvider._to_optional_int("bad") is None

    assert PopularRankProvider._to_str(None) is None
    assert PopularRankProvider._to_str("") is None
    assert PopularRankProvider._to_str(7) == "7"

    assert PopularRankProvider._to_int("bad", 3) == 3
    assert PopularRankProvider._as_list("a, b ,,c") == ["a", "b", "c"]
    assert PopularRankProvider._as_list(["x", " y "]) == ["x", "y"]
    assert PopularRankProvider._as_list(123) == []


# ===================== 奈飞(Netflix) =====================

@pytest.fixture(autouse=True)
def _clear_netflix_cache():
    """每个用例前后清空模块级周缓存，避免跨用例串扰、保证确定性。"""
    netflix_mod._NETFLIX_CACHE.clear()
    yield
    netflix_mod._NETFLIX_CACHE.clear()


def _tsv(header, rows):
    """把表头 + 行列表拼成制表符分隔文本（避免源码里出现字面制表符）。"""
    return "\n".join(["\t".join(header)] + ["\t".join(r) for r in rows])


NETFLIX_MOST_POPULAR = _tsv(
    ["category", "rank", "show_title", "season_title",
     "hours_viewed_first_91_days", "runtime", "views_first_91_days"],
    [
        ["Films (English)", "1", "MovieA", "N/A", "100", "1.5", "60"],
        ["Films (English)", "2", "MovieB", "N/A", "90", "1.5", "55"],
        ["Films (English)", "3", "MovieC", "N/A", "80", "1.5", "50"],
        ["TV (English)", "1", "ShowA", "ShowA: Season 1", "200", "6", "120"],
        ["TV (English)", "2", "ShowB", "ShowB: Limited Series", "150", "4", "90"],
    ],
)

# 含两周（2026-06-21 / 2026-06-28）用于测「只取最新周」。
NETFLIX_ALL_WEEKS_GLOBAL = _tsv(
    ["week", "category", "weekly_rank", "show_title", "season_title",
     "weekly_hours_viewed", "runtime", "weekly_views", "cumulative_weeks_in_top_10"],
    [
        ["2026-06-21", "Films (English)", "1", "OldMovie", "N/A", "50", "1.5", "30", "1"],
        # 故意让 rank 乱序，验证 provider 会按 rank 升序取。
        ["2026-06-28", "Films (English)", "2", "NewMovie2", "N/A", "40", "1.5", "25", "1"],
        ["2026-06-28", "Films (English)", "1", "NewMovie", "N/A", "60", "1.5", "35", "2"],
        ["2026-06-28", "TV (Non-English)", "1", "KTV", "KTV: Season 2", "80", "6", "40", "3"],
    ],
)

# 2 国(AR/JP) × 2 类(Films/TV) × 两周；AR Films 最新周含与全球同名 "NewMovie" 供去重测试。
NETFLIX_ALL_WEEKS_COUNTRIES = _tsv(
    ["country_name", "country_iso2", "week", "category", "weekly_rank",
     "show_title", "season_title", "cumulative_weeks_in_top_10"],
    [
        ["Argentina", "AR", "2026-06-21", "Films", "1", "AR_OldFilm", "N/A", "1"],
        ["Argentina", "AR", "2026-06-28", "Films", "1", "AR_Film1", "N/A", "2"],
        ["Argentina", "AR", "2026-06-28", "Films", "2", "AR_Film2", "N/A", "1"],
        ["Argentina", "AR", "2026-06-28", "Films", "3", "NewMovie", "N/A", "1"],
        ["Argentina", "AR", "2026-06-28", "TV", "1", "AR_Show", "AR_Show: Season 3", "3"],
        ["Japan", "JP", "2026-06-28", "Films", "1", "JP_Film1", "N/A", "1"],
        ["Japan", "JP", "2026-06-28", "TV", "1", "JP_Show", "JP_Show: Season 1", "1"],
    ],
)


def _netflix_get_res(_self, url, *a, **k):
    """按 URL 路由到对应 mini TSV 样本，模拟 RequestUtils.get_res（零真实出站）。"""
    if url == netflix_mod.MOST_POPULAR_URL:
        return SimpleNamespace(text=NETFLIX_MOST_POPULAR)
    if url == netflix_mod.ALL_WEEKS_GLOBAL_URL:
        return SimpleNamespace(text=NETFLIX_ALL_WEEKS_GLOBAL)
    if url == netflix_mod.ALL_WEEKS_COUNTRIES_URL:
        return SimpleNamespace(text=NETFLIX_ALL_WEEKS_COUNTRIES)
    return None


def test_netflix_spec_shape():
    """spec：10 个 options、filters 为空、全球 4 类 / 国家 2 类 / 94 国、默认值正确。"""
    spec = NetflixRankProvider().get_spec()
    assert spec.provider_id == "netflix"
    assert spec.filters_schema == []
    opts = {f.key: f for f in spec.options_schema}
    assert set(opts) == {"global", "global_dataset", "global_media_types",
                         "countries", "country_media_types", "limit", "proxy",
                         "rich_metadata", "max_workers", "use_cache"}
    assert opts["global"].default is True
    assert opts["limit"].default == 10
    assert opts["global_dataset"].default == "all-weeks-global"
    assert len(opts["global_media_types"].options) == 4
    assert opts["global_media_types"].default == [
        "Films (English)", "Films (Non-English)", "TV (English)", "TV (Non-English)"]
    assert len(opts["country_media_types"].options) == 2
    assert opts["country_media_types"].default == ["Films", "TV"]
    assert opts["countries"].default == []
    assert len(opts["countries"].options) == 94  # 实测 94 个上榜国家/地区
    # 富元数据模式新增两项：默认关、并发数默认 5 且归入高级选项。
    assert opts["rich_metadata"].kind == "switch"
    assert opts["rich_metadata"].default is False
    assert opts["max_workers"].kind == "number"
    assert opts["max_workers"].default == 5
    assert opts["max_workers"].advanced is True
    # 周更缓存：switch，默认开，归入高级选项。
    assert opts["use_cache"].kind == "switch"
    assert opts["use_cache"].default is True
    assert opts["use_cache"].advanced is True


def test_netflix_global_most_popular_types_and_limit(monkeypatch):
    """史上最热(most-popular)：按所选 category 产出，Films→MOVIE / TV→TV，limit 生效，季号解析。"""
    monkeypatch.setattr(RequestUtils, "get_res", _netflix_get_res)
    items = list(NetflixRankProvider().fetch(
        {"global": True, "global_dataset": "most-popular",
         "global_media_types": ["Films (English)", "TV (English)"],
         "countries": [], "limit": 2, "proxy": False}, None))
    by = {i.title: i for i in items}
    # Films (English) 取前 2（MovieA/MovieB），MovieC 被 limit 截断。
    assert "MovieC" not in by
    assert by["MovieA"].type_hint == MediaType.MOVIE
    assert by["MovieA"].year is None
    assert by["MovieA"].season is None
    assert by["MovieA"].source_meta == {"scope": "global", "category": "Films (English)", "rank": 1}
    assert by["MovieA"].unique_seed == "movie_MovieA"
    # TV (English) 取前 2（ShowA/ShowB）。
    assert by["ShowA"].type_hint == MediaType.TV
    assert by["ShowA"].season == 1                    # "ShowA: Season 1"
    assert by["ShowA"].unique_seed == "tv_ShowA"
    assert by["ShowB"].season is None                 # "Limited Series" 无 Season
    # 每类各 2 条，共 4 条。
    assert len(items) == 4


def test_netflix_global_weekly_latest_week_only(monkeypatch):
    """周榜(all-weeks-global)：只取最新周（2026-06-28），旧周条目不产出，按 rank 升序。"""
    monkeypatch.setattr(RequestUtils, "get_res", _netflix_get_res)
    items = list(NetflixRankProvider().fetch(
        {"global": True, "global_dataset": "all-weeks-global",
         "global_media_types": ["Films (English)", "TV (Non-English)"],
         "limit": 10}, None))
    titles = [i.title for i in items]
    assert "OldMovie" not in titles                   # 2026-06-21 旧周被过滤
    # Films (English) 最新周按 rank 升序：NewMovie(1) 在 NewMovie2(2) 前。
    films = [i.title for i in items if i.source_meta["category"] == "Films (English)"]
    assert films == ["NewMovie", "NewMovie2"]
    ktv = next(i for i in items if i.title == "KTV")
    assert ktv.type_hint == MediaType.TV
    assert ktv.season == 2
    assert ktv.source_meta["week"] == "2026-06-28"


def test_netflix_countries_filter_by_iso2_and_category(monkeypatch):
    """国家榜：按 iso2 + category 过滤，只取最新周，携带 country_name/scope。"""
    monkeypatch.setattr(RequestUtils, "get_res", _netflix_get_res)
    items = list(NetflixRankProvider().fetch(
        {"global": False, "global_media_types": [],
         "countries": ["AR"], "country_media_types": ["Films"], "limit": 10}, None))
    titles = [i.title for i in items]
    assert "AR_OldFilm" not in titles                 # 旧周过滤
    assert set(titles) == {"AR_Film1", "AR_Film2", "NewMovie"}
    assert all(i.type_hint == MediaType.MOVIE for i in items)
    sample = next(i for i in items if i.title == "AR_Film1")
    assert sample.source_meta["scope"] == "AR"
    assert sample.source_meta["country_name"] == "Argentina"
    assert sample.source_meta["week"] == "2026-06-28"


def test_netflix_countries_multi_country_and_type(monkeypatch):
    """多国 × 多类型：AR/JP × Films/TV 各自过滤，剧集季号解析。"""
    monkeypatch.setattr(RequestUtils, "get_res", _netflix_get_res)
    items = list(NetflixRankProvider().fetch(
        {"global": False, "global_media_types": [],
         "countries": ["AR", "JP"], "country_media_types": ["Films", "TV"], "limit": 10}, None))
    by = {i.title: i for i in items}
    assert by["JP_Show"].type_hint == MediaType.TV
    assert by["JP_Show"].season == 1
    assert by["JP_Show"].source_meta["scope"] == "JP"
    assert by["AR_Show"].season == 3
    assert {"JP_Film1", "JP_Show", "AR_Show"} <= set(by)


def test_netflix_global_and_countries_dedup_by_unique_seed(monkeypatch):
    """全球 + 国家同时启用：同名条目按 unique_seed 去重，只产一次。"""
    monkeypatch.setattr(RequestUtils, "get_res", _netflix_get_res)
    items = list(NetflixRankProvider().fetch(
        {"global": True, "global_dataset": "all-weeks-global",
         "global_media_types": ["Films (English)"],
         "countries": ["AR"], "country_media_types": ["Films"], "limit": 10}, None))
    titles = [i.title for i in items]
    # "NewMovie" 同时出现在全球周榜与 AR 国家榜，去重后仅 1 条。
    assert titles.count("NewMovie") == 1
    assert set(titles) == {"NewMovie", "NewMovie2", "AR_Film1", "AR_Film2"}


def test_netflix_disabled_scopes_yield_nothing(monkeypatch):
    """全球关闭 + 无国家：不产出任何条目。"""
    monkeypatch.setattr(RequestUtils, "get_res", _netflix_get_res)
    items = list(NetflixRankProvider().fetch(
        {"global": False, "global_media_types": [], "countries": []}, None))
    assert items == []


def test_netflix_empty_response_raises(monkeypatch):
    """整表抓取失败（响应为空）向上抛出，由 runner 捕获。"""
    monkeypatch.setattr(RequestUtils, "get_res", lambda self, url, *a, **k: None)
    import pytest
    with pytest.raises(Exception):
        list(NetflixRankProvider().fetch(
            {"global": True, "global_media_types": ["Films (English)"]}, None))


def test_netflix_static_helpers():
    assert NetflixRankProvider._extract_season("Wednesday: Season 2") == 2
    assert NetflixRankProvider._extract_season("N/A") is None
    assert NetflixRankProvider._extract_season(None) is None
    assert NetflixRankProvider._extract_season("Money Heist: Part 4") is None
    assert NetflixRankProvider._row_rank({"rank": "3"}) == 3
    assert NetflixRankProvider._row_rank({"weekly_rank": "5"}) == 5
    assert NetflixRankProvider._row_rank({}) == netflix_mod._RANK_FALLBACK
    assert NetflixRankProvider._to_int("bad", 7) == 7
    assert NetflixRankProvider._as_list("a, b ,,c") == ["a", "b", "c"]
    assert NetflixRankProvider._latest_week_rows(
        [{"week": "2026-06-21"}, {"week": "2026-06-28"}]) == [{"week": "2026-06-28"}]


# ---------- 奈飞按周（week）缓存 ----------

def _counting_netflix_get(counter):
    """返回一个计数版 get_res：每次调用 counter['n'] += 1，仍路由到 mini TSV 样本。"""
    def _get(_self, url, *a, **k):
        counter["n"] += 1
        return _netflix_get_res(_self, url, *a, **k)
    return _get


def _fix_now(monkeypatch, now):
    """monkeypatch NetflixRankProvider._now_ts 返回固定 now（staticmethod 保持无 self）。"""
    monkeypatch.setattr(NetflixRankProvider, "_now_ts", staticmethod(lambda: now))


def test_netflix_cache_hit_skips_second_fetch(monkeypatch):
    """命中缓存不重复请求：同 config 连抓两次，第二次不再调用网络、返回同样条目。"""
    counter = {"n": 0}
    monkeypatch.setattr(RequestUtils, "get_res", _counting_netflix_get(counter))
    _fix_now(monkeypatch, 1_000_000.0)          # most-popular 无 week -> fallback TTL，缓存有效
    cfg = {"global": True, "global_dataset": "most-popular",
           "global_media_types": ["Films (English)"], "countries": [], "limit": 2}
    first = list(NetflixRankProvider().fetch(cfg, None))
    n1 = counter["n"]
    assert n1 > 0
    second = list(NetflixRankProvider().fetch(cfg, None))
    assert counter["n"] == n1                     # 第二次命中缓存，网络调用数不增
    assert [i.title for i in second] == [i.title for i in first]
    assert first and [i.title for i in first] == ["MovieA", "MovieB"]


def test_netflix_cache_expires_refetches(monkeypatch):
    """过期重抓：now 推到 valid_until 之后 -> 网络调用数增。"""
    counter = {"n": 0}
    monkeypatch.setattr(RequestUtils, "get_res", _counting_netflix_get(counter))
    cfg = {"global": True, "global_dataset": "all-weeks-global",
           "global_media_types": ["Films (English)"], "limit": 10}
    # 数据最新周 2026-06-28 -> base = 该日 +9 天 epoch；取远早于 base 的 now 使 valid_until = base。
    base = NetflixRankProvider._valid_until("2026-06-28", 0.0)
    before = base - 10 * 86400
    _fix_now(monkeypatch, before)
    list(NetflixRankProvider().fetch(cfg, None))
    n1 = counter["n"]
    list(NetflixRankProvider().fetch(cfg, None))
    assert counter["n"] == n1                     # 未过期 -> 命中缓存，不重抓
    _fix_now(monkeypatch, base + 100)             # 推到 base 之后 -> 过期
    list(NetflixRankProvider().fetch(cfg, None))
    assert counter["n"] > n1                       # 过期后重新抓网络


def test_netflix_cache_key_varies_by_config(monkeypatch):
    """配置变则重抓：换 countries -> 不同 key -> 重抓。"""
    counter = {"n": 0}
    monkeypatch.setattr(RequestUtils, "get_res", _counting_netflix_get(counter))
    _fix_now(monkeypatch, 1_000_000.0)
    ar = {"global": False, "global_media_types": [],
          "countries": ["AR"], "country_media_types": ["Films"], "limit": 10}
    list(NetflixRankProvider().fetch(ar, None))
    n1 = counter["n"]
    list(NetflixRankProvider().fetch(ar, None))
    assert counter["n"] == n1                     # 同配置命中缓存
    jp = dict(ar, countries=["JP"])
    list(NetflixRankProvider().fetch(jp, None))
    assert counter["n"] > n1                        # 配置变 -> key 变 -> 重抓


def test_netflix_use_cache_false_always_fetches(monkeypatch):
    """use_cache=False 不缓存：每次都抓，且从不写缓存。"""
    counter = {"n": 0}
    monkeypatch.setattr(RequestUtils, "get_res", _counting_netflix_get(counter))
    _fix_now(monkeypatch, 1_000_000.0)
    cfg = {"global": True, "global_dataset": "most-popular",
           "global_media_types": ["Films (English)"], "limit": 2, "use_cache": False}
    list(NetflixRankProvider().fetch(cfg, None))
    n1 = counter["n"]
    list(NetflixRankProvider().fetch(cfg, None))
    assert counter["n"] > n1                        # 每次都抓
    assert netflix_mod._NETFLIX_CACHE == {}         # 从不写缓存


def test_netflix_stop_signal_not_cached(monkeypatch):
    """退出信号不缓存：event.set 时结果不完整，不写缓存，下次仍抓。"""
    counter = {"n": 0}
    monkeypatch.setattr(RequestUtils, "get_res", _counting_netflix_get(counter))
    _fix_now(monkeypatch, 1_000_000.0)
    event = threading.Event()
    event.set()
    ctx = SimpleNamespace(event=event)
    cfg = {"global": True, "global_dataset": "most-popular",
           "global_media_types": ["Films (English)"], "limit": 2}
    list(NetflixRankProvider().fetch(cfg, ctx))
    assert netflix_mod._NETFLIX_CACHE == {}         # 中途退出 -> 未写缓存
    n1 = counter["n"]
    list(NetflixRankProvider().fetch(cfg, ctx))
    assert counter["n"] > n1                        # 因未缓存，下次仍尝试抓取


def test_netflix_valid_until_week_and_fallback():
    """_valid_until：week+9 天 epoch、边界短重查、解析失败兜底。"""
    now = 1_000_000.0
    vu = NetflixRankProvider._valid_until("2025-11-16", now)   # 周日
    expected = ((datetime(2025, 11, 16, tzinfo=timezone.utc)
                 + timedelta(days=netflix_mod._PUBLISH_LAG_DAYS))
                .replace(hour=netflix_mod._PUBLISH_HOUR_UTC, minute=0, second=0, microsecond=0)
                ).timestamp()
    assert vu == expected                        # 正常取 base = 次周二 _PUBLISH_HOUR_UTC:00 UTC
    # 时区确定性：锚点必须是【周二】的 _PUBLISH_HOUR_UTC:00 UTC（周日+9天=次周二）。
    anchor = datetime.fromtimestamp(vu, tz=timezone.utc)
    assert anchor.weekday() == 1                  # 1 = Tuesday
    assert anchor.hour == netflix_mod._PUBLISH_HOUR_UTC and anchor.minute == 0
    # 解析失败 -> fallback TTL。
    assert NetflixRankProvider._valid_until(None, now) == now + netflix_mod._FALLBACK_TTL_SECONDS
    assert NetflixRankProvider._valid_until("bad", now) == now + netflix_mod._FALLBACK_TTL_SECONDS
    # 发布边界：base 已过（now 很大）-> 短重查 now + 12h。
    big_now = expected + 10_000
    assert (NetflixRankProvider._valid_until("2025-11-16", big_now)
            == big_now + netflix_mod._MIN_RECHECK_SECONDS)


def test_netflix_latest_week_from_items():
    """_latest_week：从条目 source_meta['week'] 取 max，忽略空、全空返回 None。"""
    def _mk(week):
        return SimpleNamespace(source_meta={"week": week} if week else {})
    assert NetflixRankProvider._latest_week(
        [_mk("2026-06-21"), _mk("2026-06-28"), _mk(None)]) == "2026-06-28"
    assert NetflixRankProvider._latest_week([_mk(None), _mk(None)]) is None
    assert NetflixRankProvider._latest_week([]) is None


def test_netflix_cache_key_ignores_workers_and_use_cache():
    """缓存键仅含结果相关选项：max_workers / use_cache 变化不改变键。"""
    base = {"global": True, "global_dataset": "most-popular",
            "global_media_types": ["Films (English)"], "countries": [], "limit": 2}
    k1 = NetflixRankProvider._cache_key(dict(base, max_workers=5, use_cache=True))
    k2 = NetflixRankProvider._cache_key(dict(base, max_workers=9, use_cache=False))
    assert k1 == k2
    # 结果相关选项变化 -> 键变。
    assert NetflixRankProvider._cache_key(dict(base, limit=3)) != k1
    assert NetflixRankProvider._cache_key(dict(base, countries=["AR"])) != k1


# ---------- 奈飞两级缓存 L2（持久化插件 KV，抗重启）----------

def _kv_context(store=None, fail_save=False, fail_get=False):
    """构造带内存 dict 支撑的假 context：get_data/save_data 读写一个闭包 dict，event=None。

    返回 (context, kv)；kv 即支撑 KV 的内存 dict（进程重启只清 L1、保留它，模拟 DB 存活）。
    fail_save/fail_get 置真时对应回调抛异常，用于测 KV 读写异常降级。
    """
    kv = {} if store is None else store

    def _get(key):
        if fail_get:
            raise RuntimeError("kv get boom")
        return kv.get(key)

    def _save(key, value):
        if fail_save:
            raise RuntimeError("kv save boom")
        kv[key] = value

    return SimpleNamespace(event=None, get_data=_get, save_data=_save), kv


def test_netflix_l2_survives_restart(monkeypatch):
    """L2 抗重启：fetch 写 L1+L2；清空 L1(模拟进程重启)后同一 context 再 fetch → L2 命中、网络不增、条目一致。"""
    counter = {"n": 0}
    monkeypatch.setattr(RequestUtils, "get_res", _counting_netflix_get(counter))
    _fix_now(monkeypatch, 1_000_000.0)               # most-popular 无 week -> fallback TTL，缓存有效
    ctx, kv = _kv_context()
    cfg = {"global": True, "global_dataset": "most-popular",
           "global_media_types": ["Films (English)"], "countries": [], "limit": 2}
    first = list(NetflixRankProvider().fetch(cfg, ctx))
    n1 = counter["n"]
    assert n1 > 0
    assert netflix_mod._CACHE_DATA_KEY in kv          # L2 已写入持久化 KV
    assert [i.title for i in first] == ["MovieA", "MovieB"]

    # 模拟进程重启：清 L1（模块级内存），保留假 context 的 KV dict（模拟 DB 存活）。
    netflix_mod._NETFLIX_CACHE.clear()
    second = list(NetflixRankProvider().fetch(cfg, ctx))
    assert counter["n"] == n1                          # L2 命中，网络计数不增
    assert [i.title for i in second] == [i.title for i in first]  # 反序列化条目一致
    assert second[0].type_hint == MediaType.MOVIE      # type_hint 由 .value 还原为枚举
    assert netflix_mod._NETFLIX_CACHE                   # L2 命中后回填 L1


def test_netflix_l2_entry_is_serialized(monkeypatch):
    """L2 KV 条目为 JSON 安全序列化：items 是 to_dict 列表，带 week/valid_until/fetched_ts，整 store 可 json.dumps。"""
    counter = {"n": 0}
    monkeypatch.setattr(RequestUtils, "get_res", _counting_netflix_get(counter))
    _fix_now(monkeypatch, 1_000_000.0)
    ctx, kv = _kv_context()
    cfg = {"global": True, "global_dataset": "all-weeks-global",
           "global_media_types": ["Films (English)"], "limit": 10}
    list(NetflixRankProvider().fetch(cfg, ctx))
    store = kv[netflix_mod._CACHE_DATA_KEY]
    (entry,) = store.values()                          # 单一 cache_key
    assert entry["week"] == "2026-06-28"
    assert "valid_until" in entry and "fetched_ts" in entry
    assert entry["items"] and all(isinstance(x, dict) for x in entry["items"])  # 序列化 dict
    json.dumps(store)                                  # 整个 store JSON 安全（含中文 type_hint）


def test_netflix_l2_prunes_expired_entries(monkeypatch):
    """写 L2 时剔除已过期条目防无限增长：预置一个过期条目，fetch 后被清、只留当前键。"""
    counter = {"n": 0}
    monkeypatch.setattr(RequestUtils, "get_res", _counting_netflix_get(counter))
    _fix_now(monkeypatch, 1_000_000.0)
    stale = {netflix_mod._CACHE_DATA_KEY: {
        "stale-key": {"items": [], "week": None, "valid_until": 1.0, "fetched_ts": 0.0}}}
    ctx, kv = _kv_context(store=stale)
    cfg = {"global": True, "global_dataset": "most-popular",
           "global_media_types": ["Films (English)"], "limit": 2}
    list(NetflixRankProvider().fetch(cfg, ctx))
    store = kv[netflix_mod._CACHE_DATA_KEY]
    assert "stale-key" not in store                    # 过期条目被剔除
    assert len(store) == 1                              # 只留当前抓取键


def test_netflix_l2_save_failure_degrades(monkeypatch):
    """KV 写异常降级：save_data 抛异常 → fetch 不崩、仍产出（L1 仍工作，第二次命中 L1 网络不增）。"""
    counter = {"n": 0}
    monkeypatch.setattr(RequestUtils, "get_res", _counting_netflix_get(counter))
    _fix_now(monkeypatch, 1_000_000.0)
    ctx, kv = _kv_context(fail_save=True)
    cfg = {"global": True, "global_dataset": "most-popular",
           "global_media_types": ["Films (English)"], "limit": 2}
    items = list(NetflixRankProvider().fetch(cfg, ctx))
    assert [i.title for i in items] == ["MovieA", "MovieB"]   # save 抛异常但仍正常产出
    assert netflix_mod._CACHE_DATA_KEY not in kv             # L2 未落盘
    n1 = counter["n"]
    list(NetflixRankProvider().fetch(cfg, ctx))
    assert counter["n"] == n1                                # L1 仍命中，网络不增


def test_netflix_l2_get_failure_degrades(monkeypatch):
    """KV 读异常降级：get_data 抛异常 → fetch 不崩、走网络抓取并产出（降级为仅 L1）。"""
    counter = {"n": 0}
    monkeypatch.setattr(RequestUtils, "get_res", _counting_netflix_get(counter))
    _fix_now(monkeypatch, 1_000_000.0)
    ctx, kv = _kv_context(fail_get=True)
    cfg = {"global": True, "global_dataset": "most-popular",
           "global_media_types": ["Films (English)"], "limit": 2}
    items = list(NetflixRankProvider().fetch(cfg, ctx))
    assert [i.title for i in items] == ["MovieA", "MovieB"]   # 读异常但仍抓取产出
    assert counter["n"] > 0


# ---------- 奈飞富元数据模式（Tudum 页面内嵌 GraphQL）----------

import json  # noqa: E402
import os  # noqa: E402


def _rich_html(entries, category, week="2026-07-05"):
    """构造一份最小 Tudum 榜单页 HTML：内嵌 ``reactContext.models.graphql = JSON.parse('...')``。

    按 Netflix 实测的转义方式（JSON 文本先 ``\\`` -> ``\\\\`` 再 ``'`` -> ``\\'``）把归一化 store
    嵌入单引号 JS 串；每条视频复制到两个「榜单列表 id」下，用于验证按 videoId 去重。
    """
    store = {}
    for e in entries:
        vid = e["video_id"]
        node = {
            "__typename": "PulseTop10ItemEntity",
            "top10": {"__typename": "Top10Data", "weeklyRank": e["rank"],
                      "category": category, "weekEndDate": week, "videoId": vid},
            "top10Video": {"__typename": "Top10PulseVideo", "title": e["title"],
                           "videoId": vid, "releaseYear": e.get("year"),
                           "parentShow": ({"title": e["clean_title"]}
                                          if e.get("clean_title") else None)},
        }
        store[f"PulseTop10ItemEntity:top10-L1-{vid}"] = node
        store[f"PulseTop10ItemEntity:top10-L2-{vid}"] = node  # 同一视频重复引用
    jtext = json.dumps({"data": store}, ensure_ascii=True)  # 非 ASCII -> \uXXXX
    literal = jtext.replace("\\", "\\\\").replace("'", "\\'")
    return ("<html><body><script>window.netflix={};netflix.reactContext={models:{}};"
            "netflix.reactContext.models.graphql = JSON.parse('" + literal + "');"
            "</script></body></html>")


def _rich_router(url_to_html):
    """按 URL 精确路由到对应富页 HTML；未登记的 URL 返回 None（模拟抓取失败）。"""
    def _get(_self, url, *a, **k):
        html = url_to_html.get(url)
        return SimpleNamespace(text=html) if html is not None else None
    return _get


def _fixture_html():
    path = os.path.join(os.path.dirname(__file__), "fixtures", "netflix_rich_taiwan_tv.html")
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def test_netflix_rich_js_decode_helpers():
    """单引号 JS 串转义解码：双反斜杠-u 降级、裸反斜杠-u 转字符、\\' 与 \\\\ 处理，及字面量提取。"""
    dec = NetflixRankProvider._decode_js_string
    bs = "\\"  # 单个反斜杠（避免源码里出现字面 \\uXXXX 被工具误解码）
    # 双反斜杠-u -> 单反斜杠-u（保留给 json.loads 再解析）。
    assert dec(bs + bs + "u4e2d" + bs + bs + "u6587") == bs + "u4e2d" + bs + "u6587"
    # 裸反斜杠-u -> 实际字符（CJK / 重音）。
    assert dec(bs + "u4e2d") == "中"
    assert dec(bs + "u00e9") == "é"
    # 转义单引号 / 转义反斜杠。
    assert dec(bs + "'s") == "'s"
    assert dec("a" + bs + bs + "b") == "a" + bs + "b"
    ext = NetflixRankProvider._extract_graphql_literal
    # 值内含转义单引号 he\'llo，扫描到首个未转义单引号才收尾。
    html = "junk reactContext.models.graphql = JSON.parse('he" + bs + "'llo'); tail"
    assert ext(html) == "he" + bs + "'llo"
    import pytest
    with pytest.raises(Exception):
        ext("no marker here")


def test_netflix_rich_extract_locates_last_marker():
    """倒序定位：JSON.parse 位于页面尾部，rfind 从末尾取最后（生效）的赋值，前面 decoy 用不上。"""
    ext = NetflixRankProvider._extract_graphql_literal
    marker = "reactContext.models.graphql = JSON.parse('"
    html = "head skeleton " + marker + "DECOY_EARLY') middle " + marker + "REAL_LAST'); tail"
    assert ext(html) == "REAL_LAST"


def test_netflix_rich_load_page_decodes_fixture(monkeypatch):
    """① _load_rich_page 解码 fixture（真实 Taiwan/TV 裁剪样本）得到带 year+clean_title 的条目。"""
    html = _fixture_html()
    monkeypatch.setattr(RequestUtils, "get_res",
                        lambda self, url, *a, **k: SimpleNamespace(text=html))
    entries = NetflixRankProvider()._load_rich_page("https://x/tudum/top10/taiwan/tv", False)
    assert len(entries) == 5                              # 10 视频 × 2 引用去重后 5（裁剪保留 5 条）
    by_rank = {e["rank"]: e for e in entries}
    top = by_rank[1]
    assert top["clean_title"] == "As You Stood By"        # 干净剧名（parentShow.title）
    assert top["title"] == "As You Stood By: Limited Series"
    assert top["year"] == 2025                            # 年份（TSV 没有）
    assert top["video_id"] == 81900130
    assert top["category"] == "SERIES"
    assert top["week"] == "2025-11-16"
    assert by_rank[7]["clean_title"] == "Love's Ambition"  # 撇号 \' 解码无乱码
    assert all(e["year"] and e["clean_title"] for e in entries)  # 每条都带年份 + 干净剧名


def test_netflix_rich_country_uses_clean_title_year_season(monkeypatch):
    """rich 模式国家榜：产出 RankMediaItem 用干净剧名、带年份/季号，source_meta 标 rich。"""
    base = netflix_mod._TUDUM_TOP10_BASE
    monkeypatch.setattr(RequestUtils, "get_res",
                        _rich_router({f"{base}/taiwan/tv": _fixture_html()}))
    items = list(NetflixRankProvider().fetch(
        {"rich_metadata": True, "global": False, "global_media_types": [],
         "countries": ["TW"], "country_media_types": ["TV"], "limit": 10}, None))
    assert len(items) == 5
    by = {i.title: i for i in items}               # title 用干净剧名
    a = by["As You Stood By"]
    assert a.year == "2025"
    assert a.type_hint == MediaType.TV
    assert a.season is None                         # "Limited Series" 无季号
    assert a.source_meta["scope"] == "TW"
    assert a.source_meta["source"] == "rich"
    assert a.source_meta["video_id"] == 81900130
    assert a.unique_seed == "tv_As You Stood By"
    assert by["Love's Ambition"].season == 1        # "Love's Ambition: Season 1"


def test_netflix_rich_multi_country_concurrent_dedup(monkeypatch):
    """② rich 多国家并发：产出来自多国、按 unique_seed 去重、year/clean_title/type_hint 正确。"""
    base = netflix_mod._TUDUM_TOP10_BASE
    us_tv = _rich_html([
        {"rank": 1, "title": "Shared Show: Season 1", "clean_title": "Shared Show",
         "year": 2025, "video_id": 100},
        {"rank": 2, "title": "US Only: Limited Series", "clean_title": "US Only",
         "year": 2024, "video_id": 101},
    ], "SERIES")
    jp_tv = _rich_html([
        {"rank": 1, "title": "Shared Show: Season 1", "clean_title": "Shared Show",
         "year": 2025, "video_id": 100},                       # 与 US 同片 -> 去重
        {"rank": 2, "title": "JP Drama: Season 2", "clean_title": "JP Drama",
         "year": 2023, "video_id": 102},
    ], "SERIES")
    us_films = _rich_html([
        {"rank": 1, "title": "US Film", "clean_title": None, "year": 2026, "video_id": 200},
    ], "MOVIES")
    urls = {
        f"{base}/united-states/films": us_films,
        f"{base}/united-states/tv": us_tv,
        f"{base}/japan/films": _rich_html([], "MOVIES"),        # 空页 -> 无条目
        f"{base}/japan/tv": jp_tv,
    }
    monkeypatch.setattr(RequestUtils, "get_res", _rich_router(urls))
    items = list(NetflixRankProvider().fetch(
        {"rich_metadata": True, "global": False, "global_media_types": [],
         "countries": ["US", "JP"], "country_media_types": ["Films", "TV"],
         "limit": 10, "max_workers": 4}, None))
    by = {i.title: i for i in items}
    # 来自多个国家（scope 含 US 与 JP）。
    assert {"US", "JP"} <= {i.source_meta["scope"] for i in items}
    # Shared Show 在 US/JP 均上榜，按 unique_seed 去重仅一条，scope 归先产出的 US。
    assert [i.title for i in items].count("Shared Show") == 1
    assert by["Shared Show"].source_meta["scope"] == "US"
    assert by["Shared Show"].year == "2025"
    assert by["Shared Show"].season == 1
    assert by["Shared Show"].type_hint == MediaType.TV
    assert by["Shared Show"].source_meta["video_id"] == 100
    # films 页 -> MOVIE；clean_title None 时回退完整 title。
    assert by["US Film"].type_hint == MediaType.MOVIE
    assert by["US Film"].year == "2026"
    assert by["US Film"].unique_seed == "movie_US Film"
    assert {"US Only", "JP Drama"} <= set(by)


def test_netflix_rich_global_english_pages(monkeypatch):
    """rich 全球英语：/tudum/top10/films 与 /tv 各 1 页，category 判定 MOVIE/TV。"""
    base = netflix_mod._TUDUM_TOP10_BASE
    urls = {
        f"{base}/films": _rich_html(
            [{"rank": 1, "title": "Global Film", "clean_title": None,
              "year": 2026, "video_id": 400}], "ENGLISH_MOVIES"),
        f"{base}/tv": _rich_html(
            [{"rank": 1, "title": "Global Show: Season 1", "clean_title": "Global Show",
              "year": 2026, "video_id": 401}], "ENGLISH_SERIES"),
    }
    monkeypatch.setattr(RequestUtils, "get_res", _rich_router(urls))
    items = list(NetflixRankProvider().fetch(
        {"rich_metadata": True, "global": True,
         "global_media_types": ["Films (English)", "TV (English)"],
         "countries": [], "limit": 10}, None))
    by = {i.title: i for i in items}
    assert by["Global Film"].type_hint == MediaType.MOVIE
    assert by["Global Film"].source_meta["scope"] == "global"
    assert by["Global Show"].type_hint == MediaType.TV
    assert by["Global Show"].year == "2026"


def test_netflix_rich_non_english_global_falls_back_to_tsv(monkeypatch):
    """全球非英语两类无富页 -> 回退现有 TSV（title-only，year None），与富页英语共存。"""
    base = netflix_mod._TUDUM_TOP10_BASE
    ne_tsv = _tsv(
        ["category", "rank", "show_title", "season_title",
         "hours_viewed_first_91_days", "runtime", "views_first_91_days"],
        [["Films (Non-English)", "1", "NonEngFilm", "N/A", "10", "1.5", "5"]],
    )
    eng_films = _rich_html(
        [{"rank": 1, "title": "Eng Film", "clean_title": None,
          "year": 2026, "video_id": 500}], "ENGLISH_MOVIES")

    def _router(_self, url, *a, **k):
        if url == f"{base}/films":
            return SimpleNamespace(text=eng_films)
        if url == netflix_mod.MOST_POPULAR_URL:
            return SimpleNamespace(text=ne_tsv)
        return None

    monkeypatch.setattr(RequestUtils, "get_res", _router)
    items = list(NetflixRankProvider().fetch(
        {"rich_metadata": True, "global": True, "global_dataset": "most-popular",
         "global_media_types": ["Films (English)", "Films (Non-English)"],
         "countries": [], "limit": 10}, None))
    by = {i.title: i for i in items}
    # 英语电影走富页：带年份、标 rich。
    assert by["Eng Film"].year == "2026"
    assert by["Eng Film"].source_meta["source"] == "rich"
    # 非英语电影回退 TSV：title-only、无年份、不带 rich 标记。
    assert by["NonEngFilm"].year is None
    assert by["NonEngFilm"].type_hint == MediaType.MOVIE
    assert by["NonEngFilm"].source_meta.get("source") != "rich"
    assert by["NonEngFilm"].source_meta["scope"] == "global"


def test_netflix_rich_page_failure_skipped(monkeypatch):
    """单页抓取失败仅告警跳过，不影响其余页产出。"""
    base = netflix_mod._TUDUM_TOP10_BASE
    urls = {
        f"{base}/united-states/tv": _rich_html(
            [{"rank": 1, "title": "US Show: Season 1", "clean_title": "US Show",
              "year": 2025, "video_id": 600}], "SERIES"),
        # japan/tv 未登记 -> None -> 抓取失败被跳过。
    }
    monkeypatch.setattr(RequestUtils, "get_res", _rich_router(urls))
    items = list(NetflixRankProvider().fetch(
        {"rich_metadata": True, "global": False, "global_media_types": [],
         "countries": ["US", "JP"], "country_media_types": ["TV"], "limit": 10}, None))
    titles = [i.title for i in items]
    assert titles == ["US Show"]                    # JP 页失败被跳过，US 正常产出


def test_netflix_rich_false_still_uses_tsv(monkeypatch):
    """③ rich_metadata 为 False 时仍走现有 TSV 逻辑（只请求 TSV 端点，不碰榜单页）。"""
    seen_urls = []

    def _spy(self, url, *a, **k):
        seen_urls.append(url)
        return _netflix_get_res(self, url, *a, **k)

    monkeypatch.setattr(RequestUtils, "get_res", _spy)
    items = list(NetflixRankProvider().fetch(
        {"rich_metadata": False, "global": True, "global_dataset": "most-popular",
         "global_media_types": ["Films (English)"], "countries": [], "limit": 2}, None))
    assert items                                    # TSV 正常产出
    assert seen_urls and all("/top10/data/" in u for u in seen_urls)  # 全部是 TSV 端点


def test_netflix_rich_static_helpers():
    assert NetflixRankProvider._country_slug("South Korea") == "south-korea"
    assert NetflixRankProvider._country_slug("United States") == "united-states"
    assert NetflixRankProvider._country_slug(" Taiwan ") == "taiwan"
    assert NetflixRankProvider._to_optional_int("2025") == 2025
    assert NetflixRankProvider._to_optional_int(None) is None
    assert NetflixRankProvider._to_optional_int("bad") is None
    tasks = NetflixRankProvider._build_rich_tasks(
        ["Films (English)", "Films (Non-English)", "TV (English)"],
        ["KR"], ["Films", "TV"])
    urls = [t["url"] for t in tasks]
    base = netflix_mod._TUDUM_TOP10_BASE
    # 英语两类各 1 页（非英语不进富页任务），韩国 × 2 类各 1 页。
    assert f"{base}/films" in urls
    assert f"{base}/tv" in urls
    assert f"{base}/south-korea/films" in urls
    assert f"{base}/south-korea/tv" in urls
    assert not any("Non-English" in u for u in urls)
    assert len(tasks) == 4
