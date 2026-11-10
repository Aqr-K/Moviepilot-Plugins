<template>
  <div class="asa-rules">
    <v-btn class="asa-rules__trigger" variant="outlined" @click="openManager">
      <v-icon icon="mdi-view-grid-plus-outline" start />
      <span class="asa-rules__trigger-text">{{ t('manage') }} · {{ t('count', { n: savedRows.length, enabled: savedRows.filter(r => r.on !== false).length }) }}</span>
      <v-icon icon="mdi-chevron-right" end />
    </v-btn>
    <v-dialog v-model="managerOpen" max-width="520" scrollable @after-leave="closeEditor">
      <v-card class="asa-rule-manager">
        <v-card-title class="asa-rule-manager__title">
          <v-icon icon="mdi-view-grid-plus-outline" size="20" />{{ field.label }}
        </v-card-title>
        <v-card-text class="asa-rule-manager__body">
          <p v-if="field.hint" class="asa-rule-manager__hint">{{ field.hint }}</p>
          <v-text-field v-if="rows.length" v-model="search" class="asa-rules__search" :aria-label="t('search')" :placeholder="t('search')" prepend-inner-icon="mdi-magnify" clearable density="compact" variant="outlined" hide-details />
          <div class="asa-rules__rows">
            <p v-if="!rows.length" class="asa-rules__empty">{{ t('empty') }}</p>
            <p v-else-if="!filteredRows.length" class="asa-rules__empty">{{ t('noResults') }}</p>
            <article v-for="{ row, index } in filteredRows" :key="row.id || index" class="asa-rule" :class="{ 'asa-rule--off': row.on === false }">
              <div class="asa-rule__head">
                <v-switch class="asa-rule__switch" :model-value="row.on !== false" :aria-label="`${t('enable')} ${row.name || t('rule')}`" density="compact" hide-details inset color="primary" @update:model-value="toggle(index, $event)" />
                <strong :title="row.name || t('rule')">{{ row.name || t('rule') }}</strong>
                <v-btn :aria-label="`${t('edit')} ${row.name || t('rule')}`" icon="mdi-pencil-outline" size="x-small" variant="text" @click="edit(index)" />
                <v-btn class="asa-rule__remove" :aria-label="`${t('remove')} ${row.name || t('rule')}`" icon="mdi-close" size="x-small" variant="text" @click="remove(index)" />
              </div>
              <p class="asa-rule__summary">{{ ruleSummary(fields, row) }}</p>
              <p v-if="row.subscription?.enabled" class="asa-rule__summary">{{ t('subscriptionOverride') }}</p>
            </article>
          </div>
          <div class="asa-rules__toolbar">
            <v-btn class="asa-rules__add" variant="outlined" prepend-icon="mdi-plus" @click="edit(-1)">{{ t('add') }}</v-btn>
            <v-menu v-if="field.presets?.length">
              <template #activator="{ props: menuProps }"><v-btn v-bind="menuProps" variant="text" append-icon="mdi-chevron-down">{{ t('presets') }}</v-btn></template>
              <v-list density="compact"><v-list-item v-for="(preset, i) in field.presets" :key="i" :title="preset.name" @click="edit(-1, preset)" /></v-list>
            </v-menu>
            <span class="asa-rules__count">{{ rows.length }} / 100</span>
          </div>
          <v-alert v-if="managerError" type="error" variant="tonal" density="compact" class="mt-3">{{ managerError }}</v-alert>
        </v-card-text>
        <v-card-actions>
          <div class="asa-rules__actions" role="group" :aria-label="field.label">
            <v-btn class="asa-rules__icon-btn" :aria-label="t('import')" color="success" variant="tonal" @click="transferMode = 'import'"><v-icon icon="mdi-import" /><v-tooltip activator="parent" :text="t('import')" /></v-btn>
            <v-btn class="asa-rules__icon-btn" :aria-label="t('share')" color="info" variant="tonal" :disabled="!rows.length" @click="transferMode = 'share'"><v-icon icon="mdi-share" /><v-tooltip activator="parent" :text="t('share')" /></v-btn>
            <v-btn class="asa-rules__icon-btn" :aria-label="t('clear')" color="error" variant="tonal" :disabled="!rows.length" @click="workingRows = []"><v-icon icon="mdi-delete-sweep-outline" /><v-tooltip activator="parent" :text="t('clear')" /></v-btn>
          </div>
          <v-spacer />
          <v-btn variant="text" @click="managerOpen = false">{{ t('cancel') }}</v-btn>
          <v-btn color="primary" variant="flat" @click="applyRules">{{ t('apply') }}</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
    <RuleTransferDialog :mode="transferMode" :provider-id="providerId" :provider-name="providerName" :fields="fields" :rules="rows" @close="transferMode = ''" @import="receiveImport" />
    <v-dialog v-model="open" max-width="520" scrollable>
      <v-card class="asa-rule-editor">
        <v-card-title class="asa-rule-manager__title"><v-icon :icon="editing < 0 ? 'mdi-plus' : 'mdi-pencil-outline'" size="20" />{{ editing < 0 ? t('add') : t('edit') }}</v-card-title>
        <v-card-text>
          <v-text-field v-model="draft.name" :label="t('name')" maxlength="80" counter="80" density="compact" variant="outlined" :hint="t('nameHint')" persistent-hint />
          <template v-for="f in basicFields" :key="f.key">
            <div class="asa-rule-editor__field">
              <label>{{ f.label }}</label>
              <template v-if="['select', 'multi-select'].includes(f.kind)">
                <v-select v-if="groupsFor(f).length" v-model="groupFilters[f.key]" :label="t('group')" :items="groupsFor(f)" clearable density="compact" variant="outlined" hide-details class="asa-rule-editor__group" />
                <v-autocomplete :model-value="draft[f.key]" @update:model-value="updateField(f, $event)" :items="optionsFor(f)" item-title="title" item-value="value" :multiple="f.kind === 'multi-select'" :chips="f.kind === 'multi-select'" :closable-chips="f.kind === 'multi-select'" :aria-label="f.label" :custom-filter="filterOption" :item-props="optionProps" :error-messages="fieldErrors(f)" :hint="f.hint" :persistent-hint="!!f.hint" density="compact" variant="outlined" :menu-props="{ maxHeight: 320 }">
                </v-autocomplete>
              </template>
              <v-text-field v-else :model-value="draft[f.key]" @update:model-value="updateField(f, $event)" :aria-label="f.label" :type="['number', 'float'].includes(f.kind) ? 'number' : 'text'" :min="f.minimum" :max="f.maximum" :step="f.kind === 'float' ? 0.1 : 1" :error-messages="fieldErrors(f)" :hint="f.hint" :persistent-hint="!!f.hint" density="compact" variant="outlined" />
            </div>
          </template>
          <v-expansion-panels v-model="advancedOpen" v-if="advancedFields.length" variant="accordion" class="asa-rule-editor__advanced">
            <v-expansion-panel :title="t('advanced')"><v-expansion-panel-text>
              <div v-for="f in advancedFields" :key="f.key" class="asa-rule-editor__field">
                <label>{{ f.label }}</label>
                <v-autocomplete v-if="['select', 'multi-select'].includes(f.kind)" v-model="draft[f.key]" :items="fieldOptions(f, draft)" item-title="title" item-value="value" :multiple="f.kind === 'multi-select'" :chips="f.kind === 'multi-select'" :closable-chips="f.kind === 'multi-select'" :aria-label="f.label" :error-messages="fieldErrors(f)" density="compact" variant="outlined" />
                <v-text-field v-else v-model="draft[f.key]" :aria-label="f.label" :type="['number', 'float'].includes(f.kind) ? 'number' : 'text'" :min="f.minimum" :max="f.maximum" :step="f.kind === 'float' ? 0.1 : 1" :error-messages="fieldErrors(f)" :hint="f.hint" :persistent-hint="!!f.hint" density="compact" variant="outlined" />
              </div>
            </v-expansion-panel-text></v-expansion-panel>
          </v-expansion-panels>
          <SubscriptionPolicy class="mt-4" :provider-id="providerId" :api="api" :rule="draft" rule-level v-model="draft.subscription" />
          <v-alert v-if="error" type="error" variant="tonal" density="compact" class="mt-3">{{ error }}</v-alert>
        </v-card-text>
        <v-card-actions><v-spacer /><v-btn variant="text" @click="open = false">{{ t('cancel') }}</v-btn><v-btn color="primary" variant="flat" @click="save">{{ t('save') }}</v-btn></v-card-actions>
      </v-card>
    </v-dialog>
  </div>
</template>
<script setup>
import { computed, getCurrentInstance, ref, watch } from 'vue'
import RuleTransferDialog from './RuleTransferDialog.vue'
import SubscriptionPolicy from './SubscriptionPolicy.vue'
import { normalizeSubscriptionPolicy } from '../utils/subscriptionPolicy.js'
import { createRuleId, fieldOptions, invalidFields, ruleSignature, ruleSummary, ruleValues, visibleField } from '../utils/rules.js'
const props = defineProps({ api: { type: [Object, Function], default: () => ({}) }, providerId: { type: String, required: true }, providerName: { type: String, default: '' }, field: { type: Object, required: true }, modelValue: { default: null } })
const emit = defineEmits(['update:modelValue'])
const inst = getCurrentInstance()
const messages = {
  'zh-CN': { subscriptionOverride:'已启用规则级订阅设置', import:'导入', share:'分享', search:'搜索规则', noResults:'没有匹配的规则', manage:'配置规则', count:'{n} 条，启用 {enabled} 条', apply:'应用', clear:'清空规则', conflict:'来源配置已变更，请重新打开规则配置。', add:'添加规则', rule:'规则', edit:'编辑规则', remove:'移除', enable:'启用', presets:'使用预设', empty:'暂无规则，该来源不会运行。', name:'规则名称', nameHint:'留空时自动生成名称', advanced:'高级筛选', group:'榜单分组', cancel:'取消', save:'保存', invalid:'请检查规则条件', duplicate:'已有相同规则，请编辑已有卡片。', max:'最多添加 100 条规则', fieldInvalid:'请填写有效值' },
  'zh-TW': { subscriptionOverride:'已啟用規則級訂閱設定', import:'匯入', share:'分享', search:'搜尋規則', noResults:'沒有符合的規則', manage:'設定規則', count:'{n} 條，啟用 {enabled} 條', apply:'套用', clear:'清空規則', conflict:'來源設定已變更，請重新開啟規則設定。', add:'新增規則', rule:'規則', edit:'編輯規則', remove:'移除', enable:'啟用', presets:'使用預設', empty:'尚無規則，此來源不會執行。', name:'規則名稱', nameHint:'留空時自動產生名稱', advanced:'進階篩選', group:'榜單分組', cancel:'取消', save:'儲存', invalid:'請檢查規則條件', duplicate:'已有相同規則，請編輯已有卡片。', max:'最多新增 100 條規則', fieldInvalid:'請填寫有效值' },
  'en-US': { subscriptionOverride:'Rule subscription override enabled', import:'Import', share:'Share', search:'Search rules', noResults:'No matching rules', manage:'Configure rules', count:'{n} rules, {enabled} enabled', apply:'Apply', clear:'Clear rules', conflict:'Source settings changed. Reopen the rules dialog.', add:'Add rule', rule:'Rule', edit:'Edit rule', remove:'Remove', enable:'Enable', presets:'Presets', empty:'No rules. This source will not run.', name:'Rule name', nameHint:'Leave blank to generate a name', advanced:'Advanced filters', group:'Chart group', cancel:'Cancel', save:'Save', invalid:'Check the rule conditions', duplicate:'This rule already exists. Edit its card.', max:'Up to 100 rules', fieldInvalid:'Enter a valid value' },
}
const locale = computed(() => {
  const raw = inst?.appContext?.config?.globalProperties?.$i18n?.locale
  const l = String(raw?.value ?? raw ?? '').toLowerCase()
  return l.startsWith('en') ? 'en-US' : /tw|hant|hk/.test(l) ? 'zh-TW' : 'zh-CN'
})
function t(k, params = {}) { return Object.entries(params).reduce((text, [key, value]) => text.replaceAll(`{${key}}`, String(value)), messages[locale.value][k]) }
const fields = computed(() => props.field.fields || [])
const savedRows = computed(() => Array.isArray(props.modelValue) ? props.modelValue : [])
const transferMode = ref('')
function receiveImport(value) { workingRows.value = value; search.value = ''; managerError.value = '' }
const workingRows = ref([]), managerOpen = ref(false), managerError = ref('')
const rows = computed(() => workingRows.value)
const search = ref('')
const filteredRows = computed(() => {
  const keyword = String(search.value || '').trim().toLowerCase()
  return rows.value.map((row, index) => ({ row, index })).filter(({ row }) =>
    !keyword || `${row.name || ''} ${ruleSummary(fields.value, row)}`.toLowerCase().includes(keyword))
})
let baseline = '', sourceField = null
function openManager() {
  workingRows.value = JSON.parse(JSON.stringify(savedRows.value))
  baseline = JSON.stringify(props.modelValue)
  sourceField = props.field
  managerError.value = ''
  search.value = ''
  open.value = false
  managerOpen.value = true
}
function closeEditor() { open.value = false; transferMode.value = '' }
watch(() => props.field, () => {
  if (managerOpen.value && props.field !== sourceField) { open.value = false; transferMode.value = ''; managerOpen.value = false }
})
function applyRules() {
  managerError.value = ''
  if (baseline !== JSON.stringify(props.modelValue)) { managerError.value = t('conflict'); return }
  const signatures = new Set()
  for (const row of rows.value) {
    if (invalidFields(fields.value, row).length) { managerError.value = t('invalid'); return }
    try { if (row.subscription != null) normalizeSubscriptionPolicy(row.subscription) }
    catch (exc) { managerError.value = exc.message; return }
    const signature = ruleSignature(fields.value, row)
    if (signatures.has(signature)) { managerError.value = t('duplicate'); return }
    signatures.add(signature)
  }
  if (rows.value.length > 100) { managerError.value = t('max'); return }
  emit('update:modelValue', JSON.parse(JSON.stringify(rows.value)))
  managerOpen.value = false
}

const advancedOpen = ref(null)
const open = ref(false), editing = ref(-1), draft = ref({}), attempted = ref(false), error = ref(''), groupFilters = ref({})
const basicFields = computed(() => fields.value.filter(f => !f.advanced && visibleField(f, draft.value)))
const advancedFields = computed(() => fields.value.filter(f => f.advanced && visibleField(f, draft.value)))
const invalid = computed(() => invalidFields(fields.value, draft.value))
function fieldErrors(f) { return attempted.value && invalid.value.some(x => x.key === f.key) ? [t('fieldInvalid')] : [] }
function groupsFor(f) { return [...new Set(fieldOptions(f, draft.value).map(o => o.group).filter(Boolean))] }
function optionsFor(f) {
  const selected = Array.isArray(draft.value[f.key]) ? draft.value[f.key] : [draft.value[f.key]]
  return fieldOptions(f, draft.value).filter(o => !groupFilters.value[f.key] || o.group === groupFilters.value[f.key] || selected.includes(o.value))
}
function optionProps(option) { return { subtitle: option.group || undefined } }
function filterOption(value, query, item) { return `${value} ${item.raw.group || ''}`.toLowerCase().includes(query.toLowerCase()) }
function edit(index, preset = {}) {
  editing.value = index
  draft.value = JSON.parse(JSON.stringify({ ...Object.fromEntries(fields.value.map(f => [f.key, f.default])), on:true, name:'', ...(index < 0 ? preset : rows.value[index]) }))
  attempted.value = false; advancedOpen.value = null; error.value = ''; groupFilters.value = {}; open.value = true
}
function updateField(field, value) {
  draft.value[field.key] = value
  fields.value.filter(f => f.options_by?.key === field.key).forEach(f => { draft.value[f.key] = [] })
}
function save() {
  attempted.value = true; error.value = ''
  if (invalid.value.some(f => f.advanced)) advancedOpen.value = 0
  if (invalid.value.length || String(draft.value.name || '').length > 80) { error.value = t('invalid'); return }
  const signature = ruleSignature(fields.value, draft.value)
  if (rows.value.some((row, i) => i !== editing.value && ruleSignature(fields.value, row) === signature)) { error.value = t('duplicate'); return }
  if (editing.value < 0 && rows.value.length >= 100) { error.value = t('max'); return }
  const first = fields.value.find(f => ['chart', 'category', 'dataset', 'sort', 'time'].includes(f.key))
  const automatic = first ? fieldOptions(first, draft.value).find(o => o.value === draft.value[first.key])?.title : null
  let subscription
  try { if (draft.value.subscription != null) subscription = normalizeSubscriptionPolicy(draft.value.subscription) }
  catch (exc) { error.value = exc.message; return }
  const rule = { ...ruleValues(fields.value, draft.value), ...(subscription ? { subscription } : {}), on:draft.value.on !== false, name:String(draft.value.name || '').trim() || automatic || t('rule'), id:draft.value.id || createRuleId() }
  const next = rows.value.slice()
  if (editing.value < 0) next.push(rule); else next[editing.value] = rule
  workingRows.value = next; open.value = false
}
function toggle(index, on) { workingRows.value = rows.value.map((row, i) => i === index ? { ...row, on } : row) }
function remove(index) { workingRows.value = rows.value.filter((_, i) => i !== index) }
</script>
<style scoped>
.asa-rules { inline-size: 100%; min-inline-size: 0; }
.asa-rules__trigger { inline-size: 100%; justify-content: space-between; text-transform: none; letter-spacing: 0; font-weight: 500; }
.asa-rules__trigger-text { flex: 1 1 auto; overflow: hidden; text-align: start; text-overflow: ellipsis; white-space: nowrap; }
.asa-rule-manager, .asa-rule-editor { border-radius: var(--app-surface-radius, 12px) !important; }
.asa-rule-manager__title { display: flex; align-items: center; gap: 8px; font-size: 1rem; font-weight: 700; }
.asa-rule-manager__body { display: flex; flex-direction: column; gap: 10px; padding-block: 12px 6px; }
.asa-rule-manager__hint { margin: 0 0 2px; color: rgba(var(--v-theme-on-surface), .6); font-size: .78rem; line-height: 1.4; }
.asa-rules__toolbar { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.asa-rules__add { flex: 1 1 auto; justify-content: start; }
.asa-rules__count { margin-inline-start: auto; font-size: .72rem; color: rgba(var(--v-theme-on-surface), .5); }
.asa-rules__actions { display:inline-flex; gap:0; flex:0 0 auto; overflow:hidden; border-radius:var(--app-control-radius,8px); }
.asa-rules__icon-btn { min-inline-size:36px; inline-size:36px; block-size:36px; margin:0; padding:0; border-radius:0 !important; }
.asa-rules__icon-btn + .asa-rules__icon-btn { border-inline-start:1px solid rgba(var(--v-theme-on-surface),.12); }
.asa-rules__icon-btn :deep(.v-icon) { font-size:20px; }
.asa-rule-manager :deep(.v-card-actions) { gap:8px; flex-wrap:wrap; }
.asa-rule-manager :deep(.v-card-actions > .v-btn) { margin-inline-start:0; }
.asa-rules__rows { display: flex; flex-direction: column; gap: 8px; }
.asa-rules__empty { padding: 14px 4px; font-size: .8rem; text-align: center; color: rgba(var(--v-theme-on-surface), .5); }
.asa-rule { display: flex; flex-direction: column; gap: 8px; padding: 10px 12px; border: 1px solid rgba(var(--v-theme-on-surface), .12); border-radius: var(--app-control-radius, 8px); background: rgba(var(--v-theme-on-surface), .03); min-inline-size: 0; }
.asa-rule__head { display: flex; align-items: center; gap: 8px; }
.asa-rule__head strong { flex: 1; min-inline-size: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: .86rem; font-weight: 600; }
.asa-rule--off .asa-rule__head strong { color: rgba(var(--v-theme-on-surface), .42); text-decoration: line-through; }
.asa-rule--off .asa-rule__summary { opacity: .45; }
.asa-rule__remove { color: rgba(var(--v-theme-on-surface), .45); }
.asa-rule__switch { flex: 0 0 auto; margin: 0; }
.asa-rule__switch :deep(.v-input__control),
.asa-rule__switch :deep(.v-selection-control),
.asa-rule__switch :deep(.v-selection-control__wrapper) { min-block-size: 0; block-size: auto; }
.asa-rule__switch :deep(.v-selection-control__input) { inline-size: auto; block-size: auto; }
.asa-rule__switch :deep(.v-switch__track) { block-size: 16px; min-inline-size: 28px; }
.asa-rule__switch :deep(.v-switch__thumb) { block-size: 12px; inline-size: 12px; }
.asa-rule__summary { margin: 0; color: rgba(var(--v-theme-on-surface), .6); font-size: .74rem; line-height: 1.6; overflow-wrap: anywhere; }
.asa-rule-editor__field { margin-block-start: 12px; }
.asa-rule-editor__field label { display: block; margin-block-end: 6px; font-size: .83rem; font-weight: 600; }
.asa-rule-editor__group { margin-block-end: 8px; }
.asa-rule-editor__advanced { margin-block-start: 12px; }
.asa-rule-editor :deep(.v-field), .asa-rule-editor :deep(.v-input) { min-inline-size: 0; }
.asa-rule-editor :deep(.v-chip) { max-inline-size: 100%; }
</style>
