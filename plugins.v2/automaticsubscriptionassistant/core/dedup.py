"""已订阅强标识索引：识别前的预去重快速路径。

保守原则：只登记真实订阅与本轮正向终态媒体，只用强标识（tmdbid/doubanid/bangumiid，
剧集按季）判定命中，**无假阳性**。名称回退绝不参与命中，避免同名不同作品误伤（漏订）。

此索引仅是叠加在 ``subscribechain.exists()`` 之上的快速路径：命中即跳过识别；
未命中则照常识别 + exists() 兜底。最坏情况只是「多识别了一条」，绝不会错订/重订/漏订。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Dict, Iterable, Optional

from .models import media_identity

if TYPE_CHECKING:
    from .models import RankMediaItem


def _is_tv(mtype) -> bool:
    """判断媒体类型是否剧集：兼容 MediaType 枚举与中文/英文字符串。"""
    if mtype is None:
        return False
    val = getattr(mtype, "value", mtype)  # 枚举取 .value，字符串原样
    return str(val) in ("电视剧", "tv", "TV")


class SubscribedIndex:
    """强标识键 → 规范媒体身份键 的映射。"""

    def __init__(self) -> None:
        # 键形态：电影 ``m:tmdb:{id}``；剧集 ``tv:tmdb:{id}:*`` 与 ``tv:tmdb:{id}:s{season}``；
        # 通用 ``douban:{id}`` / ``bangumi:{id}``。值为该媒体的规范身份键。
        self._keys: Dict[str, str] = {}

    def add_media(self, tmdbid: Optional[int] = None, doubanid: Optional[str] = None,
                  bangumiid: Optional[int] = None, mtype=None, season: Optional[int] = None,
                  title: str = "", year: Optional[str] = None) -> None:
        """登记一条媒体的全部强标识键。无任何强标识则忽略（名称不入索引）。"""
        if not (tmdbid or doubanid or bangumiid):
            return
        is_tv = _is_tv(mtype)
        canonical = media_identity(tmdb_id=tmdbid, douban_id=doubanid, bangumi_id=bangumiid,
                                   is_tv=is_tv, season=season, title=title, year=year)
        for key in self._strong_keys(tmdbid, doubanid, bangumiid, is_tv, season):
            # 首个登记者定规范身份，保证跨渠道命中回同一条历史记录。
            self._keys.setdefault(key, canonical)

    @staticmethod
    def _strong_keys(tmdbid, doubanid, bangumiid, is_tv: bool, season):
        """产出该媒体应登记的全部强标识键。"""
        keys = []
        if tmdbid:
            if is_tv:
                keys.append(f"tv:tmdb:{tmdbid}:*")
                if season is not None:
                    keys.append(f"tv:tmdb:{tmdbid}:s{season}")
            else:
                keys.append(f"m:tmdb:{tmdbid}")
        if doubanid:
            keys.append(f"douban:{doubanid}")
        if bangumiid:
            keys.append(f"bangumi:{bangumiid}")
        return keys

    def _match_key(self, item: "RankMediaItem") -> Optional[str]:
        """返回条目命中的强标识键（优先 tmdb > douban > bangumi），未命中返回 None。"""
        tid = item.tmdb_id
        if tid:
            if _is_tv(item.type_hint):
                # 剧集：季已知只匹配同季键；季未知匹配任意季键（与 exists(season=None) 一致）。
                if item.season is not None:
                    k = f"tv:tmdb:{tid}:s{item.season}"
                    if k in self._keys:
                        return k
                else:
                    k = f"tv:tmdb:{tid}:*"
                    if k in self._keys:
                        return k
            elif item.type_hint is not None:
                # 电影（类型已知）。类型未知时不做 tmdb 快速路径（保守）。
                k = f"m:tmdb:{tid}"
                if k in self._keys:
                    return k
        if item.douban_id:
            k = f"douban:{item.douban_id}"
            if k in self._keys:
                return k
        if item.bangumi_id:
            k = f"bangumi:{item.bangumi_id}"
            if k in self._keys:
                return k
        return None

    def contains(self, item: "RankMediaItem") -> bool:
        """条目是否被强标识命中（已订阅 / 本轮已处理）。"""
        return self._match_key(item) is not None

    def identity_for(self, item: "RankMediaItem") -> Optional[str]:
        """命中时返回其规范媒体身份键（用于跨渠道合并历史记录），否则 None。"""
        key = self._match_key(item)
        return self._keys.get(key) if key else None


def build_subscribed_index(subscriptions: Iterable) -> SubscribedIndex:
    """从订阅对象（鸭子类型 ``.tmdbid/.doubanid/.bangumiid/.type/.season``）预加载索引。

    单条异常不影响整体构建（尽力登记，兜底空索引仍安全，交由 exists() 兜底）。
    """
    index = SubscribedIndex()
    for sub in subscriptions or []:
        try:
            index.add_media(
                tmdbid=getattr(sub, "tmdbid", None),
                doubanid=getattr(sub, "doubanid", None),
                bangumiid=getattr(sub, "bangumiid", None),
                mtype=getattr(sub, "type", None),
                season=getattr(sub, "season", None),
            )
        except Exception:  # noqa: BLE001 - 单条订阅解析失败不应阻断整体预加载
            continue
    return index
