<template>
  <div class="fp" :class="{ 'fp--stacked': stacked }">
    <template v-for="field in fields" :key="field.key || field.keyMin">
      <!-- 搜索 -->
      <div v-if="field.type === 'search'" class="fp-item fp-item--search">
        <label v-if="stacked" class="fp-label" :for="fid(field.key)">{{ field.label }}</label>
        <v-text-field
          :id="fid(field.key)"
          :model-value="state[field.key]"
          :aria-label="field.label || field.placeholder"
          class="fp-ctl"
          clearable
          density="compact"
          hide-details
          :placeholder="field.placeholder"
          prepend-inner-icon="mdi-magnify"
          variant="outlined"
          @update:model-value="v => set(field.key, v || '', field)"
        />
      </div>

      <!-- 发行年份范围 -->
      <div v-else-if="field.type === 'year-range'" class="fp-item fp-item--year">
        <label v-if="stacked" class="fp-label" :for="fid(field.keyMin)">{{ field.label }}</label>
        <div class="fp-year">
          <v-text-field
            :id="fid(field.keyMin)"
            :model-value="state[field.keyMin]"
            :aria-label="`${field.label} ${field.minText}`"
            class="fp-ctl fp-year__in"
            clearable
            density="compact"
            hide-details
            inputmode="numeric"
            :placeholder="field.minText"
            type="number"
            variant="outlined"
            @update:model-value="v => set(field.keyMin, toYear(v), field)"
          />
          <span class="fp-year__sep">–</span>
          <v-text-field
            :id="fid(field.keyMax)"
            :model-value="state[field.keyMax]"
            :aria-label="`${field.label} ${field.maxText}`"
            class="fp-ctl fp-year__in"
            clearable
            density="compact"
            hide-details
            inputmode="numeric"
            :placeholder="field.maxText"
            type="number"
            variant="outlined"
            @update:model-value="v => set(field.keyMax, toYear(v), field)"
          />
        </div>
      </div>

      <!-- 下拉筛选（单选 / 多选） -->
      <div v-else-if="field.type === 'select'" class="fp-item fp-item--select">
        <label v-if="stacked" class="fp-label" :for="fid(field.key)">{{ field.label }}</label>
        <v-select
          :id="fid(field.key)"
          :model-value="state[field.key]"
          :aria-label="field.label"
          class="fp-ctl"
          :chips="!!field.multi"
          clearable
          :closable-chips="!!field.multi"
          density="compact"
          hide-details
          :items="field.items"
          item-title="title"
          item-value="value"
          :label="stacked ? undefined : field.label"
          :multiple="!!field.multi"
          :placeholder="field.allText"
          :prepend-inner-icon="field.icon"
          variant="outlined"
          @update:model-value="v => set(field.key, normalize(v, field), field)"
        />
      </div>
    </template>
  </div>
</template>

<script setup>
import { useId } from 'vue'
/**
 * 通用筛选面板（内联横排 / 弹窗堆叠两种布局）。
 *
 * 设计约定：`state` 是父级拥有的**响应式对象**，本组件按 `fields` 配置对其字段做
 * 就地赋值（单一数据源，避免 draft 拷贝在多层来回同步）；每次变更后 `emit('change', field)`，
 * 由父级决定副作用（历史→防抖重取；管理→客户端 computed 自动响应 + 复位页码）。
 * 「留空即不过滤（全部）」：搜索='' / 年份=null / 多选=[] / 单选=null。
 */
const props = defineProps({
  // 响应式筛选状态对象（父级 reactive），本组件就地写入其字段
  state: { type: Object, required: true },
  // 字段配置：
  //  { type:'search',     key, label, placeholder }
  //  { type:'year-range', keyMin, keyMax, label, minText, maxText }
  //  { type:'select',     key, label, items:[{title,value}], multi, icon, allText }
  fields: { type: Array, default: () => [] },
  // 堆叠布局（弹窗内每字段独占一行并带标题），否则内联横排
  stacked: { type: Boolean, default: false },
})
const emit = defineEmits(['change'])

// 为控件生成稳定唯一 id，供可见 <label for> 关联（无障碍：每个筛选控件有可区分的可访问名）
const uid = useId()
const fid = k => `${uid}-${k}`

function set(key, value, field) {
  props.state[key] = value
  emit('change', field)
}

// 空串/NaN → null（不过滤）；否则取整年份
function toYear(v) {
  if (v === null || v === undefined || v === '') return null
  const n = parseInt(v, 10)
  return Number.isFinite(n) ? n : null
}

// 多选：v-select 清空时可能给 null，统一规整为数组；单选清空给 null
function normalize(v, field) {
  if (field.multi) return Array.isArray(v) ? v : (v == null ? [] : [v])
  return v ?? null
}
</script>

<style scoped>
.fp { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; }
.fp-item { display: flex; align-items: center; min-inline-size: 0; }
.fp-ctl { inline-size: 100%; }

/* 内联（桌面）：各控件限定宽度，随行换行 */
.fp:not(.fp--stacked) .fp-item--search { flex: 1 1 200px; max-inline-size: 240px; }
.fp:not(.fp--stacked) .fp-item--select { flex: 1 1 170px; max-inline-size: 210px; }
.fp:not(.fp--stacked) .fp-item--year { flex: 0 0 auto; }

/* 堆叠（弹窗）：每字段独占一行，带标题 */
.fp--stacked { flex-direction: column; align-items: stretch; gap: 14px; }
.fp--stacked .fp-item { flex-direction: column; align-items: stretch; }
.fp-label {
  margin-block-end: 6px; font-size: 0.78rem; font-weight: 600;
  color: rgba(var(--v-theme-on-surface), 0.72);
}

.fp-year { display: flex; align-items: center; gap: 8px; }
.fp-year__in { inline-size: 108px; }
.fp--stacked .fp-year { inline-size: 100%; }
.fp--stacked .fp-year__in { flex: 1 1 0; inline-size: auto; }
.fp-year__sep { color: rgba(var(--v-theme-on-surface), 0.4); }

/* 隐藏数字输入框原生步进箭头，避免窄屏挤占宽度 */
.fp-year__in :deep(input[type='number']) { -moz-appearance: textfield; }
.fp-year__in :deep(input[type='number']::-webkit-outer-spin-button),
.fp-year__in :deep(input[type='number']::-webkit-inner-spin-button) {
  -webkit-appearance: none; margin: 0;
}
</style>
