"""历史补充编辑：输入校验、显式手动重建及原有自动防重复语义。"""
from copy import deepcopy
from unittest.mock import MagicMock

import pytest

from app.schemas.types import MediaType
from app.plugins.automaticsubscriptionassistant import AutomaticSubscriptionAssistant
from app.plugins.automaticsubscriptionassistant.core.blacklist import BlacklistStore
from app.plugins.automaticsubscriptionassistant.core.config import GlobalConfig
from app.plugins.automaticsubscriptionassistant.core.executor import SubscribeExecutor
from app.plugins.automaticsubscriptionassistant.core.filters import FilterChain
from app.plugins.automaticsubscriptionassistant.core.models import HistoryRecord, SubscribeStatus
from app.plugins.automaticsubscriptionassistant.core.supplement import HistorySupplementService, parse_supplement
from test_executor import _make_ctx, _make_store, _mediainfo, _PROVIDER


def request_body(**media):
    """构造明确指定媒体、目标季和剧集组的手动请求。"""
    return {"unique": "original", "media": {"title": "补充剧名", "type": "电视剧", "year": "2026",
            "media_source": "themoviedb", "media_id": "438631", "season": 2, "episode_group": "group-a", **media},
            "subscription": {}}


@pytest.fixture
def supplement():
    """提供隔离内存历史与无网络的宿主边界。"""
    history, _ = _make_store()
    history.record(HistoryRecord(unique="original", provider="douban", title="原始候选", status="error",
                                 source_item={"title": "原始候选", "douban_id": "old", "season": 1}))
    context = _make_ctx()
    context.chain.recognize_media.return_value = _mediainfo(mtype=MediaType.TV, season=1)
    context.downloadchain.get_no_exists_info.return_value = (False, {})
    context.subscribechain.exists.return_value = False
    context.subscribechain.add.return_value = (77, "")
    config = GlobalConfig({"username": "插件订阅用户", "exist_ok": False})
    yield HistorySupplementService(context, config, history), context, history
    history._session_factory.kw["bind"].dispose()


@pytest.mark.parametrize("season", [0, 2])
def test_manual_settings_reach_create_without_mutating_original(supplement, season):
    """特别篇和指定季贯穿管线，订阅参数只影响本次调用，原候选保留。"""
    service, context, history = supplement
    original = deepcopy(history.get("original"))
    body = request_body(season=season)
    body["subscription"] = {"quality": "WEB-?DL|WEB-?RIP", "resolution": "1080[pi]", "sites": [1, 2],
                            "downloader": "test-client", "save_path": "/downloads/test", "search_interval": 6,
                            "total_episode": 12, "start_episode": 3, "best_version": 1, "best_version_full": 0}
    result = service.submit(body)
    assert result["created"] is True
    assert result["subscribe_id"] == 77
    args = context.subscribechain.add.call_args.kwargs
    assert args["season"] == season
    assert args["episode_group"] == "group-a"
    assert args["username"] == "插件订阅用户"
    assert all(args[key] == value for key, value in body["subscription"].items())
    assert context.chain.recognize_media.call_args.kwargs["media_id"] == "438631"
    assert history.get("original") == original
    assert service.config.exist_ok is False


def test_manual_retry_can_rebuild_cancelled_subscription_without_erasing_ledger(supplement):
    """显式手动提交可重新创建已取消项，后续自动任务仍命中成功账本。"""
    service, context, history = supplement
    body = request_body()
    item, _, _ = parse_supplement(history.get("original"), body)
    history.mark_handled(item.identity())
    history.mark_handled(item.candidate_key())
    result = service.submit(body)
    assert result["created"] is True
    assert history.is_handled(item.candidate_key())
    automatic = SubscribeExecutor(context, service.config).process(item, _PROVIDER, FilterChain([]), history, {})
    assert automatic.status == SubscribeStatus.ALREADY_HANDLED
    context.subscribechain.add.assert_called_once()


def test_existing_subscription_prevents_manual_duplicate(supplement):
    """手动提交不绕过宿主已有订阅检查。"""
    service, context, _ = supplement
    context.subscribechain.exists.return_value = True
    result = service.submit(request_body())
    assert result["created"] is False
    assert result["status"] == "subscription_exists"
    context.subscribechain.add.assert_not_called()


def test_blacklist_still_blocks_manual_submission(supplement):
    """长期忽略规则也约束补充编辑提交。"""
    service, context, _ = supplement
    data = {}
    context.get_data = data.get
    context.save_data = lambda key, value: data.__setitem__(key, value)
    BlacklistStore(context.get_data, context.save_data).add({"title": "补充剧名", "type": "电视剧",
                                                           "media_source": "themoviedb", "media_id": "438631"})
    result = service.submit(request_body())
    assert result["status"] == "blacklisted"
    context.chain.recognize_media.assert_not_called()
    context.subscribechain.add.assert_not_called()


def test_library_check_can_be_overridden_explicitly_for_this_submission(supplement):
    """允许已有媒体只作用于本次，且历史媒体库终态不会永久阻止显式手动重建。"""
    service, context, _ = supplement
    context.downloadchain.get_no_exists_info.return_value = (True, {})
    assert service.submit(request_body())["status"] == "media_exists"
    assert service.submit({**request_body(), "exist_ok": True})["created"] is True
    assert service.config.exist_ok is False


def test_clearing_identity_really_discards_stale_source_ids(supplement):
    """清空来源和 ID 后按新名称识别，不恢复原历史中的旧豆瓣 ID。"""
    service, context, _ = supplement
    assert service.submit(request_body(media_source=None, media_id=""))["created"] is True
    args = context.chain.recognize_media.call_args.kwargs
    assert not args.get("media_source")
    assert not args.get("media_id")


@pytest.mark.parametrize("media", [
    {"title": ""}, {"type": "音乐"}, {"year": "2026.5"}, {"year": "1000"},
    {"season": None}, {"season": -1}, {"season": 2.5}, {"season": True},
    {"type": "电影"}, {"media_source": None}, {"media_id": ""},
])
def test_invalid_media_has_no_recognition_or_write(supplement, media):
    """缺失季号、非整数季和不完整身份均在识别前拒绝。"""
    service, context, _ = supplement
    with pytest.raises(ValueError):
        service.submit(request_body(**media))
    context.chain.recognize_media.assert_not_called()
    context.subscribechain.add.assert_not_called()


@pytest.mark.parametrize("options", [
    {"username": "other"}, {"state": "S"}, {"media_id": "bad"}, {"lack_episode": 0},
    {"search_interval": 0}, {"search_interval": 8761}, {"sites": [True]}, {"sites": [-1]},
    {"total_episode": 12, "start_episode": 13}, {"best_version": 3}, {"best_version_full": 1},
])
def test_subscription_whitelist_and_ranges(supplement, options):
    """归属、运行事实和越界参数不能通过手动表单写入。"""
    service, context, _ = supplement
    with pytest.raises(ValueError):
        service.submit({**request_body(), "subscription": options})
    context.chain.recognize_media.assert_not_called()
    context.subscribechain.add.assert_not_called()


def test_failed_recognition_preserves_original_and_reports_no_creation(supplement):
    """未识别时不会创建订阅，原始历史仍可再次补充。"""
    service, context, history = supplement
    context.chain.recognize_media.return_value = None
    result = service.submit(request_body())
    assert result["status"] == "unrecognized"
    assert result["created"] is False
    assert history.get("original")["source_item"]["douban_id"] == "old"
    context.subscribechain.add.assert_not_called()


def test_failed_create_without_reason_does_not_report_success(supplement):
    """宿主未给失败原因时也不能返回已创建的成功文案。"""
    service, context, _ = supplement
    context.subscribechain.add.return_value = (None, None)
    result = service.submit(request_body())
    assert result["created"] is False
    assert result["message"] == "未创建订阅，请调整信息后重试"


def test_explicit_type_must_match_recognition(supplement):
    """手动选择的电影不能被识别链静默替换成剧集。"""
    service, context, _ = supplement
    result = service.submit(request_body(type="电影", season=None, episode_group=None))
    assert result["status"] == "error"
    context.subscribechain.add.assert_not_called()


def test_missing_history_is_rejected_before_create(supplement):
    """被删除或过期的历史不会作为无来源的创建请求继续执行。"""
    service, context, _ = supplement
    with pytest.raises(ValueError):
        service.submit({**request_body(), "unique": "missing"})
    context.chain.recognize_media.assert_not_called()


def test_failed_manual_attempt_does_not_downgrade_success(supplement):
    """手动失败也不能把已经成立的成功历史与成功账本降级。"""
    service, context, history = supplement
    item, _, _ = parse_supplement(history.get("original"), request_body())
    history.record(HistoryRecord(unique=item.identity(), provider="douban", title="已成功", status="subscribed"))
    context.chain.recognize_media.return_value = None
    assert service.submit(request_body())["created"] is False
    assert history.get(item.identity())["status"] == "subscribed"
    assert history.is_handled(item.identity())


def test_endpoint_is_authenticated_and_reports_validation_error():
    """补充编辑使用 bearer 鉴权，验证失败返回业务错误。"""
    plugin = AutomaticSubscriptionAssistant.__new__(AutomaticSubscriptionAssistant)
    endpoint = next(row for row in plugin.get_api() if row["path"] == "/history/supplement")
    assert endpoint["auth"] == "bear"
    assert endpoint["methods"] == ["POST"]
    plugin.chain = MagicMock()
    plugin._downloadchain = MagicMock()
    plugin._subscribechain = MagicMock()
    plugin._event = None
    plugin._settings = MagicMock()
    plugin._AutomaticSubscriptionAssistant__history_store = MagicMock()
    assert plugin.api_history_supplement({})["code"] == 1
