// 动态网格：随容器宽度实时测量网格「实际列数」（读取 grid-template-columns 的轨道数，
// 要求网格使用 auto-fill，空轨道也计入，故少量条目时列数依然准确）。
// 仅负责测量列数；每页条数由使用方按「桌面 = 列 × 行数、单列移动端 = 用户所选行数」自行派生。
import { onBeforeUnmount, onMounted, ref, type Ref } from 'vue'

export interface UseMediaGridOptions {
  /** 网格容器内用于测量的选择器，默认 `.asa-grid` */
  gridSelector?: string
}

export interface UseMediaGridReturn {
  /** 绑定到始终存在的容器（加载 / 空态也在），需在模板上 ref 引用 */
  containerRef: Ref<HTMLElement | null>
  /** 当前测得的实际列数（≥ 1） */
  cols: Ref<number>
  /** 立即重新测量一次列数 */
  measure: () => void
}

export function useMediaGrid(
  { gridSelector = '.asa-grid' }: UseMediaGridOptions = {},
): UseMediaGridReturn {
  const containerRef = ref<HTMLElement | null>(null)
  const cols = ref(1)
  let ro: ResizeObserver | null = null
  let raf = 0
  const timers = new Set<number>()

  function countColumns(): number {
    const c = containerRef.value
    if (!c) return cols.value
    const grid = c.querySelector(gridSelector)
    if (!grid) return cols.value
    const tpl = getComputedStyle(grid).gridTemplateColumns || ''
    const n = tpl.split(' ').map(s => s.trim()).filter(s => s && s !== '0px' && s !== 'none').length
    return n || 1
  }

  function measure(): void { cols.value = countColumns() }

  function scheduleMeasure(): void {
    if (typeof window === 'undefined') return
    if (raf) window.cancelAnimationFrame(raf)
    raf = window.requestAnimationFrame(() => { raf = 0; measure() })
  }

  onMounted(() => {
    if (typeof window === 'undefined' || typeof ResizeObserver === 'undefined') { measure(); return }
    ro = new ResizeObserver(() => scheduleMeasure())
    if (containerRef.value) ro.observe(containerRef.value)
    scheduleMeasure()
    // 布局稳定后补测：兜底首帧 / 宿主弹窗展开动画期间的列数欠测（欠测会导致每页条数=列×3 偏小 → 只显示 2 行）。
    for (const d of [120, 360, 800]) {
      const id = window.setTimeout(() => { timers.delete(id); measure() }, d)
      timers.add(id)
    }
  })

  onBeforeUnmount(() => {
    if (ro) { ro.disconnect(); ro = null }
    if (raf && typeof window !== 'undefined') window.cancelAnimationFrame(raf)
    timers.forEach(id => window.clearTimeout(id))
    timers.clear()
  })

  return { containerRef, cols, measure }
}
