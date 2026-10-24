/** 在真实 Vue 响应式运行时执行组件逻辑，接口响应顺序由测试控制。 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import { test } from 'node:test'
import * as Vue from 'vue'

function component(name, props, exports) {
  const source = fs.readFileSync(new URL(`../src/components/${name}.vue`, import.meta.url), 'utf8')
  const script = source.match(/<script setup[^>]*>([\s\S]*?)<\/script>/)[1].replace(/^import .*$/mg, '')
  const scope = Vue.effectScope()
  const env = {
    computed: Vue.computed,
    reactive: Vue.reactive,
    ref: Vue.ref,
    watch: Vue.watch,
    nextTick: Vue.nextTick,
    getCurrentInstance: () => null,
    onMounted: () => {},
    onUnmounted: () => {},
    onBeforeUnmount: () => {},
    defineProps: () => props,
    defineEmits: () => () => {},
    defineExpose: () => {},
    useMediaGrid: () => ({ containerRef: Vue.ref(null), cols: Vue.ref(1), measure: () => {} }),
  }
  const result = scope.run(() => Function(...Object.keys(env), `${script}\nreturn {${exports.join(',')}}`)(...Object.values(env)))
  return { ...result, dispose: () => scope.stop() }
}

function deferred() {
  let resolve
  const promise = new Promise(done => { resolve = done })
  return { promise, resolve }
}

const template = fs.readFileSync(new URL('../src/components/Page.vue', import.meta.url), 'utf8')
if (template.includes('/history/uniques?')) {
  test('全选进行中刷新历史，过期结果不写入且加载状态正常结束', async () => {
    const request = deferred()
    const page = component('Page', {
      api: { get: url => url.includes('/uniques') ? request.promise : Promise.resolve({ list: [], total: 0 }) },
      show_switch: true,
    }, ['selectAll', 'fetchHistory', 'selected', 'selectingAll'])
    try {
      const pending = page.selectAll()
      assert.equal(page.selectingAll.value, true)
      await page.fetchHistory()
      request.resolve({ uniques: ['outdated'] })
      await pending
      assert.equal(page.selectingAll.value, false)
      assert.equal(page.selected.size, 0)
    } finally { page.dispose() }
  })

  test('两次全选只采纳最后一次响应', async () => {
    const first = deferred()
    const second = deferred()
    let requests = 0
    const page = component('Page', {
      api: { get: () => ++requests === 1 ? first.promise : second.promise }, show_switch: true,
    }, ['selectAll', 'selected', 'selectingAll'])
    try {
      const a = page.selectAll()
      const b = page.selectAll()
      second.resolve({ uniques: ['latest'] })
      await b
      first.resolve({ uniques: ['outdated'] })
      await a
      assert.deepEqual([...page.selected], ['latest'])
      assert.equal(page.selectingAll.value, false)
    } finally { page.dispose() }
  })
  test('退出多选后，未完成的全选不能重新勾选旧结果', async () => {
    const request = deferred()
    const page = component('Page', {
      api: { get: () => request.promise }, show_switch: true,
    }, ['selectAll', 'toggleSelectMode', 'selected', 'selectingAll'])
    try {
      page.toggleSelectMode()
      const pending = page.selectAll()
      page.toggleSelectMode()
      request.resolve({ uniques: ['outdated'] })
      await pending
      assert.equal(page.selected.size, 0)
      assert.equal(page.selectingAll.value, false)
    } finally { page.dispose() }
  })

}

function subscriptionView(response) {
  const view = component('SubscribeView', {
    api: { post: async () => response, get: async () => ({ list: [] }) }, page: 1, pageSize: 12,
  }, ['selected', 'confirm', 'runConfirm', 'error', 'mediaName'])
  view.selected.add(1)
  view.selected.add(2)
  Object.assign(view.confirm, { open: true, kind: 'delete', ids: [1, 2] })
  return view
}

test('批量操作部分失败，显示反馈并仅保留失败项供重试', async () => {
  const view = subscriptionView({ code: 0, ok: 1, failed: 1, ok_ids: [1], failed_ids: [2], message: '1 个失败' })
  try {
    await view.runConfirm()
    assert.deepEqual([...view.selected], [2])
    assert.deepEqual(view.confirm.ids, [2])
    assert.equal(view.confirm.open, true)
    assert.equal(view.error.value, '1 个失败')
  } finally { view.dispose() }
})

test('业务失败响应不会被当作成功关闭确认框', async () => {
  const view = subscriptionView({ code: 1, message: '权限不足' })
  try {
    await view.runConfirm()
    assert.deepEqual([...view.selected], [1, 2])
    assert.equal(view.confirm.open, true)
    assert.match(view.error.value, /权限不足/)
  } finally { view.dispose() }
})

test('全部成功才清空选择并关闭确认框', async () => {
  const view = subscriptionView({ code: 0, ok: 2, failed: 0, ok_ids: [1, 2], failed_ids: [] })
  try {
    await view.runConfirm()
    assert.equal(view.selected.size, 0)
    assert.equal(view.confirm.open, false)
    assert.equal(view.error.value, '')
  } finally { view.dispose() }
})

test('管理卡片标题可以区分不同季、特别篇和剧集组', () => {
  const view = subscriptionView({})
  try {
    assert.equal(view.mediaName({ name: '测试剧', type: '电视剧', season: 2 }), '测试剧 · S02')
    assert.equal(view.mediaName({ name: '测试剧', type: '电视剧', season: 0 }), '测试剧 · S00')
    assert.equal(view.mediaName({ name: '电影', type: '电影' }), '电影')
    assert.match(view.mediaName({ name: '测试剧', type: '电视剧', season: 2, episode_group: 'group-a' }), /剧集组: group-a/)
  } finally { view.dispose() }
})
