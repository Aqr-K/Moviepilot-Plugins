"""从历史记录补充媒体身份与订阅设置，独立执行手动识别和新增订阅。"""
from threading import Lock
from types import SimpleNamespace

from app.schemas.subscribe import Subscribe
from app.schemas.types import MediaType

from .config import GlobalConfig
from .executor import SubscribeExecutor
from .filters import FilterChain
from .models import RankMediaItem

_SUBMIT_LOCK = Lock()
_OPTIONS = frozenset({
    "keyword", "quality", "resolution", "effect", "sites", "downloader", "save_path",
    "search_interval", "total_episode", "start_episode", "best_version", "best_version_full",
    "include", "exclude", "filter_groups",
})
_MEDIA_FIELDS = frozenset({"title", "type", "year", "season", "episode_group", "media_source", "media_id"})


def parse_supplement(record: dict, request: dict):
    """校验用户输入，只接受媒体定义和公开订阅设置，不接受归属或运行事实。

    :param record: 原始历史记录，仅供追溯来源和海报
    :param request: 含 media、subscription 和可选 exist_ok 的手动请求
    :return: 新候选、经过白名单校验的订阅参数及是否允许媒体库已有内容
    """
    if set(request) - {"unique", "media", "subscription", "exist_ok"}:
        raise ValueError("请求含不支持的字段")
    media = request.get("media")
    options = request.get("subscription", {})
    if not isinstance(media, dict) or set(media) - _MEDIA_FIELDS:
        raise ValueError("媒体信息格式错误或含不支持的字段")
    if not isinstance(options, dict) or set(options) - _OPTIONS:
        raise ValueError("订阅设置格式错误或含不支持的字段")
    title = media.get("title")
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 300:
        raise ValueError("请填写影视名称（最多 300 字）")
    if media.get("type") not in (MediaType.MOVIE.value, MediaType.TV.value):
        raise ValueError("请选择电影或电视剧")
    source = media.get("media_source") or None
    media_id = media.get("media_id")
    media_id = str(media_id).strip() if media_id is not None else None
    if bool(source) != bool(media_id):
        raise ValueError("媒体来源与媒体 ID 必须同时填写或同时留空")
    if isinstance(media.get("season"), bool):
        raise ValueError("季号必须为非负整数")
    data = Subscribe(name=title.strip(), type=media["type"], year=media.get("year") or None,
                     season=media.get("season"), episode_group=media.get("episode_group") or None,
                     media_source=source, media_id=media_id or None, **options)
    if data.year and (not data.year.isdigit() or not 1800 <= int(data.year) <= 2999):
        raise ValueError("发行年份应为 1800 至 2999")
    if data.type == MediaType.TV.value:
        if data.season is None or not 0 <= data.season <= 999:
            raise ValueError("剧集必须填写目标季号（0 为特别篇）")
    elif data.season is not None or data.episode_group:
        raise ValueError("电影不能设置季号或剧集组")
    for key in ("total_episode", "start_episode"):
        value = getattr(data, key)
        if key in options and (value is None or not 1 <= value <= 10000):
            raise ValueError("总集数和开始集数应为 1 至 10000")
    if data.total_episode and data.start_episode and data.start_episode > data.total_episode:
        raise ValueError("开始集数不能大于总集数")
    for key in ("best_version", "best_version_full"):
        if key in options and getattr(data, key) not in (0, 1):
            raise ValueError("洗版选项应为 0 或 1")
    if data.best_version_full and not data.best_version:
        raise ValueError("全集洗版需要同时开启洗版订阅")
    if data.type == MediaType.MOVIE.value and data.best_version_full:
        raise ValueError("只有剧集可以设置全集洗版")
    if "sites" in options and (not isinstance(options["sites"], list)
                              or any(type(site) is not int or site <= 0 for site in options["sites"])):
        raise ValueError("订阅站点必须为有效的站点 ID 列表")
    if "exist_ok" in request and type(request["exist_ok"]) is not bool:
        raise ValueError("允许媒体库已有内容应为布尔值")
    # 不恢复旧候选中的其他 ID，用户清空身份后确实会按新名称、类型和年份重新识别。
    item = RankMediaItem(title=data.name, year=data.year, type_hint=MediaType(data.type),
                         media_source=data.media_source, media_id=data.media_id, season=data.season,
                         episode_group=data.episode_group, poster=record.get("poster"))
    parsed_options = {key: getattr(data, key) for key in options}
    return item, parsed_options, request.get("exist_ok")


class HistorySupplementService:
    """手动提交历史补充，不修改榜单设置，不删除原候选或已有成功事实。"""

    def __init__(self, context, config, history):
        """注入运行上下文、全局配置和插件历史仓库。"""
        self.context = context
        self.config = config
        self.history = history

    def submit(self, request: dict) -> dict:
        """重新识别并尝试新增订阅；串行提交并继续检查黑名单和已有订阅。"""
        if not isinstance(request, dict) or not isinstance(request.get("unique"), str) or not request["unique"]:
            raise ValueError("缺少历史记录标识")
        with _SUBMIT_LOCK:
            record = self.history.get(request["unique"])
            if record is None:
                raise ValueError("未找到该历史记录，请刷新后重试")
            item, options, exist_ok = parse_supplement(record, request)
            config = GlobalConfig({"username": self.config.username,
                                   "exist_ok": self.config.exist_ok if exist_ok is None else exist_ok})
            executor = SubscribeExecutor(self.context, config, manual=True, subscribe_options=options)
            provider = SimpleNamespace(provider_id=record.get("provider") or "manual")
            # 手动选择不再使用榜单推荐过滤条件；黑名单、识别、媒体库和订阅查重仍在管线内。
            outcome = executor.process(item, provider, FilterChain([]), self.history, {})
            self.history.flush()
            created = outcome.status.value == "subscribed"
            return {"code": 0, "status": outcome.status.value, "subscribe_id": outcome.subscribe_id,
                    "created": created,
                    "message": outcome.reason or outcome.message or
                               ("已重新识别并创建订阅" if created else "未创建订阅，请调整信息后重试")}
