"""媒体快照与黑名单身份规范。"""


def _value(value):
    return str(getattr(value, "value", value) or "").strip()


def _source(value):
    value = _value(value).casefold()
    return {"themoviedb": "tmdb"}.get(value, value)


def media_snapshot(media):
    """兼容候选、识别对象、订阅行和历史字典。"""

    def get(*names):
        for name in names:
            value = (
                media.get(name)
                if isinstance(media, dict)
                else getattr(media, name, None)
            )
            if value is not None and value != "":
                return value
        return None

    ids = {}
    for source, fields in (
        ("tmdb", ("tmdb_id", "tmdbid")),
        ("douban", ("douban_id", "doubanid")),
        ("bangumi", ("bangumi_id", "bangumiid")),
    ):
        value = _value(get(*fields))
        if value and value != "0":
            ids[source] = value
    source, media_id = _source(get("media_source")), _value(get("media_id"))
    if source and media_id and media_id != "0":
        ids[source] = media_id
    result = {
        "title": _value(get("title", "name")),
        "year": _value(get("year")),
        "type": _value(get("type", "type_hint")),
        "ids": ids,
        "season": get("season"),
        "poster": _value(get("poster")),
    }

    if result["type"] == "音乐":
        artists = get("artists") or []
        result.update(
            music_type=_value(get("music_type")),
            artists=[
                name.strip()
                for name in artists
                if isinstance(name, str) and name.strip()
            ],
        )
    return result


def validate_rule(row):
    """持久规则必须可被匹配器安全读取，损坏数据不静默丢弃。"""
    if (
        not isinstance(row, dict)
        or not isinstance(row.get("id"), str)
        or not row["id"]
        or len(row["id"]) > 32
        or row.get("type") not in {"电影", "电视剧", "音乐"}
        or not isinstance(row.get("title"), str)
        or not row["title"].strip()
        or not isinstance(row.get("aliases"), list)
        or not row["aliases"]
        or not isinstance(row.get("time"), str)
        or "season" not in row
        or (
            row["season"] is not None
            and (type(row["season"]) is not int or row["season"] < 0)
        )
    ):
        raise ValueError("存在无法解析的黑名单，源数据已保留")
    if row["type"] == "音乐" and (
        row.get("music_type") not in {"recording", "album"}
        or (not row.get("artists") and not row.get("ids"))
        or row["season"] is not None
    ):
        raise ValueError("音乐黑名单缺少实体类型或艺术家")
    if row["type"] == "音乐" and (
        not isinstance(row.get("artists"), list)
        or not all(isinstance(name, str) and name.strip() for name in row["artists"])
    ):
        raise ValueError("音乐黑名单艺术家格式错误")
    for alias in row["aliases"]:
        if (
            not isinstance(alias, dict)
            or not isinstance(alias.get("ids"), dict)
            or not all(
                isinstance(alias.get(key), str) for key in ("title", "year", "type")
            )
            or not all(
                isinstance(k, str) and isinstance(v, str) and bool(v)
                for k, v in alias["ids"].items()
            )
        ):
            raise ValueError("黑名单媒体别名损坏，源数据已保留")
    return row
