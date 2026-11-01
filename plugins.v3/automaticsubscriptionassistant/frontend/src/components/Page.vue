<template>
  <section ref="pageRef" class="asa-page" :class="{ 'asa-page--progressive': sidebarDesktop }" :style="sidebarDesktop ? { blockSize: sidebarHeight } : undefined">
    <!-- 面包屑风格头部（与订阅配置一致） -->
    <header class="asa-pg-head">
      <div class="asa-pg-head__brand">
        <div class="asa-pg-head__logo"><v-icon icon="mdi-rss" size="20" /></div>
        <div class="asa-pg-head__identity">
          <div class="asa-pg-head__crumbs">
            <span>MoviePilot</span>
            <v-icon icon="mdi-chevron-right" size="13" />
            <span>{{ t('plugin') }}</span>
          </div>
          <h1 class="asa-pg-head__title">{{ t('appTitle') }}</h1>
        </div>
      </div>
      <div class="asa-pg-head__actions">
        <v-btn :loading="loading" :aria-label="t('refresh')" icon="mdi-refresh" size="small" variant="text" @click="reloadCurrent" />
        <v-btn :aria-label="t('close')" icon="mdi-close" size="small" variant="text" @click="emit('close')" />
      </div>
    </header>

    <PluginTabs :active="view" :tabs="tabDefs" @select="onTab" />

    <div class="asa-pg-scroll" ref="containerRef">
      <!-- 订阅历史 -->
      <div v-if="view === 'history'" class="asa-pg-body">
        <div class="asa-pg-controls">
          <v-alert v-if="error" class="mb-3" density="compact" type="warning" variant="tonal">{{ error }}</v-alert>

          <!-- 统计块（点击可按状态筛选） -->
          <div class="asa-stats">
            <button
              v-for="s in statCards"
              :key="s.key"
              type="button"
              :class="['asa-stat', `asa-stat--${s.color}`, { 'asa-stat--active': filters.statuses.includes(s.key) }]"
              @click="toggleStatus(s.key)"
            >
              <span class="asa-stat__num">{{ s.count }}</span>
              <span class="asa-stat__label">{{ s.label }}</span>
            </button>
          </div>

          <!-- 搜索 + 筛选：桌面与移动端统一为「筛选」弹窗触发按钮 + 多选开关 -->
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
            <v-btn
              v-if="hasFilter" class="asa-filters__clear" size="small" variant="text" @click="clearFilters"
            >
              <v-icon icon="mdi-filter-off-outline" start />{{ t('clearFilters') }}
            </v-btn>
            <v-btn
              :color="selectMode ? 'primary' : undefined" :variant="selectMode ? 'flat' : 'tonal'" size="small"
              prepend-icon="mdi-checkbox-multiple-marked-outline" @click="toggleSelectMode"
            >{{ selectMode ? t('exitSelect') : t('select') }}</v-btn>
          </div>

          <!-- 批量操作条：选本页 / 选全部 / 清除 -->
          <div v-if="selectMode" class="asa-batch">
            <span class="asa-batch__count">{{ t('selectedN', { n: selected.size }) }}</span>
            <v-btn size="small" variant="text" prepend-icon="mdi-checkbox-marked-outline" @click="selectCurrentPage">{{ t(sidebarDesktop ? 'selLoaded' : 'selPage') }}</v-btn>
            <v-btn size="small" variant="text" prepend-icon="mdi-select-all" :loading="selectingAll" @click="selectAll">{{ t('selAll', { n: total }) }}</v-btn>
            <v-btn v-if="selected.size" size="small" variant="text" @click="selected.clear()">{{ t('selClear') }}</v-btn>
            <v-spacer />
            <v-btn :disabled="!selected.size" color="error" size="small" variant="tonal" prepend-icon="mdi-trash-can-outline" @click="askDelete([...selected])">{{ t('batchDelete') }}</v-btn>
          </div>

        </div>
        <ProgressiveList
          ref="historyListRef" :progressive="sidebarDesktop" :count="items.length"
          :loading="loading || historyRefreshing || loadingMore" :has-more="historyHasMore" :error="historyMoreError"
          @load="loadMoreHistory"
        >
          <!-- 加载骨架：数量跟随每页条数（列×3 或移动端行数），与数据网格等高，避免切换/翻页闪烁 -->
          <div v-if="loading" class="asa-grid">
            <div v-for="n in pageSize" :key="n" class="asa-skel-card"></div>
          </div>

          <!-- 空态 -->
          <div v-else-if="!items.length" class="asa-empty">
            <div class="asa-empty__ico"><v-icon :icon="hasFilter ? 'mdi-filter-off-outline' : 'mdi-playlist-star'" size="30" /></div>
            <p class="asa-empty__text">{{ hasFilter ? t('emptyFiltered') : t('emptyNone') }}</p>
            <p class="asa-empty__hint">{{ hasFilter ? t('emptyFilteredHint') : t('emptyNoneHint') }}</p>
            <v-btn v-if="hasFilter" size="small" variant="tonal" @click="clearFilters">{{ t('clearFilters') }}</v-btn>
          </div>

          <!-- 横版卡片墙 -->
          <div v-else class="asa-grid">
            <MediaCard
              v-for="item in items"
              :key="item.unique"
              :poster="item.poster || ''"
              :name="mediaName(item)"
              :lines="cardLines(item)"
              :status="statusBadge(item)"
              :selectable="selectMode"
              :selected="selected.has(item.unique)"
              :more-label="t('more')"
              @toggle="toggleOne(item.unique)"
            >
              <template #actions>
                <v-list-item prepend-icon="mdi-file-document-edit-outline" :title="t('supplement')" @click="openSupplement(item)" />
                <v-list-item prepend-icon="mdi-cancel" :title="t('blacklistAdd')" @click="openBlacklist(item)" />
                <v-list-item
                  v-if="['error', 'unrecognized'].includes(item.status)"
                  prepend-icon="mdi-refresh" :title="t('reRecognize')"
                  :disabled="recognizing.has(item.unique)"
                  @click="reRecognize(item)"
                />
                <v-list-item
                  base-color="error" prepend-icon="mdi-trash-can-outline" :title="t('delete')"
                  @click="askDelete([item.unique])"
                />
              </template>
            </MediaCard>
          </div>
        </ProgressiveList>
      </div>

      <!-- 订阅管理 -->
      <BlacklistView
        v-else-if="view === 'blacklist'"
        ref="blacklistRef"
        class="asa-pg-body"
        :api="api"
        :progressive="sidebarDesktop"
        :page-size="pageSize"
        v-model:page="blacklistPage"
        @update:page-count="v => blacklistCount = v"
      />
      <SubscribeView
        ref="subscribeRef"
        v-else
        class="asa-pg-body"
        :api="api"
        :progressive="sidebarDesktop"
        :page-size="pageSize"
        v-model:page="managePage"
        @update:page-count="v => manageCount = v"
        @changed="fetchStatus"
      />
    </div>

    <!-- 固定页脚：桌面「页码 + 跳转」左对齐；移动端页码占满可用宽度（自动截断、始终含首尾页），
         「每页行数 + 指定页跳转」收入弹窗，避免窄屏页码被跳转框覆盖。 -->
    <footer v-if="!sidebarDesktop && (activePageCount > 1 || isSingleCol)" class="asa-pg-foot" :class="{ 'asa-pg-foot--mobile': isSingleCol }">
      <!-- 页码（flex 伸缩 + min-width:0 → v-pagination 按可用宽度自动截断） -->
      <div v-if="activePageCount > 1" class="asa-pg-foot__nav">
        <v-pagination
          v-if="view === 'history'"
          v-model="page" active-color="primary" density="comfortable" :length="pageCount"
          :total-visible="paginationVisible" :size="paginationSize"
          @update:model-value="onPageChange"
        />
        <v-pagination
          v-else-if="view === 'manage'"
          v-model="managePage" active-color="primary" density="comfortable" :length="manageCount"
          :total-visible="paginationVisible" :size="paginationSize"
        />
        <v-pagination
          v-else
          v-model="blacklistPage" active-color="primary" density="comfortable" :length="blacklistCount"
          :total-visible="paginationVisible" :size="paginationSize"
        />
      </div>
      <!-- 移动端：每页行数 + 跳转 收入弹窗 -->
      <v-btn
        v-if="isSingleCol"
        class="asa-pg-foot__more"
        :aria-label="t('pageOptions')"
        icon="mdi-tune-variant"
        size="small"
        variant="tonal"
        @click="footDialog = true"
      />
      <!-- 桌面端：指定页跳转内联 -->
      <div v-if="!isSingleCol && activePageCount > 10" class="asa-pg-foot__jump">
        <v-text-field v-model.number="jumpTo" density="compact" hide-details type="number" :min="1" :max="activePageCount" variant="outlined" class="asa-pg-foot__jf" @keyup.enter="doJump" />
        <v-btn size="small" variant="tonal" @click="doJump">{{ t('go') }}</v-btn>
      </div>
      <v-spacer v-if="!isSingleCol" />
    </footer>

    <!-- 移动端页脚设置弹窗：每页行数 + 指定页跳转 -->
    <v-dialog v-model="footDialog" max-width="340">
      <v-card class="asa-foot-dlg">
        <v-card-title class="asa-foot-dlg__title">
          <v-icon icon="mdi-tune-variant" size="20" />{{ t('pageOptions') }}
        </v-card-title>
        <v-card-text class="asa-foot-dlg__body">
          <div class="asa-foot-dlg__field">
            <label class="asa-foot-dlg__label">{{ t('perPage') }}</label>
            <v-select
              v-model="mobileRows" :items="ROW_OPTIONS" density="compact" hide-details variant="outlined"
              @update:model-value="onRowsChange"
            />
          </div>
          <div v-if="activePageCount > 10" class="asa-foot-dlg__field">
            <label class="asa-foot-dlg__label">{{ t('jumpLabel', { n: activePageCount }) }}</label>
            <div class="asa-foot-dlg__jump">
              <v-text-field
                v-model.number="jumpTo" class="asa-foot-dlg__jf"
                density="compact" hide-details type="number" :min="1" :max="activePageCount"
                variant="outlined" @keyup.enter="doJumpClose"
              />
              <v-btn color="primary" variant="flat" @click="doJumpClose">{{ t('go') }}</v-btn>
            </div>
          </div>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="footDialog = false">{{ t('close') }}</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <BlacklistDialog v-model="blacklistOpen" :api="api" :target="blacklistTarget" @saved="fetchStatus" />
    <SupplementDialog v-model="supplementOpen" :api="api" :target="supplementTarget" @changed="refreshSupplement" />

    <!-- 二次确认（删除历史） -->
    <v-dialog v-model="confirm.open" max-width="380">
      <v-card>
        <v-card-title class="text-subtitle-1">{{ t('confirmTitle') }}</v-card-title>
        <v-card-text class="text-body-2">{{ t('confirmDeleteN', { n: confirm.ids.length }) }}</v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="confirm.open = false">{{ t('cancel') }}</v-btn>
          <v-btn color="error" :loading="deletingBatch" variant="flat" @click="runDelete">{{ t('delete') }}</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- 移动端筛选弹窗（搜索 / 发行年份范围 / 类型多选 / 状态多选 / 来源多选） -->
    <v-dialog v-model="filterDialog" max-width="440" scrollable>
      <v-card class="asa-filter-dlg">
        <v-card-title class="asa-filter-dlg__title">
          <v-icon icon="mdi-filter-variant" size="20" />{{ t('filterTitle') }}
        </v-card-title>
        <v-card-text class="asa-filter-dlg__body">
          <FilterPanel :state="draft" :fields="historyFilterFields" stacked />
        </v-card-text>
        <v-card-actions>
          <v-btn variant="text" @click="resetDraft">{{ t('resetFilter') }}</v-btn>
          <v-spacer />
          <v-btn variant="text" @click="filterDialog = false">{{ t('cancel') }}</v-btn>
          <v-btn color="primary" variant="flat" @click="applyFilterDialog">{{ t('applyFilter') }}</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </section>
</template>

<script setup>
import { computed, getCurrentInstance, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import MediaCard from './MediaCard.vue'
import SubscribeView from './SubscribeView.vue'
import BlacklistView from './BlacklistView.vue'
import BlacklistDialog from './BlacklistDialog.vue'
import PluginTabs from './PluginTabs.vue'
import FilterPanel from './FilterPanel.vue'
import ProgressiveList from './ProgressiveList.vue'
import SupplementDialog from './SupplementDialog.vue'
import '../styles/mediaViews.css'
import { useMediaGrid } from '../composables/useMediaGrid'

const props = defineProps({
  api: { type: Object, default: () => ({}) },
  show_switch: { type: Boolean, default: true },
  initialView: { type: String, default: '' },
  sidebar: Boolean,
})
const emit = defineEmits(['switch', 'close', 'action'])

const PLUGIN = 'plugin/AutomaticSubscriptionAssistant'
const VIEW_KEY = 'asa.pageView'
const THEME_COLORS = { primary: 1, secondary: 1, success: 1, info: 1, warning: 1, error: 1 }

const STATUS_META = {
  subscribed: { color: 'success', icon: 'mdi-check-circle' },
  media_exists: { color: 'info', icon: 'mdi-database-check-outline' },
  subscription_exists: { color: 'primary', icon: 'mdi-bell-check-outline' },
  blacklisted: { color: 'error', icon: 'mdi-cancel' },
  filtered: { color: 'warning', icon: 'mdi-filter-remove-outline' },
  unrecognized: { color: 'blue-grey', icon: 'mdi-help-circle-outline' },
  already_handled: { color: 'grey', icon: 'mdi-history' },
  error: { color: 'error', icon: 'mdi-alert-circle-outline' },
}
const STAT_ORDER = ['subscribed', 'media_exists', 'subscription_exists', 'blacklisted', 'filtered', 'unrecognized', 'error']

const MSG = {
  'zh-CN': {
    supplement: '补充编辑', blacklist: '黑名单', blacklistAdd: '加入黑名单', 'st.blacklisted': '已忽略', plugin: '插件', appTitle: '自动订阅助手', title: '订阅历史', manageTitle: '订阅管理', config: '订阅配置',
    records: '共 {n} 条记录', refresh: '刷新', close: '关闭', searchPh: '搜索名称…',
    filterSource: '来源', filterStatus: '状态', filterType: '类型', clearFilters: '清除筛选',
    filter: '筛选', filterTitle: '筛选与搜索', filterYear: '发行年份', yearFrom: '起始年', yearTo: '结束年',
    filterAll: '全部', searchLabel: '搜索', applyFilter: '应用', resetFilter: '重置',
    'mt.movie': '电影', 'mt.tv': '剧集',
    select: '多选', exitSelect: '退出多选', selectedN: '已选 {n} 项', batchDelete: '批量删除',
    selLoaded: '选择已加载', selPage: '选本页', selAll: '选全部（{n}）', selClear: '清除选择',
    emptyFiltered: '没有符合筛选条件的记录', emptyFilteredHint: '试试调整搜索或筛选条件',
    emptyNone: '暂无订阅历史记录', emptyNoneHint: '启用来源并运行后，这里会记录每次订阅结果',
    confirmTitle: '删除确认', confirmDeleteN: '确认删除选中的 {n} 条记录？', cancel: '取消', delete: '删除',
    unknown: '未知', go: '跳转', perPage: '每页行数', pageOptions: '每页行数与跳转', jumpLabel: '跳转到第几页（共 {n} 页）',
    kType: '类型', kGroup: '剧集组', kSource: '来源', kTime: '订阅时间', kYear: '发行年份',
    historyError: '获取历史记录失败：', deleteFailed: '删除失败：', apiUnavailable: 'API 不可用',
    reRecognize: '重新识别', recognizeFailed: '重新识别失败：', more: '更多',
    'st.subscribed': '已订阅', 'st.media_exists': '媒体库已存在', 'st.subscription_exists': '订阅已存在',
    'st.filtered': '被过滤', 'st.unrecognized': '未识别', 'st.already_handled': '已处理', 'st.error': '异常',
  },
  'zh-TW': {
    supplement: '補充編輯', blacklist: '黑名單', blacklistAdd: '加入黑名單', 'st.blacklisted': '已忽略', plugin: '外掛', appTitle: '自動訂閱助手', title: '訂閱歷史', manageTitle: '訂閱管理', config: '訂閱設定',
    records: '共 {n} 筆記錄', refresh: '重新整理', close: '關閉', searchPh: '搜尋名稱…',
    filterSource: '來源', filterStatus: '狀態', filterType: '類型', clearFilters: '清除篩選',
    filter: '篩選', filterTitle: '篩選與搜尋', filterYear: '發行年份', yearFrom: '起始年', yearTo: '結束年',
    filterAll: '全部', searchLabel: '搜尋', applyFilter: '套用', resetFilter: '重設',
    'mt.movie': '電影', 'mt.tv': '劇集',
    select: '多選', exitSelect: '退出多選', selectedN: '已選 {n} 項', batchDelete: '批量刪除',
    selLoaded: '選擇已載入', selPage: '選本頁', selAll: '選全部（{n}）', selClear: '清除選擇',
    emptyFiltered: '沒有符合篩選條件的記錄', emptyFilteredHint: '試試調整搜尋或篩選條件',
    emptyNone: '暫無訂閱歷史記錄', emptyNoneHint: '啟用來源並執行後，這裡會記錄每次訂閱結果',
    confirmTitle: '刪除確認', confirmDeleteN: '確認刪除選中的 {n} 筆記錄？', cancel: '取消', delete: '刪除',
    unknown: '未知', go: '跳轉', perPage: '每頁筆數', pageOptions: '每頁筆數與跳轉', jumpLabel: '跳轉到第幾頁（共 {n} 頁）',
    kType: '類型', kGroup: '劇集組', kSource: '來源', kTime: '訂閱時間', kYear: '發行年份',
    historyError: '取得歷史記錄失敗：', deleteFailed: '刪除失敗：', apiUnavailable: 'API 不可用',
    reRecognize: '重新識別', recognizeFailed: '重新識別失敗：', more: '更多',
    'st.subscribed': '已訂閱', 'st.media_exists': '媒體庫已存在', 'st.subscription_exists': '訂閱已存在',
    'st.filtered': '被過濾', 'st.unrecognized': '未識別', 'st.already_handled': '已處理', 'st.error': '異常',
  },
  'en-US': {
    supplement: 'Edit and subscribe', blacklist: 'Blacklist', blacklistAdd: 'Add to blacklist', 'st.blacklisted': 'Ignored', plugin: 'Plugin', appTitle: 'Auto Subscribe', title: 'History', manageTitle: 'Manage', config: 'Settings',
    records: '{n} records', refresh: 'Refresh', close: 'Close', searchPh: 'Search name…',
    filterSource: 'Source', filterStatus: 'Status', filterType: 'Type', clearFilters: 'Clear filters',
    filter: 'Filters', filterTitle: 'Filter & search', filterYear: 'Release year', yearFrom: 'From', yearTo: 'To',
    filterAll: 'All', searchLabel: 'Search', applyFilter: 'Apply', resetFilter: 'Reset',
    'mt.movie': 'Movies', 'mt.tv': 'TV series',
    select: 'Select', exitSelect: 'Done', selectedN: '{n} selected', batchDelete: 'Delete',
    selLoaded: 'Loaded items', selPage: 'This page', selAll: 'All ({n})', selClear: 'Clear',
    emptyFiltered: 'No records match the filters', emptyFilteredHint: 'Try adjusting the search or filters',
    emptyNone: 'No subscription history yet', emptyNoneHint: 'Once sources are enabled and run, results appear here',
    confirmTitle: 'Confirm delete', confirmDeleteN: 'Delete {n} selected record(s)?', cancel: 'Cancel', delete: 'Delete',
    unknown: 'Unknown', go: 'Go', perPage: 'Rows per page', pageOptions: 'Rows & jump', jumpLabel: 'Jump to page (of {n})',
    kType: 'Type', kGroup: 'Episode group', kSource: 'Source', kTime: 'Time', kYear: 'Year',
    historyError: 'Failed to load history: ', deleteFailed: 'Delete failed: ', apiUnavailable: 'API unavailable',
    reRecognize: 'Re-identify', recognizeFailed: 'Re-identify failed: ', more: 'More',
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
function statusMeta(status) { return STATUS_META[status] || { color: 'grey', icon: 'mdi-help-circle-outline' } }
function statusLabel(status) { return STATUS_META[status] ? t('st.' + status) : (status || t('unknown')) }

const blacklistRef = ref(null)
const subscribeRef = ref(null)
const blacklistOpen = ref(false)
const supplementOpen = ref(false)
const supplementTarget = ref({})
function openSupplement(item) { supplementTarget.value = item; supplementOpen.value = true }
async function refreshSupplement() { await Promise.all([fetchStatus(), fetchHistory(true)]) }
const blacklistTarget = ref({})
function openBlacklist(item) { blacklistTarget.value = { ...item, kind: 'history' }; blacklistOpen.value = true }
const view = ref(props.initialView || readInitialView())
const loading = ref(true)
const error = ref('')
const items = ref([])
const total = ref(0)
const page = ref(1)
const blacklistPage = ref(1)
const blacklistCount = ref(1)
const managePage = ref(1)
const manageCount = ref(1)
const jumpTo = ref(1)
const footDialog = ref(false)  // 移动端页脚「每页行数 + 跳转」弹窗
const statusCounts = ref({})
const providerNames = reactive({})
const providerList = ref([])
// 统一筛选模型（历史）：关键词 / 发行年份范围 / 类型(多) / 状态(多) / 来源(多)。
// 「留空即不过滤（全部）」：keyword='' / year=null / 多选=[]。桌面内联、移动弹窗共用此对象；
// 弹窗编辑 draft 副本，点「应用」后整体拷回 filters，避免弹窗内每次输入都触发服务端重取。
const EMPTY_FILTERS = () => ({ keyword: '', yearMin: null, yearMax: null, mtypes: [], statuses: [], providers: [] })
function cloneFilters(s) {
  return { keyword: s.keyword, yearMin: s.yearMin, yearMax: s.yearMax,
    mtypes: [...s.mtypes], statuses: [...s.statuses], providers: [...s.providers] }
}
const filters = reactive(EMPTY_FILTERS())
const draft = reactive(EMPTY_FILTERS())
const filterDialog = ref(false)
const selectMode = ref(false)
const selected = reactive(new Set())
const selectingAll = ref(false)
const recognizing = reactive(new Set())  // 正在「重新识别」的记录 unique 集合（按钮 loading）
const confirm = reactive({ open: false, ids: [] })
const deletingBatch = ref(false)

// 一次性读取目标视图：仅当由「订阅配置」标签跳回时携带；读后即清，保证下次打开始终默认订阅历史。
function readInitialView() {
  try {
    const v = localStorage.getItem(VIEW_KEY)
    if (v === 'manage' || v === 'history' || v === 'blacklist') { localStorage.removeItem(VIEW_KEY); return v }
  } catch { /* ignore */ }
  return 'history'
}

const ROW_OPTIONS = [10, 25, 50, 100]
const ROWS_KEY = 'asa.mobileRows'
function readRows() {
  try { const n = parseInt(localStorage.getItem(ROWS_KEY), 10); return ROW_OPTIONS.includes(n) ? n : 10 } catch { return 10 }
}
const mobileRows = ref(readRows())

const pageRef = ref(null)
const historyListRef = ref(null)
const viewportWidth = ref(typeof window === 'undefined' ? 0 : window.innerWidth)
const sidebarHeight = ref('calc(100dvh - 80px)')
const sidebarDesktop = computed(() => props.sidebar && viewportWidth.value >= 960)
function updateSidebarLayout() {
  if (typeof window === 'undefined') return
  viewportWidth.value = window.innerWidth
  if (pageRef.value) sidebarHeight.value = `${Math.max(240, window.innerHeight - pageRef.value.getBoundingClientRect().top - 8)}px`
}

const { containerRef, cols, measure } = useMediaGrid()
// 单列（移动端）按用户所选行数分页；多列（桌面）锁 3 行、列数自适应。
const isSingleCol = computed(() => cols.value <= 1)
const pageSize = computed(() => sidebarDesktop.value ? 24 : (isSingleCol.value ? mobileRows.value : Math.max(cols.value * 3, 1)))
const loadingMore = ref(false)
const historyRefreshing = ref(false)
const historyMoreError = ref('')
const historyLoadedPage = ref(0)
const historyExhausted = ref(false)
const historyHasMore = computed(() => !historyExhausted.value && items.value.length < total.value)

const showSwitch = computed(() => props.show_switch)
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))
const activePageCount = computed(() => (view.value === 'history' ? pageCount.value : view.value === 'blacklist' ? blacklistCount.value : manageCount.value))
// 移动端不锁死 total-visible → v-pagination 依据自身容器宽度自动截断（永远含首尾页）；桌面维持 5。
// 固定可见页码数（不依赖 ResizeObserver 自动截断，避免真机测量不准导致页码数字消失）；
// 每页行数/跳转已移入弹窗，页脚仅页码 + 设置按钮，空间充裕，固定 5 个不会溢出。
const paginationVisible = computed(() => 5)
const paginationSize = computed(() => (isSingleCol.value ? 'x-small' : 'small'))
const activeFilterCount = computed(() =>
  (filters.keyword ? 1 : 0) +
  (filters.yearMin != null || filters.yearMax != null ? 1 : 0) +
  (filters.mtypes.length ? 1 : 0) + (filters.statuses.length ? 1 : 0) + (filters.providers.length ? 1 : 0))
const hasFilter = computed(() => activeFilterCount.value > 0)
const tabDefs = computed(() => {
  const base = [
    { key: 'history', label: t('title'), icon: 'mdi-history' },
    { key: 'manage', label: t('manageTitle'), icon: 'mdi-bell-cog-outline' },
    { key: 'blacklist', label: t('blacklist'), icon: 'mdi-cancel' },
  ]
  if (showSwitch.value) base.push({ key: 'config', label: t('config'), icon: 'mdi-cog-outline' })
  return base
})
const statCards = computed(() =>
  STAT_ORDER.map(key => ({ key, label: t('st.' + key), color: STATUS_META[key].color, count: statusCounts.value[key] || 0 })))
const providerOptions = computed(() =>
  providerList.value.map(p => ({ title: p.provider_name || p.provider_id, value: p.provider_id })))
const statusSelectItems = computed(() => STAT_ORDER.map(key => ({ title: t('st.' + key), value: key })))
const typeSelectItems = computed(() => [
  { title: t('mt.movie'), value: '电影' },
  { title: t('mt.tv'), value: '电视剧' },
])
// FilterPanel 字段配置（历史）：类型多选、状态多选、来源多选 + 发行年份范围 + 搜索。
const historyFilterFields = computed(() => [
  { type: 'search', key: 'keyword', label: t('searchLabel'), placeholder: t('searchPh') },
  { type: 'year-range', keyMin: 'yearMin', keyMax: 'yearMax', label: t('filterYear'), minText: t('yearFrom'), maxText: t('yearTo') },
  { type: 'select', key: 'mtypes', multi: true, items: typeSelectItems.value, label: t('filterType'), icon: 'mdi-shape-outline', allText: t('filterAll') },
  { type: 'select', key: 'statuses', multi: true, items: statusSelectItems.value, label: t('filterStatus'), icon: 'mdi-flag-outline', allText: t('filterAll') },
  { type: 'select', key: 'providers', multi: true, items: providerOptions.value, label: t('filterSource'), icon: 'mdi-filter-variant', allText: t('filterAll') },
])

function providerName(pid) { return providerNames[pid] || pid || t('unknown') }
function cssColor(name) {
  if (THEME_COLORS[name]) return `rgb(var(--v-theme-${name}))`
  if (name === 'blue-grey') return 'rgba(var(--v-theme-on-surface), 0.55)'
  return 'rgba(var(--v-theme-on-surface), 0.4)'
}
function statusBadge(item) {
  const m = statusMeta(item.status)
  return { label: statusLabel(item.status), color: cssColor(m.color), icon: m.icon }
}
function mediaName(item) {
  const parts = [item.title || t('unknown')]
  if (item.type === '电视剧' && item.season != null) parts.push(`S${String(item.season).padStart(2, '0')}`)
  if (item.episode_group) parts.push(`${t('kGroup')}: ${item.episode_group}`)
  return parts.join(' · ')
}
function cardLines(item) {
  return [
    { icon: 'mdi-shape-outline', label: t('kType'), value: item.type || t('unknown') },
    { icon: 'mdi-rss', label: t('kSource'), value: providerName(item.provider) },
    { icon: 'mdi-clock-outline', label: t('kTime'), value: item.time || t('unknown') },
    { icon: 'mdi-calendar', label: t('kYear'), value: item.year || t('unknown') },
  ]
}

function qs(params) {
  return Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== null && v !== '')
    .map(([k, v]) => `${k}=${encodeURIComponent(v)}`)
    .join('&')
}
function normalizeList(res) {
  if (Array.isArray(res)) return res
  if (res && Array.isArray(res.list)) return res.list
  if (res && Array.isArray(res.items)) return res.items
  if (res && Array.isArray(res.data)) return res.data
  return []
}

// 历史筛选 → 查询参数：多选以逗号连接（后端按逗号切分，向后兼容单值）；空数组/空值经 qs 过滤丢弃。
function historyQuery() {
  return {
    keyword: filters.keyword,
    provider: filters.providers.join(','),
    status: filters.statuses.join(','),
    mtype: filters.mtypes.join(','),
    year_min: filters.yearMin,
    year_max: filters.yearMax,
  }
}

let fetchSeq = 0
async function fetchHistory(silent = false, append = false) {
  if (append && (!sidebarDesktop.value || loading.value || historyRefreshing.value || loadingMore.value || !historyHasMore.value)) return
  // 请求时序守卫：列数测量稳定/翻页会触发多次取数（不同 count/page），
  // 仅采纳最新一次的响应，丢弃过期响应（否则小 count 的旧响应可能覆盖大 count → 只剩 2 行）。
  const seq = ++fetchSeq
  const progressive = sidebarDesktop.value
  const requestPage = progressive ? (append ? historyLoadedPage.value + 1 : 1) : page.value
  if (append) loadingMore.value = true
  else {
    historyRefreshing.value = true
    loadingMore.value = false
    if (!silent) loading.value = true
    error.value = ''
  }
  historyMoreError.value = ''
  try {
    if (!props.api || typeof props.api.get !== 'function') throw new Error(t('apiUnavailable'))
    const query = qs({ ...historyQuery(), page: requestPage, count: pageSize.value })
    const res = await props.api.get(`${PLUGIN}/history?${query}`)
    if (seq !== fetchSeq) return
    if (res?.code != null && res.code !== 0) throw new Error(res.message || t('unknown'))
    const records = normalizeList(res)
    const previousCount = items.value.length
    items.value = append
      ? [...new Map([...items.value, ...records].map(item => [item.unique, item])).values()]
      : records
    total.value = Number(res?.total) || items.value.length
    historyLoadedPage.value = requestPage
    historyExhausted.value = !records.length || (append && items.value.length === previousCount)
    if (progressive && !append) historyListRef.value?.scrollToTop()
    if (!progressive && page.value > pageCount.value) {
      // 越界页（例如把最后一页删空了）服务端返回空数组。只把页码改回去不够：
      // 列表仍是那份空结果，界面会显示成「有 N 页却一条都没有」。必须按纠正后的
      // 页码重新取一次。
      page.value = pageCount.value
      return fetchHistory(silent)
    }
  } catch (e) {
    if (seq !== fetchSeq) return
    if (append) historyMoreError.value = t('historyError') + (e?.message || e)
    else {
      error.value = t('historyError') + (e?.message || e)
      items.value = []
      total.value = 0
    }
  } finally {
    if (seq === fetchSeq) { loading.value = false; loadingMore.value = false; historyRefreshing.value = false; emit('action') }
  }
}
function loadMoreHistory() { return fetchHistory(true, true) }

async function fetchStatus() {
  try {
    if (!props.api || typeof props.api.get !== 'function') return
    const res = await props.api.get(`${PLUGIN}/status?lang=${encodeURIComponent(locale.value)}`)
    statusCounts.value = res?.stats?.by_status || {}
    const list = Array.isArray(res?.providers) ? res.providers : []
    providerList.value = list
    list.forEach(p => { providerNames[p.provider_id] = p.provider_name || p.provider_id })
  } catch {
    statusCounts.value = {}
  }
}

function onTab(key) {
  if (key === 'config') {
    try { localStorage.setItem(VIEW_KEY, view.value) } catch { /* ignore */ }
    emit('switch')
    return
  }
  view.value = key
}
function reloadCurrent() {
  fetchStatus()
  if (view.value === 'history') fetchHistory()
  else if (view.value === 'blacklist') blacklistRef.value?.reload()
  else subscribeRef.value?.reload()
}
function applyFilters() { page.value = 1; fetchHistory() }
// 统计卡片点击：切换该状态在多选集合中的存在。
function toggleStatus(key) {
  const i = filters.statuses.indexOf(key)
  if (i >= 0) filters.statuses.splice(i, 1)
  else filters.statuses.push(key)
  applyFilters()
}
function clearFilters() { Object.assign(filters, EMPTY_FILTERS()); applyFilters() }
// 移动端筛选弹窗：打开拷入 draft，「应用」拷回并重取，「重置」清空 draft。
function openFilterDialog() { Object.assign(draft, cloneFilters(filters)); filterDialog.value = true }
function applyFilterDialog() { Object.assign(filters, cloneFilters(draft)); filterDialog.value = false; applyFilters() }
function resetDraft() { Object.assign(draft, EMPTY_FILTERS()) }
function onPageChange() {
  fetchHistory(true)  // 静默翻页：不切换到骨架屏，避免容器闪烁/高度变形
  if (typeof window !== 'undefined') window.scrollTo({ top: 0, behavior: 'smooth' })
}
function doJump() {
  const n = Math.min(Math.max(parseInt(jumpTo.value, 10) || 1, 1), activePageCount.value)
  if (view.value === 'history') {
    if (n !== page.value) { page.value = n; onPageChange() }
  } else if (view.value === 'blacklist') {
    blacklistPage.value = n
  } else {
    managePage.value = n
  }
}
function doJumpClose() { doJump(); footDialog.value = false }

function toggleSelectMode() {
  selectMode.value = !selectMode.value
  if (!selectMode.value) {
    selectionSeq++
    selectingAll.value = false
    selected.clear()
  }
}
function toggleOne(u) { selected.has(u) ? selected.delete(u) : selected.add(u) }
function selectCurrentPage() { items.value.forEach(it => it.unique && selected.add(it.unique)) }
let selectionSeq = 0
async function selectAll() {
  // 选全部：只取当前筛选下的身份键，不拉整行记录。
  // 与列表共用 fetchSeq：请求途中用户改了筛选条件就作废本次结果，
  // 否则会把已经看不见的记录悄悄勾上，接着的批量删除就删错了对象。
  const seq = fetchSeq
  const selection = ++selectionSeq
  selectingAll.value = true
  try {
    if (!props.api || typeof props.api.get !== 'function') throw new Error(t('apiUnavailable'))
    const res = await props.api.get(`${PLUGIN}/history/uniques?${qs(historyQuery())}`)
    if (seq !== fetchSeq || selection !== selectionSeq) return
    const uniques = Array.isArray(res?.uniques) ? res.uniques : []
    uniques.forEach(u => u && selected.add(u))
  } catch (e) {
    if (seq !== fetchSeq || selection !== selectionSeq) return
    error.value = t('historyError') + (e?.message || e)
  } finally {
    if (selection === selectionSeq) selectingAll.value = false
  }
}
function askDelete(ids) { if (ids && ids.length) { confirm.ids = [...ids]; confirm.open = true } }

async function runDelete() {
  deletingBatch.value = true
  error.value = ''
  try {
    if (!props.api || typeof props.api.post !== 'function') throw new Error(t('apiUnavailable'))
    const res = await props.api.post(`${PLUGIN}/history/batch-delete`, { uniques: confirm.ids })
    if (res?.code !== 0) throw new Error(res?.message || t('deleteFailed'))
    confirm.ids.forEach(u => selected.delete(u))
    confirm.open = false
    await fetchStatus()
    await fetchHistory(true)
  } catch (e) {
    error.value = t('deleteFailed') + (e?.message || e)
  } finally {
    deletingBatch.value = false
  }
}

function onRowsChange() {
  try { localStorage.setItem(ROWS_KEY, String(mobileRows.value)) } catch { /* ignore */ }
  page.value = 1; managePage.value = 1; blacklistPage.value = 1
}

// 重新识别一条异常记录：部分媒体（未上映/季度预告）识别时 tmdb/bangumi 尚无记录而异常，
// 允许用户稍后手动再跑一次识别 + 订阅。成功后刷新统计与列表（该条状态随之更新/移出异常）。
async function reRecognize(item) {
  if (!item || !item.unique || recognizing.has(item.unique)) return
  recognizing.add(item.unique)
  error.value = ''
  try {
    if (!props.api || typeof props.api.post !== 'function') throw new Error(t('apiUnavailable'))
    const res = await props.api.post(`${PLUGIN}/history/recognize`, { unique: item.unique })
    if (res && res.code === 0) {
      await fetchStatus()
      await fetchHistory(true)
    } else {
      error.value = t('recognizeFailed') + ((res && res.message) || '')
    }
  } catch (e) {
    error.value = t('recognizeFailed') + (e?.message || e)
  } finally {
    recognizing.delete(item.unique)
  }
}

// 每页条数变化（列数变化或移动端改行数）→ 历史静默重取；订阅管理由 pageSize prop 响应式重切。
watch([pageSize, sidebarDesktop], () => { if (view.value === 'history') fetchHistory(true) })
// 订阅管理页数变化时收敛当前页；切换视图后清空选择并重新测量网格列数。
watch(blacklistCount, c => { if (blacklistPage.value > c) blacklistPage.value = c })
watch(manageCount, c => { if (managePage.value > c) managePage.value = c })
watch(view, () => {
  fetchSeq++
  loading.value = false
  loadingMore.value = false
  historyRefreshing.value = false
  selectionSeq++
  selectingAll.value = false
  selectMode.value = false
  selected.clear()
  if (view.value === 'history') fetchHistory()
  nextTick(() => measure())
})

onMounted(() => {
  updateSidebarLayout()
  if (typeof window !== 'undefined') window.addEventListener('resize', updateSidebarLayout, { passive: true })
  fetchStatus()
  if (view.value === 'history') fetchHistory()
})
onBeforeUnmount(() => {
  fetchSeq++
  selectionSeq++
  if (typeof window !== 'undefined') window.removeEventListener('resize', updateSidebarLayout)
})
</script>

<style scoped>
.asa-page {
  container-type: inline-size;
  color: rgb(var(--v-theme-on-surface));
  --asa-radius: var(--app-surface-radius, 12px);
  --asa-line: rgba(var(--v-theme-on-surface), 0.08);
}
.asa-page, .asa-page * { box-sizing: border-box; }

/* 桌面侧栏只滚动卡片列表，页头、标签、统计与工具区保留在可视区域。 */
.asa-page--progressive { display: flex; flex-direction: column; min-block-size: 0; overflow: hidden; }
.asa-page--progressive > .asa-pg-head,
.asa-page--progressive > :deep(.asa-tabs) { flex: 0 0 auto; }
.asa-page--progressive .asa-pg-scroll { display: flex; flex: 1 1 auto; min-block-size: 0; overflow: hidden; }
.asa-page--progressive :deep(.asa-pg-body) {
  display: flex; flex-direction: column; flex: 1 1 auto; min-block-size: 0; min-inline-size: 0; padding-block-end: 0;
}
.asa-page--progressive :deep(.asa-pg-controls) { flex: 0 0 auto; }

/* 面包屑风格头部（与 Config 一致） */
.asa-pg-head {
  position: sticky; z-index: 5; inset-block-start: 0;
  display: flex; align-items: center; justify-content: space-between; gap: 16px;
  min-block-size: 64px; padding: 10px 16px;
  border-block-end: 1px solid rgba(var(--v-theme-on-surface), 0.1);
  background: var(--app-grouped-list-background, rgb(var(--v-theme-surface)));
}
.asa-pg-head__brand { display: flex; align-items: center; gap: 12px; min-inline-size: 0; }
.asa-pg-head__logo {
  display: flex; align-items: center; justify-content: center; flex: 0 0 40px;
  block-size: 40px; inline-size: 40px; border-radius: 11px;
  background: rgba(var(--v-theme-primary), 0.12); color: rgb(var(--v-theme-primary));
}
.asa-pg-head__identity { min-inline-size: 0; }
.asa-pg-head__crumbs { display: flex; align-items: center; gap: 2px; color: rgba(var(--v-theme-on-surface), 0.5); font-size: 0.68rem; }
.asa-pg-head__title { margin: 2px 0 0; font-size: 1.05rem; font-weight: 700; line-height: 1.3; }
.asa-pg-head__actions { display: flex; align-items: center; gap: 8px; flex: 0 0 auto; }

.asa-pg-body { padding: 14px 16px; }

.asa-stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(88px, 1fr)); gap: 10px; margin-bottom: 14px; }
.asa-stat {
  --asa-c: var(--v-theme-primary);
  display: flex; flex-direction: column; gap: 2px; padding: 11px 12px;
  border: 1px solid rgba(var(--asa-c), 0.2); border-radius: var(--asa-radius);
  background: rgba(var(--asa-c), 0.06); cursor: pointer; text-align: start;
  transition: background 0.15s ease, transform 0.15s ease, box-shadow 0.15s ease;
}
.asa-stat:hover { transform: translateY(-1px); background: rgba(var(--asa-c), 0.11); }
.asa-stat--active { box-shadow: 0 0 0 2px rgb(var(--asa-c)) inset; background: rgba(var(--asa-c), 0.14); }
.asa-stat__num { color: rgb(var(--asa-c)); font-size: 1.35rem; font-weight: 700; line-height: 1.1; font-variant-numeric: tabular-nums; }
.asa-stat__label { color: rgba(var(--v-theme-on-surface), 0.62); font-size: 0.7rem; }
.asa-stat--success { --asa-c: var(--v-theme-success); }
.asa-stat--info { --asa-c: var(--v-theme-info); }
.asa-stat--primary { --asa-c: var(--v-theme-primary); }
.asa-stat--warning { --asa-c: var(--v-theme-warning); }
.asa-stat--error { --asa-c: var(--v-theme-error); }
.asa-stat--blue-grey, .asa-stat--grey { --asa-c: var(--v-theme-secondary); }

.asa-batch {
  display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-bottom: 12px; padding: 6px 12px;
  border-radius: 10px; background: rgba(var(--v-theme-primary), 0.06); border: 1px solid rgba(var(--v-theme-primary), 0.16);
}
.asa-batch__count { font-size: 0.8rem; font-weight: 600; color: rgba(var(--v-theme-on-surface), 0.8); margin-inline-end: 4px; }

.asa-pg-foot {
  position: sticky; z-index: 4; inset-block-end: 0;
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  padding: 8px 16px; border-block-start: 1px solid rgba(var(--v-theme-on-surface), 0.12);
  background: var(--app-grouped-list-background, rgb(var(--v-theme-surface)));
}
.asa-pg-foot__nav { display: flex; align-items: center; gap: 10px; min-inline-size: 0; }
.asa-pg-foot__nav :deep(.v-pagination__list) { display: flex; margin: 0; }
/* 图标可能高于紧凑按钮，按点击区域居中，避免网格内容从顶部溢出。 */
.asa-pg-foot__nav :deep(.v-pagination__prev .v-btn__content),
.asa-pg-foot__nav :deep(.v-pagination__next .v-btn__content) {
  position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
}
.asa-pg-foot__jump { display: flex; align-items: center; gap: 6px; flex: 0 0 auto; }
.asa-pg-foot__jf { inline-size: 72px; }
.asa-pg-foot__jf :deep(.v-field) {
  --v-input-control-height: 30px;
  --v-field-input-padding-top: 0px;
  --v-field-input-padding-bottom: 0px;
}
.asa-pg-foot__more { flex: 0 0 auto; }

/* 宿主可配置大圆角，描边起始段不能小于圆角半径，否则左侧弧度会被压扁。 */
.asa-pg-foot__jf :deep(.v-field__outline__start),
.asa-foot-dlg__field :deep(.v-field__outline__start) {
  flex-basis: max(12px, var(--app-field-radius, 4px));
}

/* 移动端页脚：页码占满可用宽度（自动截断中段、始终保留首尾页），设置按钮固定在右侧；
   每页行数与跳转已收入弹窗，页码不再被跳转框挤占/覆盖。 */
.asa-pg-foot--mobile { flex-wrap: nowrap; gap: 8px; padding-inline: 12px; }
/* 直接使用整行空间，分页均匀展开，设置按钮保持宿主原有尺寸。 */
.asa-pg-foot--mobile .asa-pg-foot__nav { flex: 1 1 auto; min-inline-size: 0; }
/* 页码与前后翻页按钮随可用宽度分布，所有按钮保持同一水平中心线。 */
.asa-pg-foot--mobile .asa-pg-foot__nav :deep(.v-pagination) { inline-size: 100%; }
.asa-pg-foot--mobile .asa-pg-foot__nav :deep(.v-pagination__list) { inline-size: 100%; flex-wrap: nowrap; align-items: center; justify-content: space-between; gap: 2px; padding-inline: 8px; }
/* li 使用 flex 消除内联按钮的基线留白，与设置按钮按同一中心线对齐。 */
.asa-pg-foot--mobile .asa-pg-foot__nav :deep(.v-pagination__list > li) {
  display: flex; align-items: center; justify-content: center; margin: 0;
}

/* 页脚设置弹窗：每页行数 + 跳转（输入框与「跳转」按钮等高对齐） */
.asa-foot-dlg__title { display: flex; align-items: center; gap: 8px; font-size: 1rem; font-weight: 700; }
.asa-foot-dlg__body { padding-block: 12px 4px; }
.asa-foot-dlg__field + .asa-foot-dlg__field { margin-block-start: 16px; }
.asa-foot-dlg__label { display: block; margin-block-end: 6px; font-size: 0.8rem; font-weight: 600; color: rgba(var(--v-theme-on-surface), 0.72); }
.asa-foot-dlg__jump { display: flex; align-items: center; gap: 8px; }
.asa-foot-dlg__jump .asa-foot-dlg__jf { flex: 1 1 auto; }
.asa-foot-dlg__jump .v-btn { block-size: 40px; }

@container (width < 480px) {
  .asa-stats { grid-template-columns: 1fr; gap: 6px; }
  .asa-stat { flex-direction: row; align-items: center; justify-content: space-between; gap: 10px; padding: 10px 14px; }
  .asa-stat__num { order: 2; font-size: 1.15rem; }
  .asa-stat__label { font-size: 0.82rem; }
}
@media (prefers-reduced-motion: reduce) {
  .asa-stat { transition: none; }
}
</style>
