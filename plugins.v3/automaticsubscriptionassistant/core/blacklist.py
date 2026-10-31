"""用户主动忽略的媒体，独立于订阅历史持久保存，v2/v3 共用语义。"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from threading import RLock
from uuid import uuid4


# 跨仓库实例串行化 KV 的读改写，以及「最终检查 + 添加订阅」。
BLACKLIST_LOCK = RLock()
BLACKLIST_KEY = "subscription_blacklist"


def _value(value):
    return str(getattr(value, "value", value) or "").strip()


def _source(value):
    value = _value(value).casefold()
    return {"themoviedb": "tmdb"}.get(value, value)


def media_snapshot(media):
    """兼容候选、识别对象、订阅行和历史字典。"""
    def get(*names):
        for name in names:
            value = media.get(name) if isinstance(media, dict) else getattr(media, name, None)
            if value is not None and value != "":
                return value
        return None

    ids = {}
    for source, fields in (("tmdb", ("tmdb_id", "tmdbid")),
                           ("douban", ("douban_id", "doubanid")),
                           ("bangumi", ("bangumi_id", "bangumiid"))):
        value = _value(get(*fields))
        if value and value != "0":
            ids[source] = value
    source, media_id = _source(get("media_source")), _value(get("media_id"))
    if source and media_id and media_id != "0":
        ids[source] = media_id
    return {"title": _value(get("title", "name")), "year": _value(get("year")),
            "type": _value(get("type", "type_hint")), "ids": ids,
            "season": get("season"), "poster": _value(get("poster"))}


class BlacklistStore:
    """每次操作读取最新 KV；不会因为历史清理、订阅删除或插件重启而失效。"""

    def __init__(self, get_data, save_data):
        self.get_data = get_data
        self.save_data = save_data

    def list(self):
        with BLACKLIST_LOCK:
            rows = self.get_data(BLACKLIST_KEY) if callable(self.get_data) else None
            return deepcopy(rows) if isinstance(rows, list) else []

    def _save(self, rows):
        if not callable(self.save_data) or self.save_data(BLACKLIST_KEY, rows) is False:
            raise RuntimeError("黑名单保存失败")

    def add(self, media, *, season=None, aliases=()):
        snapshot = media_snapshot(media)
        if snapshot["type"] not in ("电影", "电视剧"):
            raise ValueError("请选择电影或电视剧")
        if not snapshot["title"]:
            raise ValueError("请填写影视名称")
        if season is not None:
            if snapshot["type"] != "电视剧" or isinstance(season, bool):
                raise ValueError("只有剧集可以设置季号")
            if not str(season).isdigit():
                raise ValueError("季号必须是非负整数（0 为特别篇）")
            season = int(season)
        snapshots = [snapshot] + [media_snapshot(alias) for alias in aliases if alias]
        row = {**snapshot, "season": season, "aliases": snapshots,
               "id": uuid4().hex, "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        with BLACKLIST_LOCK:
            rows = self.list()
            for existing in rows:
                if (existing["type"] == row["type"] and existing["season"] == season
                        and existing["aliases"] == snapshots):
                    return existing
            rows.insert(0, row)
            self._save(rows)
        return row

    def delete(self, ids):
        with BLACKLIST_LOCK:
            rows = self.list()
            remaining = [row for row in rows if row["id"] not in ids]
            self._save(remaining)
            return len(rows) - len(remaining)

    def match(self, media, *, season=None):
        candidate = media_snapshot(media)
        if season is None:
            season = candidate["season"]
        for row in self.list():
            if candidate["type"] and candidate["type"] != row["type"]:
                continue
            if row["season"] is not None and str(row["season"]) != str(season):
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
                name = " ".join(candidate["title"].casefold().split())
                expected = " ".join(alias["title"].casefold().split())
                if name and name == expected and (not alias["year"] or alias["year"] == candidate["year"]):
                    return row
        return None


class BlacklistApiMixin:
    """从服务端已有记录提取身份，前端不必拼接媒体 ID。"""

    def blacklist_store(self):
        return BlacklistStore(self.get_data, self.save_data)

    def api_blacklist(self):
        rows = self.blacklist_store().list()
        return {"code": 0, "list": rows, "total": len(rows)}

    def api_blacklist_add(self, request: dict = None):
        body = request if isinstance(request, dict) else {}
        try:
            kind = body.get("kind", "manual")
            aliases = []
            if kind == "history":
                media = self.blacklist_history_store().get(body.get("unique"))
                if not media:
                    raise ValueError("未找到该历史记录")
                aliases = [media.get("source_item")]
            elif kind == "subscription":
                media = next((row for row in self.blacklist_subscribe_manager().list_mine()
                              if str(row["id"]) == str(body.get("id"))), None)
                if not media:
                    raise ValueError("未找到本插件的订阅")
            elif kind == "manual":
                media = body.get("media")
                if not isinstance(media, dict):
                    raise ValueError("缺少影视信息")
                source, media_id = media.get("media_source"), media.get("media_id")
                if bool(source) != bool(media_id):
                    raise ValueError("媒体来源与 ID 必须同时填写")
            else:
                raise ValueError("未知的添加方式")
            scope = body.get("scope", "all")
            if scope not in ("all", "season"):
                raise ValueError("无效的忽略范围")
            season = media.get("season") if scope == "season" else None
            if scope == "season" and season is None:
                raise ValueError("该记录没有明确季号，请选择全部季")
            snapshot = media_snapshot(media)
            if (scope == "all" and snapshot["type"] == "电视剧"
                    and "tmdb" not in snapshot["ids"]
                    and snapshot["ids"].keys() & {"douban", "bangumi"}):
                # 豆瓣/番组计划往往是一季一个 ID；整剧规则须补充宿主的整剧身份。
                resolved = self.blacklist_resolve_media(media)
                if (not resolved or media_snapshot(resolved)["type"] != "电视剧"
                        or "tmdb" not in media_snapshot(resolved)["ids"]):
                    raise ValueError("未识别到整剧身份，请改用 TMDB ID、按名称添加，或只忽略当前季")
                aliases.append(resolved)
            row = self.blacklist_store().add(media, season=season, aliases=aliases)
            return {"code": 0, "message": "已加入黑名单", "item": row}
        except Exception as exc:  # noqa: BLE001 - 持久化失败必须告知前端
            return {"code": 1, "message": str(exc)}

    def api_blacklist_delete(self, request: dict = None):
        body = request if isinstance(request, dict) else {}
        ids = body.get("ids")
        if not isinstance(ids, list) or not ids or not all(isinstance(i, str) for i in ids):
            return {"code": 1, "message": "缺少黑名单 ID 列表"}
        try:
            removed = self.blacklist_store().delete(ids)
            return {"code": 0, "removed": removed, "message": f"已移除 {removed} 条黑名单"}
        except Exception as exc:  # noqa: BLE001
            return {"code": 1, "message": str(exc)}

    def api_subscribes_block(self, request: dict = None):
        """先保存忽略规则再退订；退订失败时保留规则，防止下轮重建。"""
        body = request if isinstance(request, dict) else {}
        ids = body.get("ids")
        if not isinstance(ids, list) or not ids:
            return {"code": 1, "message": "缺少订阅 ID 列表"}
        ok_ids, failed_ids, errors = [], [], []
        for sid in dict.fromkeys(str(sid) for sid in ids):
            with BLACKLIST_LOCK:
                try:
                    result = self.api_blacklist_add({"kind": "subscription", "id": sid,
                                                     "scope": body.get("scope", "all")})
                    if result["code"] != 0:
                        raise ValueError(result["message"])
                    result = self.blacklist_subscribe_manager().delete([int(sid)])
                    if not result["ok"]:
                        raise RuntimeError("黑名单已保存，退订失败，请重试或在宿主中手动退订")
                    ok_ids.append(sid)
                except Exception as exc:  # noqa: BLE001 - 单条失败不掩盖其他条目的结果
                    failed_ids.append(sid)
                    errors.append({"id": sid, "message": str(exc)})
        # 保留输入 ID 的类型，方便前端勾选集合直接更新。
        ok_ids = [sid for sid in ids if str(sid) in ok_ids]
        failed_ids = [sid for sid in ids if str(sid) in failed_ids]
        return {"code": 0, "ok": len(ok_ids), "failed": len(failed_ids),
                "ok_ids": ok_ids, "failed_ids": failed_ids, "errors": errors,
                "message": f"已退订并忽略 {len(ok_ids)} 个" +
                           (f"，{len(failed_ids)} 个失败：{errors[0]['message']}" if errors else "")}
