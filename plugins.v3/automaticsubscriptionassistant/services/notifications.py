"""来源运行通知正文；每轮只发送一个结果，失败与部分统计合并。"""

STATUS_LABELS = {
    "subscribed": "已订阅",
    "media_exists": "媒体库已存在",
    "subscription_exists": "订阅已存在",
    "already_handled": "已处理",
    "filtered": "已过滤",
    "blacklisted": "已忽略",
    "unrecognized": "未识别",
    "error": "异常",
}


def format_run_result(name, stats, error=None):
    summary = "，".join(
        f"{STATUS_LABELS.get(key, key)}：{value}" for key, value in stats.items()
    )
    if error is not None:
        message = f"{name}运行失败：{error}"
        return f"{message}；已处理结果（{summary}）" if summary else message
    return (
        f"{name}运行完成（{summary}）"
        if summary
        else f"{name}运行完成，本次未获取到待处理条目"
    )
