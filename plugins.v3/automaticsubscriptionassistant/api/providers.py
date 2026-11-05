"""providers HTTP 端点；使用入口提供的服务，不直接拥有数据库连接。"""

from copy import deepcopy
from datetime import datetime
from typing import Any

from app.sdk.logging import logger

from ..core.config import ProviderConfig
from ..core.i18n import localize_spec
from ..core.provider import ProviderContext
from ..core.registry import registry


class ProvidersApiMixin:
    def api_providers(self, lang: str | None = None) -> dict[str, Any]:
        """返回所有来源的 spec 元描述，供前端动态渲染配置表单（按 lang 本地化标签）。"""
        specs = [provider.get_spec().to_dict() for provider in self._providers]
        return {"providers": [localize_spec(spec, lang) for spec in specs]}

    def api_run(
        self, request: dict | None = None, provider_id: str | None = None
    ) -> dict[str, Any]:
        """触发指定来源在 3 秒后运行一次（provider_id 支持 body 或 query）。"""
        if not self._database_ready:
            return {
                "code": 1,
                "message": "数据库未就绪，请检查数据库状态后重新加载插件",
            }
        pid = provider_id or (
            (request or {}).get("provider_id") if isinstance(request, dict) else None
        )
        if not pid:
            return {"code": 1, "message": "缺少 provider_id"}
        provider = registry.get(pid)
        if provider is None:
            return {"code": 1, "message": f"未知来源: {pid}"}
        self._schedule_once(self.run_provider, provider_id=pid)
        return {
            "code": 0,
            "message": f"{provider.provider_name} 已触发，将在 3 秒后运行",
        }

    def api_test_provider(
        self, request: dict | None = None, provider_id: str | None = None
    ) -> dict[str, Any]:
        """连通性测试：抓取该来源前几条以验证可达，**绝不进入订阅管线、绝不订阅、绝不写历史**。

        服务端防抖：同一来源两次测试的最小间隔 2 秒，短时间高频触发直接拒绝（防止绕过前端疯狂点击）。
        """
        pid = provider_id or (
            (request or {}).get("provider_id") if isinstance(request, dict) else None
        )
        if not pid:
            return {"code": 1, "message": "缺少 provider_id"}
        provider = registry.get(pid)
        if provider is None:
            return {"code": 1, "message": f"未知来源: {pid}"}
        # 防抖：同一来源 2 秒内重复测试直接拒绝。
        now = datetime.now().astimezone()
        with self._test_lock:
            last = self._test_last.get(pid)
            if last is not None and (now - last).total_seconds() < 2.0:
                return {
                    "code": 1,
                    "throttled": True,
                    "message": "操作过于频繁，请稍后再试",
                }
            self._test_last[pid] = now
        spec = provider.get_spec()
        pconf = ProviderConfig(self._settings.provider_raw(pid), spec)
        context = ProviderContext(
            chain=self.chain,
            downloadchain=self._downloadchain,
            subscribechain=self._subscribechain,
            logger=logger,
            event=self._event,
            proxy=bool(pconf.option("proxy")),
            get_data=self.get_data,
            save_data=self.save_data,
        )
        # 连通性测试用「spec 默认值兜底 + 用户已存配置覆盖」的完整 options：
        # 避免未细配的来源（如热门/奈飞的启用开关、类别未落库）被判为「已连通但无条目」。
        test_options = {f.key: f.default for f in (spec.options_schema or [])}
        test_options.update(pconf.options or {})
        # 连通性测试强制关缓存（须盖过用户已存的 use_cache=True）：既不读缓存（真实走网络验证连通、
        # 而非产出旧的缓存条目），也不写缓存（不产生持久化副作用、不污染正常运行的缓存周期）。
        test_options["use_cache"] = False
        try:
            test_options = deepcopy(test_options)
            # 规则聚合必须收集后才产出；探测只请求首条启用规则的少量元数据。
            if 'rules' in test_options:
                enabled = [r for r in test_options['rules'] if r.get('on', True)]
                test_options['rules'] = [{**r, **({'limit':min(int(r.get('limit', 3)), 3)} if pid != 'mikan' else {})} for r in enabled[:1]]
            count = 0
            sample = None
            # 仅消费前几条即 break：验证连通与产出，不遍历全部、不调用任何订阅/历史逻辑。
            for item in provider.fetch(test_options, context):
                count += 1
                if sample is None:
                    sample = getattr(item, "title", None)
                if count >= 3:
                    break
        except Exception as exc:  # noqa: BLE001 - 测试失败即返回失败，不影响插件本体
            logger.warning(
                f"{self.plugin_name}：{spec.provider_name} 连通性测试失败: {exc}"
            )
            return {"code": 0, "ok": False, "message": f"连通失败：{exc}"}
        if count > 0:
            return {
                "code": 0,
                "ok": True,
                "count": count,
                "sample": sample,
                "message": f"连通正常，取到示例：{sample}",
            }
        return {
            "code": 0,
            "ok": False,
            "count": 0,
            "message": "已连通但未取到条目（可能暂无数据或配置为空）",
        }
