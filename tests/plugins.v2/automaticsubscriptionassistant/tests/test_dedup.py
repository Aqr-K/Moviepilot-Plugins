"""core/dedup.py 单元测试：媒体身份键与已订阅强标识索引。

只用强标识（tmdbid/doubanid/bangumiid，剧集按季）判定命中，名称回退绝不用于跳过。
"""
from __future__ import annotations

from types import SimpleNamespace

from app.schemas.types import MediaType

from app.plugins.automaticsubscriptionassistant.core.dedup import (
    SubscribedIndex,
    build_subscribed_index,
)
from app.plugins.automaticsubscriptionassistant.core.models import RankMediaItem, media_identity


# --------------------------------------------------------------------------- #
# media_identity 纯函数
# --------------------------------------------------------------------------- #
def test_identity_prefers_tmdb_movie():
    assert media_identity(tmdb_id=550, is_tv=False) == "tmdb:movie:550"


def test_identity_tmdb_tv_with_and_without_season():
    assert media_identity(tmdb_id=1396, is_tv=True, season=1) == "tmdb:tv:1396:s1"
    assert media_identity(tmdb_id=1396, is_tv=True, season=None) == "tmdb:tv:1396"


def test_identity_falls_back_to_douban_then_bangumi():
    assert media_identity(douban_id="26794435") == "douban:26794435"
    assert media_identity(bangumi_id=326) == "bangumi:326"


def test_identity_name_fallback_only_when_no_strong_id():
    assert media_identity(title="沙丘", year="2021") == "name:沙丘:2021"
    # 有强标识时绝不用名称
    assert media_identity(tmdb_id=1, title="沙丘", year="2021") == "tmdb:movie:1"


def test_item_identity_uses_own_ids():
    item = RankMediaItem(title="剧", tmdb_id=1396, type_hint=MediaType.TV, season=2)
    assert item.identity() == "tmdb:tv:1396:s2"
    movie = RankMediaItem(title="片", douban_id="D1")
    assert movie.identity() == "douban:D1"


# --------------------------------------------------------------------------- #
# SubscribedIndex 强标识判定
# --------------------------------------------------------------------------- #
def test_contains_by_tmdb_movie():
    idx = SubscribedIndex()
    idx.add_media(tmdbid=550, mtype=MediaType.MOVIE)
    assert idx.contains(RankMediaItem(title="x", tmdb_id=550, type_hint=MediaType.MOVIE)) is True
    # 不同 tmdbid 不命中
    assert idx.contains(RankMediaItem(title="y", tmdb_id=551, type_hint=MediaType.MOVIE)) is False


def test_contains_by_douban_and_bangumi():
    idx = SubscribedIndex()
    idx.add_media(doubanid="D9")
    idx.add_media(bangumiid=326)
    assert idx.contains(RankMediaItem(title="x", douban_id="D9")) is True
    assert idx.contains(RankMediaItem(title="x", bangumi_id=326)) is True
    assert idx.contains(RankMediaItem(title="x", douban_id="D8")) is False


def test_contains_tv_is_season_aware():
    idx = SubscribedIndex()
    idx.add_media(tmdbid=1396, mtype=MediaType.TV, season=1)
    # 同季命中
    assert idx.contains(RankMediaItem(title="x", tmdb_id=1396, type_hint=MediaType.TV, season=1)) is True
    # 不同季不命中（不能误伤新一季）
    assert idx.contains(RankMediaItem(title="x", tmdb_id=1396, type_hint=MediaType.TV, season=2)) is False
    # 季未知匹配任意季（与 exists(season=None) 语义一致）
    assert idx.contains(RankMediaItem(title="x", tmdb_id=1396, type_hint=MediaType.TV, season=None)) is True


def test_contains_ignores_tmdb_when_type_unknown():
    # 仅有 tmdbid 且类型未知时不做 tmdb 快速路径（保守，交给识别+exists 兜底）
    idx = SubscribedIndex()
    idx.add_media(tmdbid=550, mtype=MediaType.MOVIE)
    assert idx.contains(RankMediaItem(title="x", tmdb_id=550, type_hint=None)) is False


def test_never_contains_on_name_only():
    idx = SubscribedIndex()
    idx.add_media(tmdbid=1, doubanid="D", mtype=MediaType.MOVIE)
    # 无任何强标识的条目永不命中
    assert idx.contains(RankMediaItem(title="沙丘", year="2021")) is False


def test_identity_for_returns_canonical_across_id_types():
    # 一条订阅同时有 tmdb 与 douban，规范身份取 tmdb；用 douban 命中也返回该规范身份（跨渠道合并）
    idx = SubscribedIndex()
    idx.add_media(tmdbid=550, doubanid="D9", mtype=MediaType.MOVIE)
    by_tmdb = idx.identity_for(RankMediaItem(title="x", tmdb_id=550, type_hint=MediaType.MOVIE))
    by_douban = idx.identity_for(RankMediaItem(title="x", douban_id="D9"))
    assert by_tmdb == "tmdb:movie:550"
    assert by_douban == "tmdb:movie:550"


def test_add_media_without_strong_id_is_noop():
    idx = SubscribedIndex()
    idx.add_media(title="沙丘", year="2021")  # 无强标识
    assert idx.contains(RankMediaItem(title="沙丘", year="2021")) is False


# --------------------------------------------------------------------------- #
# build_subscribed_index 预加载
# --------------------------------------------------------------------------- #
def test_build_from_subscriptions_duck_typed():
    subs = [
        SimpleNamespace(tmdbid=550, doubanid=None, bangumiid=None, type="电影", season=None),
        SimpleNamespace(tmdbid=1396, doubanid=None, bangumiid=None, type="电视剧", season=3),
        SimpleNamespace(tmdbid=None, doubanid="D42", bangumiid=None, type="电影", season=None),
    ]
    idx = build_subscribed_index(subs)
    assert idx.contains(RankMediaItem(title="a", tmdb_id=550, type_hint=MediaType.MOVIE)) is True
    assert idx.contains(RankMediaItem(title="b", tmdb_id=1396, type_hint=MediaType.TV, season=3)) is True
    assert idx.contains(RankMediaItem(title="b2", tmdb_id=1396, type_hint=MediaType.TV, season=1)) is False
    assert idx.contains(RankMediaItem(title="c", douban_id="D42")) is True


def test_build_tolerates_bad_rows():
    # 单条异常不应影响整体构建
    bad = SimpleNamespace()  # 缺全部属性
    good = SimpleNamespace(tmdbid=550, doubanid=None, bangumiid=None, type="电影", season=None)
    idx = build_subscribed_index([bad, good])
    assert idx.contains(RankMediaItem(title="a", tmdb_id=550, type_hint=MediaType.MOVIE)) is True
