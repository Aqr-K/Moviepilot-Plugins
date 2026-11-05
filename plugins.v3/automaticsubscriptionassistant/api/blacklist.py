"""黑名单 HTTP 端点；生产仓库由插件入口注入。"""

from ..schemas.blacklist import media_snapshot
from ..services.blacklist import BLACKLIST_LOCK


class BlacklistApiMixin:
    """从服务端已有记录提取身份，前端不必拼接媒体 ID。"""

    def api_blacklist(self):
        rows = self.blacklist_store().list()
        return {"code": 0, "list": rows, "total": len(rows)}

    def api_blacklist_add(self, request: dict | None = None):
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
                media = next(
                    (
                        row
                        for row in self.blacklist_subscribe_manager().list_mine()
                        if str(row["id"]) == str(body.get("id"))
                    ),
                    None,
                )
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
            if (
                scope == "all"
                and snapshot["type"] == "电视剧"
                and "tmdb" not in snapshot["ids"]
                and snapshot["ids"].keys() & {"douban", "bangumi"}
            ):
                # 豆瓣/番组计划往往是一季一个 ID；整剧规则须补充宿主的整剧身份。
                resolved = self.blacklist_resolve_media(media)
                if (
                    not resolved
                    or media_snapshot(resolved)["type"] != "电视剧"
                    or "tmdb" not in media_snapshot(resolved)["ids"]
                ):
                    raise ValueError(
                        "未识别到整剧身份，请改用 TMDB ID、按名称添加，或只忽略当前季"
                    )
                aliases.append(resolved)
            row = self.blacklist_store().add(media, season=season, aliases=aliases)
            return {"code": 0, "message": "已加入黑名单", "item": row}
        except Exception as exc:  # noqa: BLE001 - 持久化失败必须告知前端
            return {"code": 1, "message": str(exc)}

    def api_blacklist_delete(self, request: dict | None = None):
        body = request if isinstance(request, dict) else {}
        ids = body.get("ids")
        if (
            not isinstance(ids, list)
            or not ids
            or not all(isinstance(i, str) for i in ids)
        ):
            return {"code": 1, "message": "缺少黑名单 ID 列表"}
        try:
            removed = self.blacklist_store().delete(ids)
            return {
                "code": 0,
                "removed": removed,
                "message": f"已移除 {removed} 条黑名单",
            }
        except Exception as exc:  # noqa: BLE001
            return {"code": 1, "message": str(exc)}

    def api_subscribes_block(self, request: dict | None = None):
        """先保存忽略规则再退订；退订失败时保留规则，防止下轮重建。"""
        body = request if isinstance(request, dict) else {}
        ids = body.get("ids")
        if not isinstance(ids, list) or not ids:
            return {"code": 1, "message": "缺少订阅 ID 列表"}
        ok_ids, failed_ids, errors = [], [], []
        for sid in dict.fromkeys(str(sid) for sid in ids):
            with BLACKLIST_LOCK:
                try:
                    result = self.api_blacklist_add(
                        {
                            "kind": "subscription",
                            "id": sid,
                            "scope": body.get("scope", "all"),
                        }
                    )
                    if result["code"] != 0:
                        raise ValueError(result["message"])
                    result = self.blacklist_subscribe_manager().delete([int(sid)])
                    if not result["ok"]:
                        raise RuntimeError(
                            "黑名单已保存，退订失败，请重试或在宿主中手动退订"
                        )
                    ok_ids.append(sid)
                except Exception as exc:  # noqa: BLE001 - 单条失败不掩盖其他条目的结果
                    failed_ids.append(sid)
                    errors.append({"id": sid, "message": str(exc)})
        # 保留输入 ID 的类型，方便前端勾选集合直接更新。
        ok_ids = [sid for sid in ids if str(sid) in ok_ids]
        failed_ids = [sid for sid in ids if str(sid) in failed_ids]
        return {
            "code": 0,
            "ok": len(ok_ids),
            "failed": len(failed_ids),
            "ok_ids": ok_ids,
            "failed_ids": failed_ids,
            "errors": errors,
            "message": f"已退订并忽略 {len(ok_ids)} 个"
            + (f"，{len(failed_ids)} 个失败：{errors[0]['message']}" if errors else ""),
        }
