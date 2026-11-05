"""音乐榜单共享投影：平台身份只表示原榜单对象，识别后使用宿主规范身份订阅。"""

from datetime import datetime, timezone

from app.schemas.types import MediaType

from ..schemas import FieldSpec, RankMediaItem


def music_options(charts, default, *, maximum=100):
    return [
        FieldSpec(
            "charts",
            "音乐榜单",
            "multi-select",
            default=default,
            options=[{"title": title, "value": key} for key, title in charts.items()],
        ),
        FieldSpec(
            "limit", "每榜取前N", "number", default=20, hint=f"1 至 {maximum} 条"
        ),
        FieldSpec("proxy", "使用代理访问", "switch", default=False),
    ]


def music_item(
    source,
    identity,
    title,
    artists,
    *,
    music_type="recording",
    album=None,
    year=None,
    poster=None,
    isrc=None,
    chart=None,
    rank=None,
):
    title = str(title or "").strip()
    names = list(
        dict.fromkeys(
            name.strip() for name in artists if isinstance(name, str) and name.strip()
        )
    )
    if (
        not identity
        or not title
        or not names
        or music_type not in {"recording", "album"}
    ):
        return None
    return RankMediaItem(
        title=title,
        type_hint=MediaType.MUSIC,
        media_source=source,
        media_id=str(identity),
        music_type=music_type,
        artists=names,
        album=album,
        isrc=isrc,
        year=str(year)[:4] if year else None,
        poster=poster,
        unique_seed=f"{music_type}:{identity}",
        source_meta={"chart": chart, "rank": rank},
    )


def timestamp_year(value):
    try:
        return (
            str(datetime.fromtimestamp(float(value) / 1000, timezone.utc).year)
            if value
            else None
        )
    except (ValueError, TypeError, OverflowError, OSError):
        return None
