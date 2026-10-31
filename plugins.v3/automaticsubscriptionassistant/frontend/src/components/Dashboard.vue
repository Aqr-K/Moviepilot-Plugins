<template>
  <div class="asa-dash">
    <div class="asa-dash__surface" :class="{ 'asa-dash__surface--flat': !bordered }">
      <header v-if="bordered" class="asa-dash__head">
        <div class="asa-dash__brand">
          <v-icon icon="mdi-rss" size="22" color="primary" />
          <div class="asa-dash__head-copy">
            <h3 class="asa-dash__title">{{ t('title') }}</h3>
            <p class="asa-dash__subtitle">{{ t('subtitle') }}</p>
          </div>
        </div>
        <div class="asa-dash__head-actions">
          <span v-if="hasData" class="asa-chip" :class="{ 'asa-chip--on': enabled }">{{ t(enabled ? 'enabled' : 'disabled') }}</span>
          <v-btn v-if="allowRefresh" :loading="loading" :aria-label="t('refresh')" class="asa-dash__refresh" icon="mdi-refresh" size="small" variant="text" @click="fetchData" />
        </div>
      </header>

      <div v-if="loading && !hasData" class="asa-dash__body" :aria-label="t('loading')" aria-busy="true">
        <div class="asa-dash__metrics">
          <div v-for="n in 3" :key="n" class="asa-skel asa-skel--metric"></div>
        </div>
        <div class="asa-skel asa-skel--line"></div>
        <div class="asa-skel asa-skel--line short"></div>
      </div>
      <div v-else-if="!hasData" class="asa-dash__state" role="alert">
        <div class="asa-state-ico asa-state-ico--error"><v-icon icon="mdi-alert-circle-outline" size="22" /></div>
        <p class="asa-state__text">{{ error }}</p>
        <button class="asa-state__btn" type="button" @click="fetchData">{{ t('retry') }}</button>
      </div>
      <div v-else class="asa-dash__body">
        <div v-if="error" class="asa-dash__notice" role="alert">{{ error }}</div>
        <div class="asa-dash__metrics">
          <div v-for="metric in metrics" :key="metric.key" class="asa-dash__metric">
            <div class="asa-dash__metric-label" :title="metric.label"><v-icon :icon="metric.icon" size="15" />{{ metric.label }}</div>
            <strong class="asa-dash__metric-value">{{ metric.count }}</strong>
            <span v-if="metric.key === 'subscriptions' && counts.paused" class="asa-dash__metric-hint">{{ t('pausedN', { n: counts.paused }) }}</span>
          </div>
        </div>

        <section v-if="running.length" class="asa-dash__running" :aria-label="t('running')">
          <div class="asa-dash__running-title"><v-icon icon="mdi-progress-clock" size="16" />{{ t('running') }}</div>
          <div v-for="task in running" :key="task.provider_id" class="asa-dash__running-row">
            <span>{{ providerName(task) }}</span><strong>{{ t('processedN', { n: number(task.processed) }) }}</strong>
          </div>
        </section>

        <div v-if="historyCount" class="asa-donut">
          <div class="asa-donut__ring" :style="donutStyle" role="img" :aria-label="t('historyN', { n: historyCount })">
            <div class="asa-donut__hole"><span class="asa-donut__num">{{ historyCount }}</span><span class="asa-donut__cap">{{ t('cap') }}</span></div>
          </div>
          <ul class="asa-legend">
            <li v-for="row in segments.rows" :key="row.key" class="asa-legend__item">
              <span class="asa-legend__dot" :style="{ background: cssColor(row.color) }"></span>
              <span class="asa-legend__label">{{ row.label }}</span><span class="asa-legend__val">{{ row.count }} · {{ pct(row.count) }}%</span>
            </li>
          </ul>
        </div>
        <p v-else class="asa-dash__empty-history">{{ t('emptyHint') }}</p>

        <section class="asa-sources">
          <div class="asa-sources__head"><span class="asa-sources__title">{{ t('sources') }}</span><span class="asa-sources__count">{{ t('enabledOf', { a: enabledProviders.length, b: providers.length }) }}</span></div>
          <div class="asa-sources__chips">
            <span v-for="provider in providers" :key="provider.provider_id" class="asa-chip" :class="{ 'asa-chip--on': provider.enabled }">
              <v-icon :icon="provider.enabled ? 'mdi-check-circle' : 'mdi-circle-outline'" size="13" />{{ providerName(provider) }}
            </span>
            <span v-if="!providers.length" class="asa-sources__empty">{{ t('noSources') }}</span>
          </div>
        </section>

        <section v-if="recent.length" class="asa-recent">
          <div class="asa-recent__head">{{ t('recent') }}</div>
          <ul class="asa-recent__list">
            <li v-for="item in recent.slice(0, 5)" :key="item.unique" class="asa-recent__item">
              <img v-if="item.poster && !failed[item.unique]" class="asa-recent__poster" :src="item.poster" alt="" loading="lazy" @error="failed[item.unique] = true" />
              <span v-else class="asa-recent__poster asa-recent__poster--ph"><v-icon icon="mdi-movie-open-outline" size="16" /></span>
              <div class="asa-recent__meta"><span class="asa-recent__name" :title="mediaName(item)">{{ mediaName(item) }}</span><span class="asa-recent__sub">{{ recentInfo(item) }}</span></div>
            </li>
          </ul>
        </section>
      </div>

      <footer class="asa-dash__footer">
        <a class="asa-dash__open" :href="pluginHref"><v-icon icon="mdi-open-in-new" size="15" />{{ t('open') }}</a>
        <time v-if="lastUpdated" :datetime="new Date(lastUpdated).toISOString()" class="asa-dash__updated">{{ t('updated') }} {{ updatedLabel }}</time>
        <v-btn v-if="!bordered && allowRefresh" :loading="loading" :aria-label="t('refresh')" icon="mdi-refresh" size="small" variant="text" @click="fetchData" />
      </footer>
    </div>
  </div>
</template>

<script setup>
import { computed, getCurrentInstance, onMounted, onUnmounted, reactive, ref, watch } from 'vue'

const props = defineProps({
  config: { type: Object, default: () => ({}) },
  allowRefresh: { type: Boolean, default: true },
  api: { type: Object, default: () => ({}) },
})
const MSG = {
  'zh-CN': {
    title: '自动订阅助手', subtitle: '订阅概览', cap: '保留历史', sources: '来源', subscriptions: '插件订阅', blacklist: '黑名单', history: '历史记录',
    enabled: '已启用', disabled: '已停用', enabledOf: '{a} / {b} 启用', noSources: '无可用来源', recent: '最近订阅',
    emptyHint: '暂无处理历史，启用来源并运行后展示结果分布', running: '正在运行', processedN: '已处理 {n} 项', pausedN: '已暂停 {n} 项', historyN: '当前保留 {n} 条历史记录',
    open: '打开插件', updated: '更新于', loading: '正在加载概览', retry: '重试', refresh: '刷新', apiUnavailable: 'API 不可用', loadError: '数据加载失败：',
    movie: '电影', tv: '剧集', group: '剧集组', unknown: '未知',
    'provider.douban': '豆瓣榜单', 'provider.maoyan': '猫眼榜单', 'provider.popular': '热门媒体', 'provider.mikan': 'Mikan 季度新番', 'provider.netflix': '奈飞榜单',
    'st.subscribed': '已订阅', 'st.media_exists': '媒体库已存在', 'st.subscription_exists': '订阅已存在', 'st.blacklisted': '已忽略',
    'st.filtered': '被过滤', 'st.unrecognized': '未识别', 'st.already_handled': '已处理', 'st.error': '异常', 'st.other': '其他',
  },
  'zh-TW': {
    title: '自動訂閱助手', subtitle: '訂閱概覽', cap: '保留歷史', sources: '來源', subscriptions: '外掛訂閱', blacklist: '黑名單', history: '歷史記錄',
    enabled: '已啟用', disabled: '已停用', enabledOf: '{a} / {b} 啟用', noSources: '無可用來源', recent: '最近訂閱',
    emptyHint: '暫無處理歷史，啟用來源並執行後顯示結果分布', running: '正在執行', processedN: '已處理 {n} 項', pausedN: '已暫停 {n} 項', historyN: '目前保留 {n} 筆歷史記錄',
    open: '開啟外掛', updated: '更新於', loading: '正在載入概覽', retry: '重試', refresh: '重新整理', apiUnavailable: 'API 無法使用', loadError: '資料載入失敗：',
    movie: '電影', tv: '劇集', group: '劇集組', unknown: '未知',
    'provider.douban': '豆瓣榜單', 'provider.maoyan': '貓眼榜單', 'provider.popular': '熱門媒體', 'provider.mikan': 'Mikan 季度新番', 'provider.netflix': '奈飛榜單',
    'st.subscribed': '已訂閱', 'st.media_exists': '媒體庫已存在', 'st.subscription_exists': '訂閱已存在', 'st.blacklisted': '已忽略',
    'st.filtered': '被過濾', 'st.unrecognized': '未識別', 'st.already_handled': '已處理', 'st.error': '異常', 'st.other': '其他',
  },
  'en-US': {
    title: 'Auto Subscribe', subtitle: 'Overview', cap: 'History', sources: 'Sources', subscriptions: 'Subscriptions', blacklist: 'Blacklist', history: 'History',
    enabled: 'Enabled', disabled: 'Disabled', enabledOf: '{a} / {b} enabled', noSources: 'No sources', recent: 'Recent subscriptions',
    emptyHint: 'No history yet. Enable and run a source to see the result distribution.', running: 'Running', processedN: '{n} processed', pausedN: '{n} paused', historyN: '{n} retained history records',
    open: 'Open plugin', updated: 'Updated', loading: 'Loading overview', retry: 'Retry', refresh: 'Refresh', apiUnavailable: 'API unavailable', loadError: 'Failed to load data: ',
    movie: 'Movie', tv: 'TV series', group: 'Episode group', unknown: 'Unknown',
    'provider.douban': 'Douban', 'provider.maoyan': 'Maoyan', 'provider.popular': 'Popular media', 'provider.mikan': 'Mikan seasonal anime', 'provider.netflix': 'Netflix',
    'st.subscribed': 'Subscribed', 'st.media_exists': 'In library', 'st.subscription_exists': 'Already subscribed', 'st.blacklisted': 'Ignored',
    'st.filtered': 'Filtered', 'st.unrecognized': 'Unrecognized', 'st.already_handled': 'Handled', 'st.error': 'Error', 'st.other': 'Other',
  },
}
const inst = getCurrentInstance()
const locale = computed(() => {
  const raw = inst?.appContext?.config?.globalProperties?.$i18n?.locale
  const lang = String(raw?.value || raw || '').toLowerCase()
  return lang.startsWith('en') ? 'en-US' : /tw|hant|hk/.test(lang) ? 'zh-TW' : 'zh-CN'
})
function t(key, params) {
  let text = MSG[locale.value][key] || key
  if (params) for (const key in params) text = text.replaceAll(`{${key}}`, params[key])
  return text
}
const PLUGIN = 'plugin/AutomaticSubscriptionAssistant'
const STATUS_COLORS = { subscribed: 'success', media_exists: 'info', subscription_exists: 'primary', blacklisted: 'secondary', filtered: 'warning', unrecognized: 'secondary', already_handled: 'secondary', error: 'error' }
const loading = ref(true)
const error = ref('')
const hasData = ref(false)
const enabled = ref(false)
const counts = ref({ history: 0, subscriptions: 0, paused: 0, blacklist: 0 })
const byStatus = ref({})
const providers = ref([])
const running = ref([])
const recent = ref([])
const failed = reactive({})
const lastUpdated = ref(0)
const bordered = computed(() => props.config?.attrs?.border !== false)
const refreshSecs = computed(() => number(props.config?.attrs?.refresh))
const pluginHref = computed(() => `#/plugin-app/${encodeURIComponent(props.config?.id || 'AutomaticSubscriptionAssistant')}/blacklist`)
const updatedLabel = computed(() => lastUpdated.value ? new Date(lastUpdated.value).toLocaleTimeString(locale.value, { hour: '2-digit', minute: '2-digit' }) : '')
const historyCount = computed(() => counts.value.history)
const enabledProviders = computed(() => providers.value.filter(provider => provider.enabled))
const metrics = computed(() => [
  { key: 'subscriptions', label: t('subscriptions'), count: counts.value.subscriptions, icon: 'mdi-bell-ring-outline' },
  { key: 'blacklist', label: t('blacklist'), count: counts.value.blacklist, icon: 'mdi-cancel' },
  { key: 'history', label: t('history'), count: historyCount.value, icon: 'mdi-history' },
])
function number(value) {
  const result = Number(value)
  return Number.isFinite(result) && result > 0 ? result : 0
}
const segments = computed(() => {
  const rows = Object.entries(STATUS_COLORS).map(([key, color]) => ({ key, color, count: number(byStatus.value[key]), label: t('st.' + key) })).filter(row => row.count)
  const known = rows.reduce((sum, row) => sum + row.count, 0)
  if (historyCount.value > known) rows.push({ key: 'other', color: 'secondary', count: historyCount.value - known, label: t('st.other') })
  return { rows, sum: rows.reduce((sum, row) => sum + row.count, 0) }
})
function cssColor(color) { return `rgb(var(--v-theme-${color}))` }
const donutStyle = computed(() => {
  if (!segments.value.sum) return { background: 'rgba(var(--v-theme-on-surface), 0.08)' }
  let position = 0
  const stops = segments.value.rows.map(row => {
    const start = position / segments.value.sum * 100
    position += row.count
    return `${cssColor(row.color)} ${start}% ${position / segments.value.sum * 100}%`
  })
  return { background: `conic-gradient(${stops.join(', ')})` }
})
function pct(count) { return segments.value.sum ? Math.round(count / segments.value.sum * 100) : 0 }
function providerName(provider) {
  const key = 'provider.' + provider.provider_id
  return MSG[locale.value][key] || provider.provider_name || provider.name || provider.provider_id
}
function mediaName(item) {
  const parts = [item.title || t('unknown')]
  if (item.type === '电视剧' && item.season != null) parts.push(`S${String(item.season).padStart(2, '0')}`)
  if (item.episode_group) parts.push(`${t('group')}: ${item.episode_group}`)
  return parts.join(' · ')
}
function recentInfo(item) {
  const type = item.type === '电视剧' ? t('tv') : item.type === '电影' ? t('movie') : item.type
  return [item.year, type, item.time].filter(Boolean).join(' · ') || '—'
}
let timer = null
let inFlight = false
let disposed = false
function clearTimer() { if (timer !== null) clearTimeout(timer); timer = null }
function setupTimer() {
  clearTimer()
  if (!disposed && !inFlight && props.allowRefresh && refreshSecs.value) timer = setTimeout(fetchData, refreshSecs.value * 1000)
}
function stopRefresh() { disposed = true; clearTimer() }
async function fetchData() {
  if (inFlight || disposed) return
  clearTimer()
  inFlight = true
  loading.value = true
  error.value = ''
  try {
    if (typeof props.api?.get !== 'function') throw new Error(t('apiUnavailable'))
    const result = await props.api.get(`${PLUGIN}/dashboard?lang=${encodeURIComponent(locale.value)}`)
    if (disposed) return
    if (result?.code !== 0) throw new Error(result?.message || t('unknown'))
    counts.value = Object.fromEntries(['history', 'subscriptions', 'paused', 'blacklist'].map(key => [key, number(result.counts?.[key])]))
    byStatus.value = result.stats?.by_status || {}
    providers.value = Array.isArray(result.providers) ? result.providers : []
    running.value = Array.isArray(result.running) ? result.running : []
    recent.value = Array.isArray(result.recent) ? result.recent.slice(0, 5) : []
    enabled.value = !!result.enabled
    Object.keys(failed).forEach(key => delete failed[key])
    lastUpdated.value = Date.now()
    hasData.value = true
  } catch (e) { if (!disposed) error.value = t('loadError') + (e?.message || String(e)) }
  finally {
    inFlight = false
    if (!disposed) { loading.value = false; setupTimer() }
  }
}
watch([() => props.allowRefresh, refreshSecs], setupTimer)
onMounted(fetchData)
onUnmounted(stopRefresh)
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
.asa-dash__head { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 12px; }
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

.asa-dash__brand, .asa-dash__head-actions { display: flex; align-items: center; gap: 8px; min-inline-size: 0; }
.asa-dash__head-copy { min-inline-size: 0; }
.asa-dash__metrics { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
.asa-dash__metric { display: flex; flex-direction: column; gap: 6px; min-inline-size: 0; padding: 10px; border: 1px solid var(--asa-line); border-radius: 10px; background: rgba(var(--v-theme-primary), 0.04); }
.asa-dash__metric-label { display: flex; align-items: center; gap: 5px; overflow: hidden; font-size: 0.72rem; color: rgba(var(--v-theme-on-surface), 0.65); }
.asa-dash__metric-value { font-size: 1.4rem; line-height: 1.2; font-variant-numeric: tabular-nums; }
.asa-dash__metric-hint, .asa-dash__updated { color: rgba(var(--v-theme-on-surface), 0.55); font-size: 0.68rem; }
.asa-dash__notice { padding: 8px 10px; border-radius: 8px; background: rgba(var(--v-theme-warning), 0.1); color: rgb(var(--v-theme-warning)); font-size: 0.75rem; }
.asa-dash__empty-history { margin: 0; color: rgba(var(--v-theme-on-surface), 0.55); font-size: 0.74rem; line-height: 1.5; }
.asa-dash__running { padding: 10px; border-radius: 10px; background: rgba(var(--v-theme-primary), 0.06); }
.asa-dash__running-title { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; font-size: 0.78rem; color: rgb(var(--v-theme-primary)); }
.asa-dash__running-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; font-size: 0.74rem; }
.asa-dash__running-row strong { font-weight: 500; color: rgba(var(--v-theme-on-surface), 0.6); }
.asa-dash__footer { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; padding-top: 12px; margin-top: 14px; border-top: 1px solid var(--asa-line); }
.asa-dash__open { display: inline-flex; align-items: center; gap: 5px; margin-inline-end: auto; color: rgb(var(--v-theme-primary)); text-decoration: none; font-size: 0.75rem; }
.asa-skel--metric { block-size: 78px; }
@container (width < 340px) {
  .asa-dash__metric { padding: 8px 6px; }
  .asa-dash__metric-label { flex-direction: column; align-items: flex-start; gap: 4px; font-size: 0.68rem; }
  .asa-dash__head-actions { flex-wrap: wrap; justify-content: flex-end; }
}
</style>
