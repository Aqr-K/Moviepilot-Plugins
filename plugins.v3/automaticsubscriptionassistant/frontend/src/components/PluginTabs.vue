<template>
  <!-- 三标签导航（订阅历史 / 订阅管理 / 订阅配置），Page 与 Config 共用以保证风格一致 -->
  <nav class="asa-tabs" role="tablist">
    <button
      v-for="tab in tabs"
      :key="tab.key"
      type="button"
      role="tab"
      :aria-selected="active === tab.key"
      :class="['asa-tab', { 'asa-tab--active': active === tab.key }]"
      @click="emit('select', tab.key)"
    >
      <v-icon :icon="tab.icon" size="16" />
      <span class="asa-tab__label">{{ tab.label }}</span>
    </button>
  </nav>
</template>

<script setup>
defineProps({
  active: { type: String, default: '' },
  // [{ key, label, icon }]
  tabs: { type: Array, default: () => [] },
})
const emit = defineEmits(['select'])
</script>

<style scoped>
.asa-tabs {
  display: flex; align-items: center; gap: 4px; padding: 6px 16px 0;
  border-block-end: 1px solid rgba(var(--v-theme-on-surface), 0.1);
  background: var(--app-grouped-list-background, rgb(var(--v-theme-surface)));
  overflow-x: auto;
}
.asa-tabs::-webkit-scrollbar { block-size: 0; }
.asa-tab {
  display: inline-flex; align-items: center; gap: 6px; padding: 8px 14px; white-space: nowrap;
  border: 0; border-block-end: 2px solid transparent; background: transparent; cursor: pointer;
  color: rgba(var(--v-theme-on-surface), 0.6); font-size: 0.82rem; font-weight: 600;
  transition: color 0.15s ease, border-color 0.15s ease;
}
.asa-tab:hover { color: rgb(var(--v-theme-primary)); }
.asa-tab--active { color: rgb(var(--v-theme-primary)); border-block-end-color: rgb(var(--v-theme-primary)); }
</style>
