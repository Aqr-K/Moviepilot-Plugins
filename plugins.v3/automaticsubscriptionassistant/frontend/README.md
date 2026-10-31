# 自动订阅助手 v3 前端

本目录是自动订阅助手的 Vue 3 联邦前端，后续仅维护、测试和发布 MoviePilot v3 版本。使用方法见[插件说明](../README.md)，后端边界见[架构文档](../docs/architecture.md)。本文说明 3.2.0 的前端实现，包含黑名单、侧栏入口与仪表盘概览。

## 联邦入口

`vite.config.js` 暴露以下组件，构建入口为 `dist/assets/remoteEntry.js`：

| 名称 | 组件 | 用途 |
| --- | --- | --- |
| `Page` | `src/components/Page.vue` | 历史、订阅管理、黑名单的数据页与分页；默认进入历史 |
| `Config` | `src/components/Config.vue` | 全局与五类来源配置，可切换到数据页 |
| `Dashboard` | `src/components/Dashboard.vue` | 当前订阅/黑名单/历史指标、来源运行状态、结果分布与最近成功记录 |
| `AppPage` | `src/components/AppPage.vue` | 侧栏通用入口，复用 Page，默认进入黑名单 |
| `AppPageBlacklist` | `src/components/AppPageBlacklist.vue` | `nav_key=blacklist` 的专用入口，向 AppPage 透传宿主属性和事件 |

后端侧栏名称取 `self.plugin_name`，显示“自动订阅助手”，使用 `mdi-rss` 订阅图标。宿主只为已启用插件聚合入口，要求 `subscribe` 权限。`nav_key=blacklist` 保留原路由，不因展示名称或图标改变而变化。

专用入口使用独立的 Vue 包装文件，避免将两个联邦入口指向同一文件时产生无法解析的产物引用。

## 共用布局

- `PluginTabs.vue`：历史、管理、黑名单、配置导航；侧栏数据页不显示配置切换标签。
- `MediaCard.vue`：横版海报、状态徽标、元数据与“更多”菜单。列表中明确显示剧集季号，特别篇为 S00。
- `FilterPanel.vue`：筛选与添加表单共用的上置标签、紧凑控件与字段间距；支持搜索、年份范围、选择、单值文本和数字。
- `styles/mediaViews.css`：历史与黑名单共用的工具栏、440px 弹窗、卡片网格、加载骨架和空状态。
- `Page.vue`：统一分页、跳页与移动端每页行数；`useMediaGrid.ts` 测量列数，桌面每页三行，单列使用用户行数设置。
- `BlacklistView.vue`：黑名单筛选、添加与移除；按名称、类型和年份范围筛选，草稿应用后生效。
- `BlacklistDialog.vue`：手动添加、从历史加入、退订并忽略的共用弹窗；只有取消真实订阅时使用危险操作按钮。

黑名单列表从后端读取完整规则，筛选与分页在前端完成；历史列表的筛选、分页与全选身份键查询由后端完成。批量退订或暂停/恢复须保留失败项供重试，不能把部分成功当作全部成功。

## 仪表盘接入

在主程序仪表盘设置中启用“自动订阅助手”（元信息名称为“自动订阅助手 · 订阅概览”）。`Dashboard.vue` 沿用 `overview` 标识，通过宿主注入的 API 请求 `plugin/AutomaticSubscriptionAssistant/dashboard`，默认 300 秒刷新。

历史数量表示当前保留的展示记录，黑名单数量表示规则条数，插件订阅数量按配置用户名读取并包含暂停项。空历史不会隐藏来源或规则指标；近期成功记录最多五条，标题包含季号与剧集组。底部入口指向该插件的侧栏页面。

刷新采用请求完成后调度，在途去重；`allowRefresh=false`、周期变更和卸载时清理计时器。失败时保留最近成功值并提示错误，卸载后不再接收迟到响应。模板支持宿主边框模式及窄卡片，按钮和提示随宿主语言切换。

## 本地预览

在本目录安装锁定依赖后启动：

```bash
yarn install --frozen-lockfile
yarn dev
```

Vite 开发端口默认 `5001`。`src/App.vue` 是开发壳，可切换宽度、语言和主题；`src/dev/mockApi.ts` 提供内存 API。预览数据随刷新重置，不用于验证宿主鉴权、真实订阅、重启持久化或跨来源识别。

## 真实宿主联调

1. 构建联邦产物：`npm run build`。
2. 将当前源码及 `frontend/dist/assets` 安装到 MoviePilot v3 的运行插件目录，或通过宿主本地插件仓安装/同步。
3. 在插件详情页或侧栏“自动订阅助手”打开页面。启用总开关和至少一个有效来源后，宿主才会显示侧栏入口。
4. 前端使用宿主注入的 `api` 调用 `plugin/AutomaticSubscriptionAssistant/...`，由宿主完成认证和静态资源访问授权。

页面依赖宿主 Vue/Vuetify。构建按现有配置共享这些运行时，且仅在联邦构建时剥离重复的 Vuetify 样式；开发壳保留完整样式。切换本地安装产物后，可强制刷新页面清除旧模块缓存。

## 验证与分发

```bash
npm test
npm run build
```

`tests/regressions.test.mjs` 使用实际组件脚本及 Vue 响应式环境，覆盖历史全选响应顺序、管理部分失败、黑名单提交与重试、筛选草稿、共享分页和特别篇显示，以及仪表盘零历史、刷新失败保留数据、在途去重与计时器清理。这些是组件行为测试，不能替代浏览器联调。

浏览器应检查详情与侧栏入口、添加/筛选弹窗的一致性、桌面与窄屏布局，并在测试后移除临时验证规则，保留用户原有数据。

`dist/` 按仓库规则忽略；Release 工作流在发布时构建并打包产物。源码目录本身包含黑名单功能不代表已发布到插件市场。后续只发布 v3。
