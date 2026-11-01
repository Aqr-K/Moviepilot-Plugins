<template>
  <v-dialog :model-value="modelValue" :persistent="busy" max-width="680" scrollable @update:model-value="v => !busy && emit('update:modelValue', v)">
    <v-card class="asa-filter-dlg">
      <v-card-title class="asa-filter-dlg__title"><v-icon icon="mdi-file-document-edit-outline" size="20" />{{ t('title') }}</v-card-title>
      <v-card-text class="asa-filter-dlg__body">
        <p class="hs-hint">{{ t('hint') }}</p>
        <v-alert v-if="feedback" :type="feedbackType" variant="tonal" density="compact" class="mb-3">{{ feedback }}</v-alert>
        <div :inert="busy ? '' : null">
          <FilterPanel :state="media" :fields="mediaFields" stacked />
          <v-expansion-panels v-model="advanced" class="mt-4" variant="accordion">
            <v-expansion-panel :title="t('settings')">
              <v-expansion-panel-text>
                <p class="hs-hint">{{ t('defaults') }}</p>
                <p v-if="optionsError" class="hs-hint" role="status">{{ t('optionsError') }}</p>
                <FilterPanel :state="subscription" :fields="subscriptionFields" stacked />
              </v-expansion-panel-text>
            </v-expansion-panel>
          </v-expansion-panels>
        </div>
      </v-card-text>
      <v-card-actions>
        <v-btn :disabled="busy" variant="text" @click="resetForm">{{ t('reset') }}</v-btn>
        <v-spacer />
        <v-btn :disabled="busy" variant="text" @click="emit('update:modelValue', false)">{{ t('cancel') }}</v-btn>
        <v-btn :loading="busy" color="primary" variant="flat" @click="submit">{{ t('submit') }}</v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>

<script setup>
import { computed, getCurrentInstance, inject, onBeforeUnmount, reactive, ref, watch } from 'vue'
import FilterPanel from './FilterPanel.vue'
import '../styles/mediaViews.css'

const props = defineProps({ modelValue: Boolean, target: { type: Object, default: () => ({}) }, api: { type: Object, default: () => ({}) } })
const emit = defineEmits(['update:modelValue', 'changed'])
const toast = inject('moviepilot:toast', null)
const inst = getCurrentInstance()
const messages = {
  'zh-CN': {
    title: '补充编辑', hint: '补充媒体信息后重新识别并添加订阅。本次手动操作不使用榜单筛选；仍检查黑名单、媒体库和已有订阅，不修改自动任务设置。',
    name: '影视名称', type: '类型', movie: '电影', tv: '电视剧', year: '发行年份（可选）', source: '媒体来源（可选）', mediaId: '媒体 ID（可选）',
    identityHint: '来源和 ID 同时留空时按名称、类型和年份重新识别。', season: '目标季号（0 为特别篇）', group: '剧集组（可选）',
    settings: '本次订阅设置', defaults: '留空使用主程序默认设置。参数仅作用于本次创建，不修改来源或全局配置。',
    keyword: '搜索关键词', quality: '质量', resolution: '分辨率', effect: '特效', sites: '订阅站点', downloader: '下载器', path: '保存路径',
    interval: '搜索间隔（小时，留空跟随系统）', total: '总集数（可选）', start: '开始集数（可选）', include: '资源包含表达式', exclude: '资源排除表达式', rules: '过滤规则组',
    mode: '订阅模式', normal: '普通订阅', best: '洗版订阅', whole: '全集洗版', exists: '媒体库已有内容', inherit: '跟随主程序/插件默认设置', skip: '跳过已入库内容', allow: '允许创建订阅',
    reset: '重置', cancel: '取消', submit: '重新识别并添加', required: '请填写影视名称', pair: '媒体来源与 ID 必须同时填写或同时留空',
    invalid: '{name} 格式或范围不正确', optionsError: '部分选项加载失败，可留空使用默认设置，或稍后重新打开。', failed: '操作失败', created: '已添加新订阅',
  },
  'zh-TW': {
    title: '補充編輯', hint: '補充媒體資訊後重新識別並新增訂閱。本次手動操作不使用榜單篩選；仍檢查黑名單、媒體庫和已有訂閱，不修改自動工作設定。',
    name: '影視名稱', type: '類型', movie: '電影', tv: '劇集', year: '發行年份（可選）', source: '媒體來源（可選）', mediaId: '媒體 ID（可選）',
    identityHint: '來源和 ID 同時留空時按名稱、類型和年份重新識別。', season: '目標季號（0 為特別篇）', group: '劇集組（可選）',
    settings: '本次訂閱設定', defaults: '留空使用主程式預設設定。參數僅作用於本次建立，不修改來源或全域設定。',
    keyword: '搜尋關鍵字', quality: '品質', resolution: '解析度', effect: '特效', sites: '訂閱站點', downloader: '下載器', path: '儲存路徑',
    interval: '搜尋間隔（小時，留空跟隨系統）', total: '總集數（可選）', start: '開始集數（可選）', include: '資源包含運算式', exclude: '資源排除運算式', rules: '篩選規則組',
    mode: '訂閱模式', normal: '普通訂閱', best: '洗版訂閱', whole: '全集洗版', exists: '媒體庫已有內容', inherit: '跟隨主程式/外掛預設設定', skip: '略過已入庫內容', allow: '允許建立訂閱',
    reset: '重設', cancel: '取消', submit: '重新識別並新增', required: '請填寫影視名稱', pair: '媒體來源與 ID 必須同時填寫或同時留空',
    invalid: '{name} 格式或範圍不正確', optionsError: '部分選項載入失敗，可留空使用預設設定，或稍後重新開啟。', failed: '操作失敗', created: '已新增訂閱',
  },
  'en-US': {
    title: 'Edit and subscribe', hint: 'Correct the media, recognize it again and add a subscription. This manual action skips ranking filters, checks the blacklist, library and existing subscriptions, and keeps automatic task settings.',
    name: 'Title', type: 'Type', movie: 'Movie', tv: 'TV series', year: 'Release year (optional)', source: 'Media source (optional)', mediaId: 'Media ID (optional)',
    identityHint: 'Clear both source and ID to recognize by title, type and year.', season: 'Target season (0 for specials)', group: 'Episode group (optional)',
    settings: 'Subscription settings', defaults: 'Leave blank to use host defaults. Settings apply only to this subscription.',
    keyword: 'Search keywords', quality: 'Quality', resolution: 'Resolution', effect: 'Effects', sites: 'Subscription sites', downloader: 'Downloader', path: 'Save path',
    interval: 'Search interval (hours, blank for default)', total: 'Total episodes (optional)', start: 'Start episode (optional)', include: 'Include expression', exclude: 'Exclude expression', rules: 'Filter rule groups',
    mode: 'Subscription mode', normal: 'Normal', best: 'Version upgrade', whole: 'Whole-season upgrade', exists: 'Already in library', inherit: 'Use host/plugin default', skip: 'Skip existing content', allow: 'Allow subscription',
    reset: 'Reset', cancel: 'Cancel', submit: 'Recognize and add', required: 'Enter a media title', pair: 'Provide both media source and ID, or clear both',
    invalid: 'Invalid {name}', optionsError: 'Some options could not load. Use defaults or reopen later.', failed: 'Action failed', created: 'Subscription added',
  },
}
function t(key, params) {
  const raw = inst?.appContext?.config?.globalProperties?.$i18n?.locale
  const lang = String(raw?.value || raw || '').toLowerCase()
  let text = messages[lang.startsWith('en') ? 'en-US' : /tw|hant|hk/.test(lang) ? 'zh-TW' : 'zh-CN'][key] || key
  if (params) for (const name in params) text = text.replaceAll(`{${name}}`, params[name])
  return text
}
const media = reactive({ title: '', type: '电影', year: '', media_source: null, media_id: '', season: '', episode_group: '' })
const emptySettings = () => ({ keyword: '', quality: null, resolution: null, effect: null, sites: [], downloader: null,
  save_path: '', search_interval: '', total_episode: '', start_episode: '', include: '', exclude: '', filter_groups: [], mode: null, exist_ok: null })
const subscription = reactive(emptySettings())
const busy = ref(false)
const feedback = ref('')
const feedbackType = ref('error')
const advanced = ref()
const optionsError = ref(false)
const siteOptions = ref([])
const downloaderOptions = ref([])
const ruleOptions = ref([])
const isTV = computed(() => media.type === '电视剧')
const sources = [{ title: 'TMDB', value: 'themoviedb' }, { title: 'Douban', value: 'douban' }, { title: 'Bangumi', value: 'bangumi' }]
const mediaFields = computed(() => [
  { type: 'text', key: 'title', label: t('name') },
  { type: 'select', key: 'type', label: t('type'), clearable: false, items: [{ title: t('movie'), value: '电影' }, { title: t('tv'), value: '电视剧' }] },
  { type: 'number', key: 'year', label: t('year'), min: 1800, max: 2999, step: 1 },
  { type: 'select', key: 'media_source', label: t('source'), items: sources },
  { type: 'text', key: 'media_id', label: t('mediaId'), hint: t('identityHint') },
  ...(isTV.value ? [{ type: 'number', key: 'season', label: t('season'), min: 0, max: 999, step: 1 }, { type: 'text', key: 'episode_group', label: t('group') }] : []),
])
const subscriptionFields = computed(() => [
  { type: 'text', key: 'keyword', label: t('keyword') },
  { type: 'select', key: 'quality', label: t('quality'), items: ['Remux', ['Blu-ray', 'Blu-?Ray'], ['UHD', 'UHD|UltraHD'], ['WEB-DL / WEBRip', 'WEB-?DL|WEB-?RIP'], 'HDTV'].map(v => ({ title: Array.isArray(v) ? v[0] : v, value: Array.isArray(v) ? v[1] : v })) },
  { type: 'select', key: 'resolution', label: t('resolution'), items: [{ title: '4K', value: '4K|2160p|x2160' }, { title: '1080p', value: '1080[pi]|x1080' }, { title: '720p', value: '720[pi]|x720' }] },
  { type: 'text', key: 'effect', label: t('effect') },
  { type: 'select', key: 'sites', label: t('sites'), multi: true, items: siteOptions.value },
  { type: 'select', key: 'downloader', label: t('downloader'), items: downloaderOptions.value },
  { type: 'text', key: 'save_path', label: t('path') },
  { type: 'number', key: 'search_interval', label: t('interval'), min: 1, max: 8760, step: 1 },
  ...(isTV.value ? [{ type: 'number', key: 'total_episode', label: t('total'), min: 1, max: 10000, step: 1 }, { type: 'number', key: 'start_episode', label: t('start'), min: 1, max: 10000, step: 1 }] : []),
  { type: 'select', key: 'mode', label: t('mode'), items: [{ title: t('normal'), value: 'normal' }, { title: t('best'), value: 'best' }, ...(isTV.value ? [{ title: t('whole'), value: 'whole' }] : [])] },
  { type: 'text', key: 'include', label: t('include') }, { type: 'text', key: 'exclude', label: t('exclude') },
  { type: 'select', key: 'filter_groups', label: t('rules'), multi: true, items: ruleOptions.value },
  { type: 'select', key: 'exist_ok', label: t('exists'), items: [{ title: t('skip'), value: false }, { title: t('allow'), value: true }], placeholder: t('inherit') },
])

function resetForm() {
  const item = props.target
  Object.assign(media, { title: item.title || '', type: item.type || '电影', year: item.year || '',
    media_source: item.media_source || null, media_id: item.media_id == null ? '' : String(item.media_id),
    season: item.season ?? '', episode_group: item.episode_group || '' })
  Object.assign(subscription, emptySettings())
  feedback.value = ''
  advanced.value = undefined
}
function integer(value, key, min, max, required = false) {
  if (value === '' || value == null) {
    if (required) throw new Error(t('invalid', { name: t(key) }))
    return null
  }
  const number = Number(value)
  if (!Number.isSafeInteger(number) || number < min || number > max) throw new Error(t('invalid', { name: t(key) }))
  return number
}
function buildRequest() {
  if (!media.title.trim()) throw new Error(t('required'))
  const mediaId = media.media_id.trim()
  if (!!media.media_source !== !!mediaId) throw new Error(t('pair'))
  const year = integer(media.year, 'year', 1800, 2999)
  const season = isTV.value ? integer(media.season, 'season', 0, 999, true) : null
  const options = {}
  for (const key of ['keyword', 'quality', 'resolution', 'effect', 'downloader', 'save_path', 'include', 'exclude']) {
    const value = String(subscription[key] ?? '').trim()
    if (value) options[key] = value
  }
  for (const key of ['sites', 'filter_groups']) if (subscription[key].length) options[key] = [...subscription[key]]
  const interval = integer(subscription.search_interval, 'interval', 1, 8760)
  if (interval != null) options.search_interval = interval
  if (isTV.value) {
    for (const [key, label] of [['total_episode', 'total'], ['start_episode', 'start']]) {
      const value = integer(subscription[key], label, 1, 10000)
      if (value != null) options[key] = value
    }
  }
  if (subscription.mode) {
    options.best_version = subscription.mode === 'normal' ? 0 : 1
    options.best_version_full = isTV.value && subscription.mode === 'whole' ? 1 : 0
  }
  return { unique: props.target.unique, media: { title: media.title.trim(), type: media.type, year: year == null ? null : String(year),
    media_source: media.media_source, media_id: mediaId, season, episode_group: isTV.value ? media.episode_group.trim() : null },
    subscription: options, ...(typeof subscription.exist_ok === 'boolean' ? { exist_ok: subscription.exist_ok } : {}) }
}

let generation = 0
let disposed = false
async function loadOptions() {
  const current = ++generation
  optionsError.value = false
  const results = await Promise.allSettled(['site/rss', 'download/clients', 'rule/groups?include_usage=false'].map(async url => props.api.get(url, { feedback: 'silent' })))
  if (disposed || current !== generation || !props.modelValue) return
  const data = results.map(result => {
    if (result.status === 'rejected' || result.value?.success === false) { optionsError.value = true; return null }
    return result.value?.success === true ? result.value.data : result.value
  })
  siteOptions.value = (Array.isArray(data[0]) ? data[0] : []).map(site => ({ title: site.name, value: site.id }))
  downloaderOptions.value = (Array.isArray(data[1]) ? data[1] : []).map(client => ({ title: client.name, value: client.name }))
  ruleOptions.value = (data[2]?.rule_groups || []).map(group => ({ title: group.name, value: group.name }))
}
watch(() => props.modelValue, open => {
  if (!open) { generation++; return }
  resetForm()
  loadOptions()
})
async function submit() {
  if (busy.value || disposed) return
  feedback.value = ''
  feedbackType.value = 'error'
  let body
  try { body = buildRequest() } catch (error) { feedback.value = error.message; return }
  busy.value = true
  try {
    const result = await props.api.post('plugin/AutomaticSubscriptionAssistant/history/supplement', body)
    if (disposed) return
    if (result?.code !== 0) throw new Error(result?.message || t('failed'))
    emit('changed', result)
    if (result.created) { toast?.success?.(t('created')); emit('update:modelValue', false) }
    else { feedbackType.value = 'warning'; feedback.value = result.message || t('failed') }
  } catch (error) { if (!disposed) feedback.value = error?.message || String(error) }
  finally { busy.value = false }
}
onBeforeUnmount(() => { disposed = true; generation++ })
</script>

<style scoped>
.hs-hint { margin: 0 0 14px; font-size: 0.78rem; line-height: 1.6; color: rgba(var(--v-theme-on-surface), 0.65); }
</style>
