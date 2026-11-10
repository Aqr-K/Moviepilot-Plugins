"""独立来源规则：有界校验、逐规则请求与跨规则候选合并。"""

from __future__ import annotations

import json
import math
from abc import abstractmethod
from collections.abc import Iterator
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from ..schemas import FieldSpec, ProviderSpec

if TYPE_CHECKING:
    from ..schemas import RankMediaItem
    from .provider import ProviderContext
from .provider import RankProvider
from .subscription_policy import normalize_subscription_policy


def active_field(field: FieldSpec, values: dict[str, Any]) -> bool:
    return all(
        values.get(key) in allowed
        for key, allowed in (field.visible_when or {}).items()
    )


def normalize_rules(field: FieldSpec, raw: Any) -> list[dict[str, Any]]:
    """显式空列表停用；非法规则在任何网络请求前拒绝，不替换为其它榜单。"""
    if not isinstance(raw, list) or len(raw) > 100:
        raise ValueError("规则必须为列表，最多 100 条")
    fields = field.fields or []
    result, signatures, ids = [], set(), set()
    for entry in raw:
        if not isinstance(entry, dict) or not isinstance(entry.get("on", True), bool):
            raise TypeError("规则及启用状态格式无效")
        values = {f.key: deepcopy(entry.get(f.key, f.default)) for f in fields}
        values = {
            k: v
            for k, v in values.items()
            if active_field(next(f for f in fields if f.key == k), values)
        }
        for spec in fields:
            if spec.key not in values:
                continue
            value = values[spec.key]
            options = spec.options or []
            if spec.options_by:
                options = spec.options_by["values"].get(
                    values.get(spec.options_by["key"]), []
                )
            allowed = [option["value"] for option in options]
            if spec.kind in {"number", "float"}:
                try:
                    n = float(value)
                except (ValueError, TypeError):
                    raise ValueError(f"{spec.label}必须为数字") from None
                if (
                    isinstance(value, bool)
                    or not math.isfinite(n)
                    or (spec.kind == "number" and not n.is_integer())
                ):
                    raise ValueError(f"{spec.label}格式无效")
                if (spec.minimum is not None and n < spec.minimum) or (
                    spec.maximum is not None and n > spec.maximum
                ):
                    raise ValueError(f"{spec.label}超出允许范围")
                values[spec.key] = int(n) if spec.kind == "number" else n
            elif spec.kind == "multi-select":
                if not isinstance(value, list) or any(v not in allowed for v in value):
                    raise ValueError(f"{spec.label}含不支持的选项")
                values[spec.key] = sorted(set(value), key=str)
            elif spec.kind == "select":
                if value not in allowed:
                    raise ValueError(f"{spec.label}含不支持的选项")
            elif not isinstance(value, str) or len(value) > 2048:
                raise ValueError(f"{spec.label}格式无效")
            else:
                values[spec.key] = value.strip()
            if spec.required and values[spec.key] in (None, "", []):
                raise ValueError(f"请填写{spec.label}")
        if values.get("chart") == "custom":
            url = urlparse(values.get("url", ""))
            if url.scheme not in {"http", "https"} or not url.netloc:
                raise ValueError("RSS 地址必须为完整 HTTP/HTTPS 地址")
        signature = json.dumps(values, ensure_ascii=False, sort_keys=True)
        if signature in signatures:
            raise ValueError("存在重复规则，请编辑已有规则")
        signatures.add(signature)
        name = entry.get("name", "")
        if not isinstance(name, str) or len(name.strip()) > 80:
            raise ValueError("规则名称最多 80 个字符")
        identity = entry.get("id") or sha256(signature.encode()).hexdigest()[:16]
        if not isinstance(identity, str) or len(identity) > 80 or identity in ids:
            raise ValueError("规则标识无效或重复")
        ids.add(identity)
        result.append(
            {
                **values,
                **({"subscription": normalize_subscription_policy(entry["subscription"])} if "subscription" in entry else {}),
                "id": identity,
                "name": name.strip() or field.label,
                "on": entry.get("on", True),
            }
        )
    return result


def quarter(offset=0):
    now = datetime.now(timezone.utc)
    year, season = divmod(now.year * 4 + (now.month - 1) // 3 + offset, 4)
    return year, season


def merge_jobs(jobs, context):
    """完整收集命中规则再落地；单规则失败仍保留其它规则结果并向 runner 报告失败。"""
    items, errors = {}, []
    for match, fetch in jobs:
        if context is not None and context.event is not None and context.event.is_set():
            return
        try:
            for original in fetch():
                if (
                    context is not None
                    and context.event is not None
                    and context.event.is_set()
                ):
                    return
                item = deepcopy(original)  # 缓存中的对象不能被本轮规则名/过滤条件污染
                key = item.candidate_key()
                hit = {**deepcopy(match), "source": deepcopy(item.source_meta)}
                if key not in items:
                    item.source_meta = {**item.source_meta, "matches": []}
                    items[key] = item
                matches = items[key].source_meta["matches"]
                if not any(
                    m.get("id") == hit.get("id")
                    and m.get("provider") == hit.get("provider")
                    for m in matches
                ):
                    matches.append(hit)
        except Exception as exc:  # noqa: BLE001 - 保留部分结果，结束时报告每个失败规则
            errors.append((match["name"], exc))
    yield from items.values()
    if len(errors) == 1:
        raise errors[0][1]
    if errors:
        raise RuntimeError("；".join(f"{name}: {exc}" for name, exc in errors))


class RuleRankProvider(RankProvider):
    """来源保留单次请求实现，外层统一管理卡片配置与合并。"""

    @abstractmethod
    def _source_spec(self) -> ProviderSpec:
        """声明来源共享字段及调度信息。"""
        raise NotImplementedError

    @abstractmethod
    def _fetch_options(
        self, options: dict, context: ProviderContext
    ) -> Iterator[RankMediaItem]:
        """执行一次已经解析的榜单请求。"""
        raise NotImplementedError

    def get_spec(self):
        from ..providers.rule_specs import definition

        fields, defaults, presets, shared = definition(self.provider_id)
        spec = self._source_spec()
        spec.options_schema = [
            FieldSpec(
                "rules",
                "榜单规则",
                "rule-list",
                defaults,
                fields=fields,
                presets=presets,
                hint="每张卡片独立设置条件；全部移除后停止监听。",
            )
        ] + [f for f in spec.options_schema if f.key in shared]
        spec.filters_schema = []
        return spec

    def rules(self, options):
        spec = self.get_spec()
        field = spec.options_schema[0]
        options = options or {}
        if "rules" not in options and set(options) - {
            f.key for f in spec.options_schema
        }:
            raise ValueError("来源规则配置已更新，请重新设置并保存规则卡片")
        return normalize_rules(field, options.get("rules", field.default))

    def validate_options(self, options):
        self.rules(options)

    def has_listening(self, options):
        if self.provider_id == "popular":
            from app.sdk.config import settings

            if not settings.SUBSCRIBE_STATISTIC_SHARE:
                return False
        return any(r["on"] and r.get("limit", 1) > 0 for r in self.rules(options))

    def fetch(self, options, context):
        options = options or {}
        self.validate_options(options)
        jobs = []
        payload_cache = {}

        def fetch_rule(values):
            if self.provider_id == "spotify":
                from ..providers.spotify import (
                    ENDPOINT,
                    SpotifyRankProvider,
                    request_json,
                )

                assert isinstance(self, SpotifyRankProvider)

                if "response" not in payload_cache:
                    payload_cache["response"] = request_json(ENDPOINT, context)
                yield from SpotifyRankProvider._fetch_options(
                    self, values, context, payload_cache["response"]
                )
            elif self.provider_id == "popular":
                from itertools import islice

                yield from islice(self._fetch_options(values, context), values["limit"])
            else:
                yield from self._fetch_options(values, context)

        for entry in self.rules(options):
            if not entry["on"] or entry.get("limit", 1) == 0:
                continue
            values = self._rule_options(entry, options)
            filters = {
                key: entry[key] for key in ("vote", "media_type") if key in entry
            }
            if "min_year" in entry:
                filters["year"] = entry["min_year"]
            match = {
                "provider": self.provider_id,
                "id": entry["id"],
                "name": entry["name"],
                "filters": filters,
                **({"subscription": deepcopy(entry["subscription"])} if "subscription" in entry else {}),
            }
            jobs.append((match, lambda values=values: fetch_rule(values)))
        yield from merge_jobs(jobs, context)

    def _rule_options(self, rule, shared):
        """转换为单次请求参数；不读取旧的用户规则字段。"""
        options = {**shared, **rule}
        pid = self.provider_id
        if pid == "anilist":
            return options
        if pid == "mikan":
            if rule["time"] != "fixed":
                year, season = quarter(
                    {"current": 0, "previous": -1, "next": 1}[rule["time"]]
                )
                options.update(year=year, season=["冬", "春", "夏", "秋"][season])
        elif pid == "popular":
            cat = rule["category"]
            options.update(movie_enabled=cat == "movie", tv_enabled=cat == "tv")
            for old, new in [
                ("genres", "genres"),
                ("page_cnt", "limit"),
                ("min_rating", "min_rating"),
                ("popularity", "popularity"),
            ]:
                options[f"{cat}_{old}"] = rule[new]
        elif pid == "douban":
            options.update(
                ranks=[] if rule["chart"] == "custom" else [rule["chart"]],
                rss_addrs=rule.get("url", ""),
            )
        elif pid == "applemusic" or pid == "maoyan":
            return options
        elif pid == "netflix":
            from ..providers.netflix import DATASET_WEEKLY

            country = rule["dataset"] == "country"
            options.update(
                {
                    "global": not country,
                    "global_dataset": DATASET_WEEKLY
                    if rule["dataset"] != "most-popular"
                    else "most-popular",
                    "global_media_types": [] if country else rule["categories"],
                    "country_selections": {rule["country"]: rule["categories"]}
                    if country
                    else {},
                }
            )
        else:
            options["charts"] = [rule["chart"]]
        return options
