"""忽略规则的 SQL 持久化、校验与匹配服务。"""

from datetime import datetime
from threading import RLock
from uuid import uuid4

from ..database.lifecycle import DatabaseSession
from ..db.oper.blacklist import BlacklistOper
from ..schemas.blacklist import media_snapshot

BLACKLIST_LOCK = RLock()


class BlacklistStore:
    """当前插件实例的忽略规则，不使用 KV 读写回退。"""

    def __init__(self, session_factory):
        self._database = DatabaseSession(session_factory)

    def list(self):
        with BLACKLIST_LOCK, self._database.session() as session:
            return BlacklistOper(session).list()

    def add(self, media, *, season=None, aliases=()):
        snapshot = media_snapshot(media)
        if snapshot["type"] not in ("电影", "电视剧", "音乐"):
            raise ValueError("请选择电影、电视剧或音乐")
        if snapshot["type"] == "音乐" and (
            snapshot.get("music_type") not in {"recording", "album"}
            or (not snapshot.get("artists") and not snapshot.get("ids"))
        ):
            raise ValueError("音乐黑名单必须填写单曲/专辑类型及艺术家")
        if not snapshot["title"]:
            raise ValueError("请填写影视名称")
        if season is not None:
            if snapshot["type"] != "电视剧" or isinstance(season, bool):
                raise ValueError("只有剧集可以设置季号")
            if not str(season).isdigit():
                raise ValueError("季号必须是非负整数（0 为特别篇）")
            season = int(season)
        snapshots = [snapshot] + [media_snapshot(alias) for alias in aliases if alias]
        row = {
            **snapshot,
            "season": season,
            "aliases": snapshots,
            "id": uuid4().hex,
            "time": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S"),
        }
        with BLACKLIST_LOCK, self._database.session() as session:
            return BlacklistOper(session).insert(row)

    def delete(self, ids):
        with BLACKLIST_LOCK, self._database.session() as session:
            return BlacklistOper(session).delete(ids)

    def match(self, media, *, season=None):
        candidate = media_snapshot(media)
        if season is None:
            season = candidate["season"]
        for row in self.list():
            if candidate["type"] and candidate["type"] != row["type"]:
                continue
            if row["season"] is not None and str(row["season"]) != str(season):
                continue
            if row["type"] == "音乐" and candidate.get("music_type") != row.get(
                "music_type"
            ):
                continue
            for alias in row["aliases"]:
                shared = candidate["ids"].keys() & alias["ids"].keys()
                # 同一来源 ID 冲突时不回退名称，避免同名不同片被误拦截。
                # TMDB 整剧 ID 相同即可覆盖不同季的豆瓣 subject ID。
                if "tmdb" in shared and candidate["type"]:
                    if candidate["ids"]["tmdb"] == alias["ids"]["tmdb"]:
                        return row
                    continue
                if any(candidate["ids"][key] != alias["ids"][key] for key in shared):
                    continue
                if shared:
                    # TMDB 的电影/剧集 ID 空间重叠，类型未知时留给识别后复核。
                    if not candidate["type"] and shared == {"tmdb"}:
                        continue
                    return row
                # 有 ID 的规则只按 ID 命中，跨来源转换交给识别后的规范身份。
                if alias["ids"] or not candidate["type"]:
                    continue
                if row["type"] == "音乐":
                    names = {name.casefold() for name in candidate.get("artists", [])}
                    if not names & {
                        name.casefold() for name in alias.get("artists", [])
                    }:
                        continue
                name = " ".join(candidate["title"].casefold().split())
                expected = " ".join(alias["title"].casefold().split())
                if (
                    name
                    and name == expected
                    and (not alias["year"] or alias["year"] == candidate["year"])
                ):
                    return row
        return None
