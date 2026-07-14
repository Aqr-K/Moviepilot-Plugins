<template>
  <v-app>
    <v-app-bar color="surface" flat border>
      <v-app-bar-title class="text-body-1 font-weight-bold">自动订阅助手 · 组件预览</v-app-bar-title>
      <template #append>
        <v-btn-toggle v-model="previewWidth" density="comfortable" mandatory variant="outlined" class="mr-3">
          <v-btn :value="380" size="small">窄</v-btn>
          <v-btn :value="720" size="small">中</v-btn>
          <v-btn :value="1120" size="small">宽</v-btn>
        </v-btn-toggle>
        <v-btn prepend-icon="mdi-translate" variant="tonal" class="mr-2" @click="cycleLang">{{ langLabel }}</v-btn>
        <v-btn
          :prepend-icon="isDark ? 'mdi-weather-night' : 'mdi-weather-sunny'"
          variant="tonal"
          @click="toggleTheme"
        >{{ isDark ? '深色' : '浅色' }}</v-btn>
      </template>
    </v-app-bar>

    <v-main>
      <div class="preview-root">
        <v-tabs v-model="tab" color="primary" class="mb-4">
          <v-tab value="config">配置页 Config</v-tab>
          <v-tab value="page">历史页 Page</v-tab>
          <v-tab value="dashboard">仪表盘 Dashboard</v-tab>
        </v-tabs>

        <v-window v-model="tab">
          <!-- Config -->
          <v-window-item value="config">
            <div class="preview-frame" :style="frameStyle">
              <config-component :initial-config="mockConfig" :api="api" @save="onSave" @switch="tab = 'page'" @close="onClose" @layout="onLayout" />
            </div>
          </v-window-item>

          <!-- Page -->
          <v-window-item value="page">
            <div class="preview-frame" :style="frameStyle">
              <page-component :api="api" :show_switch="true" @switch="tab = 'config'" @close="onClose" />
            </div>
          </v-window-item>

          <!-- Dashboard -->
          <v-window-item value="dashboard">
            <div class="dash-controls mb-4">
              <v-switch v-model="dashBorder" color="primary" density="compact" hide-details inset label="显示边框" />
            </div>
            <div class="dash-grid">
              <div class="dash-cell">
                <div class="dash-cell__cap">仪表盘部件（宿主网格内约 1/2 宽）</div>
                <v-card v-if="!dashBorder" class="pa-4">
                  <dashboard-component :config="dashConfig" :allow-refresh="true" :api="api" />
                </v-card>
                <dashboard-component v-else :config="dashConfig" :allow-refresh="true" :api="api" />
              </div>
            </div>
          </v-window-item>
        </v-window>
      </div>
    </v-main>

    <v-snackbar v-model="snackbar.show" :color="snackbar.color" :timeout="2600">
      {{ snackbar.text }}
    </v-snackbar>
  </v-app>
</template>

<script setup>
import { computed, getCurrentInstance, reactive, ref } from 'vue'
import { useTheme } from 'vuetify'
import PageComponent from './components/Page.vue'
import ConfigComponent from './components/Config.vue'
import DashboardComponent from './components/Dashboard.vue'
import { createMockApi } from './dev/mockApi'

const theme = useTheme()
const api = createMockApi()

// 开发壳模拟宿主的 $i18n：组件读 appContext.globalProperties.$i18n.locale 跟随语言
const LANGS = ['zh-CN', 'zh-TW', 'en-US']
const LANG_LABEL = { 'zh-CN': '简体', 'zh-TW': '繁體', 'en-US': 'EN' }
const i18nStub = reactive({ locale: 'zh-CN' })
getCurrentInstance().appContext.config.globalProperties.$i18n = i18nStub
const langLabel = computed(() => LANG_LABEL[i18nStub.locale])
function cycleLang() {
  const i = LANGS.indexOf(i18nStub.locale)
  i18nStub.locale = LANGS[(i + 1) % LANGS.length]
}

const tab = ref('config')
const previewWidth = ref(1120)
const dashBorder = ref(true)
const snackbar = reactive({ show: false, text: '', color: 'success' })

const isDark = computed(() => theme.global.current.value.dark)
const frameStyle = computed(() => ({ maxWidth: `${previewWidth.value}px` }))

// 代表性已保存配置：启用部分来源，供脏值追踪 / 概览渲染
const mockConfig = {
  global: { enabled: true, notify: true, exist_ok: true, username: '自动订阅助手', onlyonce: false, clear: false },
  providers: {
    douban: { enabled: true, cron: '0 8 * * *' },
    maoyan: { enabled: true, cron: '30 9 * * *' },
    popular: { enabled: false },
    mikan: { enabled: true, cron: '0 10 * * 1' },
    netflix: {
      enabled: true,
      // 演示逐区组合：美国=电影+剧集、台湾=仅电影、日本=仅剧集
      options: { country_selections: { US: ['Films', 'TV'], TW: ['Films'], JP: ['TV'] } },
    },
  },
}

const dashConfig = reactive({
  id: 'AutomaticSubscriptionAssistant',
  name: '自动订阅助手',
  render_mode: 'vue',
  attrs: { title: '自动订阅助手', subtitle: '订阅概览', border: true, refresh: 0 },
})

function toggleTheme() {
  theme.global.name.value = isDark.value ? 'light' : 'dark'
}

function toast(text, color = 'success') {
  snackbar.text = text
  snackbar.color = color
  snackbar.show = true
}

function onSave(config) {
  console.log('[dev] save config:', config)
  toast('配置已保存（开发壳模拟）')
}
function onClose() { toast('close 事件', 'info') }
function onLayout(layout) { console.log('[dev] layout:', layout) }
</script>

<style scoped>
.preview-root {
  max-width: 1240px;
  margin: 0 auto;
  padding: 20px 16px 60px;
}
.preview-frame {
  margin: 0 auto;
  overflow: hidden;
  border: 1px solid rgba(var(--v-theme-on-surface), 0.12);
  border-radius: 14px;
  background: rgb(var(--v-theme-surface));
  box-shadow: 0 12px 40px rgba(var(--v-theme-on-surface), 0.08);
  transition: max-width 0.25s ease;
}
.dash-controls { max-width: 1240px; margin: 0 auto; }
.dash-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 20px; max-width: 1240px; margin: 0 auto; }
.dash-cell__cap { margin-bottom: 8px; color: rgba(var(--v-theme-on-surface), 0.5); font-size: 0.75rem; }
</style>
