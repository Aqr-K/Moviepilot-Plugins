<template>
  <div class="sv">
    <!-- 工具条：搜索 + 筛选（桌面与移动端统一为弹窗）+ 多选开关 -->
    <div class="sv-tools">
      <v-btn
        class="sv-tools__trigger"
        :color="hasFilter ? 'primary' : undefined"
        prepend-icon="mdi-filter-variant"
        size="small"
        :variant="hasFilter ? 'tonal' : 'outlined'"
        @click="openFilterDialog"
      >
        {{ t('filter') }}
        <span v-if="activeFilterCount" class="sv-tools__badge">{{ activeFilterCount }}</span>
      </v-btn>
      <v-spacer />
      <v-btn v-if="hasFilter" size="small" variant="text" @click="clearFilters">
        <v-icon icon="mdi-filter-off-outline" start />{{ t('clearFilters') }}
      </v-btn>
      <v-btn
        :color="selectMode ? 'primary' : undefined"
        :variant="selectMode ? 'flat' : 'tonal'"
        size="small"
        prepend-icon="mdi-checkbox-multiple-marked-outline"
        @click="toggleSelectMode"
      >{{ selectMode ? t('exitSelect') : t('select') }}</v-btn>
    </div>

    <!-- 批量操作条：选本页 / 选全部 / 清除 -->
    <div v-if="selectMode" class="sv-batch">
      <span class="sv-batch__count">{{ t('selectedN', { n: selected.size }) }}</span>
      <v-btn size="small" variant="text" prepend-icon="mdi-checkbox-marked-outline" @click="selectCurrentPage">{{ t('selPage') }}</v-btn>
      <v-btn size="small" variant="text" prepend-icon="mdi-select-all" @click="selectAll">{{ t('selAll', { n: filtered.length }) }}</v-btn>
      <v-btn v-if="selected.size" size="small" variant="text" @click="selected.clear()">{{ t('selClear') }}</v-btn>
      <v-spacer />
      <v-btn :disabled="!selected.size" color="success" size="small" variant="tonal" prepend-icon="mdi-play" @click="askBatch('resume')">{{ t('resume') }}</v-btn>
      <v-btn :disabled="!selected.size" color="warning" size="small" variant="tonal" prepend-icon="mdi-pause" @click="askBatch('pause')">{{ t('pause') }}</v-btn>
      <v-btn :disabled="!selected.size" color="error" size="small" variant="tonal" prepend-icon="mdi-bell-off-outline" @click="askBatch('delete')">{{ t('unsub') }}</v-btn>
    </div>

    <v-alert v-if="error" class="mb-3" density="compact" type="warning" variant="tonal">{{ error }}</v-alert>

    <!-- 加载骨架：数量跟随每页条数，与数据网格等高，避免切换/翻页闪烁 -->
    <div v-if="loading" class="asa-grid">
      <div v-for="n in pageSize" :key="n" class="asa-skel-card"></div>
    </div>

    <!-- 空态 -->
    <div v-else-if="!filtered.length" class="sv-empty">
      <div class="sv-empty__ico"><v-icon icon="mdi-bell-outline" size="30" /></div>
      <p class="sv-empty__text">{{ hasFilter ? t('emptyFiltered') : t('emptyNone') }}</p>
      <p class="sv-empty__hint">{{ t('emptyHint') }}</p>
    </div>

    <!-- 订阅卡片网格 -->
    <div v-else class="asa-grid">
      <MediaCard
        v-for="item in paged"
        :key="item.id"
        :poster="item.poster || ''"
        :name="item.name || t('unknown')"
        :lines="cardLines(item)"
        :status="stateBadge(item.state)"
        :selectable="selectMode"
        :selected="selected.has(item.id)"
        :more-label="t('more')"
        @toggle="toggleOne(item.id)"
      >
        <template #actions>
          <v-list-item v-if="item.state === 'S'" base-color="success" prepend-icon="mdi-play" :title="t('resume')" @click="askOne('resume', item)" />
          <v-list-item v-else base-color="warning" prepend-icon="mdi-pause" :title="t('pause')" @click="askOne('pause', item)" />
          <v-list-item base-color="error" prepend-icon="mdi-bell-off-outline" :title="t('unsub')" @click="askOne('delete', item)" />
        </template>
      </MediaCard>
    </div>

    <!-- 二次确认对话框 -->
    <v-dialog v-model="confirm.open" max-width="380">
      <v-card>
        <v-card-title class="text-subtitle-1">{{ confirmTitle }}</v-card-title>
        <v-card-text class="text-body-2">{{ confirmText }}</v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="confirm.open = false">{{ t('cancel') }}</v-btn>
          <v-btn :color="confirm.kind === 'delete' ? 'error' : 'primary'" :loading="acting" variant="flat" @click="runConfirm">{{ t('ok') }}</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- 移动端筛选弹窗（搜索 / 发行年份范围 / 类型单选 / 状态多选） -->
    <v-dialog v-model="filterDialog" max-width="440" scrollable>
      <v-card class="sv-filter-dlg">
        <v-card-title class="sv-filter-dlg__title">
          <v-icon icon="mdi-filter-variant" size="20" />{{ t('filterTitle') }}
        </v-card-title>
        <v-card-text class="sv-filter-dlg__body">
          <FilterPanel :state="draft" :fields="filterFields" stacked />
        </v-card-text>
        <v-card-actions>
          <v-btn variant="text" @click="resetDraft">{{ t('resetFilter') }}</v-btn>
          <v-spacer />
          <v-btn variant="text" @click="filterDialog = false">{{ t('cancel') }}</v-btn>
          <v-btn color="primary" variant="flat" @click="applyFilterDialog">{{ t('applyFilter') }}</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </div>
</template>

<script setup>
import { computed, getCurrentInstance, onMounted, reactive, ref, watch } from 'vue'
import MediaCard from './MediaCard.vue'
import FilterPanel from './FilterPanel.vue'

const props = defineProps({
  api: { type: Object, default: () => ({}) },
  pageSize: { type: Number, default: 12 },
  page: { type: Number, default: 1 },
})
const emit = defineEmits(['changed', 'update:page', 'update:pageCount'])
const PLUGIN = 'plugin/AutomaticSubscriptionAssistant'
const THEME_COLORS = { primary: 1, secondary: 1, success: 1, info: 1, warning: 1, error: 1 }

const STATE_META = {
  R: { color: 'success', icon: 'mdi-bell-ring-outline' },
  N: { color: 'info', icon: 'mdi-bell-plus-outline' },
  P: { color: 'warning', icon: 'mdi-bell-sleep-outline' },
  S: { color: 'grey', icon: 'mdi-pause-circle-outline' },
}

const MSG = {
  'zh-CN': {
    select: '多选', exitSelect: '退出多选', selectedN: '已选 {n} 项', searchPh: '搜索名称…',
    selPage: '选本页', selAll: '选全部（{n}）', selClear: '清除选择',
    resume: '恢复', pause: '暂停', unsub: '退订', cancel: '取消', ok: '确定', unknown: '未知', more: '更多',
    all: '全部', 'st.R': '订阅中', 'st.N': '新建', 'st.P': '待定', 'st.S': '已暂停',
    filter: '筛选', filterTitle: '筛选与搜索', filterType: '类型', filterStatus: '状态', filterYear: '发行年份',
    yearFrom: '起始年', yearTo: '结束年', filterAll: '全部', searchLabel: '搜索', applyFilter: '应用', resetFilter: '重置',
    clearFilters: '清除筛选', 'mt.movie': '电影', 'mt.tv': '电视剧',
    kType: '类型', kSource: '来源', kTime: '订阅时间', kYear: '发行年份', source: '自动订阅助手',
    emptyNone: '暂无本插件创建的订阅', emptyFiltered: '没有符合条件的订阅', emptyHint: '启用来源运行后，订阅会出现在这里',
    error: '获取订阅失败：', actionFailed: '操作失败：',
    confirmDelete: '确认退订选中的 {n} 个订阅？此操作不可撤销。',
    confirmPause: '确认暂停选中的 {n} 个订阅？', confirmResume: '确认恢复选中的 {n} 个订阅？',
    titleDelete: '退订确认', titlePause: '暂停确认', titleResume: '恢复确认',
  },
  'zh-TW': {
    select: '多選', exitSelect: '退出多選', selectedN: '已選 {n} 項', searchPh: '搜尋名稱…',
    selPage: '選本頁', selAll: '選全部（{n}）', selClear: '清除選擇',
    resume: '恢復', pause: '暫停', unsub: '退訂', cancel: '取消', ok: '確定', unknown: '未知', more: '更多',
    all: '全部', 'st.R': '訂閱中', 'st.N': '新建', 'st.P': '待定', 'st.S': '已暫停',
    filter: '篩選', filterTitle: '篩選與搜尋', filterType: '類型', filterStatus: '狀態', filterYear: '發行年份',
    yearFrom: '起始年', yearTo: '結束年', filterAll: '全部', searchLabel: '搜尋', applyFilter: '套用', resetFilter: '重設',
    clearFilters: '清除篩選', 'mt.movie': '電影', 'mt.tv': '電視劇',
    kType: '類型', kSource: '來源', kTime: '訂閱時間', kYear: '發行年份', source: '自動訂閱助手',
    emptyNone: '暫無本外掛建立的訂閱', emptyFiltered: '沒有符合條件的訂閱', emptyHint: '啟用來源執行後，訂閱會出現在這裡',
    error: '取得訂閱失敗：', actionFailed: '操作失敗：',
    confirmDelete: '確認退訂選中的 {n} 個訂閱？此操作不可復原。',
    confirmPause: '確認暫停選中的 {n} 個訂閱？', confirmResume: '確認恢復選中的 {n} 個訂閱？',
    titleDelete: '退訂確認', titlePause: '暫停確認', titleResume: '恢復確認',
  },
  'en-US': {
    select: 'Select', exitSelect: 'Done', selectedN: '{n} selected', searchPh: 'Search name…',
    selPage: 'This page', selAll: 'All ({n})', selClear: 'Clear',
    resume: 'Resume', pause: 'Pause', unsub: 'Unsubscribe', cancel: 'Cancel', ok: 'OK', unknown: 'Unknown', more: 'More',
    all: 'All', 'st.R': 'Active', 'st.N': 'New', 'st.P': 'Pending', 'st.S': 'Paused',
    filter: 'Filters', filterTitle: 'Filter & search', filterType: 'Type', filterStatus: 'Status', filterYear: 'Release year',
    yearFrom: 'From', yearTo: 'To', filterAll: 'All', searchLabel: 'Search', applyFilter: 'Apply', resetFilter: 'Reset',
    clearFilters: 'Clear filters', 'mt.movie': 'Movies', 'mt.tv': 'TV series',
    kType: 'Type', kSource: 'Source', kTime: 'Added', kYear: 'Year', source: 'Auto Subscribe Assistant',
    emptyNone: 'No subscriptions created by this plugin', emptyFiltered: 'No subscriptions match', emptyHint: 'Subscriptions appear here after sources run',
    error: 'Failed to load subscriptions: ', actionFailed: 'Action failed: ',
    confirmDelete: 'Unsubscribe {n} selected subscription(s)? This cannot be undone.',
    confirmPause: 'Pause {n} selected subscription(s)?', confirmResume: 'Resume {n} selected subscription(s)?',
    titleDelete: 'Confirm unsubscribe', titlePause: 'Confirm pause', titleResume: 'Confirm resume',
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

const loading = ref(true)
const error = ref('')
const rows = ref([])
// 统一筛选模型（管理）：关键词 / 发行年份范围 / 类型(单选) / 状态(多选)。
// 「留空即不过滤（全部）」：keyword='' / year=null / mtype=null / statuses=[]。桌面内联、移动弹窗共用；
// 弹窗编辑 draft 副本，点「应用」整体拷回（管理为客户端筛选，拷回即时生效）。
const emptyFilters = () => ({ keyword: '', yearMin: null, yearMax: null, mtype: null, statuses: [] })
function cloneFilters(s) {
  return { keyword: s.keyword, yearMin: s.yearMin, yearMax: s.yearMax, mtype: s.mtype, statuses: [...s.statuses] }
}
const filters = reactive(emptyFilters())
const draft = reactive(emptyFilters())
const filterDialog = ref(false)
const selectMode = ref(false)
const selected = reactive(new Set())
const acting = ref(false)
const confirm = reactive({ open: false, kind: 'delete', ids: [] })

const filtered = computed(() => {
  const kw = (filters.keyword || '').trim().toLowerCase()
  const { yearMin, yearMax, mtype, statuses } = filters
  return rows.value.filter(r => {
    if (kw && !String(r.name || '').toLowerCase().includes(kw)) return false
    if (mtype && r.type !== mtype) return false
    if (statuses.length && !statuses.includes(r.state)) return false
    if (yearMin != null || yearMax != null) {
      const y = parseInt(r.year, 10)
      if (!Number.isFinite(y)) return false
      if (yearMin != null && y < yearMin) return false
      if (yearMax != null && y > yearMax) return false
    }
    return true
  })
})
const pageCount = computed(() => Math.max(1, Math.ceil(filtered.value.length / props.pageSize)))
const paged = computed(() => {
  const start = (props.page - 1) * props.pageSize
  return filtered.value.slice(start, start + props.pageSize)
})
// 状态多选项：始终列出 4 态，带当前计数。
const stateItems = computed(() => {
  const counts = {}
  rows.value.forEach(r => { counts[r.state] = (counts[r.state] || 0) + 1 })
  return ['R', 'S', 'P', 'N'].map(k => ({ title: `${t('st.' + k)}${counts[k] ? ` (${counts[k]})` : ''}`, value: k }))
})
const typeItems = computed(() => [
  { title: t('mt.movie'), value: '电影' },
  { title: t('mt.tv'), value: '电视剧' },
])
// FilterPanel 字段配置（管理）：类型单选、状态多选 + 发行年份范围 + 搜索。
const filterFields = computed(() => [
  { type: 'search', key: 'keyword', label: t('searchLabel'), placeholder: t('searchPh') },
  { type: 'year-range', keyMin: 'yearMin', keyMax: 'yearMax', label: t('filterYear'), minText: t('yearFrom'), maxText: t('yearTo') },
  { type: 'select', key: 'mtype', multi: false, items: typeItems.value, label: t('filterType'), icon: 'mdi-shape-outline', allText: t('filterAll') },
  { type: 'select', key: 'statuses', multi: true, items: stateItems.value, label: t('filterStatus'), icon: 'mdi-flag-outline', allText: t('filterAll') },
])
const activeFilterCount = computed(() =>
  (filters.keyword ? 1 : 0) +
  (filters.yearMin != null || filters.yearMax != null ? 1 : 0) +
  (filters.mtype ? 1 : 0) + (filters.statuses.length ? 1 : 0))
const hasFilter = computed(() => activeFilterCount.value > 0)
const confirmTitle = computed(() => t({ delete: 'titleDelete', pause: 'titlePause', resume: 'titleResume' }[confirm.kind]))
const confirmText = computed(() => t({ delete: 'confirmDelete', pause: 'confirmPause', resume: 'confirmResume' }[confirm.kind], { n: confirm.ids.length }))

function cssColor(name) {
  if (THEME_COLORS[name]) return `rgb(var(--v-theme-${name}))`
  return 'rgba(var(--v-theme-on-surface), 0.45)'
}
function stateBadge(state) {
  const m = STATE_META[state] || { color: 'grey', icon: 'mdi-bell-outline' }
  const label = MSG['zh-CN']['st.' + state] ? t('st.' + state) : (state || t('unknown'))
  return { label, color: cssColor(m.color), icon: m.icon }
}
function cardLines(item) {
  return [
    { icon: 'mdi-shape-outline', label: t('kType'), value: item.type || t('unknown') },
    { icon: 'mdi-robot-outline', label: t('kSource'), value: t('source') },
    { icon: 'mdi-clock-outline', label: t('kTime'), value: item.date || t('unknown') },
    { icon: 'mdi-calendar', label: t('kYear'), value: item.year || t('unknown') },
  ]
}

function clearFilters() { Object.assign(filters, emptyFilters()) }
// 移动端筛选弹窗：打开拷入 draft，「应用」拷回，「重置」清空 draft。
function openFilterDialog() { Object.assign(draft, cloneFilters(filters)); filterDialog.value = true }
function applyFilterDialog() { Object.assign(filters, cloneFilters(draft)); filterDialog.value = false }
function resetDraft() { Object.assign(draft, emptyFilters()) }
function toggleSelectMode() { selectMode.value = !selectMode.value; if (!selectMode.value) selected.clear() }
function toggleOne(id) { selected.has(id) ? selected.delete(id) : selected.add(id) }
function selectCurrentPage() { paged.value.forEach(r => selected.add(r.id)) }
function selectAll() { filtered.value.forEach(r => selected.add(r.id)) }
function askBatch(kind) { if (selected.size) { confirm.kind = kind; confirm.ids = [...selected]; confirm.open = true } }
function askOne(kind, item) { confirm.kind = kind; confirm.ids = [item.id]; confirm.open = true }

async function runConfirm() {
  acting.value = true
  error.value = ''
  try {
    if (!props.api || typeof props.api.post !== 'function') throw new Error('API')
    if (confirm.kind === 'delete') {
      await props.api.post(`${PLUGIN}/subscribes/delete`, { ids: confirm.ids })
    } else {
      await props.api.post(`${PLUGIN}/subscribes/state`, { ids: confirm.ids, state: confirm.kind === 'pause' ? 'S' : 'R' })
    }
    confirm.ids.forEach(id => selected.delete(id))
    confirm.open = false
    await fetchSubs()
    emit('changed')
  } catch (e) {
    error.value = t('actionFailed') + (e?.message || e)
  } finally {
    acting.value = false
  }
}

async function fetchSubs() {
  loading.value = true
  error.value = ''
  try {
    if (!props.api || typeof props.api.get !== 'function') throw new Error('API')
    const res = await props.api.get(`${PLUGIN}/subscribes`)
    rows.value = Array.isArray(res?.list) ? res.list : []
  } catch (e) {
    error.value = t('error') + (e?.message || e)
    rows.value = []
  } finally {
    loading.value = false
  }
}

// 向父级同步页数；筛选变化（含弹窗「应用」拷回）时请求父级复位到第 1 页。
watch(pageCount, v => emit('update:pageCount', v), { immediate: true })
watch(filters, () => emit('update:page', 1), { deep: true })

defineExpose({ reload: fetchSubs })
onMounted(fetchSubs)
</script>

<style scoped>
.sv { container-type: inline-size; }
.sv-tools { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 12px; }
.sv-tools__trigger { position: relative; }
.sv-tools__badge {
  display: inline-flex; align-items: center; justify-content: center;
  min-inline-size: 18px; block-size: 18px; margin-inline-start: 6px; padding: 0 5px;
  border-radius: 9px; background: rgb(var(--v-theme-primary)); color: rgb(var(--v-theme-on-primary));
  font-size: 0.7rem; font-weight: 700; line-height: 1;
}
.sv-filter-dlg__title { display: flex; align-items: center; gap: 8px; font-size: 1rem; font-weight: 700; }
.sv-filter-dlg__body { padding-block: 10px 6px; }

.sv-batch {
  display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-bottom: 12px; padding: 6px 12px;
  border-radius: 10px; background: rgba(var(--v-theme-primary), 0.06); border: 1px solid rgba(var(--v-theme-primary), 0.16);
}
.sv-batch__count { font-size: 0.8rem; font-weight: 600; color: rgba(var(--v-theme-on-surface), 0.8); margin-inline-end: 4px; }

/* 网格与骨架样式复用 Page.vue 中的 .asa-grid / .asa-skel-card（同一联邦块，非 scoped 冲突时以本地为准） */
.asa-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 12px; }
.asa-skel-card { block-size: 116px; border-radius: 12px; background: rgba(var(--v-theme-on-surface), 0.08); animation: sv-pulse 1.4s ease infinite; }
@keyframes sv-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }

.sv-empty { display: flex; flex-direction: column; align-items: center; gap: 8px; padding: 44px 16px; text-align: center; }
.sv-empty__ico { display: flex; align-items: center; justify-content: center; inline-size: 58px; block-size: 58px; border-radius: 50%; background: rgba(var(--v-theme-primary), 0.1); color: rgb(var(--v-theme-primary)); }
.sv-empty__text { margin: 4px 0 0; font-size: 0.92rem; font-weight: 600; }
.sv-empty__hint { margin: 0; color: rgba(var(--v-theme-on-surface), 0.55); font-size: 0.76rem; }

@container (width < 480px) {
  .asa-grid { grid-template-columns: 1fr; }
}
</style>
