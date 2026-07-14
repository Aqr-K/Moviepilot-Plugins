<template>
  <section ref="layoutRef" class="asa-config" :class="{ 'asa-config--docked': changedCount > 0 }">
    <!-- 粘性头部 -->
    <header class="asa-cfg-head">
      <div class="asa-cfg-head__brand">
        <div class="asa-cfg-head__logo"><v-icon icon="mdi-rss" size="20" /></div>
        <div class="asa-cfg-head__identity">
          <div class="asa-cfg-head__crumbs">
            <span>MoviePilot</span>
            <v-icon icon="mdi-chevron-right" size="13" />
            <span>{{ t('plugin') }}</span>
          </div>
          <h1 class="asa-cfg-head__title">{{ t('title') }}</h1>
        </div>
      </div>
      <div class="asa-cfg-head__actions">
        <span v-if="changedCount > 0" class="asa-cfg-head__dirty">
          <v-icon color="warning" icon="mdi-circle" size="8" />
          {{ t('changes', { n: changedCount }) }}
        </span>
        <v-btn
          v-if="changedCount > 0"
          class="asa-cfg-head__save"
          color="primary"
          :loading="saving"
          variant="flat"
          @click="saveConfig"
        >
          <v-icon icon="mdi-content-save-outline" start />
          {{ t('save') }}
        </v-btn>
        <!-- 移动端：概览收纳切换（桌面端概览常驻右列，由容器查询隐藏，无需 JS 判定，兼容宿主弹窗渲染） -->
        <v-btn
          class="asa-cfg-head__overview"
          :aria-label="t('overview')"
          icon="mdi-chart-box-outline"
          size="small"
          variant="text"
          @click="asideOpen = true"
        />
        <v-btn :aria-label="t('close')" icon="mdi-close" size="small" variant="text" @click="emit('close')" />
      </div>
    </header>

    <PluginTabs active="config" :tabs="tabDefs" @select="onTab" />

    <v-alert v-if="error" class="ma-3 mb-0" density="compact" type="warning" variant="tonal">{{ error }}</v-alert>

    <div class="asa-cfg-body">
      <div :class="['asa-cfg-layout', mobileView === 'nav' ? 'asa-cfg-layout--mnav' : 'asa-cfg-layout--mcontent']">
        <!-- 左侧分组导航（移动端禁用「仅图标」折叠，始终完整显示） -->
        <nav :class="['asa-nav', { 'asa-nav--collapsed': navCollapsed && !isNarrow }]" :aria-label="t('settingsGroups')">
          <div class="asa-nav__top">
            <span class="asa-nav__heading">{{ t('settingsGroups') }}</span>
            <button
              class="asa-nav__collapse"
              type="button"
              :aria-label="navCollapsed ? t('expand') : t('collapse')"
              @click="toggleNav"
            >
              <v-icon :icon="navCollapsed ? 'mdi-chevron-double-right' : 'mdi-chevron-double-left'" size="18" />
              <v-tooltip activator="parent" location="right" :text="navCollapsed ? t('expand') : t('collapse')" />
            </button>
          </div>
          <div class="asa-nav__list">
            <button
              v-for="g in groups"
              :key="g.key"
              :class="['asa-nav__item', { 'asa-nav__item--active': activeGroup === g.key }]"
              type="button"
              @click="selectGroup(g.key)"
            >
              <provider-logo :provider="g.key" :fallback="g.icon" :size="20" />
              <span class="asa-nav__label">{{ g.name }}</span>
              <span
                v-if="g.key !== GLOBAL_KEY"
                :class="['asa-nav__dot', { 'asa-nav__dot--on': isProviderEnabled(g.key) }]"
              ></span>
              <v-tooltip v-if="navCollapsed" activator="parent" location="right" :text="g.name" />
            </button>
          </div>

          <!-- 分割线：功能栏（分组列表）与「插件帮助」分区 -->
          <div class="asa-nav__sep" aria-hidden="true"></div>
          <!-- 插件帮助：格式布局与分组项（如「全局设置」）一致，始终位于最后一个榜单下方 -->
          <a
            class="asa-nav__item asa-nav__help"
            :href="HELP_URL"
            target="_blank"
            rel="noopener noreferrer"
          >
            <v-icon class="asa-nav__help-ico" icon="mdi-help-circle-outline" size="20" />
            <span class="asa-nav__label">{{ t('help') }}</span>
            <v-tooltip v-if="navCollapsed" activator="parent" location="right" :text="t('help')" />
          </a>
        </nav>

        <!-- 中间字段区 -->
        <main class="asa-surface">
          <!-- 移动端：返回功能栏 -->
          <button class="asa-mobile-back" type="button" @click="mobileView = 'nav'">
            <v-icon icon="mdi-arrow-left" size="18" />
            <span>{{ t('back') }}</span>
          </button>
          <v-skeleton-loader v-if="loading" type="article, article" />

          <!-- 全局设置 -->
          <template v-else-if="activeGroup === GLOBAL_KEY">
            <div class="asa-surface__heading">
              <v-icon color="primary" icon="mdi-tune-variant" size="22" />
              <div>
                <h2>{{ t('globalHeading') }}</h2>
                <p>{{ t('globalDesc') }}</p>
              </div>
            </div>
            <section v-for="(sec, i) in globalSections" :key="sec.title" class="asa-section">
              <h3>{{ i + 1 }}. {{ sec.title }}</h3>
              <div class="asa-section__rows">
                <div v-for="field in sec.fields" :key="field.key" :class="rowClass(field)">
                  <div class="asa-row__copy">
                    <div class="asa-row__label">{{ field.label }}</div>
                    <p v-if="field.hint">{{ field.hint }}</p>
                  </div>
                  <div class="asa-row__control">
                    <dynamic-field :field="field" v-model="config.global[field.key]" />
                  </div>
                </div>
              </div>
            </section>
          </template>

          <!-- 来源设置 -->
          <template v-else-if="activeSpec">
            <div class="asa-surface__heading">
              <provider-logo :provider="activeGroup" :fallback="groupIcon(activeGroup)" :size="24" />
              <div>
                <h2>{{ activeSpec.provider_name || activeGroup }}</h2>
                <p>{{ isProviderEnabled(activeGroup) ? t('provEnabled') : t('provDisabled') }}</p>
              </div>
            </div>

            <!-- 来源级告示（如某能力停更下线） -->
            <v-alert
              v-if="activeSpec.notice"
              class="mb-3"
              density="compact"
              type="warning"
              variant="tonal"
            >{{ activeSpec.notice }}</v-alert>

            <!-- 来源开关 + 定时 -->
            <section class="asa-section">
              <h3>1. {{ t('secSourceSchedule') }}</h3>
              <div class="asa-section__rows">
                <div class="asa-row asa-row--switch">
                  <div class="asa-row__copy">
                    <div class="asa-row__label">{{ t('enableSource') }}</div>
                    <p>{{ t('enableSourceHint') }}</p>
                  </div>
                  <div class="asa-row__control">
                    <v-switch v-model="config.providers[activeGroup].enabled" color="primary" density="compact" hide-details inset />
                  </div>
                </div>
                <div class="asa-row">
                  <div class="asa-row__copy">
                    <div class="asa-row__label">{{ t('cronLabel') }}</div>
                    <p>{{ t('cronHint') }}</p>
                  </div>
                  <div class="asa-row__control">
                    <v-text-field
                      v-model="config.providers[activeGroup].cron"
                      class="asa-control"
                      density="compact"
                      hide-details
                      :placeholder="activeSpec.default_cron || '0 8 * * *'"
                      variant="outlined"
                    />
                  </div>
                </div>
              </div>
            </section>

            <!-- 抓取选项 -->
            <section v-if="normalOptions(activeSpec).length" class="asa-section">
              <h3>2. {{ t('secOptions') }}</h3>
              <div class="asa-section__rows">
                <div v-for="field in normalOptions(activeSpec)" :key="field.key" :class="rowClass(field)">
                  <div class="asa-row__copy">
                    <div class="asa-row__label">{{ field.label }}</div>
                    <p v-if="field.hint">{{ field.hint }}</p>
                  </div>
                  <div class="asa-row__control">
                    <dynamic-field :field="field" v-model="config.providers[activeGroup].options[field.key]" />
                  </div>
                </div>
              </div>
            </section>

            <!-- 过滤条件 -->
            <section v-if="normalFilters(activeSpec).length" class="asa-section">
              <h3>{{ normalOptions(activeSpec).length ? 3 : 2 }}. {{ t('secFilters') }}</h3>
              <div class="asa-section__rows">
                <div v-for="field in normalFilters(activeSpec)" :key="field.key" :class="rowClass(field)">
                  <div class="asa-row__copy">
                    <div class="asa-row__label">{{ field.label }}</div>
                    <p v-if="field.hint">{{ field.hint }}</p>
                  </div>
                  <div class="asa-row__control">
                    <dynamic-field :field="field" v-model="config.providers[activeGroup].filters[field.key]" />
                  </div>
                </div>
              </div>
            </section>

            <!-- 高级选项 -->
            <section v-if="hasAdvanced(activeSpec)" class="asa-section asa-section--advanced">
              <button class="asa-advanced-toggle" type="button" @click="toggleAdvanced(activeGroup)">
                <v-icon :icon="showAdvanced[activeGroup] ? 'mdi-chevron-down' : 'mdi-chevron-right'" size="20" />
                {{ t('advanced') }}
                <span class="asa-advanced-toggle__hint">{{ t('advancedHint') }}</span>
              </button>
              <v-expand-transition>
                <div v-show="showAdvanced[activeGroup]" class="asa-section__rows">
                  <div v-for="field in advancedOptions(activeSpec)" :key="field.key" :class="rowClass(field)">
                    <div class="asa-row__copy">
                      <div class="asa-row__label">{{ field.label }}</div>
                      <p v-if="field.hint">{{ field.hint }}</p>
                    </div>
                    <div class="asa-row__control">
                      <dynamic-field :field="field" v-model="config.providers[activeGroup].options[field.key]" />
                    </div>
                  </div>
                  <div v-for="field in advancedFilters(activeSpec)" :key="field.key" :class="rowClass(field)">
                    <div class="asa-row__copy">
                      <div class="asa-row__label">{{ field.label }}</div>
                      <p v-if="field.hint">{{ field.hint }}</p>
                    </div>
                    <div class="asa-row__control">
                      <dynamic-field :field="field" v-model="config.providers[activeGroup].filters[field.key]" />
                    </div>
                  </div>
                </div>
              </v-expand-transition>
            </section>

            <!-- 立即运行 -->
            <div class="asa-run">
              <transition name="asa-fade">
                <span
                  v-if="runMsg.pid === activeGroup && runMsg.text"
                  :class="['asa-run__msg', runMsg.ok ? 'asa-run__msg--ok' : 'asa-run__msg--err']"
                >
                  <v-icon :icon="runMsg.ok ? 'mdi-check-circle-outline' : 'mdi-alert-circle-outline'" size="15" />
                  {{ runMsg.text }}
                </span>
              </transition>
              <v-spacer />
              <v-btn
                class="asa-run__test"
                :disabled="running[activeGroup]"
                :loading="testing[activeGroup]"
                size="small"
                variant="text"
                @click="testProvider(activeGroup)"
              >
                <v-icon icon="mdi-lan-connect" start />
                {{ t('testConn') }}
              </v-btn>
              <v-btn color="primary" :disabled="testing[activeGroup]" :loading="running[activeGroup]" size="small" variant="tonal" @click="runProvider(activeGroup)">
                <v-icon icon="mdi-play" start />
                {{ t('runNow') }}
              </v-btn>
            </div>
          </template>
        </main>

        <!-- 右侧概览（桌面端常驻右列；移动端为右侧可收纳抽屉，就地 fixed + 容器查询控制，兼容宿主弹窗层级） -->
        <aside class="asa-aside" :class="{ 'asa-aside--open': asideOpen }">
          <button class="asa-aside__close" type="button" :aria-label="t('close')" @click="asideOpen = false">
            <v-icon icon="mdi-close" size="18" />
          </button>
          <!-- 处理中：实时展示运行中的来源与已处理条数（打开即可感知任务进度） -->
          <div v-if="runState.length" class="asa-running">
            <div class="asa-running__title">
              <v-progress-circular color="primary" indeterminate size="15" width="2" />
              <span>{{ t('processing') }}</span>
            </div>
            <div v-for="r in runState" :key="r.provider_id" class="asa-running__row">
              <provider-logo :provider="r.provider_id" fallback="mdi-rss" :size="16" />
              <span class="asa-running__name">{{ r.name }}</span>
              <strong>{{ t('procN', { n: r.processed }) }}</strong>
            </div>
          </div>
          <div class="asa-aside__title">
            <v-icon color="primary" icon="mdi-chart-box-outline" size="19" />
            <h3>{{ t('overview') }}</h3>
          </div>
          <ul class="asa-aside__list">
            <li>
              <v-icon icon="mdi-power-plug-outline" size="17" />
              <span>{{ t('ovSources') }}</span>
              <strong>{{ enabledCount }} / {{ providerSpecs.length }}</strong>
            </li>
            <li>
              <v-icon icon="mdi-bell-outline" size="17" />
              <span>{{ t('ovNotify') }}</span>
              <strong>{{ config.global.notify ? t('on') : t('off') }}</strong>
            </li>
            <li>
              <v-icon icon="mdi-database-check-outline" size="17" />
              <span>{{ t('ovExistOk') }}</span>
              <strong>{{ config.global.exist_ok ? t('on') : t('off') }}</strong>
            </li>
          </ul>
          <!-- 运行概览：订阅历史粗略统计 -->
          <div class="asa-aside__title asa-aside__title--sub">
            <v-icon color="primary" icon="mdi-history" size="18" />
            <h3>{{ t('runtimeTitle') }}</h3>
          </div>
          <div v-if="summaryState === 'loading'" class="asa-runtime__state">{{ t('rtLoading') }}</div>
          <template v-else-if="summaryState === 'available' && totalHandled > 0">
            <div class="asa-runtime__total">
              <span>{{ t('rtTotal') }}</span><strong>{{ totalHandled }}</strong>
            </div>
            <div class="asa-runtime__grid">
              <div v-for="r in overviewRows" :key="r.key" class="asa-runtime__cell">
                <v-icon :color="r.color" :icon="r.icon" size="16" />
                <span>{{ t('rt.' + r.key) }}</span>
                <strong>{{ r.n }}</strong>
              </div>
            </div>
          </template>
          <div v-else class="asa-runtime__state">{{ t('rtEmpty') }}</div>
        </aside>

        <!-- 移动端概览抽屉遮罩（点击空白处收起） -->
        <transition name="asa-fade">
          <div v-if="asideOpen" class="asa-aside-scrim" @click="asideOpen = false"></div>
        </transition>
      </div>
    </div>

    <!-- 窄屏底部保存条：就地 sticky 固定于底部（容器查询控制显示）；独占一行、配置内容区预留底部空间不遮挡配置项。 -->
    <transition name="asa-dock">
      <div v-if="changedCount > 0" class="asa-mobile-dock">
        <span class="asa-mobile-dock__state">
          <v-icon color="warning" icon="mdi-circle" size="8" />
          {{ t('unsaved', { n: changedCount }) }}
        </span>
        <v-spacer />
        <v-btn color="primary" :loading="saving" variant="flat" @click="saveConfig">
          <v-icon icon="mdi-content-save-outline" start />
          {{ t('save') }}
        </v-btn>
      </div>
    </transition>
  </section>
</template>

<script setup>
import { computed, getCurrentInstance, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import DynamicField from './DynamicField.vue'
import ProviderLogo from './ProviderLogo.vue'
import PluginTabs from './PluginTabs.vue'

const HELP_URL = 'https://github.com/Aqr-K/MoviePilot-Plugins/blob/main/plugins.v2/automaticsubscriptionassistant/README.md'

const props = defineProps({
  initialConfig: { type: Object, default: () => ({}) },
  api: { type: Object, default: () => ({}) },
})
const emit = defineEmits(['save', 'close', 'switch', 'layout'])
emit('layout', { maxWidth: '72rem' })

const PLUGIN = 'plugin/AutomaticSubscriptionAssistant'
const GLOBAL_KEY = '__global__'

// --- i18n（内联，保持联邦块自包含）---
const MSG = {
  'zh-CN': {
    plugin: '插件', title: '自动订阅助手', changes: '{n} 项改动', save: '保存', close: '关闭',
    settingsGroups: '设置分组', globalHeading: '全局设置', globalDesc: '插件总开关、通知与订阅归属，作用于所有来源',
    secRunning: '运行', secSubscription: '订阅', secOneTime: '一次性维护',
    'g.enabled.label': '启用插件', 'g.enabled.hint': '总开关，关闭后所有定时任务停止',
    'g.notify.label': '运行通知', 'g.notify.hint': '每次运行后发送消息通知',
    'g.username.label': '订阅用户名', 'g.username.hint': '订阅记录归属的用户名',
    'g.exist_ok.label': '媒体库已存在仍订阅', 'g.exist_ok.hint': '媒体库已有资源时仍允许添加订阅',
    'g.onlyonce.label': '保存后立即运行一次', 'g.onlyonce.hint': '保存后运行所有启用来源一次，随后自动复位',
    'g.clear.label': '清空历史记录', 'g.clear.hint': '保存后清空全部订阅历史，随后自动复位',
    provEnabled: '已启用 · 按下方定时规则自动运行', provDisabled: '未启用 · 打开开关后加入定时调度',
    secSourceSchedule: '来源与调度', enableSource: '启用该来源', enableSourceHint: '关闭后不为该来源注册定时任务',
    cronLabel: '定时规则', cronHint: '五位 cron 表达式，缺省取来源默认值',
    secOptions: '抓取选项', secFilters: '过滤条件', advanced: '高级选项', advancedHint: '默认隐藏，谨慎修改',
    runNow: '立即运行一次', runTriggered: '已触发，将在 3 秒后运行', runFailed: '触发失败：', apiUnavailable: 'API 不可用',
    testConn: '连通性测试', testOk: '连通正常', testFail: '连通失败：', throttled: '操作过于频繁，请稍后再试',
    overview: '概览', ovSources: '启用来源', ovNotify: '运行通知', ovExistOk: '已存在仍订阅', on: '开', off: '关',
    navHistory: '订阅历史', navManage: '订阅管理', navConfig: '订阅配置',
    viewHistory: '查看订阅历史', unsaved: '{n} 项未保存', providersError: '获取来源列表失败，已按现有配置渲染：',
    help: '插件帮助', collapse: '收起侧栏', expand: '展开侧栏', runtimeTitle: '运行概览', back: '返回',
    processing: '处理中', procN: '已处理 {n} 条',
    rtTotal: '累计处理', rtLoading: '统计加载中…', rtEmpty: '暂无运行记录',
    'rt.subscribed': '已订阅', 'rt.media_exists': '已存在', 'rt.subscription_exists': '已订阅过', 'rt.filtered': '已过滤',
  },
  'zh-TW': {
    plugin: '外掛', title: '自動訂閱助手', changes: '{n} 項變更', save: '儲存', close: '關閉',
    settingsGroups: '設定分組', globalHeading: '全域設定', globalDesc: '外掛總開關、通知與訂閱歸屬，作用於所有來源',
    secRunning: '執行', secSubscription: '訂閱', secOneTime: '一次性維護',
    'g.enabled.label': '啟用外掛', 'g.enabled.hint': '總開關，關閉後所有定時任務停止',
    'g.notify.label': '執行通知', 'g.notify.hint': '每次執行後傳送訊息通知',
    'g.username.label': '訂閱使用者名稱', 'g.username.hint': '訂閱記錄歸屬的使用者名稱',
    'g.exist_ok.label': '媒體庫已存在仍訂閱', 'g.exist_ok.hint': '媒體庫已有資源時仍允許新增訂閱',
    'g.onlyonce.label': '儲存後立即執行一次', 'g.onlyonce.hint': '儲存後執行所有啟用來源一次，隨後自動復位',
    'g.clear.label': '清空歷史記錄', 'g.clear.hint': '儲存後清空全部訂閱歷史，隨後自動復位',
    provEnabled: '已啟用 · 按下方定時規則自動執行', provDisabled: '未啟用 · 開啟開關後加入定時排程',
    secSourceSchedule: '來源與排程', enableSource: '啟用此來源', enableSourceHint: '關閉後不為此來源註冊定時任務',
    cronLabel: '定時規則', cronHint: '五位 cron 運算式，缺省取來源預設值',
    secOptions: '抓取選項', secFilters: '過濾條件', advanced: '進階選項', advancedHint: '預設隱藏，謹慎修改',
    runNow: '立即執行一次', runTriggered: '已觸發，將在 3 秒後執行', runFailed: '觸發失敗：', apiUnavailable: 'API 不可用',
    testConn: '連通性測試', testOk: '連通正常', testFail: '連通失敗：', throttled: '操作過於頻繁，請稍後再試',
    overview: '概覽', ovSources: '啟用來源', ovNotify: '執行通知', ovExistOk: '已存在仍訂閱', on: '開', off: '關',
    navHistory: '訂閱歷史', navManage: '訂閱管理', navConfig: '訂閱設定',
    viewHistory: '檢視訂閱歷史', unsaved: '{n} 項未儲存', providersError: '取得來源列表失敗，已按現有設定渲染：',
    help: '外掛說明', collapse: '收合側欄', expand: '展開側欄', runtimeTitle: '執行概覽', back: '返回',
    processing: '處理中', procN: '已處理 {n} 筆',
    rtTotal: '累計處理', rtLoading: '統計載入中…', rtEmpty: '暫無執行記錄',
    'rt.subscribed': '已訂閱', 'rt.media_exists': '已存在', 'rt.subscription_exists': '已訂閱過', 'rt.filtered': '已過濾',
  },
  'en-US': {
    plugin: 'Plugin', title: 'Auto Subscribe', changes: '{n} changed', save: 'Save', close: 'Close',
    settingsGroups: 'Settings', globalHeading: 'Global settings', globalDesc: 'Master switch, notifications and subscription owner; applies to all sources',
    secRunning: 'Running', secSubscription: 'Subscription', secOneTime: 'One-time',
    'g.enabled.label': 'Enable plugin', 'g.enabled.hint': 'Master switch; off stops all scheduled tasks',
    'g.notify.label': 'Run notifications', 'g.notify.hint': 'Send a message after each run',
    'g.username.label': 'Subscription user', 'g.username.hint': 'User the subscription records belong to',
    'g.exist_ok.label': 'Subscribe even if in library', 'g.exist_ok.hint': 'Allow adding subscriptions even when already in the library',
    'g.onlyonce.label': 'Run once after saving', 'g.onlyonce.hint': 'Run all enabled sources once after saving, then auto-reset',
    'g.clear.label': 'Clear history', 'g.clear.hint': 'Clear all subscription history after saving, then auto-reset',
    provEnabled: 'Enabled · runs automatically on the schedule below', provDisabled: 'Disabled · turn on to add to the scheduler',
    secSourceSchedule: 'Source & schedule', enableSource: 'Enable this source', enableSourceHint: 'Off: no scheduled task is registered for this source',
    cronLabel: 'Schedule', cronHint: 'Five-field cron expression; empty uses the source default',
    secOptions: 'Fetch options', secFilters: 'Filters', advanced: 'Advanced', advancedHint: 'Hidden by default; edit with care',
    runNow: 'Run once now', runTriggered: 'Triggered; will run in 3s', runFailed: 'Trigger failed: ', apiUnavailable: 'API unavailable',
    testConn: 'Test connection', testOk: 'Connected', testFail: 'Connection failed: ', throttled: 'Too frequent, please retry later',
    overview: 'Overview', ovSources: 'Enabled sources', ovNotify: 'Notifications', ovExistOk: 'Subscribe if exists', on: 'On', off: 'Off',
    navHistory: 'History', navManage: 'Manage', navConfig: 'Settings',
    viewHistory: 'View history', unsaved: '{n} unsaved', providersError: 'Failed to load sources; rendered from current config: ',
    help: 'Plugin help', collapse: 'Collapse', expand: 'Expand', runtimeTitle: 'Run overview', back: 'Back',
    processing: 'Processing', procN: '{n} processed',
    rtTotal: 'Processed', rtLoading: 'Loading stats…', rtEmpty: 'No runs yet',
    'rt.subscribed': 'Subscribed', 'rt.media_exists': 'In library', 'rt.subscription_exists': 'Already subscribed', 'rt.filtered': 'Filtered',
  },
}
const inst = getCurrentInstance()
const locale = computed(() => normLocale(inst?.appContext?.config?.globalProperties?.$i18n?.locale))
function normLocale(src) {
  const v = src && typeof src === 'object' && 'value' in src ? src.value : src
  const s = String(v || '').toLowerCase()
  if (s.startsWith('en')) return 'en-US'
  if (s.includes('tw') || s.includes('hant') || s.includes('hk')) return 'zh-TW'
  return 'zh-CN'
}
function t(k, p) {
  let s = (MSG[locale.value] || MSG['zh-CN'])[k] ?? MSG['zh-CN'][k] ?? k
  if (p) for (const key in p) s = s.replaceAll(`{${key}}`, p[key])
  return s
}

const GLOBAL_DEFAULTS = { enabled: false, notify: false, exist_ok: true, username: '自动订阅助手', onlyonce: false, clear: false }
const GLOBAL_SECTIONS = [
  { titleKey: 'secRunning', fields: [{ key: 'enabled', kind: 'switch' }, { key: 'notify', kind: 'switch' }] },
  { titleKey: 'secSubscription', fields: [{ key: 'username', kind: 'text' }, { key: 'exist_ok', kind: 'switch' }] },
  { titleKey: 'secOneTime', fields: [{ key: 'onlyonce', kind: 'switch' }, { key: 'clear', kind: 'switch' }] },
]
const PROVIDER_ICONS = {
  douban: 'mdi-movie-open-outline', maoyan: 'mdi-ticket-confirmation-outline', popular: 'mdi-fire',
  mikan: 'mdi-television-classic', netflix: 'mdi-play-box-outline',
}

const loading = ref(true)
const saving = ref(false)
const error = ref('')
const providerSpecs = ref([])
const activeGroup = ref(GLOBAL_KEY)
const running = reactive({})
const testing = reactive({})          // provider_id -> 连通性测试进行中
const testCooldown = reactive({})     // provider_id -> 冷却截止时间戳(ms)，防抖/防疯狂点击
const showAdvanced = reactive({})
const runMsg = reactive({ pid: '', text: '', ok: true })
const snapshot = ref(null)

// 左侧导航收起（仅图标）—— 记忆到本地存储，跨会话保持
const navCollapsed = ref(readCollapsed())
function readCollapsed() {
  try { return localStorage.getItem('asa.navCollapsed') === '1' } catch { return false }
}
function toggleNav() {
  navCollapsed.value = !navCollapsed.value
  try { localStorage.setItem('asa.navCollapsed', navCollapsed.value ? '1' : '0') } catch { /* ignore */ }
}

// 移动端（容器 < 680px，与窗口式导航同一断点）禁用「仅图标」折叠：功能栏始终完整显示。
// 用 ResizeObserver 监听布局容器宽度（贴合 CSS 容器查询语义）。
const layoutRef = ref(null)
const isNarrow = ref(false)
const asideOpen = ref(false)  // 移动端「概览」右侧抽屉开合（桌面端概览常驻右列，不使用此状态）
let navRO = null
onMounted(() => {
  if (typeof ResizeObserver === 'undefined' || !layoutRef.value) return
  navRO = new ResizeObserver(entries => {
    for (const e of entries) isNarrow.value = (e.contentRect?.width || 0) < 680
    if (!isNarrow.value && asideOpen.value) asideOpen.value = false  // 切回桌面自动收起抽屉
  })
  navRO.observe(layoutRef.value)
})
onUnmounted(() => { if (navRO) { navRO.disconnect(); navRO = null } })

// 顶部三标签（与订阅历史/管理一致）。点历史/管理：记忆目标视图并切回数据页（宿主在 Page 与 Config 间切换）。
const tabDefs = computed(() => [
  { key: 'history', label: t('navHistory'), icon: 'mdi-history' },
  { key: 'manage', label: t('navManage'), icon: 'mdi-bell-cog-outline' },
  { key: 'config', label: t('navConfig'), icon: 'mdi-cog-outline' },
])
function onTab(key) {
  if (key === 'config') return
  try { localStorage.setItem('asa.pageView', key) } catch { /* ignore */ }
  emit('switch')
}

// 移动端窗口式导航：先展示功能栏，点选渠道后进入对应配置页，返回回到功能栏（桌面端不影响）
const mobileView = ref('nav') // 'nav' | 'content'
function selectGroup(key) {
  activeGroup.value = key
  mobileView.value = 'content'
}

// 运行概览（订阅历史粗略统计）+ 处理中运行态，来自 /status
const summaryState = ref('loading') // loading | available | unavailable
const stats = ref(null)
const runState = ref([]) // [{provider_id, name, processed, started}]（运行中的来源）
let pollTimer = null
function armPoll(ms) {
  clearTimeout(pollTimer)
  pollTimer = setTimeout(loadStatus, ms)
}
async function loadStatus() {
  try {
    if (!props.api || typeof props.api.get !== 'function') throw new Error('no api')
    const res = await props.api.get(`${PLUGIN}/status?lang=${encodeURIComponent(locale.value)}`)
    const s = res && res.stats ? res.stats : null
    stats.value = s
    summaryState.value = s ? 'available' : 'unavailable'
    runState.value = Array.isArray(res && res.running) ? res.running : []
    // 有运行中的来源则持续轮询，直至全部结束
    if (runState.value.length) armPoll(2500)
  } catch {
    stats.value = null
    summaryState.value = 'unavailable'
    runState.value = []
  }
}
onUnmounted(() => clearTimeout(pollTimer))
const overviewRows = computed(() => {
  const by = (stats.value && stats.value.by_status) || {}
  return [
    { key: 'subscribed', icon: 'mdi-check-circle-outline', color: 'success', n: by.subscribed || 0 },
    { key: 'media_exists', icon: 'mdi-database-check-outline', color: 'info', n: by.media_exists || 0 },
    { key: 'subscription_exists', icon: 'mdi-bell-check-outline', color: 'primary', n: by.subscription_exists || 0 },
    { key: 'filtered', icon: 'mdi-filter-remove-outline', color: 'warning', n: by.filtered || 0 },
  ]
})
const totalHandled = computed(() => (stats.value && stats.value.total) || 0)

function deepClone(obj) { try { return JSON.parse(JSON.stringify(obj ?? {})) } catch { return {} } }

const initClone = deepClone(props.initialConfig)
const config = reactive({
  global: { ...GLOBAL_DEFAULTS, ...(initClone.global || {}) },
  providers: initClone.providers && typeof initClone.providers === 'object' ? initClone.providers : {},
})

const globalSections = computed(() => GLOBAL_SECTIONS.map(s => ({
  title: t(s.titleKey),
  fields: s.fields.map(f => ({ key: f.key, kind: f.kind, label: t(`g.${f.key}.label`), hint: t(`g.${f.key}.hint`) })),
})))

const groups = computed(() => [
  { key: GLOBAL_KEY, name: t('globalHeading'), icon: 'mdi-tune-variant' },
  ...providerSpecs.value.map(s => ({ key: s.provider_id, name: s.provider_name || s.provider_id, icon: groupIcon(s.provider_id) })),
])
const activeSpec = computed(() => providerSpecs.value.find(s => s.provider_id === activeGroup.value) || null)
const enabledCount = computed(() => providerSpecs.value.filter(s => isProviderEnabled(s.provider_id)).length)

const changedCount = computed(() => {
  if (!snapshot.value) return 0
  const cur = flatten(config)
  const base = snapshot.value
  let n = 0
  const keys = new Set([...Object.keys(cur), ...Object.keys(base)])
  keys.forEach(k => { if (cur[k] !== base[k]) n++ })
  return n
})
function flatten(obj, prefix = '', out = {}) {
  if (obj === null || typeof obj !== 'object' || Array.isArray(obj)) { out[prefix] = JSON.stringify(obj); return out }
  for (const [k, v] of Object.entries(obj)) flatten(v, prefix ? `${prefix}.${k}` : k, out)
  return out
}

function groupIcon(pid) { return PROVIDER_ICONS[pid] || 'mdi-rss' }
function isProviderEnabled(pid) { return !!(config.providers[pid] && config.providers[pid].enabled) }

function ensureProviderConfig(spec) {
  const pid = spec.provider_id
  if (!config.providers[pid] || typeof config.providers[pid] !== 'object') config.providers[pid] = {}
  const pc = config.providers[pid]
  if (typeof pc.enabled !== 'boolean') pc.enabled = false
  if (!pc.cron) pc.cron = spec.default_cron || ''
  if (!pc.options || typeof pc.options !== 'object') pc.options = {}
  if (!pc.filters || typeof pc.filters !== 'object') pc.filters = {}
  ;(spec.options_schema || []).forEach(f => { if (pc.options[f.key] === undefined) pc.options[f.key] = f.default })
  ;(spec.filters_schema || []).forEach(f => { if (pc.filters[f.key] === undefined) pc.filters[f.key] = f.default })
}

function inferProvidersFromConfig() {
  return Object.keys(config.providers || {}).map(pid => ({
    provider_id: pid, provider_name: pid,
    default_cron: (config.providers[pid] && config.providers[pid].cron) || '',
    options_schema: [], filters_schema: [],
  }))
}

async function loadProviders() {
  loading.value = true
  error.value = ''
  try {
    if (!props.api || typeof props.api.get !== 'function') throw new Error(t('apiUnavailable'))
    const res = await props.api.get(`${PLUGIN}/providers?lang=${encodeURIComponent(locale.value)}`)
    if (Array.isArray(res)) providerSpecs.value = res
    else if (res && Array.isArray(res.providers)) providerSpecs.value = res.providers
    else providerSpecs.value = []
  } catch (e) {
    error.value = t('providersError') + (e?.message || e)
    providerSpecs.value = inferProvidersFromConfig()
  }
  if (!providerSpecs.value.length) providerSpecs.value = inferProvidersFromConfig()
  providerSpecs.value.forEach(ensureProviderConfig)
  // 结构补全完成后拍快照作为脏值基线（仅首次，避免语言切换刷新时误清改动计数）
  if (!snapshot.value) snapshot.value = flatten(config)
  loading.value = false
}

// 语言切换时仅刷新来源标签（重新拉取本地化 spec），不重置脏值基线
watch(locale, () => { loadProviders() })

function visibleFilters(spec) { return (spec.filters_schema || []).filter(f => f.kind !== 'hidden') }
function normalOptions(spec) { return (spec.options_schema || []).filter(f => f.advanced !== true) }
function advancedOptions(spec) { return (spec.options_schema || []).filter(f => f.advanced === true) }
function normalFilters(spec) { return visibleFilters(spec).filter(f => f.advanced !== true) }
function advancedFilters(spec) { return visibleFilters(spec).filter(f => f.advanced === true) }
function hasAdvanced(spec) { return advancedOptions(spec).length > 0 || advancedFilters(spec).length > 0 }
function toggleAdvanced(pid) { showAdvanced[pid] = !showAdvanced[pid] }

function rowClass(field) {
  return ['asa-row', {
    'asa-row--switch': field.kind === 'switch',
    'asa-row--wide': field.kind === 'textarea' || field.kind === 'region-media-map',
  }]
}

async function runProvider(pid) {
  running[pid] = true
  runMsg.pid = pid
  runMsg.text = ''
  try {
    if (!props.api || typeof props.api.post !== 'function') throw new Error(t('apiUnavailable'))
    const res = await props.api.post(`${PLUGIN}/run`, { provider_id: pid })
    runMsg.ok = true
    runMsg.text = (res && res.message) || t('runTriggered')
    // 3 秒后开始运行，稍后轮询运行态以显示「处理中」
    armPoll(3500)
  } catch (e) {
    runMsg.ok = false
    runMsg.text = t('runFailed') + (e?.message || e)
  } finally {
    running[pid] = false
  }
}

// 连通性测试：抓取来源前几条验证连通（后端不订阅、不写历史）。前端防抖：进行中禁用 + 冷却期忽略，
// 双保险配合后端最小间隔，避免疯狂点击/短时间高频触发。
async function testProvider(pid) {
  const now = Date.now()
  if (testing[pid]) return
  if (now < (testCooldown[pid] || 0)) {
    runMsg.pid = pid; runMsg.ok = false; runMsg.text = t('throttled')
    return
  }
  testCooldown[pid] = now + 2000
  testing[pid] = true
  runMsg.pid = pid; runMsg.text = ''
  try {
    if (!props.api || typeof props.api.post !== 'function') throw new Error(t('apiUnavailable'))
    const res = await props.api.post(`${PLUGIN}/providers/test`, { provider_id: pid })
    if (res && res.throttled) { runMsg.ok = false; runMsg.text = (res && res.message) || t('throttled') }
    else { runMsg.ok = !!(res && res.ok); runMsg.text = (res && res.message) || (runMsg.ok ? t('testOk') : t('testFail')) }
  } catch (e) {
    runMsg.ok = false
    runMsg.text = t('testFail') + (e?.message || e)
  } finally {
    testing[pid] = false
    testCooldown[pid] = Date.now() + 2000
  }
}

function saveConfig() {
  saving.value = true
  try {
    emit('save', deepClone(config))
    snapshot.value = flatten(config)
  } finally {
    saving.value = false
  }
}

onMounted(() => { loadProviders(); loadStatus() })
</script>

<style scoped>
.asa-config {
  container-type: inline-size;
  color: rgb(var(--v-theme-on-surface));
  --asa-radius: var(--app-surface-radius, 12px);
  --asa-line: rgba(var(--v-theme-on-surface), 0.08);
}
.asa-config, .asa-config * { box-sizing: border-box; }

.asa-cfg-head {
  position: sticky; z-index: 5; inset-block-start: 0;
  display: flex; align-items: center; justify-content: space-between; gap: 16px;
  min-block-size: 64px; padding: 10px 16px;
  border-block-end: 1px solid rgba(var(--v-theme-on-surface), 0.1);
  background: var(--app-grouped-list-background, rgb(var(--v-theme-surface)));
}
.asa-cfg-head__brand { display: flex; align-items: center; gap: 12px; min-inline-size: 0; }
.asa-cfg-head__logo {
  display: flex; align-items: center; justify-content: center; flex: 0 0 40px;
  block-size: 40px; inline-size: 40px; border-radius: 11px;
  background: rgba(var(--v-theme-primary), 0.12); color: rgb(var(--v-theme-primary));
}
.asa-cfg-head__identity { min-inline-size: 0; }
.asa-cfg-head__crumbs { display: flex; align-items: center; gap: 2px; color: rgba(var(--v-theme-on-surface), 0.5); font-size: 0.68rem; }
.asa-cfg-head__title { margin: 2px 0 0; font-size: 1.05rem; font-weight: 700; line-height: 1.3; }
.asa-cfg-head__actions { display: flex; align-items: center; gap: 8px; flex: 0 0 auto; }
.asa-cfg-head__dirty { display: inline-flex; align-items: center; gap: 6px; color: rgb(var(--v-theme-warning)); font-size: 0.8rem; font-weight: 600; white-space: nowrap; }
.asa-cfg-head__save { min-inline-size: 104px; font-weight: 600; }

.asa-cfg-body { padding: 18px 18px 24px; }
.asa-cfg-layout { display: grid; gap: 16px; grid-template-columns: minmax(0, 1fr); }

.asa-nav { display: flex; flex-direction: column; gap: 4px; min-inline-size: 0; }
.asa-nav__list { display: flex; flex-direction: column; gap: 3px; min-block-size: 0; }
.asa-nav__top { display: flex; align-items: center; justify-content: space-between; gap: 6px; padding: 4px 6px 8px; }
.asa-nav__heading { color: rgba(var(--v-theme-on-surface), 0.5); font-size: 0.72rem; font-weight: 600; white-space: nowrap; }
.asa-nav__collapse {
  display: inline-flex; align-items: center; justify-content: center; flex: 0 0 auto;
  inline-size: 28px; block-size: 28px; border: 0; border-radius: 8px; background: transparent;
  color: rgba(var(--v-theme-on-surface), 0.55); cursor: pointer; transition: background 0.15s ease, color 0.15s ease;
}
.asa-nav__collapse:hover { background: rgba(var(--v-theme-on-surface), 0.06); color: rgb(var(--v-theme-primary)); }
.asa-nav__item {
  display: flex; align-items: center; gap: 12px; min-block-size: 46px; padding: 0 12px;
  border: 0; border-radius: 10px; background: transparent; color: rgba(var(--v-theme-on-surface), 0.78);
  font-size: 0.85rem; font-weight: 600; text-align: start; text-decoration: none; cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease;
}
.asa-nav__item:hover { background: rgba(var(--v-theme-on-surface), 0.05); }
.asa-nav__item--active { background: rgba(var(--v-theme-primary), 0.1); color: rgb(var(--v-theme-primary)); }
.asa-nav__label { flex: 1 1 auto; overflow: hidden; white-space: nowrap; }
.asa-nav__dot { flex: 0 0 auto; inline-size: 8px; block-size: 8px; border-radius: 50%; background: rgba(var(--v-theme-on-surface), 0.22); transition: opacity 0.16s ease; }
.asa-nav__dot--on { background: rgb(var(--v-theme-success)); box-shadow: 0 0 0 3px rgba(var(--v-theme-success), 0.16); }
/* 功能栏（分组列表）与「插件帮助」之间的分割线 */
.asa-nav__sep { flex: 0 0 auto; block-size: 1px; margin: 6px 6px 4px; background: rgba(var(--v-theme-on-surface), 0.1); }
/* 插件帮助：沿用 .asa-nav__item 的「图标 + 标签」布局（与「全局设置」等分组项一致）；链接去下划线、图标淡色 */
.asa-nav__help { flex: 0 0 auto; text-decoration: none; color: rgba(var(--v-theme-on-surface), 0.72); }
.asa-nav__help-ico { color: rgba(var(--v-theme-on-surface), 0.5); }

/* 收起：仅图标（标签宽度动画收合，流畅不卡顿；图标居中于预选框） */
.asa-nav--collapsed .asa-nav__heading { display: none; }
.asa-nav--collapsed .asa-nav__top { justify-content: center; padding-inline: 0; }
.asa-nav--collapsed .asa-nav__list { align-items: center; }
.asa-nav--collapsed .asa-nav__label { display: none; }
.asa-nav--collapsed .asa-nav__dot { display: none; }
.asa-nav--collapsed .asa-nav__item,
.asa-nav--collapsed .asa-nav__collapse { inline-size: 44px; padding-inline: 0; justify-content: center; gap: 0; }
@media (prefers-reduced-motion: reduce) {
  .asa-nav__label { transition: none; }
}

.asa-surface { min-inline-size: 0; }
.asa-mobile-back {
  display: none; align-items: center; gap: 6px; margin: 0 0 12px; padding: 6px 12px 6px 8px;
  border: 0; border-radius: 9px; background: rgba(var(--v-theme-on-surface), 0.05);
  color: rgb(var(--v-theme-primary)); font-size: 0.85rem; font-weight: 600; cursor: pointer;
}
.asa-mobile-back:hover { background: rgba(var(--v-theme-on-surface), 0.09); }
.asa-surface__heading { display: flex; align-items: flex-start; gap: 10px; padding: 2px 2px 14px; }
.asa-surface__heading h2 { margin: 0; font-size: 1.05rem; font-weight: 700; line-height: 1.3; }
.asa-surface__heading p { margin: 3px 0 0; color: rgba(var(--v-theme-on-surface), 0.6); font-size: 0.76rem; }

.asa-section {
  overflow: hidden; border: var(--app-surface-border, 1px solid var(--asa-line));
  border-radius: var(--asa-radius); background: var(--app-grouped-list-background, rgb(var(--v-theme-surface)));
}
.asa-section + .asa-section { margin-block-start: 12px; }
.asa-section > h3 { padding: 13px 16px 9px; margin: 0; font-size: 0.9rem; font-weight: 700; }
.asa-section__rows { padding-inline: 16px; }

.asa-row {
  display: grid; align-items: start; gap: 18px; padding-block: 13px;
  border-block-start: 1px solid var(--asa-line);
  grid-template-columns: minmax(0, 1.4fr) minmax(160px, 0.85fr);
}
.asa-row--switch { align-items: center; }
.asa-row--switch .asa-row__control { display: flex; justify-content: flex-end; }
.asa-row--wide { grid-template-columns: minmax(0, 1fr); gap: 8px; }
.asa-row__copy { min-inline-size: 0; }
.asa-row__label { color: rgb(var(--v-theme-on-surface)); font-size: 0.83rem; font-weight: 600; line-height: 1.2; }
.asa-row__copy p { margin: 4px 0 0; color: rgba(var(--v-theme-on-surface), 0.56); font-size: 0.7rem; line-height: 1.05rem; }
.asa-row__control { min-inline-size: 0; }

.asa-section--advanced > h3 { display: none; }
.asa-advanced-toggle {
  display: flex; align-items: center; gap: 6px; inline-size: 100%; padding: 12px 16px;
  border: 0; background: transparent; color: rgb(var(--v-theme-primary)); font-size: 0.85rem; font-weight: 600; cursor: pointer;
}
.asa-advanced-toggle__hint { color: rgba(var(--v-theme-on-surface), 0.45); font-weight: 400; font-size: 0.72rem; }
.asa-section--advanced .asa-section__rows { padding-block-end: 6px; }

.asa-run { display: flex; align-items: center; gap: 10px; margin-block-start: 14px; }
.asa-run__msg { display: inline-flex; align-items: center; gap: 5px; font-size: 0.78rem; font-weight: 500; }
.asa-run__msg--ok { color: rgb(var(--v-theme-success)); }
.asa-run__msg--err { color: rgb(var(--v-theme-error)); }

.asa-aside {
  align-self: start; padding: 16px; border: var(--app-surface-border, 1px solid var(--asa-line));
  border-radius: var(--asa-radius); background: var(--app-grouped-list-background, rgb(var(--v-theme-surface)));
}
.asa-aside__title { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.asa-aside__title h3 { margin: 0; font-size: 0.95rem; font-weight: 700; }
/* 处理中：运行态高亮区 */
.asa-running {
  margin-bottom: 14px; padding: 12px; border-radius: 10px;
  background: rgba(var(--v-theme-primary), 0.08); border: 1px solid rgba(var(--v-theme-primary), 0.18);
}
.asa-running__title { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; color: rgb(var(--v-theme-primary)); font-size: 0.82rem; font-weight: 700; }
.asa-running__row { display: flex; align-items: center; gap: 8px; padding-block: 4px; font-size: 0.78rem; color: rgba(var(--v-theme-on-surface), 0.8); }
.asa-running__name { flex: 1 1 auto; min-inline-size: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.asa-running__row strong { flex: 0 0 auto; color: rgb(var(--v-theme-primary)); font-variant-numeric: tabular-nums; }
.asa-aside__list { padding: 0; margin: 6px 0 14px; list-style: none; }
.asa-aside__list li {
  display: grid; grid-template-columns: 22px minmax(0, 1fr) auto; align-items: center; gap: 8px;
  padding-block: 9px; color: rgba(var(--v-theme-on-surface), 0.72); font-size: 0.82rem;
  border-block-start: 1px solid var(--asa-line);
}
.asa-aside__list li:first-child { border-block-start: 0; }
.asa-aside__list li > .v-icon { color: rgba(var(--v-theme-on-surface), 0.5); }
.asa-aside__list strong { color: rgb(var(--v-theme-on-surface)); font-variant-numeric: tabular-nums; }
.asa-aside__btn { font-weight: 600; }

/* 概览按钮与抽屉关闭按钮默认隐藏（桌面端概览常驻右列，无需按钮），仅移动端容器查询下显示。 */
.asa-cfg-head__overview { display: none; }
.asa-aside__close { display: none; }

/* 运行概览（订阅历史粗略统计） */
.asa-aside__title--sub { margin-block-start: 18px; margin-bottom: 6px; }
.asa-runtime__state { padding: 4px 2px 12px; color: rgba(var(--v-theme-on-surface), 0.5); font-size: 0.76rem; }
.asa-runtime__total { display: flex; align-items: baseline; justify-content: space-between; padding: 2px 2px 10px; font-size: 0.82rem; color: rgba(var(--v-theme-on-surface), 0.72); }
.asa-runtime__total strong { color: rgb(var(--v-theme-on-surface)); font-size: 1.05rem; font-weight: 700; font-variant-numeric: tabular-nums; }
.asa-runtime__grid { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; margin-block-end: 14px; }
.asa-runtime__cell {
  display: flex; align-items: center; gap: 5px; min-inline-size: 0; padding: 8px 9px; border-radius: 9px;
  background: rgba(var(--v-theme-on-surface), 0.04); font-size: 0.72rem; color: rgba(var(--v-theme-on-surface), 0.7);
}
.asa-runtime__cell span { flex: 1 1 auto; min-inline-size: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.asa-runtime__cell strong { color: rgb(var(--v-theme-on-surface)); font-variant-numeric: tabular-nums; }

/* 底部保存条：就地 sticky 贴底（在 .asa-config 容器上下文内，兼容宿主弹窗层级，不用 Teleport 以免被宿主高层弹窗遮挡）；
   不透明白底、去掉 backdrop-filter 消除滚动时轻微重绘位移；配合下方 .asa-config { min-block-size:100dvh } 让短内容视图也稳定贴底。 */
.asa-mobile-dock {
  position: sticky; z-index: 6; inset-block-end: 0; margin: 0 12px 12px;
  display: flex; align-items: center; gap: 12px;
  padding: 10px 14px; border: 1px solid rgba(var(--v-theme-on-surface), 0.14);
  border-radius: var(--app-surface-radius, 12px); background: rgb(var(--v-theme-surface));
  box-shadow: 0 8px 28px rgba(0, 0, 0, 0.18);
}
.asa-mobile-dock__state { display: inline-flex; align-items: center; gap: 6px; color: rgb(var(--v-theme-warning)); font-size: 0.8rem; font-weight: 600; }

.asa-fade-enter-active, .asa-fade-leave-active { transition: opacity 0.2s ease; }
.asa-fade-enter-from, .asa-fade-leave-to { opacity: 0; }

/* 底部保存条弹出过渡（从下方滑入，独占一行） */
.asa-dock-enter-active, .asa-dock-leave-active { transition: transform 0.24s ease, opacity 0.24s ease; }
.asa-dock-enter-from, .asa-dock-leave-to { transform: translateY(100%); opacity: 0; }
@media (prefers-reduced-motion: reduce) {
  .asa-dock-enter-active, .asa-dock-leave-active { transition: opacity 0.2s ease; }
  .asa-dock-enter-from, .asa-dock-leave-to { transform: none; }
}

@container (width >= 680px) {
  .asa-cfg-layout { grid-template-columns: max-content minmax(0, 1fr); }
  .asa-nav { grid-column: 1; }
  .asa-surface { grid-column: 2; }
  .asa-mobile-dock { display: none; }
}
@container (width >= 940px) {
  /* 侧栏按内容宽（一行完整显示，不锁死）；中间内容区独立滚动，
     滚动条落在内容与右侧概览之间，而非整体最右侧。 */
  .asa-cfg-layout { grid-template-columns: max-content minmax(0, 1fr) 240px; grid-template-areas: 'nav content aside'; gap: 18px; align-items: start; }
  .asa-nav {
    grid-area: nav; position: sticky; inset-block-start: 124px;
    display: flex; flex-direction: column; block-size: calc(100dvh - 214px);
  }
  /* 渠道列表可内部滚动，帮助钉在左下角、与列表分区，渠道再多也不叠加 */
  .asa-nav__list {
    flex: 1 1 auto; overflow-y: auto; overscroll-behavior: contain; min-block-size: 0;
    scrollbar-width: thin; scrollbar-color: rgba(var(--v-theme-on-surface), 0.22) transparent;
  }
  .asa-nav__list::-webkit-scrollbar { inline-size: 6px; }
  .asa-nav__list::-webkit-scrollbar-thumb { background: rgba(var(--v-theme-on-surface), 0.18); border-radius: 3px; }
  .asa-nav__help { flex: 0 0 auto; margin-block-start: 10px; }
  .asa-surface {
    grid-area: content; overflow-y: auto; overscroll-behavior: contain;
    block-size: calc(100dvh - 214px); padding-inline-end: 10px;
    scrollbar-width: thin; scrollbar-color: rgba(var(--v-theme-on-surface), 0.22) transparent;
  }
  .asa-surface::-webkit-scrollbar { inline-size: 8px; }
  .asa-surface::-webkit-scrollbar-thumb { background: rgba(var(--v-theme-on-surface), 0.2); border-radius: 4px; }
  .asa-surface::-webkit-scrollbar-thumb:hover { background: rgba(var(--v-theme-on-surface), 0.32); }
  .asa-aside { grid-area: aside; position: sticky; inset-block-start: 124px; }
}
/* iPad / 中等宽度（< 940px，即非三栏布局）：概览一律改为右侧可收纳抽屉，不再堆叠追加在配置界面末尾。
   就地 fixed（留在 .asa-config 内，随宿主弹窗层级正常显示，不用 Teleport 以免被宿主高层弹窗遮挡）；
   整屏高、整体不透明白底。 */
@container (width < 940px) {
  .asa-cfg-head__overview { display: inline-flex; }
  .asa-aside {
    position: fixed; z-index: 30; inset-block: 0; inset-inline-end: 0;
    inline-size: min(320px, 86vw); block-size: 100dvh; overflow-y: auto;
    padding: 46px 16px 16px; border-radius: 0; border: 0;
    border-inline-start: 1px solid rgba(var(--v-theme-on-surface), 0.12);
    background: rgb(var(--v-theme-surface));
    transform: translateX(100%); transition: transform 0.26s ease;
  }
  /* 阴影仅在展开时出现，避免收起（移出屏幕右侧）时阴影仍溢到视口边缘 */
  .asa-aside--open { transform: translateX(0); box-shadow: -12px 0 32px rgba(0, 0, 0, 0.34); }
  .asa-aside__close {
    position: absolute; inset-block-start: 8px; inset-inline-end: 8px;
    display: inline-flex; align-items: center; justify-content: center;
    inline-size: 32px; block-size: 32px; border: 0; border-radius: 8px;
    background: rgba(var(--v-theme-on-surface), 0.06); color: rgba(var(--v-theme-on-surface), 0.7); cursor: pointer;
  }
  .asa-aside__close:hover { background: rgba(var(--v-theme-on-surface), 0.12); }
  .asa-aside-scrim { display: block; position: fixed; z-index: 29; inset: 0; background: rgba(0, 0, 0, 0.42); }
}
@container (width < 680px) {
  .asa-row { grid-template-columns: minmax(0, 1fr) minmax(130px, 0.8fr); gap: 12px; align-items: center; }
  .asa-row--wide { grid-template-columns: minmax(0, 1fr); }
  /* 移动端窗口式导航：功能栏 / 配置页二选一显示，点选进入、返回回到功能栏 */
  .asa-nav__collapse { display: none; }
  .asa-mobile-back { display: inline-flex; }
  .asa-cfg-layout--mnav .asa-surface { display: none; }
  .asa-cfg-layout--mcontent .asa-nav { display: none; }
  /* 顶部不显示「未保存 + 保存」，避免面包屑整行被挤压（改由底部 sticky 保存条承担） */
  .asa-cfg-head__dirty, .asa-cfg-head__save { display: none; }
  /* 让内容区至少铺满视口高度，使底部 sticky 保存条稳定贴底、切换视图不上移；并为末尾配置项预留空间不被遮挡。 */
  .asa-cfg-body { min-block-size: calc(100dvh - 118px); }
  .asa-config--docked .asa-cfg-body { padding-block-end: 92px; }
}
@media (prefers-reduced-motion: reduce) {
  .asa-aside { transition: none; }
}
</style>
