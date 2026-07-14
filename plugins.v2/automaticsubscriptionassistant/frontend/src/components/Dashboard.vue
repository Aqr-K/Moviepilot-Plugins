<template>
  <div class="asa-dash">
    <div class="asa-dash__surface" :class="{ 'asa-dash__surface--flat': !bordered }">
      <header v-if="bordered" class="asa-dash__head">
        <div class="asa-dash__head-copy">
          <h3 class="asa-dash__title">{{ title }}</h3>
          <p v-if="subtitle" class="asa-dash__subtitle">{{ subtitle }}</p>
        </div>
        <v-btn
          v-if="allowRefresh"
          :loading="loading"
          :aria-label="t('refresh')"
          class="asa-dash__refresh"
          density="comfortable"
          icon="mdi-refresh"
          size="small"
          variant="text"
          @click="refresh"
        />
      </header>

      <!-- 骨架 -->
      <div v-if="loading && !totalHandled && !error" class="asa-dash__body">
        <div class="asa-skel asa-skel--ring"></div>
        <div class="asa-skel-lines">
          <div class="asa-skel asa-skel--line"></div>
          <div class="asa-skel asa-skel--line"></div>
          <div class="asa-skel asa-skel--line short"></div>
        </div>
      </div>

      <!-- 错误 -->
      <div v-else-if="error" class="asa-dash__state">
        <div class="asa-state-ico asa-state-ico--error"><v-icon icon="mdi-alert-circle-outline" size="22" /></div>
        <p class="asa-state__text">{{ error }}</p>
        <button class="asa-state__btn" type="button" @click="refresh">{{ t('retry') }}</button>
      </div>

      <!-- 空态 -->
      <div v-else-if="!totalHandled" class="asa-dash__state">
        <div class="asa-state-ico"><v-icon icon="mdi-playlist-star" size="22" /></div>
        <p class="asa-state__text">{{ t('emptyText') }}</p>
        <p class="asa-state__hint">{{ t('emptyHint') }}</p>
      </div>

      <!-- 数据 -->
      <div v-else class="asa-dash__body">
        <!-- 环形图 + 图例 -->
        <div class="asa-donut">
          <div class="asa-donut__ring" :style="donutStyle">
            <div class="asa-donut__hole">
              <span class="asa-donut__num">{{ totalHandled }}</span>
              <span class="asa-donut__cap">{{ t('cap') }}</span>
            </div>
          </div>
          <ul class="asa-legend">
            <li v-for="r in segments.rows" :key="r.key" class="asa-legend__item">
              <span class="asa-legend__dot" :style="{ background: cssColor(r.color) }"></span>
              <span class="asa-legend__label">{{ r.label }}</span>
              <span class="asa-legend__val">{{ r.count }} · {{ pct(r.count) }}%</span>
            </li>
          </ul>
        </div>

        <!-- 来源状态 -->
        <div class="asa-sources">
          <div class="asa-sources__head">
            <span class="asa-sources__title">{{ t('sources') }}</span>
            <span class="asa-sources__count">{{ t('enabledOf', { a: enabledProviders.length, b: providers.length }) }}</span>
          </div>
          <div class="asa-sources__chips">
            <template v-if="providers.length">
              <span v-for="p in providers" :key="p.provider_id" class="asa-chip" :class="{ 'asa-chip--on': p.enabled }">
                <v-icon :icon="p.enabled ? 'mdi-check-circle' : 'mdi-circle-outline'" size="13" />
                {{ p.provider_name || p.provider_id }}
              </span>
            </template>
            <span v-else class="asa-sources__empty">{{ t('noSources') }}</span>
          </div>
        </div>

        <!-- 最近订阅 -->
        <div v-if="recent.length" class="asa-recent">
          <div class="asa-recent__head">{{ t('recent') }}</div>
          <ul class="asa-recent__list">
            <li v-for="it in recent.slice(0, 5)" :key="it.unique" class="asa-recent__item">
              <img
                v-if="it.poster && !failed[it.unique]"
                class="asa-recent__poster"
                :src="it.poster"
                alt=""
                loading="lazy"
                @error="failed[it.unique] = true"
              />
              <span v-else class="asa-recent__poster asa-recent__poster--ph"><v-icon icon="mdi-movie-open-outline" size="16" /></span>
              <div class="asa-recent__meta">
                <span class="asa-recent__name" :title="it.title">{{ it.title }}</span>
                <span class="asa-recent__sub">{{ [it.year, it.type].filter(Boolean).join(' · ') || '—' }}</span>
              </div>
            </li>
          </ul>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, getCurrentInstance, onMounted, onUnmounted, reactive, ref } from 'vue'

// --- 状态展示（color 内联，label 走 i18n）---
const STATUS_META = {
  subscribed: { color: 'success' },
  media_exists: { color: 'info' },
  subscription_exists: { color: 'primary' },
  filtered: { color: 'warning' },
  unrecognized: { color: 'blue-grey' },
  already_handled: { color: 'grey' },
  error: { color: 'error' },
}
const STAT_ORDER = ['subscribed', 'media_exists', 'subscription_exists', 'filtered', 'unrecognized', 'error']

// --- i18n（内联，保持联邦块自包含）---
const MSG = {
  'zh-CN': {
    title: '自动订阅助手', subtitle: '订阅概览', cap: '累计处理', sources: '来源',
    enabledOf: '{a} / {b} 启用', noSources: '无可用来源', recent: '最近订阅',
    emptyText: '暂无订阅记录', emptyHint: '启用来源并运行后，这里会展示订阅统计',
    retry: '重试', refresh: '刷新', apiUnavailable: 'API 不可用', loadError: '数据加载失败：',
    'st.subscribed': '已订阅', 'st.media_exists': '媒体库已存在', 'st.subscription_exists': '订阅已存在',
    'st.filtered': '被过滤', 'st.unrecognized': '未识别', 'st.already_handled': '已处理', 'st.error': '异常',
  },
  'zh-TW': {
    title: '自動訂閱助手', subtitle: '訂閱概覽', cap: '累計處理', sources: '來源',
    enabledOf: '{a} / {b} 啟用', noSources: '無可用來源', recent: '最近訂閱',
    emptyText: '暫無訂閱記錄', emptyHint: '啟用來源並執行後，這裡會顯示訂閱統計',
    retry: '重試', refresh: '重新整理', apiUnavailable: 'API 不可用', loadError: '資料載入失敗：',
    'st.subscribed': '已訂閱', 'st.media_exists': '媒體庫已存在', 'st.subscription_exists': '訂閱已存在',
    'st.filtered': '被過濾', 'st.unrecognized': '未識別', 'st.already_handled': '已處理', 'st.error': '異常',
  },
  'en-US': {
    title: 'Auto Subscribe', subtitle: 'Overview', cap: 'Handled', sources: 'Sources',
    enabledOf: '{a} / {b} enabled', noSources: 'No sources', recent: 'Recent',
    emptyText: 'No subscriptions yet', emptyHint: 'Stats appear here once sources are enabled and run',
    retry: 'Retry', refresh: 'Refresh', apiUnavailable: 'API unavailable', loadError: 'Failed to load data: ',
    'st.subscribed': 'Subscribed', 'st.media_exists': 'In library', 'st.subscription_exists': 'Already subscribed',
    'st.filtered': 'Filtered', 'st.unrecognized': 'Unrecognized', 'st.already_handled': 'Handled', 'st.error': 'Error',
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

const props = defineProps({
  config: { type: Object, default: () => ({}) },
  allowRefresh: { type: Boolean, default: true },
  api: { type: Object, default: () => ({}) },
})

const PLUGIN = 'plugin/AutomaticSubscriptionAssistant'
const THEME_COLORS = { primary: 1, secondary: 1, success: 1, info: 1, warning: 1, error: 1 }

const loading = ref(true)
const error = ref('')
const byStatus = ref({})
const providers = ref([])
const totalHandled = ref(0)
const recent = ref([])
const failed = reactive({})
let timer = null

const bordered = computed(() => props.config?.attrs?.border !== false)
// 仪表盘为固定部件，标题/子标题跟随语言（忽略后端 attrs 文本，仅沿用 border）
const title = computed(() => t('title'))
const subtitle = computed(() => t('subtitle'))
const refreshSecs = computed(() => {
  const v = Number(props.config?.attrs?.refresh)
  return Number.isFinite(v) && v > 0 ? v : 0
})

const enabledProviders = computed(() => providers.value.filter(p => p.enabled))

const segments = computed(() => {
  const src = byStatus.value || {}
  const rows = STAT_ORDER
    .map(key => ({ key, count: Number(src[key]) || 0, color: STATUS_META[key].color, label: t('st.' + key) }))
    .filter(r => r.count > 0)
  const sum = rows.reduce((acc, r) => acc + r.count, 0)
  return { rows, sum }
})

const donutStyle = computed(() => {
  const { rows, sum } = segments.value
  if (!sum) return { background: 'rgba(var(--v-theme-on-surface), 0.08)' }
  let acc = 0
  const stops = rows.map(r => {
    const start = (acc / sum) * 100
    acc += r.count
    const end = (acc / sum) * 100
    return `${cssColor(r.color)} ${start}% ${end}%`
  })
  return { background: `conic-gradient(${stops.join(', ')})` }
})

function pct(count) {
  const sum = segments.value.sum
  return sum ? Math.round((count / sum) * 100) : 0
}
function cssColor(name) {
  if (THEME_COLORS[name]) return `rgb(var(--v-theme-${name}))`
  if (name === 'blue-grey') return 'rgba(var(--v-theme-on-surface), 0.5)'
  return 'rgba(var(--v-theme-on-surface), 0.32)'
}
function qs(params) {
  return Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== null && v !== '')
    .map(([k, v]) => `${k}=${encodeURIComponent(v)}`)
    .join('&')
}

async function fetchData() {
  if (!props.api || typeof props.api.get !== 'function') {
    error.value = t('apiUnavailable')
    loading.value = false
    return
  }
  loading.value = true
  error.value = ''
  try {
    const [statusRes, historyRes] = await Promise.allSettled([
      props.api.get(`${PLUGIN}/status?${qs({ lang: locale.value })}`),
      props.api.get(`${PLUGIN}/history?${qs({ status: 'subscribed', count: 6 })}`),
    ])
    if (statusRes.status === 'fulfilled') {
      const s = statusRes.value || {}
      byStatus.value = s.stats?.by_status || {}
      totalHandled.value = Number(s.stats?.total) || 0
      providers.value = Array.isArray(s.providers) ? s.providers : []
    } else {
      throw statusRes.reason || new Error('status failed')
    }
    recent.value = historyRes.status === 'fulfilled' ? normalizeList(historyRes.value) : []
  } catch (e) {
    error.value = t('loadError') + (e?.message || e)
  } finally {
    loading.value = false
  }
}
function normalizeList(res) {
  if (Array.isArray(res)) return res
  if (res && Array.isArray(res.list)) return res.list
  if (res && Array.isArray(res.items)) return res.items
  return []
}
function refresh() { if (!loading.value) fetchData() }
function setupTimer() {
  if (props.allowRefresh && refreshSecs.value) timer = setInterval(fetchData, refreshSecs.value * 1000)
}
onMounted(() => { fetchData(); setupTimer() })
onUnmounted(() => timer && clearInterval(timer))
</script>

<style scoped>
.asa-dash {
  --asa-radius: var(--app-surface-radius, 12px);
  --asa-line: rgba(var(--v-theme-on-surface), 0.09);
  --asa-ease: var(--mp-motion-ease-standard, cubic-bezier(0.2, 0.8, 0.2, 1));
  container-type: inline-size;
  color: rgb(var(--v-theme-on-surface));
}
.asa-dash__surface {
  padding: 14px 16px 16px;
  border: var(--app-surface-border, 1px solid rgba(var(--v-theme-on-surface), 0.08));
  border-radius: var(--asa-radius);
  background: var(--app-grouped-list-background, rgb(var(--v-theme-surface)));
}
.asa-dash__surface--flat { padding: 4px 2px 2px; border: 0; background: transparent; }
.asa-dash__head { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; margin-bottom: 12px; }
.asa-dash__title { margin: 0; font-size: 0.95rem; font-weight: 700; line-height: 1.3; }
.asa-dash__subtitle { margin: 2px 0 0; color: rgba(var(--v-theme-on-surface), 0.6); font-size: 0.75rem; }
.asa-dash__refresh { margin: -4px -6px 0 0; }
.asa-dash__body { display: flex; flex-direction: column; gap: 14px; }

.asa-donut { display: grid; grid-template-columns: auto minmax(0, 1fr); align-items: center; gap: 18px; }
.asa-donut__ring { position: relative; flex: 0 0 auto; inline-size: 96px; block-size: 96px; border-radius: 50%; }
.asa-donut__hole {
  position: absolute; inset: 13px; display: flex; flex-direction: column; align-items: center; justify-content: center;
  border-radius: 50%; background: var(--app-grouped-list-background, rgb(var(--v-theme-surface)));
}
.asa-dash__surface--flat .asa-donut__hole { background: rgb(var(--v-theme-surface)); }
.asa-donut__num { font-size: 1.4rem; font-weight: 700; line-height: 1; }
.asa-donut__cap { margin-top: 3px; color: rgba(var(--v-theme-on-surface), 0.55); font-size: 0.62rem; }

.asa-legend { display: flex; flex-direction: column; gap: 7px; padding: 0; margin: 0; list-style: none; min-inline-size: 0; }
.asa-legend__item { display: grid; grid-template-columns: 10px minmax(0, 1fr) auto; align-items: center; gap: 8px; font-size: 0.78rem; }
.asa-legend__dot { inline-size: 9px; block-size: 9px; border-radius: 3px; }
.asa-legend__label { overflow: hidden; color: rgba(var(--v-theme-on-surface), 0.78); text-overflow: ellipsis; white-space: nowrap; }
.asa-legend__val { color: rgba(var(--v-theme-on-surface), 0.55); font-size: 0.72rem; font-variant-numeric: tabular-nums; white-space: nowrap; }

.asa-sources { padding-top: 12px; border-top: 1px solid var(--asa-line); }
.asa-sources__head { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 8px; }
.asa-sources__title { font-size: 0.8rem; font-weight: 600; }
.asa-sources__count { color: rgba(var(--v-theme-on-surface), 0.55); font-size: 0.72rem; }
.asa-sources__chips { display: flex; flex-wrap: wrap; gap: 6px; }
.asa-sources__empty { color: rgba(var(--v-theme-on-surface), 0.5); font-size: 0.75rem; }
.asa-chip {
  display: inline-flex; align-items: center; gap: 4px; padding: 3px 9px 3px 7px; border-radius: 999px;
  background: rgba(var(--v-theme-on-surface), 0.06); color: rgba(var(--v-theme-on-surface), 0.55); font-size: 0.72rem; line-height: 1.2;
}
.asa-chip--on { background: rgba(var(--v-theme-success), 0.14); color: rgb(var(--v-theme-success)); }

.asa-recent { padding-top: 12px; border-top: 1px solid var(--asa-line); }
.asa-recent__head { margin-bottom: 8px; font-size: 0.8rem; font-weight: 600; }
.asa-recent__list { display: flex; flex-direction: column; gap: 8px; padding: 0; margin: 0; list-style: none; }
.asa-recent__item { display: grid; grid-template-columns: 30px minmax(0, 1fr); align-items: center; gap: 10px; }
.asa-recent__poster { inline-size: 30px; block-size: 44px; border-radius: 5px; object-fit: cover; background: rgba(var(--v-theme-on-surface), 0.08); }
.asa-recent__poster--ph { display: flex; align-items: center; justify-content: center; color: rgba(var(--v-theme-on-surface), 0.4); }
.asa-recent__meta { display: flex; flex-direction: column; min-inline-size: 0; }
.asa-recent__name { overflow: hidden; font-size: 0.8rem; font-weight: 500; text-overflow: ellipsis; white-space: nowrap; }
.asa-recent__sub { color: rgba(var(--v-theme-on-surface), 0.5); font-size: 0.7rem; }

.asa-dash__state { display: flex; flex-direction: column; align-items: center; gap: 8px; padding: 22px 12px; text-align: center; }
.asa-state-ico {
  display: flex; align-items: center; justify-content: center; inline-size: 44px; block-size: 44px; border-radius: 50%;
  background: rgba(var(--v-theme-primary), 0.1); color: rgb(var(--v-theme-primary));
}
.asa-state-ico--error { background: rgba(var(--v-theme-error), 0.12); color: rgb(var(--v-theme-error)); }
.asa-state__text { margin: 0; font-size: 0.85rem; font-weight: 500; }
.asa-state__hint { margin: 0; color: rgba(var(--v-theme-on-surface), 0.55); font-size: 0.74rem; }
.asa-state__btn {
  margin-top: 2px; padding: 5px 14px; border: 0; border-radius: 8px;
  background: rgba(var(--v-theme-primary), 0.12); color: rgb(var(--v-theme-primary)); font-size: 0.78rem; cursor: pointer;
}

.asa-skel { background: rgba(var(--v-theme-on-surface), 0.08); border-radius: 8px; animation: asa-pulse 1.4s var(--asa-ease) infinite; }
.asa-skel--ring { inline-size: 96px; block-size: 96px; border-radius: 50%; }
.asa-skel-lines { display: flex; flex-direction: column; gap: 10px; margin-top: 14px; }
.asa-skel--line { block-size: 12px; }
.asa-skel--line.short { inline-size: 60%; }
@keyframes asa-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.45; } }

@container (width < 260px) {
  .asa-donut { grid-template-columns: minmax(0, 1fr); justify-items: center; gap: 12px; }
  .asa-legend { inline-size: 100%; }
}
@media (prefers-reduced-motion: reduce) { .asa-skel { animation: none; } }
</style>
