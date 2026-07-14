"""core/models.py 单元测试：数据对象序列化、去重键、裁决工厂。"""
from __future__ import annotations

from app.plugins.automaticsubscriptionassistant.core.models import (
    FieldSpec,
    FilterVerdict,
    HistoryRecord,
    ProviderSpec,
    RankMediaItem,
    SubscribeStatus,
)


def test_rank_media_item_dedup_key():
    item = RankMediaItem(title="沙丘", year="2021", unique_seed="沙丘_2021_(DB:123)")
    assert item.dedup_key("douban") == "douban:沙丘_2021_(DB:123)"


def test_rank_media_item_to_from_dict_roundtrip():
    """RankMediaItem 往返：to_dict 全字段 JSON 安全（type_hint→.value），from_dict 还原枚举。"""
    from app.schemas.types import MediaType

    item = RankMediaItem(
        title="沙丘",
        year="2021",
        type_hint=MediaType.MOVIE,
        douban_id="1234567",
        tmdb_id=438631,
        bangumi_id=99,
        tvdb_id=77,
        imdb_id="tt1",
        season=2,
        poster="p.jpg",
        source_meta={"scope": "global", "week": "2026-06-28", "rank": 1},
        unique_seed="movie_沙丘",
    )
    d = item.to_dict()
    # type_hint 序列化为枚举 value（JSON 安全）。
    assert d["type_hint"] == MediaType.MOVIE.value
    # 整个 dict 可 JSON 序列化。
    import json
    json.dumps(d)
    # 往返一致。
    assert RankMediaItem.from_dict(d) == item


def test_rank_media_item_from_dict_defaults():
    """from_dict 缺字段走安全默认；type_hint 为空 → None；None 入参安全。"""
    item = RankMediaItem.from_dict({"title": "X"})
    assert item.title == "X"
    assert item.type_hint is None
    assert item.year is None
    assert item.source_meta == {}
    assert item.unique_seed == ""
    assert RankMediaItem.from_dict(None).title == ""


def test_rank_media_item_defaults():
    item = RankMediaItem(title="X")
    # source_meta 默认工厂产出独立 dict，unique_seed 默认空串
    assert item.source_meta == {}
    item.source_meta["a"] = 1
    assert RankMediaItem(title="Y").source_meta == {}
    assert item.unique_seed == ""


def test_history_record_roundtrip():
    rec = HistoryRecord(
        unique="douban:seed",
        provider="douban",
        title="沙丘",
        year="2021",
        type="电影",
        tmdbid=438631,
        doubanid="123",
        poster="p.jpg",
        season=None,
        status=SubscribeStatus.SUBSCRIBED.value,
        reason=None,
        time="2026-07-12 08:00:00",
    )
    data = rec.to_dict()
    assert data["unique"] == "douban:seed"
    assert data["status"] == "subscribed"
    # 往返一致
    assert HistoryRecord.from_dict(data) == rec


def test_history_record_from_dict_missing_fields():
    rec = HistoryRecord.from_dict({})
    assert rec.unique == ""
    assert rec.provider == ""
    assert rec.title == ""
    assert rec.year is None
    assert rec.tmdbid is None
    assert rec.status == ""
    assert rec.time == ""
    # None 安全
    assert HistoryRecord.from_dict(None).unique == ""


def test_filter_verdict_accept_reject():
    ok = FilterVerdict.accept()
    assert ok.accepted is True
    assert ok.filter_id is None and ok.reason is None

    bad = FilterVerdict.reject("year", "年份 2000 < 2020")
    assert bad.accepted is False
    assert bad.filter_id == "year"
    assert bad.reason == "年份 2000 < 2020"


def test_field_spec_to_dict():
    fs = FieldSpec(key="vote", label="评分≥", kind="float", default=0,
                   options=[{"title": "全部", "value": "all"}], hint="提示")
    d = fs.to_dict()
    assert d == {
        "key": "vote",
        "label": "评分≥",
        "kind": "float",
        "default": 0,
        "options": [{"title": "全部", "value": "all"}],
        "hint": "提示",
        "advanced": False,
        "columns": None,
        "row_noun": None,
    }


def test_field_spec_advanced_flag():
    """advanced 默认 False，可置 True 供前端归入高级选项。"""
    assert FieldSpec(key="k", label="l", kind="text").to_dict()["advanced"] is False
    assert FieldSpec(key="k", label="l", kind="text", advanced=True).to_dict()["advanced"] is True


def test_provider_spec_to_dict():
    spec = ProviderSpec(
        provider_id="douban",
        provider_name="豆瓣榜单",
        default_cron="0 8 * * *",
        options_schema=[FieldSpec(key="ranks", label="榜单", kind="multi-select", default=["a"])],
        filters_schema=[FieldSpec(key="year", label="年份≥", kind="number", default=0)],
    )
    d = spec.to_dict()
    assert d["provider_id"] == "douban"
    assert d["provider_name"] == "豆瓣榜单"
    assert d["default_cron"] == "0 8 * * *"
    assert d["options_schema"][0]["key"] == "ranks"
    assert d["filters_schema"][0]["key"] == "year"
    # 嵌套字段亦为 dict（已 to_dict）
    assert isinstance(d["options_schema"][0], dict)


def test_subscribe_status_values():
    assert SubscribeStatus.SUBSCRIBED.value == "subscribed"
    assert SubscribeStatus.MEDIA_EXISTS.value == "media_exists"
    assert SubscribeStatus.ALREADY_HANDLED.value == "already_handled"
    # str Enum：可直接与字符串比较
    assert SubscribeStatus.ERROR == "error"
