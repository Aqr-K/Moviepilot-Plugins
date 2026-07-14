<template>
  <span
    class="asa-logo"
    :style="{ width: px, height: px }"
    role="img"
    :aria-label="provider"
  >
    <span v-if="svg" class="asa-logo__svg" v-html="svg"></span>
    <v-icon v-else :icon="fallback" :size="size" />
  </span>
</template>

<script setup>
import { computed } from 'vue'
// 猫眼电影官方 logo（用户提供的官方 SVG，以 raw 内联，保持联邦块自包含、规避资源 URL 解析问题）
import maoyanSvg from '../assets/maoyan.svg?raw'

// 官方 SVG 规整：去内部 <style>（防全局 path 样式泄漏）、补 viewBox 并去固定尺寸以随容器缩放
function normalizeSvg(raw) {
  const s = String(raw || '').replace(/<style[^>]*>[\s\S]*?<\/style>/gi, '')
  return s.replace(/<svg\b[^>]*>/i, (tag) => {
    let t = tag
    if (!/viewBox=/i.test(t)) t = t.replace(/<svg\b/i, '<svg viewBox="0 0 500 500"')
    if (!/preserveAspectRatio=/i.test(t)) t = t.replace(/<svg\b/i, '<svg preserveAspectRatio="xMidYMid meet"')
    return t.replace(/\swidth="[^"]*"/i, '').replace(/\sheight="[^"]*"/i, '')
  })
}

const props = defineProps({
  provider: { type: String, default: '' },
  size: { type: [Number, String], default: 20 },
  fallback: { type: String, default: 'mdi-rss' },
})

const px = computed(() => `${Number(props.size)}px`)

/**
 * 各来源的品牌化内联 SVG（24×24 视图框，几何简化、单色可识别）。
 * mikan=柑桔，netflix=官方 N，maoyan=猫头，douban=豆荚；其余走 mdi 兜底。
 */
const LOGOS = {
  // Mikan（蜜柑计划）—— 柑桔：橙色果身 + 顶部绿叶 + 果瓣分隔
  mikan: `<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path d="M12 5.6c-1.1-1.9-3.2-2.6-4.7-1.8 1 .2 2.4 1 3.1 2.4.5-.3 1-.5 1.6-.6Z" fill="#4CAF50"/>
    <circle cx="12" cy="14" r="7.3" fill="#FF9800"/>
    <circle cx="12" cy="14" r="7.3" fill="url(#mkg)" fill-opacity="0.35"/>
    <g stroke="#EF6C00" stroke-width="0.9" stroke-linecap="round" opacity="0.55">
      <path d="M12 7.2v13.6M5.4 12.4l13.2 3.2M18.6 12.4 5.4 15.6"/>
    </g>
    <defs><radialGradient id="mkg" cx="0.35" cy="0.3" r="0.8">
      <stop offset="0" stop-color="#FFCC80"/><stop offset="1" stop-color="#FF9800" stop-opacity="0"/>
    </radialGradient></defs>
  </svg>`,

  // Netflix —— 官方 N：左右竖条 + 贯穿对角
  netflix: `<svg viewBox="0 0 24 24" fill="#E50914" xmlns="http://www.w3.org/2000/svg">
    <rect x="4" y="3" width="4.3" height="18" rx="0.3"/>
    <rect x="15.7" y="3" width="4.3" height="18" rx="0.3"/>
    <path d="M4 3h4.3l11.7 18h-4.3L4 3Z" fill="#B20710"/>
  </svg>`,

  // 猫眼电影 —— 官方 logo（用户提供的官方 SVG，规整后原样显示）
  maoyan: normalizeSvg(maoyanSvg),

  // 豆瓣 —— 官方绿方标（品牌绿 #2CA253）+ 白「豆」字
  douban: `<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
    <rect x="2.5" y="2.5" width="19" height="19" rx="4.6" fill="#2CA253"/>
    <text x="12" y="16.7" text-anchor="middle" fill="#fff" font-weight="700" font-size="13"
      font-family="'PingFang SC','Hiragino Sans GB','Microsoft YaHei',sans-serif">豆</text>
  </svg>`,
}

const svg = computed(() => LOGOS[props.provider] || '')
</script>

<style scoped>
.asa-logo {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  line-height: 0;
}
.asa-logo__svg { display: inline-flex; inline-size: 100%; block-size: 100%; }
.asa-logo__svg :deep(svg) { inline-size: 100%; block-size: 100%; display: block; }
</style>
