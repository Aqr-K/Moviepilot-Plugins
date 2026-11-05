"""公开榜单 HTTP 请求和有界配置解析，统一使用宿主 SDK。"""

from app.sdk.config import settings
from app.sdk.network import RequestUtils


def request_json(url, context, *, payload=None, params=None, headers=None):
    if context.event is not None and context.event.is_set():
        raise InterruptedError("插件已停止")
    request = RequestUtils(
        timeout=25,
        verify=True,
        headers={"Accept": "application/json", **(headers or {})},
        proxies=settings.PROXY if context.proxy else None,
    )
    response = (
        request.get_res(url, params=params)
        if payload is None
        else request.post_res(url, json=payload)
    )
    if response is None:
        raise RuntimeError("榜单请求失败，请检查网络或代理")
    try:
        if response.status_code != 200:
            raise RuntimeError(f"榜单接口返回 HTTP {response.status_code}")
        result = response.json()
        if not isinstance(result, dict):
            raise TypeError("榜单响应不是 JSON 对象")
        return result
    finally:
        response.close()


def selected(options, key, allowed, defaults):
    raw = options.get(key, defaults)
    if isinstance(raw, str):
        raw = raw.split(",")
    if not isinstance(raw, (list, tuple)):
        raise TypeError(f"{key} 必须为选项列表")
    values = list(
        dict.fromkeys(str(value).strip() for value in raw if str(value).strip())
    )
    if any(value not in allowed for value in values):
        raise ValueError(f"{key} 含不支持的选项，请重新选择")
    return values


def limit_of(options, maximum=100, default=20):
    try:
        return max(1, min(int(options.get("limit", default)), maximum))
    except (TypeError, ValueError):
        return default


def stopped(context):
    return context.event is not None and context.event.is_set()
