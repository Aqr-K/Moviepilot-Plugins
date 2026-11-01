<template>
  <div class="bl-view">
    <div class="asa-pg-controls">
      <div class="asa-filters">
        <v-btn
          class="asa-filters__trigger"
          :color="hasFilter ? 'primary' : undefined"
          prepend-icon="mdi-filter-variant"
          size="small"
          :variant="hasFilter ? 'tonal' : 'outlined'"
          @click="openFilterDialog"
        >
          {{ t('filter') }}
          <span v-if="activeFilterCount" class="asa-filters__badge">{{ activeFilterCount }}</span>
        </v-btn>
        <v-spacer />
        <v-btn v-if="hasFilter" class="asa-filters__clear" size="small" variant="text" @click="clearFilters">
          <v-icon icon="mdi-filter-off-outline" start />{{ t('clearFilters') }}
        </v-btn>
        <v-btn prepend-icon="mdi-plus" size="small" color="primary" variant="tonal" @click="addOpen = true">{{ t('add') }}</v-btn>
      </div>
      <p class="bl-hint">{{ t('hint') }}</p>
      <v-alert v-if="error" type="warning" variant="tonal" density="compact" class="mb-3">{{ error }}</v-alert>
    </div>

    <ProgressiveList ref="listRef" :progressive="progressive" :count="paged.length" :loading="loading"
      :has-more="paged.length < filtered.length" @load="loadMore">
      <div v-if="loading" class="asa-grid">
        <div v-for="n in pageSize" :key="n" class="asa-skel-card"></div>
      </div>
      <div v-else-if="!filtered.length" class="asa-empty">
        <div class="asa-empty__ico"><v-icon :icon="hasFilter ? 'mdi-filter-off-outline' : 'mdi-cancel'" size="30" /></div>
        <p class="asa-empty__text">{{ t(hasFilter ? 'emptyFiltered' : 'emptyNone') }}</p>
        <p class="asa-empty__hint">{{ t(hasFilter ? 'emptyFilteredHint' : 'emptyNoneHint') }}</p>
        <v-btn v-if="hasFilter" size="small" variant="tonal" @click="clearFilters">{{ t('clearFilters') }}</v-btn>
      </div>
      <div v-else class="asa-grid">
        <MediaCard
          v-for="item in paged"
          :key="item.id"
          :poster="item.poster || ''"
          :name="mediaName(item)"
          :lines="lines(item)"
          :status="{ label: t('ignored'), color: 'rgb(var(--v-theme-error))', icon: 'mdi-cancel' }"
          :more-label="t('more')"
        >
          <template #actions>
            <v-list-item prepend-icon="mdi-restore" :title="t('remove')" @click="removing = item" />
          </template>
        </MediaCard>
      </div>

    </ProgressiveList>
    <v-dialog v-model="filterDialog" max-width="440" scrollable>
      <v-card class="asa-filter-dlg">
        <v-card-title class="asa-filter-dlg__title">
          <v-icon icon="mdi-filter-variant" size="20" />{{ t('filterTitle') }}
        </v-card-title>
        <v-card-text class="asa-filter-dlg__body">
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
    <BlacklistDialog v-model="addOpen" :api="api" @saved="reload" />
    <v-dialog :model-value="!!removing" max-width="380" @update:model-value="v => !acting && !v && (removing = null)">
      <v-card>
        <v-card-title class="text-subtitle-1">{{ t('remove') }}</v-card-title>
        <v-card-text class="text-body-2">{{ removing?.title }}<p class="mt-2">{{ t('removeHint') }}</p></v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn :disabled="acting" variant="text" @click="removing = null">{{ t('cancel') }}</v-btn>
          <v-btn :loading="acting" color="primary" variant="flat" @click="remove">{{ t('remove') }}</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </div>
</template>

<script setup>
import { computed, getCurrentInstance, onMounted, reactive, ref, watch } from 'vue'
import MediaCard from './MediaCard.vue'
import BlacklistDialog from './BlacklistDialog.vue'
import FilterPanel from './FilterPanel.vue'
import ProgressiveList from './ProgressiveList.vue'
import '../styles/mediaViews.css'
const props = defineProps({
  api: { type: Object, default: () => ({}) },
  pageSize: { type: Number, default: 12 },
  page: { type: Number, default: 1 },
  progressive: Boolean,
})
const emit = defineEmits(['update:page', 'update:pageCount'])
const MSG = {
  'zh-CN': { filter: '筛选', filterTitle: '筛选与搜索', clearFilters: '清除筛选', searchLabel: '搜索', searchPh: '搜索名称…', filterYear: '发行年份', yearFrom: '起始年', yearTo: '结束年', filterType: '类型', filterAll: '全部', movie: '电影', tv: '剧集', applyFilter: '应用', resetFilter: '重置', emptyNone: '暂无黑名单', emptyNoneHint: '将不想自动订阅的影视加入黑名单', emptyFiltered: '没有符合筛选条件的记录', emptyFilteredHint: '试试调整搜索或筛选条件', hint: '已忽略的影视不会再被自动订阅，规则不会随历史清理而删除。', search: '搜索黑名单', add: '手动添加', refresh: '刷新', empty: '暂无符合条件的黑名单', ignored: '已忽略', more: '更多', remove: '移出黑名单', removeHint: '移出后，下次运行将重新按正常订阅规则评估。已有成功历史仍参与去重。', cancel: '取消', type: '类型', scope: '忽略范围', all: '全部季', year: '发行年份', time: '加入时间', failed: '操作失败' },
  'zh-TW': { filter: '篩選', filterTitle: '篩選與搜尋', clearFilters: '清除篩選', searchLabel: '搜尋', searchPh: '搜尋名稱…', filterYear: '發行年份', yearFrom: '起始年', yearTo: '結束年', filterType: '類型', filterAll: '全部', movie: '電影', tv: '劇集', applyFilter: '套用', resetFilter: '重設', emptyNone: '暫無黑名單', emptyNoneHint: '將不想自動訂閱的影視加入黑名單', emptyFiltered: '沒有符合篩選條件的記錄', emptyFilteredHint: '試試調整搜尋或篩選條件', hint: '已忽略的影視不會再被自動訂閱，規則不會隨歷史清理而刪除。', search: '搜尋黑名單', add: '手動新增', refresh: '重新整理', empty: '暫無符合條件的黑名單', ignored: '已忽略', more: '更多', remove: '移出黑名單', removeHint: '移出後，下次執行將重新按正常訂閱規則評估。已有成功歷史仍參與去重。', cancel: '取消', type: '類型', scope: '忽略範圍', all: '全部季', year: '發行年份', time: '加入時間', failed: '操作失敗' },
  'en-US': { filter: 'Filters', filterTitle: 'Filter & search', clearFilters: 'Clear filters', searchLabel: 'Search', searchPh: 'Search name…', filterYear: 'Release year', yearFrom: 'From', yearTo: 'To', filterType: 'Type', filterAll: 'All', movie: 'Movies', tv: 'TV series', applyFilter: 'Apply', resetFilter: 'Reset', emptyNone: 'No blacklist entries yet', emptyNoneHint: 'Add media you want to skip automatically', emptyFiltered: 'No records match the filters', emptyFilteredHint: 'Try adjusting the search or filters', hint: 'Ignored media will be skipped automatically. Rules survive history cleanup.', search: 'Search blacklist', add: 'Add manually', refresh: 'Refresh', empty: 'No matching blacklist entries', ignored: 'Ignored', more: 'More', remove: 'Remove from blacklist', removeHint: 'Future runs will evaluate this media normally. Successful history still prevents duplicate subscriptions.', cancel: 'Cancel', type: 'Type', scope: 'Ignore', all: 'All seasons', year: 'Release year', time: 'Added', failed: 'Action failed' },
}
const inst = getCurrentInstance()
function t(key) {
  const raw = inst?.appContext?.config?.globalProperties?.$i18n?.locale
  const lang = String(raw?.value || raw || '').toLowerCase()
  return MSG[lang.startsWith('en') ? 'en-US' : /tw|hant|hk/.test(lang) ? 'zh-TW' : 'zh-CN'][key] || key
}
const rows = ref([])
const emptyFilters = () => ({ keyword: '', yearMin: null, yearMax: null, mtypes: [] })
const cloneFilters = source => ({ ...source, mtypes: [...source.mtypes] })
const filters = reactive(emptyFilters())
const draft = reactive(emptyFilters())
const filterDialog = ref(false)
const filterFields = computed(() => [
  { type: 'search', key: 'keyword', label: t('searchLabel'), placeholder: t('searchPh') },
  { type: 'year-range', keyMin: 'yearMin', keyMax: 'yearMax', label: t('filterYear'), minText: t('yearFrom'), maxText: t('yearTo') },
  { type: 'select', key: 'mtypes', multi: true, label: t('filterType'), icon: 'mdi-shape-outline', allText: t('filterAll'),
    items: [{ title: t('movie'), value: '电影' }, { title: t('tv'), value: '电视剧' }] },
])
const activeFilterCount = computed(() => (filters.keyword ? 1 : 0) +
  (filters.yearMin != null || filters.yearMax != null ? 1 : 0) + (filters.mtypes.length ? 1 : 0))
const hasFilter = computed(() => activeFilterCount.value > 0)
function openFilterDialog() { Object.assign(draft, cloneFilters(filters)); filterDialog.value = true }
function applyFilterDialog() { Object.assign(filters, cloneFilters(draft)); filterDialog.value = false }
function resetDraft() { Object.assign(draft, emptyFilters()) }
function clearFilters() { Object.assign(filters, emptyFilters()) }
const loading = ref(false)
const error = ref('')
const addOpen = ref(false)
const removing = ref(null)
const acting = ref(false)
const filtered = computed(() => {
  const keyword = (filters.keyword || '').trim().toLowerCase()
  return rows.value.filter(row => {
    if (keyword && !String(row.title || '').toLowerCase().includes(keyword)) return false
    if (filters.mtypes.length && !filters.mtypes.includes(row.type)) return false
    if (filters.yearMin != null || filters.yearMax != null) {
      const year = parseInt(row.year, 10)
      if (!Number.isFinite(year)) return false
      if (filters.yearMin != null && year < filters.yearMin) return false
      if (filters.yearMax != null && year > filters.yearMax) return false
    }
    return true
  })
})
const pageCount = computed(() => Math.max(1, Math.ceil(filtered.value.length / props.pageSize)))
const listRef = ref(null)
const visibleCount = ref(props.pageSize)
const paged = computed(() => props.progressive ? filtered.value.slice(0, visibleCount.value)
  : filtered.value.slice((props.page - 1) * props.pageSize, props.page * props.pageSize))
function loadMore() { visibleCount.value += props.pageSize }
watch([filtered, () => props.progressive, () => props.pageSize], () => {
  visibleCount.value = props.pageSize
  if (props.progressive) listRef.value?.scrollToTop()
})
watch(pageCount, count => emit('update:pageCount', count), { immediate: true })
watch(filters, () => emit('update:page', 1), { deep: true })
function mediaName(item) {
  return item.type === '电视剧' && item.season != null
    ? `${item.title} · S${String(item.season).padStart(2, '0')}` : item.title
}
function lines(item) {
  return [
    { icon: 'mdi-shape-outline', label: t('type'), value: item.type },
    { icon: 'mdi-cancel', label: t('scope'), value: item.type === '电视剧' ? item.season == null ? t('all') : `S${String(item.season).padStart(2, '0')}` : '—' },
    { icon: 'mdi-clock-outline', label: t('time'), value: item.time || '—' },
    { icon: 'mdi-calendar', label: t('year'), value: item.year || '—' },
  ]
}
let requestSeq = 0
async function reload() {
  const seq = ++requestSeq
  loading.value = true
  error.value = ''
  try {
    const result = await props.api.get('plugin/AutomaticSubscriptionAssistant/blacklist')
    if (seq !== requestSeq) return
    if (result?.code !== 0) throw new Error(result?.message || t('failed'))
    rows.value = Array.isArray(result.list) ? result.list : []
  } catch (e) { if (seq === requestSeq) error.value = e?.message || String(e) }
  finally { if (seq === requestSeq) loading.value = false }
}
async function remove() {
  if (acting.value || !removing.value) return
  acting.value = true
  try {
    const result = await props.api.post('plugin/AutomaticSubscriptionAssistant/blacklist/delete', { ids: [removing.value.id] })
    if (result?.code !== 0) throw new Error(result?.message || t('failed'))
    removing.value = null
    await reload()
  } catch (e) { error.value = e?.message || String(e); removing.value = null }
  finally { acting.value = false }
}
defineExpose({ reload })
onMounted(reload)
</script>

<style scoped>
.bl-view { container-type: inline-size; }
.bl-hint { margin: 0 0 14px; font-size: 0.78rem; line-height: 1.5; color: rgba(var(--v-theme-on-surface), 0.55); }
</style>
