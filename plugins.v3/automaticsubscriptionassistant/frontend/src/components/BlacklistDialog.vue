<template>
  <v-dialog :model-value="modelValue" max-width="440" scrollable @update:model-value="v => !saving && emit('update:modelValue', v)">
    <v-card class="asa-filter-dlg">
      <v-card-title class="asa-filter-dlg__title">
        <v-icon icon="mdi-cancel" size="20" />{{ t('title') }}
      </v-card-title>
      <v-card-text class="asa-filter-dlg__body">
        <v-alert v-if="error" type="error" variant="tonal" density="compact" class="mb-3">{{ error }}</v-alert>
        <div class="bl-form">
          <FilterPanel v-if="manual" :state="form" :fields="manualFields" stacked />
          <p v-else class="bl-target">{{ target.title || t('selected', { n: pendingIds.length }) }}</p>
          <FilterPanel v-if="isTV" :state="scopeState" :fields="scopeFields" stacked />
          <FilterPanel v-if="manual && isTV && scope === 'season'" :state="form" :fields="seasonFields" stacked />
          <p class="bl-form__hint">{{ t(unsubscribe ? 'unsubHint' : 'hint') }}</p>
        </div>
      </v-card-text>
      <v-card-actions>
        <v-btn v-if="manual" :disabled="saving" variant="text" @click="resetForm">{{ t('reset') }}</v-btn>
        <v-spacer />
        <v-btn :disabled="saving" variant="text" @click="emit('update:modelValue', false)">{{ t('cancel') }}</v-btn>
        <v-btn :loading="saving" :color="unsubscribe ? 'error' : 'primary'" variant="flat" @click="save">{{ t(unsubscribe ? 'unsub' : 'add') }}</v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>

<script setup>
import { computed, getCurrentInstance, reactive, ref, watch } from 'vue'
import FilterPanel from './FilterPanel.vue'
import '../styles/mediaViews.css'
const props = defineProps({ api: { type: Object, default: () => ({}) }, modelValue: Boolean, target: { type: Object, default: () => ({}) } })
const emit = defineEmits(['update:modelValue', 'saved'])
const MSG = {
  'zh-CN': { reset: '重置', title: '加入黑名单', name: '影视名称（必填）', type: '类型', year: '发行年份（可选）', source: '媒体来源（可选）', mediaId: '媒体 ID（可选）', idHint: '填写 ID 可准确匹配；不填则按名称、类型及可选年份精确匹配。', scope: '忽略范围', all: '全部季', current: '指定季', season: '季号（0 为特别篇）', selected: '已选 {n} 个订阅', hint: '阻止插件以后自动订阅。现有订阅保留；清理历史不会清除黑名单。', unsubHint: '先保存黑名单，再取消选中的订阅，以后插件将跳过这些影视。', cancel: '取消', add: '加入黑名单', unsub: '退订并加入黑名单', movie: '电影', tv: '剧集', failed: '操作失败', required: '请填写影视名称', api: 'API 不可用' },
  'zh-TW': { reset: '重設', title: '加入黑名單', name: '影視名稱（必填）', type: '類型', year: '發行年份（可選）', source: '媒體來源（可選）', mediaId: '媒體 ID（可選）', idHint: '填寫 ID 可準確匹配；不填則按名稱、類型及可選年份精確匹配。', scope: '忽略範圍', all: '全部季', current: '指定季', season: '季號（0 為特別篇）', selected: '已選 {n} 個訂閱', hint: '阻止外掛以後自動訂閱。現有訂閱保留；清理歷史不會清除黑名單。', unsubHint: '先儲存黑名單，再取消選中的訂閱，以後外掛將略過這些影視。', cancel: '取消', add: '加入黑名單', unsub: '退訂並加入黑名單', movie: '電影', tv: '劇集', failed: '操作失敗', required: '請填寫影視名稱', api: 'API 無法使用' },
  'en-US': { reset: 'Reset', title: 'Add to blacklist', name: 'Media title (required)', type: 'Type', year: 'Release year (optional)', source: 'Media source (optional)', mediaId: 'Media ID (optional)', idHint: 'An ID gives an exact match. Otherwise match the exact title, type and optional year.', scope: 'Ignore', all: 'All seasons', current: 'Specific season', season: 'Season (0 for specials)', selected: '{n} selected subscriptions', hint: 'Prevents future automatic subscriptions. Existing subscriptions remain. Clearing history keeps this rule.', unsubHint: 'Save blacklist rules, then cancel the selected subscriptions to prevent automatic resubscription.', cancel: 'Cancel', add: 'Add to blacklist', unsub: 'Unsubscribe and blacklist', movie: 'Movie', tv: 'TV series', failed: 'Action failed', required: 'Enter a media title', api: 'API unavailable' },
}
const inst = getCurrentInstance()
function t(key, params) {
  const raw = inst?.appContext?.config?.globalProperties?.$i18n?.locale
  const lang = String(raw?.value || raw || '').toLowerCase()
  const locale = lang.startsWith('en') ? 'en-US' : /tw|hant|hk/.test(lang) ? 'zh-TW' : 'zh-CN'
  let text = MSG[locale][key] || key
  if (params) for (const key in params) text = text.replaceAll(`{${key}}`, params[key])
  return text
}
const form = reactive({ title: '', type: '电视剧', year: '', media_source: null, media_id: '', season: '' })
const scopeState = reactive({ scope: 'all' })
const scope = computed({ get: () => scopeState.scope, set: value => { scopeState.scope = value } })
const saving = ref(false)
const error = ref('')
const pendingIds = ref([])
const manual = computed(() => !props.target.kind || props.target.kind === 'manual')
const unsubscribe = computed(() => props.target.kind === 'unsubscribe')
const isTV = computed(() => manual.value ? form.type === '电视剧' : props.target.type === '电视剧')
const types = computed(() => [{ title: t('movie'), value: '电影' }, { title: t('tv'), value: '电视剧' }])
const sources = [{ title: 'TMDB', value: 'themoviedb' }, { title: 'Douban', value: 'douban' }, { title: 'Bangumi', value: 'bangumi' }]
const scopes = computed(() => [{ title: t('all'), value: 'all' }, { title: t('current') + (!manual.value && props.target.season != null ? ` (S${String(props.target.season).padStart(2, '0')})` : ''), value: 'season', props: { disabled: !manual.value && props.target.season == null } }])
const manualFields = computed(() => [
  { type: 'text', key: 'title', label: t('name'), icon: 'mdi-movie-open-outline' },
  { type: 'select', key: 'type', label: t('type'), items: types.value, clearable: false, icon: 'mdi-shape-outline' },
  { type: 'number', key: 'year', label: t('year'), min: 1800, max: 2999, step: 1 },
  { type: 'select', key: 'media_source', label: t('source'), items: sources, icon: 'mdi-database-outline' },
  { type: 'text', key: 'media_id', label: t('mediaId'), hint: t('idHint') },
])
const scopeFields = computed(() => [
  { type: 'select', key: 'scope', label: t('scope'), items: scopes.value, clearable: false, icon: 'mdi-television' },
])
const seasonFields = computed(() => [
  { type: 'number', key: 'season', label: t('season'), min: 0, step: 1 },
])
function resetForm() {
  Object.assign(form, { title: '', type: '电视剧', year: '', media_source: null, media_id: '', season: '' })
  scope.value = 'all'
  error.value = ''
}
watch(() => props.modelValue, open => {
  if (!open) return
  resetForm()
  pendingIds.value = [...(props.target.ids || [])]
})
async function save() {
  if (saving.value) return
  if (manual.value && !form.title.trim()) { error.value = t('required'); return }
  saving.value = true
  error.value = ''
  try {
    if (typeof props.api.post !== 'function') throw new Error(t('api'))
    const selectedScope = isTV.value ? scope.value : 'all'
    const body = unsubscribe.value ? { ids: pendingIds.value, scope: selectedScope }
      : manual.value ? { kind: 'manual', scope: selectedScope, media: { ...form, title: form.title.trim(), media_source: form.media_source || '', media_id: form.media_id.trim() } }
      : { kind: props.target.kind, unique: props.target.unique, id: props.target.id, scope: selectedScope }
    const result = await props.api.post(`plugin/AutomaticSubscriptionAssistant/${unsubscribe.value ? 'subscribes/block' : 'blacklist/add'}`, body)
    if (result?.code !== 0) throw new Error(result?.message || t('failed'))
    emit('saved', result)
    if (result.failed) {
      pendingIds.value = Array.isArray(result.failed_ids) ? result.failed_ids : pendingIds.value
      error.value = result.message || t('failed')
    } else emit('update:modelValue', false)
  } catch (e) { error.value = e?.message || String(e) }
  finally { saving.value = false }
}
</script>

<style scoped>
.bl-form { display: flex; flex-direction: column; gap: 14px; }
.bl-target { margin: 0; font-size: 0.86rem; font-weight: 600; line-height: 1.5; overflow-wrap: anywhere; }
.bl-form__hint { margin: 0; font-size: 0.72rem; line-height: 1.5; color: rgba(var(--v-theme-on-surface), 0.55); }
</style>
