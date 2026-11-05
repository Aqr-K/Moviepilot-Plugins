<template>
  <rule-cards v-if="field.kind === 'rule-list'" :key="field.key" :field="field" :provider-id="providerId" :provider-name="providerName" :model-value="modelValue" @update:model-value="emitVal" />
  <!-- 开关：紧凑、无内联标签（标签由字段行提供） -->
  <v-switch
    v-else-if="field.kind === 'switch'"
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
import { computed, getCurrentInstance } from 'vue'
import RuleCards from './RuleCards.vue'

const props = defineProps({
  field: { type: Object, required: true },
  providerId: { type: String, default: '' },
  providerName: { type: String, default: '' },
  modelValue: { default: null },
})
const emit = defineEmits(['update:modelValue'])

// --- i18n（内联，保持联邦块自包含）---
const MSG = {
  'zh-CN': { unset:'未选择', clearAll:'清空' },
  'zh-TW': { unset:'未選擇', clearAll:'清空' },
  'en-US': { unset:'None', clearAll:'Clear' },
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
const isSelect = computed(() => props.field.kind === 'select' || props.field.kind === 'multi-select')
const isNumber = computed(() => props.field.kind === 'number' || props.field.kind === 'float')

const normalizedSelectValue = computed(() => {
  if (props.field.kind === 'multi-select') return Array.isArray(props.modelValue) ? props.modelValue : []
  return props.modelValue
})
const overflowCount = computed(() => (Array.isArray(props.modelValue) ? Math.max(0, props.modelValue.length - 1) : 0))
const selCount = computed(() => (Array.isArray(props.modelValue) ? props.modelValue.length : 0))

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

</style>
