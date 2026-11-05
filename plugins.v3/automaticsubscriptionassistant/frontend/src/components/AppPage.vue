<template>
  <Page :api="api" sidebar :show_switch="false" @close="emit('close')" />
</template>

<script setup>
import Page from './Page.vue'
defineProps({
  api: { type: Object, default: () => ({}) },
  navKey: { type: String, default: 'main' },
  pluginId: { type: String, default: '' },
})
const emit = defineEmits(['close'])
</script>
