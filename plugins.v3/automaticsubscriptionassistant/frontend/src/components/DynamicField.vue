<template>
  <!-- 开关：紧凑、无内联标签（标签由字段行提供） -->
  <v-switch
    v-if="field.kind === 'switch'"
    :model-value="modelValue"
    @update:model-value="emitVal"
    :aria-label="field.label"
    color="primary"
    density="compact"
    hide-details
    inset
  ></v-switch>

  <!-- 单选 / 多选 -->
  <v-select
    v-else-if="isSelect"
    class="asa-control"
    :model-value="normalizedSelectValue"
    @update:model-value="emitVal"
    :aria-label="field.label"
    :items="field.options || []"
    item-title="title"
    item-value="value"
    :multiple="field.kind === 'multi-select'"
    :placeholder="field.kind === 'multi-select' ? t('unset') : undefined"
    density="compact"
    variant="outlined"
    hide-details
  >
    <template v-if="field.kind === 'multi-select'" #selection="{ item, index }">
      <span v-if="index === 0" class="asa-select__primary">{{ item.title }}</span>
      <span v-else-if="index === 1" class="asa-select__more">+{{ overflowCount }}</span>
    </template>
    <!-- 多选：一键清除快捷图标（有选中项时显示） -->
    <template v-if="field.kind === 'multi-select' && selCount" #append-inner>
      <v-icon
        class="asa-select__clear"
        icon="mdi-close-circle"
        size="18"
        :aria-label="t('clearAll')"
        @mousedown.stop.prevent
        @click.stop="emitVal([])"
      />
      <v-tooltip activator="parent" location="top" :text="t('clearAll')" />
    </template>
  </v-select>

  <!-- 数字：− 输入 + 步进器 -->
  <div v-else-if="isNumber" class="asa-stepper">
    <v-btn :aria-label="`- ${field.label}`" icon="mdi-minus" size="small" variant="text" @click="step(-1)"></v-btn>
    <input
      class="asa-stepper__input"
      :aria-label="field.label"
      inputmode="decimal"
      type="number"
      min="0"
      :value="modelValue"
      @keydown="blockNegative"
      @input="emitNum($event.target.value)"
    />
    <v-btn :aria-label="`+ ${field.label}`" icon="mdi-plus" size="small" variant="text" @click="step(1)"></v-btn>
  </div>

  <!-- 多行文本（整行铺开） -->
  <v-textarea
    v-else-if="field.kind === 'textarea'"
    class="asa-control"
    :model-value="modelValue"
    @update:model-value="emitVal"
    :aria-label="field.label"
    :placeholder="field.placeholder || ''"
    auto-grow
    density="compact"
    hide-details
    rows="3"
    variant="outlined"
  ></v-textarea>

  <!-- 地区 × 媒体类型：折叠为弹窗式卡片管理，避免行列在窄栏被挤压（选项再多也在弹窗内换行完整显示） -->
  <div v-else-if="field.kind === 'region-media-map'" class="asa-rmm-field">
    <v-btn class="asa-rmm-trigger" variant="outlined" @click="rmmOpen = true">
      <v-icon icon="mdi-view-grid-plus-outline" start />
      <span class="asa-rmm-trigger__txt">{{ rmmSummary }}</span>
      <v-icon icon="mdi-chevron-right" end />
    </v-btn>

    <v-dialog v-model="rmmOpen" max-width="520" scrollable>
      <v-card class="asa-rmm-dlg">
        <v-card-title class="asa-rmm-dlg__title">
          <v-icon icon="mdi-view-grid-plus-outline" size="20" />{{ field.label }}
        </v-card-title>
        <v-card-text class="asa-rmm-dlg__body">
          <p v-if="field.hint" class="asa-rmm-dlg__hint">{{ field.hint }}</p>
          <div class="asa-rmm">
            <div v-if="regionRows.length" class="asa-rmm__rows">
              <div v-for="row in regionRows" :key="row.value" class="asa-rmm__row">
                <div class="asa-rmm__head">
                  <v-switch
                    :model-value="row.on"
                    @update:model-value="toggleEnabled(row.value)"
                    class="asa-rmm__switch"
                    :aria-label="`${t('enable')} ${row.title}`"
                    color="primary"
                    density="compact"
                    hide-details
                    inset
                  ></v-switch>
                  <span class="asa-rmm__name" :class="{ 'asa-rmm__name--off': !row.on }" :title="row.title">{{ row.title }}</span>
                  <v-spacer />
                  <v-btn
                    :aria-label="`${t('remove')} ${row.title}`"
                    class="asa-rmm__del"
                    icon="mdi-close"
                    size="x-small"
                    variant="text"
                    @click="removeRegion(row.value)"
                  ></v-btn>
                </div>
                <div class="asa-rmm__cats" :class="{ 'asa-rmm__cats--off': !row.on }">
                  <button
                    v-for="col in columnsForRow(row.value)"
                    :key="col.value"
                    type="button"
                    :class="['asa-rmm__cat', { 'asa-rmm__cat--on': row.cats.includes(col.value) }]"
                    @click="toggleCat(row.value, col.value)"
                  >{{ col.title }}</button>
                </div>
              </div>
            </div>
            <div v-else class="asa-rmm__empty">{{ emptyText }}</div>

            <v-autocomplete
              class="asa-rmm__add"
              :model-value="null"
              @update:model-value="addRegion"
              :items="availableRegions"
              item-title="title"
              item-value="value"
              :placeholder="addText"
              density="compact"
              variant="outlined"
              hide-details
              prepend-inner-icon="mdi-plus"
              :no-data-text="t('allAdded')"
            ></v-autocomplete>
          </div>
        </v-card-text>
        <v-card-actions>
          <v-btn v-if="regionRows.length" variant="text" @click="commitMap({})">{{ t('clearAll') }}</v-btn>
          <v-spacer />
          <v-btn color="primary" variant="flat" @click="rmmOpen = false">{{ t('done') }}</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </div>

  <!-- 普通文本 / cron / 其它 -->
  <v-text-field
    v-else
    class="asa-control"
    :model-value="modelValue"
    @update:model-value="emitVal"
    :aria-label="field.label"
    :placeholder="field.placeholder || ''"
    density="compact"
    hide-details
    variant="outlined"
  ></v-text-field>
</template>

<script setup>
import { computed, getCurrentInstance, ref } from 'vue'

const props = defineProps({
  field: { type: Object, required: true },
  modelValue: { default: null },
})
const emit = defineEmits(['update:modelValue'])

// --- i18n（内联，保持联邦块自包含）---
const MSG = {
  'zh-CN': { unset: '未选择', add: '添加{n}…', allAdded: '已全部添加', empty: '暂未选择{n}', remove: '移除', clearAll: '清空', n_region: '地区', n_platform: '平台', done: '完成', rmmSummary: '已配置 {n} 项', enable: '启用' },
  'zh-TW': { unset: '未選擇', add: '新增{n}…', allAdded: '已全部新增', empty: '尚未選擇{n}', remove: '移除', clearAll: '清空', n_region: '地區', n_platform: '平台', done: '完成', rmmSummary: '已設定 {n} 項', enable: '啟用' },
  'en-US': { unset: 'None', add: 'Add {n}…', allAdded: 'All added', empty: 'No {n} selected', remove: 'Remove', clearAll: 'Clear', n_region: 'region', n_platform: 'platform', done: 'Done', rmmSummary: '{n} configured', enable: 'Enable' },
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
// 行的名词（地区/平台…）+ 组合文案，供 region-media-map 文案本地化
const rowNoun = computed(() => t('n_' + (props.field.row_noun || 'region')))
const addText = computed(() => t('add', { n: rowNoun.value }))
const emptyText = computed(() => t('empty', { n: rowNoun.value }))

const isSelect = computed(() => props.field.kind === 'select' || props.field.kind === 'multi-select')
const isNumber = computed(() => props.field.kind === 'number' || props.field.kind === 'float')

const normalizedSelectValue = computed(() => {
  if (props.field.kind === 'multi-select') return Array.isArray(props.modelValue) ? props.modelValue : []
  return props.modelValue
})
const overflowCount = computed(() => (Array.isArray(props.modelValue) ? Math.max(0, props.modelValue.length - 1) : 0))
const selCount = computed(() => (Array.isArray(props.modelValue) ? props.modelValue.length : 0))

// region-media-map ------------------------------------------------------
const columns = computed(() => props.field.columns || [])
const regionMap = computed(() => (props.modelValue && typeof props.modelValue === 'object' && !Array.isArray(props.modelValue) ? props.modelValue : {}))
// 条目形态兼容：旧 [cats]（启用）与新 {on, cats}（可禁用而不丢配置）。
function entryCats(v) { return (v && typeof v === 'object' && !Array.isArray(v)) ? (Array.isArray(v.cats) ? v.cats : []) : (Array.isArray(v) ? v : []) }
function entryOn(v) { return (v && typeof v === 'object' && !Array.isArray(v)) ? (v.on !== false) : true }
// 已添加地区行，按 options 顺序稳定排列
const regionRows = computed(() =>
  (props.field.options || [])
    .filter(o => regionMap.value[o.value] !== undefined)
    .map(o => ({ value: o.value, title: o.title, cats: entryCats(regionMap.value[o.value]), on: entryOn(regionMap.value[o.value]) })))
const availableRegions = computed(() => (props.field.options || []).filter(o => regionMap.value[o.value] === undefined))
// 弹窗开关 + 内联触发按钮上的摘要（已配置地区数）
const rmmOpen = ref(false)
const rmmSummary = computed(() => (regionRows.value.length ? t('rmmSummary', { n: regionRows.value.length }) : emptyText.value))

function commitMap(next) {
  emit('update:modelValue', next)
}
// 某行适用的列：列声明了 rows 则仅这些行显示该列（如猫眼网络电影仅腾讯/爱奇艺/优酷）。
function columnsForRow(rowValue) {
  return columns.value.filter(c => !Array.isArray(c.rows) || c.rows.includes(rowValue))
}
function addRegion(value) {
  if (!value || regionMap.value[value] !== undefined) return
  // 默认启用并勾选该行适用的全部媒体类型
  commitMap({ ...regionMap.value, [value]: { on: true, cats: columnsForRow(value).map(c => c.value) } })
}
function removeRegion(value) {
  const next = { ...regionMap.value }
  delete next[value]
  commitMap(next)
}
function toggleCat(region, cat) {
  const entry = regionMap.value[region]
  const cur = entryCats(entry)
  const nextCats = cur.includes(cat) ? cur.filter(c => c !== cat) : [...cur, cat]
  if (!nextCats.length) {
    // 全部取消则移除该地区，避免产生空条目（如需保留配置请用「启用」开关关闭而非清空）
    removeRegion(region)
    return
  }
  commitMap({ ...regionMap.value, [region]: { on: entryOn(entry), cats: nextCats } })
}
// 启用/禁用某组合：禁用时保留其类别配置（后端跳过不生效），便于以后重新启用无需重设。
function toggleEnabled(region) {
  const entry = regionMap.value[region]
  commitMap({ ...regionMap.value, [region]: { on: !entryOn(entry), cats: entryCats(entry) } })
}

function emitVal(v) { emit('update:modelValue', v) }
// 拦截负号/科学计数键，从源头禁止输入负数（配合 min=0 与下方 clamp）
function blockNegative(e) {
  if (e.key === '-' || e.key === '+' || e.key === 'e' || e.key === 'E') e.preventDefault()
}
function emitNum(v) {
  if (v === '' || v === null || v === undefined) { emit('update:modelValue', v); return }
  let n = props.field.kind === 'float' ? parseFloat(v) : parseInt(v, 10)
  if (Number.isNaN(n)) { emit('update:modelValue', v); return }
  if (n < 0) n = 0  // 锁死非负：负值统一归零，避免负条数/负年份等引发错误
  emit('update:modelValue', n)
}
function step(dir) {
  const cur = Number(props.modelValue)
  const base = Number.isFinite(cur) ? cur : 0
  let next = props.field.kind === 'float' ? Math.round((base + dir * 0.5) * 10) / 10 : base + dir
  if (next < 0) next = 0  // 步进不越过 0
  emit('update:modelValue', next)
}
</script>

<style scoped>
.asa-control { inline-size: 100%; }
.asa-control :deep(.v-select__selection),
.asa-control:not(.v-textarea) :deep(input) { justify-content: flex-end; }
.asa-select__primary { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.asa-select__more { flex: 0 0 auto; margin-inline-start: 6px; color: rgba(var(--v-theme-on-surface), 0.58); white-space: nowrap; }
.asa-select__clear { cursor: pointer; color: rgba(var(--v-theme-on-surface), 0.4); transition: color 0.15s ease; }
.asa-select__clear:hover { color: rgb(var(--v-theme-error)); }
.asa-rmm__clear {
  display: inline-flex; align-items: center; gap: 4px; align-self: flex-end;
  padding: 2px 6px; border: 0; background: transparent; color: rgba(var(--v-theme-on-surface), 0.5);
  font-size: 0.72rem; cursor: pointer; transition: color 0.15s ease;
}
.asa-rmm__clear:hover { color: rgb(var(--v-theme-error)); }

/* 数字步进器 */
.asa-stepper {
  display: grid;
  align-items: center;
  inline-size: 100%;
  min-block-size: 40px;
  overflow: hidden;
  border: 1px solid rgba(var(--v-theme-on-surface), 0.22);
  border-radius: var(--app-control-radius, 8px);
  grid-template-columns: 38px minmax(48px, 1fr) 38px;
  transition: border-color 0.15s ease;
}
.asa-stepper:focus-within { border-color: rgb(var(--v-theme-primary)); }
.asa-stepper :deep(.v-btn) { block-size: 38px; inline-size: 38px; border-radius: 0; color: rgba(var(--v-theme-on-surface), 0.6); }
.asa-stepper__input {
  min-inline-size: 0; inline-size: 100%; padding: 0 4px; border: 0; background: transparent;
  color: rgb(var(--v-theme-on-surface)); font-size: 0.85rem; text-align: center;
  font-variant-numeric: tabular-nums; outline: none; -moz-appearance: textfield;
}
.asa-stepper__input::-webkit-outer-spin-button,
.asa-stepper__input::-webkit-inner-spin-button { margin: 0; -webkit-appearance: none; }

/* region-media-map：内联折叠触发按钮 + 弹窗卡片管理 */
.asa-rmm-field { inline-size: 100%; }
.asa-rmm-trigger { inline-size: 100%; justify-content: space-between; text-transform: none; letter-spacing: 0; font-weight: 500; }
.asa-rmm-trigger__txt { flex: 1 1 auto; overflow: hidden; text-align: start; text-overflow: ellipsis; white-space: nowrap; }
.asa-rmm-dlg__title { display: flex; align-items: center; gap: 8px; font-size: 1rem; font-weight: 700; }
.asa-rmm-dlg__hint { margin: 0 0 12px; color: rgba(var(--v-theme-on-surface), 0.6); font-size: 0.78rem; line-height: 1.4; }
.asa-rmm-dlg__body { padding-block: 12px 6px; }

.asa-rmm { inline-size: 100%; display: flex; flex-direction: column; gap: 10px; }
.asa-rmm__rows { display: flex; flex-direction: column; gap: 8px; }
/* 每个地区为一张卡：名称+删除在上、类别 chips 换行在下 → 列（媒体类型）再多也完整显示不挤压 */
.asa-rmm__row {
  display: flex; flex-direction: column; gap: 8px; padding: 10px 12px;
  border: 1px solid rgba(var(--v-theme-on-surface), 0.12);
  border-radius: var(--app-control-radius, 8px);
  background: rgba(var(--v-theme-on-surface), 0.03);
}
.asa-rmm__head { display: flex; align-items: center; gap: 8px; }
/* 启用开关：去掉 v-switch 默认 ~40px 的触控最小高度、并缩小轨道/滑块，使其与单行文字（约 20px）高度一致（不再过高） */
.asa-rmm__switch { flex: 0 0 auto; margin: 0; }
.asa-rmm__switch :deep(.v-input__control),
.asa-rmm__switch :deep(.v-selection-control),
.asa-rmm__switch :deep(.v-selection-control__wrapper) { min-block-size: 0; block-size: auto; }
.asa-rmm__switch :deep(.v-selection-control__input) { inline-size: auto; block-size: auto; }
.asa-rmm__switch :deep(.v-switch__track) { block-size: 16px; min-inline-size: 28px; }
.asa-rmm__switch :deep(.v-switch__thumb) { block-size: 12px; inline-size: 12px; }
.asa-rmm__name { min-inline-size: 0; overflow: hidden; font-size: 0.86rem; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
/* 禁用态：名称置灰划线、类别整体淡化（配置保留，可随时重新启用） */
.asa-rmm__name--off { color: rgba(var(--v-theme-on-surface), 0.42); text-decoration: line-through; }
.asa-rmm__cats { display: flex; flex-wrap: wrap; gap: 6px; }
.asa-rmm__cats--off { opacity: 0.45; }
.asa-rmm__cat {
  padding: 4px 12px;
  border: 1px solid rgba(var(--v-theme-on-surface), 0.2);
  border-radius: 999px;
  background: transparent;
  color: rgba(var(--v-theme-on-surface), 0.65);
  font-size: 0.76rem;
  cursor: pointer;
  transition: all 0.12s ease;
}
.asa-rmm__cat--on { border-color: rgb(var(--v-theme-primary)); background: rgba(var(--v-theme-primary), 0.14); color: rgb(var(--v-theme-primary)); font-weight: 600; }
.asa-rmm__del { color: rgba(var(--v-theme-on-surface), 0.45); }
.asa-rmm__empty { padding: 14px 4px; color: rgba(var(--v-theme-on-surface), 0.5); font-size: 0.8rem; text-align: center; }
.asa-rmm__add { margin-top: 2px; }
</style>
