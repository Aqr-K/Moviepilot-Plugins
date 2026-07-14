"""Mikan(蜜柑计划) 来源单元测试：仅测解析，网络全部 mock，零真实出站。

两层样本：
1. 内嵌 mini-HTML（``SEASON_HTML`` / ``DETAIL_HTML_*``）用于覆盖各解析分支与边界；
2. ``fixtures/`` 下裁剪自 mikanani.me 的**真实**季度页 / 详情页片段用于回归，断言
   fetch 产出 ``RankMediaItem`` 的 title/year(真实放送年)/type_hint=TV/bangumi_id/
   poster/mikan_id/original_title 等。

实测说明：Mikan 详情页信息区为多个 ``p.bangumi-info``（``key：value`` 全角冒号），
key 恒为 放送日期/放送开始/官方网站/Bangumi番组计划链接——真实放送年取自「放送开始」，
**并无原名/别名字段**（故真实样本 ``original_title`` 回退取 ``p.bangumi-title`` 全名、
``aliases`` 为 ``[]``；显式原名/别名 key 的解析路径以合成 HTML 覆盖）。
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.schemas.types import MediaType
from app.utils.http import RequestUtils

from app.plugins.automaticsubscriptionassistant.providers import mikan as mikan_mod
from app.plugins.automaticsubscriptionassistant.providers.mikan import (
    MikanApi,
    MikanRankProvider,
)

# ----------------------------------------------------------------------------
# mini-HTML 样本（内嵌，覆盖各分支）
# ----------------------------------------------------------------------------

# 季度番剧列表 HTML：两个星期分组、两部番剧（相对封面，走命中基址拼绝对）。
SEASON_HTML = """<!DOCTYPE html><html><body>
<div class="sk-bangumi" data-dayofweek="6">
    <div id="data-row-6" class="row">星期六</div>
    <div class="an-box animated fadeIn"><ul class="list-inline an-ul">
        <li>
            <span data-src="/images/Bangumi/202601/51b8d587.jpg?width=400&amp;height=400&amp;format=webp"
                  class="js-expand_bangumi b-lazy" data-bangumiid="3848" data-bangumiindex="1"></span>
            <div class="an-info"><div class="an-info-group">
                <div class="date-text">2026/04/17 更新</div>
                <a href="/Home/Bangumi/3848" target="_blank" class="an-text"
                   title="&#x5361;&#x7247;&#x6218;&#x6597;&#x5148;&#x5BFC;&#x8005;">卡片战斗先导者</a>
            </div></div>
        </li>
    </ul></div>
</div>
<div class="sk-bangumi" data-dayofweek="1">
    <div id="data-row-1" class="row">星期一</div>
    <div class="an-box"><ul class="list-inline an-ul">
        <li>
            <span data-src="/images/Bangumi/202601/38b1ae51.jpg"
                  class="js-expand_bangumi b-lazy" data-bangumiid="3900"></span>
            <div class="an-info"><div class="an-info-group">
                <a href="/Home/Bangumi/3900" class="an-text" title="勇者之屑">勇者之屑</a>
            </div></div>
        </li>
    </ul></div>
</div>
</body></html>"""

# 详情页：3848 含 bgm 链接 + 放送开始(2025，异于配置年，验证真实放送年覆盖) + 完整标题。
DETAIL_HTML_WITH_BGM = """<html><body><div id="sk-container">
<div class="pull-left leftbar-container">
<p class="bangumi-title">卡片战斗先导者 Divinez 幻真星战篇 <a class="mikan-rss" href="/RSS/Bangumi?bangumiId=3848"></a></p>
<p class="bangumi-info">放送日期：星期六</p>
<p class="bangumi-info">放送开始：10/5/2025</p>
<p class="bangumi-info">官方网站： https://anime.example.com/</p>
<p class="bangumi-info">Bangumi番组计划链接： https://bgm.tv/subject/591584</p>
</div></div></body></html>"""

# 详情页：3900 无 bgm 链接（退化名称识别），放送开始年份与配置一致。
DETAIL_HTML_NO_BGM = """<html><body><div id="sk-container">
<div class="pull-left leftbar-container">
<p class="bangumi-title">勇者之屑</p>
<p class="bangumi-info">放送开始：2026/01/10</p>
</div></div></body></html>"""


def _fake_get_res(_self, url, *args, **kwargs):
    """按 URL 路由到 mini 季度列表 / 详情 HTML，模拟 RequestUtils.get_res。"""
    if "BangumiCoverFlowByDayOfWeek" in url:
        return SimpleNamespace(text=SEASON_HTML)
    if url.endswith("/Home/Bangumi/3848"):
        return SimpleNamespace(text=DETAIL_HTML_WITH_BGM)
    if url.endswith("/Home/Bangumi/3900"):
        return SimpleNamespace(text=DETAIL_HTML_NO_BGM)
    return None


def test_mikan_fetch_with_bangumi_id(monkeypatch):
    """resolve_bangumi_id=True：补 bgm id + 真实放送年覆盖 + 原名(详情全名) + poster。"""
    monkeypatch.setattr(RequestUtils, "get_res", _fake_get_res)
    monkeypatch.setattr(mikan_mod, "sleep", lambda *_a, **_k: None)  # 免真实等待

    items = list(MikanRankProvider().fetch(
        {"year": 2026, "season": "春", "resolve_bangumi_id": True}, None))
    assert len(items) == 2
    by_title = {i.title: i for i in items}

    a = by_title["卡片战斗先导者"]
    assert a.type_hint == MediaType.TV
    assert a.bangumi_id == 591584                       # 详情页 bgm.tv 链接提取
    assert a.year == "2025"                             # 真实放送年覆盖配置年 2026
    assert a.poster.startswith("https://mikanani.me/images/Bangumi/")
    assert a.source_meta["cover"] == a.poster           # 封面同时落 poster 与 source_meta
    assert a.source_meta["mikan_id"] == "3848"
    assert a.source_meta["week"] == "星期六"
    assert a.source_meta["air_date"] == "10/5/2025"
    # 原名回退取详情页 bangumi-title 全名（比列表标题更完整）。
    assert a.source_meta["original_title"] == "卡片战斗先导者 Divinez 幻真星战篇"
    assert a.source_meta["aliases"] == []
    assert a.unique_seed == "3848"
    assert a.dedup_key("mikan") == "mikan:3848"

    b = by_title["勇者之屑"]
    assert b.type_hint == MediaType.TV
    assert b.bangumi_id is None                         # 详情无 bgm 链接 -> 退化名称识别
    assert b.year == "2026"                             # 放送年与配置一致
    assert b.source_meta["mikan_id"] == "3900"
    assert b.source_meta["original_title"] == "勇者之屑"


def test_mikan_fetch_without_resolve_skips_detail(monkeypatch):
    """resolve_bangumi_id=False：不抓详情，bangumi_id 全 None，年份用配置，仅一次请求。"""
    calls = {"n": 0}

    def _spy(self, url, *a, **k):
        calls["n"] += 1
        return _fake_get_res(self, url, *a, **k)

    monkeypatch.setattr(RequestUtils, "get_res", _spy)
    monkeypatch.setattr(mikan_mod, "sleep", lambda *_a, **_k: None)

    items = list(MikanRankProvider().fetch(
        {"year": 2026, "season": "春", "resolve_bangumi_id": False}, None))
    assert len(items) == 2
    assert all(i.bangumi_id is None for i in items)
    assert all(i.year == "2026" for i in items)         # 无详情 -> 用配置年
    assert all(i.poster for i in items)                 # poster 恒设（封面）
    assert calls["n"] == 1                              # 仅季度列表一次，未抓详情


def test_mikan_empty_response_yields_nothing(monkeypatch):
    """季度页无返回时产出空。"""
    monkeypatch.setattr(RequestUtils, "get_res", lambda self, url, *a, **k: None)
    items = list(MikanRankProvider().fetch({"year": 2026, "season": "夏"}, None))
    assert items == []


def test_mikan_api_season_parses(monkeypatch):
    """MikanApi.season 直接解析季度 HTML（默认主站基址拼封面）。"""
    monkeypatch.setattr(RequestUtils, "get_res",
                        lambda self, url, *a, **k: SimpleNamespace(text=SEASON_HTML))
    entries = MikanApi().season(2026, "春")
    assert [e["mikan_id"] for e in entries] == ["3848", "3900"]
    assert entries[0]["title"] == "卡片战斗先导者"
    assert entries[0]["cover"].startswith("https://mikanani.me/images/Bangumi/")


def test_mikan_api_bangumi_detail(monkeypatch):
    """MikanApi.bangumi_detail：含/缺 bgm 两种详情页。"""
    monkeypatch.setattr(RequestUtils, "get_res", _fake_get_res)
    d1 = MikanApi().bangumi_detail("3848")
    assert d1["bgm_id"] == 591584
    assert d1["year"] == "2025"
    assert d1["air_date"] == "10/5/2025"
    assert d1["original_title"] == "卡片战斗先导者 Divinez 幻真星战篇"
    d2 = MikanApi().bangumi_detail("3900")
    assert d2["bgm_id"] is None
    assert d2["year"] == "2026"


# ----------------------------------------------------------------------------
# 真实样本回归（fixtures/）
# ----------------------------------------------------------------------------

FIXTURES = Path(__file__).parent / "fixtures"
SEASON_SAMPLE = (FIXTURES / "mikan_season_sample.html").read_text(encoding="utf-8")
DETAIL_SAMPLE = (FIXTURES / "mikan_bangumi_detail_sample.html").read_text(encoding="utf-8")

# 无 bgm / 无放送开始的真实结构详情片段：触发降级（bgm None、年份回退配置年）。
DETAIL_NO_BGM_FRAGMENT = """<html><body><div id="sk-container">
<div class="pull-left leftbar-container">
<p class="bangumi-title">某无 Bangumi 链接番剧</p>
<p class="bangumi-info">放送日期：星期日</p>
</div></div></body></html>"""


def _fixture_get_res(_self, url, *args, **kwargs):
    """真实季度页 + 3904 真实详情；其余详情走无 bgm 片段（触发降级）。"""
    if "BangumiCoverFlowByDayOfWeek" in url:
        return SimpleNamespace(text=SEASON_SAMPLE)
    if url.endswith("/Home/Bangumi/3904"):
        return SimpleNamespace(text=DETAIL_SAMPLE)
    if "/Home/Bangumi/" in url:
        return SimpleNamespace(text=DETAIL_NO_BGM_FRAGMENT)
    return None


def test_mikan_regression_from_fixtures(monkeypatch):
    """真实样本端到端：3904 补齐 bgm/放送年/原名/poster，其余降级。"""
    monkeypatch.setattr(RequestUtils, "get_res", _fixture_get_res)
    monkeypatch.setattr(mikan_mod, "sleep", lambda *_a, **_k: None)

    items = list(MikanRankProvider().fetch(
        {"year": 2026, "season": "春", "resolve_bangumi_id": True}, None))
    by_id = {i.source_meta["mikan_id"]: i for i in items}
    assert set(by_id) == {"227", "3899", "3904"}

    # 真实解析目标：自称恶役大小姐的婚约者观察记录。
    hit = by_id["3904"]
    assert hit.title == "自称恶役大小姐的婚约者观察记录。"
    assert hit.type_hint == MediaType.TV
    assert hit.bangumi_id == 558088                     # 真实 bgm.tv subject id
    assert hit.year == "2026"                           # 真实放送年(放送开始 4/6/2026)
    assert hit.source_meta["air_date"] == "4/6/2026"
    assert hit.source_meta["week"] == "星期一"
    assert hit.poster.startswith("https://mikanani.me/images/Bangumi/202604/")
    assert hit.source_meta["cover"] == hit.poster
    assert hit.source_meta["original_title"] == "自称恶役大小姐的婚约者观察记录。"
    assert hit.source_meta["aliases"] == []

    # 降级项：无 bgm、年份回退配置年，但 poster 仍恒设。
    other = by_id["227"]
    assert other.title == "名侦探柯南"
    assert other.bangumi_id is None
    assert other.year == "2026"
    assert other.source_meta["week"] == "星期日"
    assert other.poster.startswith("https://mikanani.me/images/Bangumi/201310/")
    assert by_id["3899"].bangumi_id is None


def test_mikan_parse_detail_real_sample():
    """直接对真实详情样本跑 _parse_detail，断言整份解析结果。"""
    detail = MikanApi._parse_detail(DETAIL_SAMPLE)
    assert detail == {
        "bgm_id": 558088,
        "year": "2026",
        "air_date": "4/6/2026",
        "original_title": "自称恶役大小姐的婚约者观察记录。",
        "aliases": [],
    }


def test_mikan_parse_season_real_sample():
    """真实季度样本：三部番剧、按星期分组、相对封面拼主站基址。"""
    entries = MikanApi._parse_season(SEASON_SAMPLE, "https://mikanani.me")
    assert [e["mikan_id"] for e in entries] == ["227", "3899", "3904"]
    weeks = {e["mikan_id"]: e["week"] for e in entries}
    assert weeks == {"227": "星期日", "3899": "星期一", "3904": "星期一"}
    assert all(e["cover"].startswith("https://mikanani.me/images/Bangumi/") for e in entries)


# ----------------------------------------------------------------------------
# 盲点补测
# ----------------------------------------------------------------------------

# 单条季度样本（相对封面），用于基址 fallback 断言。
SEASON_ONE = """<html><body>
<div class="sk-bangumi" data-dayofweek="2">
  <div class="row">星期二</div>
  <ul><li>
    <span data-bangumiid="777" data-src="/images/Bangumi/x.jpg"></span>
    <a class="an-text" title="测试番">测试番</a>
  </li></ul>
</div></body></html>"""


def test_mikan_fallback_to_backup_base(monkeypatch):
    """主站抛异常 -> 走备用站；相对封面拼命中的备用站基址（不再硬编码主站）。"""
    def _get_res(self, url, *a, **k):
        if url.startswith("https://mikanani.me"):
            raise ConnectionError("primary down")     # 主站失败
        return SimpleNamespace(text=SEASON_ONE)       # 备用站命中
    monkeypatch.setattr(RequestUtils, "get_res", _get_res)

    entries = MikanApi().season(2026, "春")
    assert len(entries) == 1
    assert entries[0]["cover"] == "https://mikanime.tv/images/Bangumi/x.jpg"


def test_mikan_all_bases_fail_returns_empty(monkeypatch):
    """全部基址失败 -> season 返回空、bangumi_detail 返回 {}。"""
    monkeypatch.setattr(RequestUtils, "get_res",
                        lambda self, url, *a, **k: None)
    assert MikanApi().season(2026, "春") == []
    assert MikanApi().bangumi_detail("123") == {}


def test_mikan_bgm_regex_variants():
    """bgm.tv 与 bangumi.tv 两种变体均可提取 subject id。"""
    for host, expect in (("bgm.tv", 111), ("bangumi.tv", 222), ("www.bgm.tv", 333)):
        html = f"""<html><body>
        <p class="bangumi-info">Bangumi番组计划链接： https://{host}/subject/{expect}</p>
        </body></html>"""
        assert MikanApi._parse_detail(html)["bgm_id"] == expect


def test_mikan_bgm_scoped_to_info_container():
    """bgm 提取收敛到 .bangumi-info：容器内无链接则不误取页面别处的 bgm 链接。"""
    html = """<html><body><div class="leftbar-container">
    <p class="bangumi-title">容器内无 bgm</p>
    <p class="bangumi-info">放送日期：星期三</p>
    </div>
    <a href="https://bgm.tv/subject/999999">页面别处 stray</a>
    </body></html>"""
    assert MikanApi._parse_detail(html)["bgm_id"] is None


def test_mikan_bgm_fallback_whole_page_when_no_info_container():
    """无 .bangumi-info 容器时回退整页匹配 bgm（不回归）。"""
    html = """<html><body>
    <p>没有信息容器</p>
    <a href="https://bangumi.tv/subject/12345">x</a>
    </body></html>"""
    assert MikanApi._parse_detail(html)["bgm_id"] == 12345


def test_mikan_detail_explicit_alias_keys():
    """显式原名/别名 key 的解析路径（Mikan 实际无此字段，合成 HTML 覆盖）。"""
    html = """<html><body><div class="leftbar-container">
    <p class="bangumi-title">主标题</p>
    <p class="bangumi-info">原名：Original Name</p>
    <p class="bangumi-info">别名：别名一、别名二/别名三</p>
    </div></body></html>"""
    detail = MikanApi._parse_detail(html)
    assert detail["original_title"] == "Original Name"    # 原名 key 优先于 bangumi-title
    assert detail["aliases"] == ["别名一", "别名二", "别名三"]


def test_mikan_season_dedup_by_bangumiid():
    """同一 data-bangumiid 重复出现只保留一条（seen 去重）。"""
    html = """<html><body>
    <div class="sk-bangumi"><div class="row">星期一</div><ul>
      <li><span data-bangumiid="3848" data-src="/a.jpg"></span><a class="an-text" title="番A">番A</a></li>
      <li><span data-bangumiid="3848" data-src="/b.jpg"></span><a class="an-text" title="番A重复">番A重复</a></li>
    </ul></div></body></html>"""
    entries = MikanApi._parse_season(html, "https://mikanani.me")
    assert [e["mikan_id"] for e in entries] == ["3848"]
    assert entries[0]["title"] == "番A"


def test_mikan_season_skips_incomplete_entries():
    """缺 span[data-bangumiid] 或缺标题的 li 跳过。"""
    html = """<html><body>
    <div class="sk-bangumi"><div class="row">星期五</div><ul>
      <li><div class="an-info">无 span 无标题</div></li>
      <li><span data-bangumiid="500" data-src="/c.jpg"></span></li>
      <li><span data-bangumiid="501" data-src="/d.jpg"></span><a class="an-text" title="有效番">有效番</a></li>
    </ul></div></body></html>"""
    entries = MikanApi._parse_season(html, "https://mikanani.me")
    assert [e["mikan_id"] for e in entries] == ["501"]


def test_mikan_detail_failure_degrades_in_fetch(monkeypatch):
    """详情请求失败(get_res None)时降级：bgm None、年份回退配置年，仍产出条目。"""
    def _get_res(self, url, *a, **k):
        if "BangumiCoverFlowByDayOfWeek" in url:
            return SimpleNamespace(text=SEASON_ONE)
        return None                                    # 详情请求失败
    monkeypatch.setattr(RequestUtils, "get_res", _get_res)
    monkeypatch.setattr(mikan_mod, "sleep", lambda *_a, **_k: None)

    items = list(MikanRankProvider().fetch(
        {"year": 2030, "season": "春", "resolve_bangumi_id": True}, None))
    assert len(items) == 1
    assert items[0].bangumi_id is None
    assert items[0].year == "2030"                     # 降级用配置年
    assert items[0].poster == "https://mikanani.me/images/Bangumi/x.jpg"


def test_mikan_year_extraction_range_guard():
    """放送年只取 1900-2100 合法四位年；日期外的杂 4 位数不误判。"""
    # 无日期类 key、官方网站含 4 位数 -> 不误取。
    html = """<html><body>
    <p class="bangumi-info">官方网站： https://example.com/12340000</p>
    </body></html>"""
    assert MikanApi._parse_detail(html)["year"] is None
    # 放送开始含合法年。
    html2 = """<html><body>
    <p class="bangumi-info">放送开始：2027/07/01</p>
    </body></html>"""
    assert MikanApi._parse_detail(html2)["year"] == "2027"


def test_mikan_season_by_month():
    """按月份推导季度。"""
    f = MikanRankProvider._season_by_month
    assert [f(m) for m in (1, 2, 3)] == ["冬", "冬", "冬"]
    assert [f(m) for m in (4, 5, 6)] == ["春", "春", "春"]
    assert [f(m) for m in (7, 8, 9)] == ["夏", "夏", "夏"]
    assert [f(m) for m in (10, 11, 12)] == ["秋", "秋", "秋"]


def test_mikan_resolve_season_and_year():
    """季度：实测季名直用，'当前'/未知按月推导；年份 0 -> 当前年。"""
    assert MikanRankProvider._resolve_season("春") == "春"
    assert MikanRankProvider._resolve_season("当前") in mikan_mod.MIKAN_SEASONS
    assert MikanRankProvider._resolve_season("") in mikan_mod.MIKAN_SEASONS
    assert MikanRankProvider._resolve_year(2025) == 2025
    assert MikanRankProvider._resolve_year(0) > 0     # -> 当前年
    assert MikanRankProvider._resolve_year("bad") > 0


def test_mikan_spec_shape():
    """get_spec：provider 标识、默认 cron、season 选项含'当前'与四季。"""
    spec = MikanRankProvider().get_spec()
    assert spec.provider_id == "mikan"
    assert spec.default_cron == "0 10 * * 1"
    season_field = next(f for f in spec.options_schema if f.key == "season")
    values = [o["value"] for o in season_field.options]
    assert mikan_mod.SEASON_AUTO in values
    for s in mikan_mod.MIKAN_SEASONS:
        assert s in values
    assert [f.key for f in spec.filters_schema] == ["year"]
