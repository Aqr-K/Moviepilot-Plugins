<template>
  <div ref="scrollRef" class="asa-results" :class="{ 'asa-results--progressive': progressive }">
    <slot />
    <div v-if="progressive && (count || loading)" ref="sentinelRef" class="asa-results__end" aria-live="polite">
      <template v-if="loading">
        <v-progress-circular indeterminate size="20" width="2" :aria-label="t('loading')" />
        <span>{{ t('loading') }}</span>
      </template>
      <template v-else-if="error">
        <span role="alert">{{ error }}</span>
        <v-btn variant="text" size="small" @click="emit('load')">{{ t('retry') }}</v-btn>
      </template>
      <v-btn v-else-if="hasMore" variant="text" size="small" @click="emit('load')">{{ t('more') }}</v-btn>
      <span v-else>{{ t('finished') }}</span>
    </div>
  </div>
</template>

<script setup>
import { getCurrentInstance, nextTick, onBeforeUnmount, ref, watch } from 'vue'

const props = defineProps({
  progressive: Boolean,
  loading: Boolean,
  hasMore: Boolean,
  count: { type: Number, default: 0 },
  error: { type: String, default: '' },
})
const emit = defineEmits(['load'])
const scrollRef = ref(null)
const sentinelRef = ref(null)
const inst = getCurrentInstance()
const messages = {
  'zh-CN': { loading: '加载中…', more: '加载更多', retry: '重试', finished: '已全部加载' },
  'zh-TW': { loading: '載入中…', more: '載入更多', retry: '重試', finished: '已全部載入' },
  'en-US': { loading: 'Loading…', more: 'Load more', retry: 'Retry', finished: 'All loaded' },
}
function t(key) {
  const raw = inst?.appContext?.config?.globalProperties?.$i18n?.locale
  const lang = String(raw?.value || raw || '').toLowerCase()
  return messages[lang.startsWith('en') ? 'en-US' : /tw|hant|hk/.test(lang) ? 'zh-TW' : 'zh-CN'][key]
}

let observer = null
let generation = 0
function disconnect() { observer?.disconnect(); observer = null }
// 每批完成后重新观察，列表不足一屏时也会继续填充；错误后只接受手动重试。
watch(() => [props.progressive, props.loading, props.hasMore, props.count, props.error], async () => {
  const current = ++generation
  disconnect()
  await nextTick()
  if (current !== generation || !props.progressive || props.loading || !props.hasMore || props.error
      || !scrollRef.value || !sentinelRef.value || typeof IntersectionObserver === 'undefined') return
  observer = new IntersectionObserver(entries => {
    if (current === generation && entries.some(entry => entry.isIntersecting)
        && !props.loading && props.hasMore && !props.error) emit('load')
  }, { root: scrollRef.value, rootMargin: '0px 0px 160px 0px' })
  observer.observe(sentinelRef.value)
}, { immediate: true, flush: 'post' })

function scrollToTop() { if (scrollRef.value) scrollRef.value.scrollTop = 0 }
defineExpose({ scrollToTop })
onBeforeUnmount(() => { generation++; disconnect() })
</script>

<style scoped>
.asa-results--progressive {
  flex: 1 1 auto; min-block-size: 0; overflow-y: auto; overscroll-behavior: contain;
  scrollbar-gutter: stable; padding-block-end: 14px;
}
.asa-results__end {
  display: flex; align-items: center; justify-content: center; flex-wrap: wrap; gap: 8px;
  min-block-size: 56px; padding: 10px; color: rgba(var(--v-theme-on-surface), 0.6); font-size: 0.8rem;
}
</style>
