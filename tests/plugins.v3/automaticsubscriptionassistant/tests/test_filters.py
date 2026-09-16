"""core/filters.py 单元测试：各过滤器判定、链短路、按 id 构建。"""
from __future__ import annotations

from types import SimpleNamespace

from app.schemas.types import MediaType

from app.plugins.automaticsubscriptionassistant.core.filters import (
    FilterChain,
    MediaFilter,
    MediaTypeFilter,
    PopularityFilter,
    VoteFilter,
    YearFilter,
    build_filter_chain,
)
from app.plugins.automaticsubscriptionassistant.core.models import RankMediaItem


def _item(**kw) -> RankMediaItem:
    return RankMediaItem(title=kw.pop("title", "X"), **kw)


# ---------- VoteFilter (post) ----------

def test_vote_filter_threshold_off():
    mi = SimpleNamespace(vote_average=1.0)
    assert VoteFilter().accept(_item(), mi, {"vote": 0}).accepted is True
    # 缺配置也视为关闭
    assert VoteFilter().accept(_item(), mi, {}).accepted is True


def test_vote_filter_pass_and_reject():
    f = VoteFilter()
    assert f.accept(_item(), SimpleNamespace(vote_average=8.0), {"vote": 7}).accepted is True
    v = f.accept(_item(), SimpleNamespace(vote_average=5.0), {"vote": 7})
    assert v.accepted is False
    assert v.filter_id == "vote"
    assert "评分" in v.reason


def test_vote_filter_missing_vote_data_rejected_when_enabled():
    # 无 vote_average 属性 -> 0.0 < 阈值 -> reject
    v = VoteFilter().accept(_item(), SimpleNamespace(), {"vote": 7})
    assert v.accepted is False


# ---------- YearFilter (pre) ----------

def test_year_filter_threshold_off():
    assert YearFilter().accept(_item(year="2000"), None, {"year": 0}).accepted is True


def test_year_filter_pass_and_reject():
    f = YearFilter()
    assert f.accept(_item(year="2021"), None, {"year": 2020}).accepted is True
    v = f.accept(_item(year="2000"), None, {"year": 2020})
    assert v.accepted is False
    assert "年份" in v.reason


def test_year_filter_missing_year_passes():
    # item 与 mediainfo 均无年份 -> 放行，避免误伤
    assert YearFilter().accept(_item(year=None), None, {"year": 2020}).accepted is True


def test_year_filter_uses_mediainfo_year():
    v = YearFilter().accept(_item(year=None), SimpleNamespace(year="2000"), {"year": 2020})
    assert v.accepted is False


# ---------- PopularityFilter (pre) ----------

def test_popularity_filter_threshold_off():
    assert PopularityFilter().accept(_item(source_meta={"count": 1}), None, {"popularity": 0}).accepted is True


def test_popularity_filter_pass_and_reject():
    f = PopularityFilter()
    assert f.accept(_item(source_meta={"count": 100}), None, {"popularity": 50}).accepted is True
    v = f.accept(_item(source_meta={"count": 10}), None, {"popularity": 50})
    assert v.accepted is False
    assert "订阅人次" in v.reason


def test_popularity_filter_missing_count_rejected():
    v = PopularityFilter().accept(_item(source_meta={}), None, {"popularity": 50})
    assert v.accepted is False


# ---------- MediaTypeFilter (post) ----------

def test_media_type_filter_all_passes():
    mi = SimpleNamespace(type=MediaType.TV)
    assert MediaTypeFilter().accept(_item(), mi, {"media_type": "all"}).accepted is True
    # 非法值当作 all
    assert MediaTypeFilter().accept(_item(), mi, {"media_type": "xxx"}).accepted is True


def test_media_type_filter_movie():
    f = MediaTypeFilter()
    assert f.accept(_item(), SimpleNamespace(type=MediaType.MOVIE), {"media_type": "movie"}).accepted is True
    v = f.accept(_item(), SimpleNamespace(type=MediaType.TV), {"media_type": "movie"})
    assert v.accepted is False and v.reason == "非电影"


def test_media_type_filter_tv():
    f = MediaTypeFilter()
    assert f.accept(_item(), SimpleNamespace(type=MediaType.TV), {"media_type": "tv"}).accepted is True
    v = f.accept(_item(), SimpleNamespace(type=MediaType.MOVIE), {"media_type": "tv"})
    assert v.accepted is False and v.reason == "非电视剧"


# ---------- FilterChain ----------

class _CountingFilter(MediaFilter):
    """记录是否被调用的探针过滤器。"""

    def __init__(self, filter_id, stage, accepted):
        self.filter_id = filter_id
        self.stage = stage
        self._accepted = accepted
        self.called = False

    def accept(self, item, mediainfo, config):
        from app.plugins.automaticsubscriptionassistant.core.models import FilterVerdict
        self.called = True
        if self._accepted:
            return FilterVerdict.accept()
        return FilterVerdict.reject(self.filter_id, "rejected")


def test_filter_chain_short_circuit():
    first = _CountingFilter("a", "pre", accepted=False)
    second = _CountingFilter("b", "pre", accepted=True)
    chain = FilterChain([first, second])
    verdict = chain.run("pre", _item(), None, {})
    assert verdict.accepted is False
    assert verdict.filter_id == "a"
    assert first.called is True
    # 第一个拒绝后短路，第二个不执行
    assert second.called is False


def test_filter_chain_stage_isolation():
    pre = _CountingFilter("a", "pre", accepted=False)
    post = _CountingFilter("b", "post", accepted=False)
    chain = FilterChain([pre, post])
    # 只跑 post 阶段：pre 不应被调用
    verdict = chain.run("post", _item(), None, {})
    assert verdict.filter_id == "b"
    assert pre.called is False
    assert post.called is True


def test_filter_chain_all_accept():
    chain = FilterChain([_CountingFilter("a", "pre", True)])
    assert chain.run("pre", _item(), None, {}).accepted is True
    # 空链恒放行
    assert FilterChain([]).run("pre", _item(), None, {}).accepted is True


# ---------- build_filter_chain ----------

def test_build_filter_chain_selects_by_id():
    chain = build_filter_chain(["vote", "year", "unknown", "media_type"])
    ids = [f.filter_id for f in chain._filters]
    # 未知 id 被跳过
    assert ids == ["vote", "year", "media_type"]


def test_build_filter_chain_popularity():
    chain = build_filter_chain(["popularity"])
    types = [type(f) for f in chain._filters]
    assert PopularityFilter in types


def test_build_filter_chain_empty():
    assert build_filter_chain([])._filters == []
    assert build_filter_chain(None)._filters == []
