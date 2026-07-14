<template>
  <!-- 横版卡片：左海报容器，右元数据。所有展示串由父级预解析（缺失已填「未知」）。 -->
  <article :class="['mc', { 'mc--selectable': selectable, 'mc--selected': selected }]" @click="onCardClick">
    <!-- 选择框（多选模式） -->
    <label v-if="selectable" class="mc__check" @click.stop>
      <input type="checkbox" :checked="selected" @change="emit('toggle')" />
      <span class="mc__checkbox"><v-icon v-if="selected" icon="mdi-check" size="13" /></span>
    </label>

    <div class="mc__poster">
      <img v-if="poster && !imgFailed" :src="poster" :alt="name" class="mc__img" loading="lazy" @error="imgFailed = true" />
      <div v-else class="mc__ph"><v-icon icon="mdi-movie-open-outline" size="26" /></div>
      <span v-if="status" class="mc__badge" :style="{ background: status.color }">
        <v-icon :icon="status.icon" size="11" />
        {{ status.label }}
      </span>
    </div>

    <div class="mc__body">
      <div class="mc__title" :title="name">{{ name }}</div>
      <ul class="mc__meta">
        <li v-for="(ln, i) in lines" :key="i" class="mc__row" :title="`${ln.label}：${ln.value}`">
          <v-icon :icon="ln.icon" size="13" class="mc__row-ico" />
          <span class="mc__row-k">{{ ln.label }}</span>
          <span class="mc__row-v">{{ ln.value }}</span>
        </li>
      </ul>
    </div>

    <!-- 右下角「更多」操作：收进下拉菜单，避免卡片外露按钮被误触 -->
    <div v-if="$slots.actions && !selectable" class="mc__more" @click.stop>
      <v-btn
        :aria-label="moreLabel"
        class="mc__more-btn"
        icon="mdi-dots-horizontal"
        size="small"
        variant="text"
      />
      <v-menu activator="parent" location="top end" :close-on-content-click="true">
        <v-list class="mc__more-list" density="compact" nav>
          <slot name="actions" />
        </v-list>
      </v-menu>
    </div>
  </article>
</template>

<script setup>
import { ref } from 'vue'

const props = defineProps({
  poster: { type: String, default: '' },
  name: { type: String, default: '' },
  // 元数据行：[{ icon, label, value }]，value 已由父级填好（缺失为「未知」）
  lines: { type: Array, default: () => [] },
  // 状态徽标：{ label, color, icon }
  status: { type: Object, default: null },
  selectable: { type: Boolean, default: false },
  selected: { type: Boolean, default: false },
  // 「更多」菜单按钮的无障碍名（父级按语言传入）
  moreLabel: { type: String, default: '更多' },
})
const emit = defineEmits(['toggle'])
const imgFailed = ref(false)

function onCardClick() {
  // 多选模式下，点整卡即切换选择（操作按钮区已 stop）
  if (props.selectable) emit('toggle')
}
</script>

<style scoped>
.mc {
  position: relative;
  display: grid; grid-template-columns: 84px 1fr; gap: 10px;
  padding: 8px; overflow: hidden;
  border: var(--app-surface-border, 1px solid rgba(var(--v-theme-on-surface), 0.08));
  border-radius: var(--app-surface-radius, 12px);
  background: var(--app-grouped-list-background, rgb(var(--v-theme-surface)));
  transition: transform 0.16s ease, box-shadow 0.16s ease, border-color 0.16s ease;
}
.mc:hover { transform: translateY(-2px); box-shadow: 0 8px 22px rgba(var(--v-theme-on-surface), 0.12); }
.mc--selectable { cursor: pointer; }
.mc--selected { border-color: rgb(var(--v-theme-primary)); box-shadow: 0 0 0 2px rgba(var(--v-theme-primary), 0.5) inset; }

.mc__check { position: absolute; inset-block-start: 6px; inset-inline-start: 6px; z-index: 3; display: inline-flex; cursor: pointer; }
.mc__check input { position: absolute; opacity: 0; inline-size: 1px; block-size: 1px; }
.mc__checkbox {
  display: inline-flex; align-items: center; justify-content: center; inline-size: 20px; block-size: 20px;
  border: 2px solid #fff; border-radius: 6px; background: rgba(0, 0, 0, 0.45); color: #fff;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.4);
}
.mc--selected .mc__checkbox { background: rgb(var(--v-theme-primary)); border-color: rgb(var(--v-theme-primary)); }

.mc__poster { position: relative; aspect-ratio: 2 / 3; border-radius: 8px; overflow: hidden; background: rgba(var(--v-theme-on-surface), 0.06); }
.mc__img { display: block; inline-size: 100%; block-size: 100%; object-fit: cover; }
.mc__ph { display: flex; align-items: center; justify-content: center; block-size: 100%; color: rgba(var(--v-theme-on-surface), 0.3); }
.mc__badge {
  position: absolute; inset-block-end: 4px; inset-inline-start: 4px; inset-inline-end: 4px;
  display: inline-flex; align-items: center; justify-content: center; gap: 3px; padding: 2px 4px; border-radius: 6px;
  color: #fff; font-size: 0.6rem; font-weight: 600; line-height: 1.3; box-shadow: 0 2px 6px rgba(0, 0, 0, 0.28);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}

.mc__body { display: flex; flex-direction: column; gap: 5px; min-inline-size: 0; }
.mc__title { overflow: hidden; font-size: 0.86rem; font-weight: 700; line-height: 1.25; text-overflow: ellipsis; white-space: nowrap; }
.mc__meta { display: flex; flex-direction: column; gap: 2px; margin: 0; padding: 0; list-style: none; }
.mc__row { display: flex; align-items: center; gap: 5px; min-inline-size: 0; font-size: 0.72rem; line-height: 1.35; }
.mc__row-ico { flex: 0 0 auto; color: rgba(var(--v-theme-on-surface), 0.45); }
.mc__row-k { flex: 0 0 auto; color: rgba(var(--v-theme-on-surface), 0.5); }
.mc__row-v { overflow: hidden; color: rgba(var(--v-theme-on-surface), 0.82); text-overflow: ellipsis; white-space: nowrap; }
/* 右下角「更多」菜单触发按钮（位于海报撑起的行高内、元数据下方余白处，不遮挡文字） */
.mc__more { position: absolute; inset-block-end: 4px; inset-inline-end: 4px; z-index: 2; }
.mc__more-btn { color: rgba(var(--v-theme-on-surface), 0.6); }
.mc__more-btn:hover { color: rgb(var(--v-theme-primary)); }
.mc__more-list { min-inline-size: 132px; }

@media (prefers-reduced-motion: reduce) { .mc { transition: none; } }
</style>
