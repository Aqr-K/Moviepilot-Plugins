/** 在真实 Vue 响应式运行时执行组件逻辑，接口响应顺序由测试控制。 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import { test } from 'node:test'
import * as Vue from 'vue'

function component(name, props, exports, overrides = {}) {
  const source = fs.readFileSync(new URL(`../src/components/${name}.vue`, import.meta.url), 'utf8')
  const script = source.match(/<script setup[^>]*>([\s\S]*?)<\/script>/)[1].replace(/^import .*$/mg, '')
  const scope = Vue.effectScope()
  const events = []
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
    defineEmits: () => (...args) => events.push(args),
    defineExpose: () => {},
    useMediaGrid: () => ({ containerRef: Vue.ref(null), cols: Vue.ref(1), measure: () => {} }),
    ...overrides,
  }
  const result = scope.run(() => Function(...Object.keys(env), `${script}\nreturn {${exports.join(',')}}`)(...Object.values(env)))
  return { ...result, events, dispose: () => scope.stop() }
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

test('手动黑名单提交明确的类型、ID 与特别篇季号', async () => {
  const requests = []
  const dialog = component('BlacklistDialog', {
    modelValue: true, target: {}, api: { post: async (...args) => { requests.push(args); return { code: 0 } } },
  }, ['form', 'scope', 'save', 'error'])
  try {
    Object.assign(dialog.form, { title: ' 测试剧 ', type: '电视剧', media_source: 'themoviedb', media_id: ' 42 ', season: '0' })
    dialog.scope.value = 'season'
    await dialog.save()
    assert.equal(requests[0][0], 'plugin/AutomaticSubscriptionAssistant/blacklist/add')
    assert.equal(requests[0][1].media.title, '测试剧')
    assert.equal(requests[0][1].media.media_id, '42')
    assert.equal(requests[0][1].media.season, '0')
    assert.equal(requests[0][1].scope, 'season')
    assert(dialog.events.some(([event, value]) => event === 'update:modelValue' && value === false))
  } finally { dialog.dispose() }
})

test('加入黑名单失败时保留对话框并显示服务端错误', async () => {
  const dialog = component('BlacklistDialog', {
    modelValue: true, target: { kind: 'history', unique: 'old', type: '电影' },
    api: { post: async () => ({ code: 1, message: '黑名单保存失败' }) },
  }, ['save', 'error', 'saving'])
  try {
    await dialog.save()
    assert.equal(dialog.error.value, '黑名单保存失败')
    assert.equal(dialog.saving.value, false)
    assert.equal(dialog.events.length, 0)
  } finally { dialog.dispose() }
})

test('退订并忽略部分失败时只重试失败的订阅', async () => {
  const requests = []
  const dialog = component('BlacklistDialog', {
    modelValue: true, target: { kind: 'unsubscribe', ids: [1, 2] },
    api: { post: async (...args) => { requests.push(args); return { code: 0, failed: 1, ok_ids: [1], failed_ids: [2], message: '2 退订失败' } } },
  }, ['save', 'pendingIds', 'error'])
  try {
    dialog.pendingIds.value = [1, 2]
    await dialog.save()
    assert.deepEqual(dialog.pendingIds.value, [2])
    assert.equal(dialog.error.value, '2 退订失败')
    assert(!dialog.events.some(([event]) => event === 'update:modelValue'))
    await dialog.save()
    assert.equal(requests[0][0], 'plugin/AutomaticSubscriptionAssistant/subscribes/block')
    assert.deepEqual(requests[1][1].ids, [2])
  } finally { dialog.dispose() }
})

test('黑名单列表忽略过期响应，移除后刷新列表', async () => {
  const first = deferred()
  let calls = 0
  const requests = []
  const view = component('BlacklistView', {
    api: { get: () => ++calls === 1 ? first.promise : Promise.resolve({ code: 0, list: [{ id: 'new', title: '新规则' }] }),
      post: async (...args) => { requests.push(args); return { code: 0 } } },
  }, ['reload', 'rows', 'removing', 'remove'])
  try {
    const pending = view.reload()
    await view.reload()
    first.resolve({ code: 0, list: [{ id: 'old', title: '旧规则' }] })
    await pending
    assert.equal(view.rows.value[0].id, 'new')
    view.removing.value = { id: 'new' }
    await view.remove()
    assert.deepEqual(requests[0], ['plugin/AutomaticSubscriptionAssistant/blacklist/delete', { ids: ['new'] }])
    assert.equal(view.removing.value, null)
  } finally { view.dispose() }
})

test('历史和配置页均提供独立黑名单标签，订阅管理提供退订并忽略入口', () => {
  const source = fs.readFileSync(new URL('../src/components/Page.vue', import.meta.url), 'utf8')
  const config = fs.readFileSync(new URL('../src/components/Config.vue', import.meta.url), 'utf8')
  const manage = fs.readFileSync(new URL('../src/components/SubscribeView.vue', import.meta.url), 'utf8')
  assert(source.includes("key: 'blacklist'"))
  assert(config.includes("key: 'blacklist'"))
  assert(manage.includes('openBlacklist(item)'))
  const page = component('Page', { api: {}, show_switch: true }, ['onTab', 'view'])
  try { page.onTab('blacklist'); assert.equal(page.view.value, 'blacklist') }
  finally { page.dispose() }
})

test('黑名单筛选草稿取消不生效，应用后按名称、类型与年份组合过滤', async () => {
  const view = component('BlacklistView', { api: {}, pageSize: 10, page: 2 },
    ['rows', 'draft', 'filtered', 'openFilterDialog', 'applyFilterDialog', 'clearFilters', 'activeFilterCount'])
  try {
    view.rows.value = [
      { id: 'tv', title: '测试剧', type: '电视剧', year: '2026' },
      { id: 'old', title: '测试剧', type: '电视剧', year: '2024' },
      { id: 'movie', title: '测试剧', type: '电影', year: '2026' },
      { id: 'unknown', title: '测试剧', type: '电视剧', year: '' },
    ]
    view.openFilterDialog()
    Object.assign(view.draft, { keyword: '测试', yearMin: 2025, yearMax: 2026, mtypes: ['电视剧'] })
    assert.equal(view.filtered.value.length, 4)
    view.openFilterDialog()
    assert.equal(view.draft.keyword, '')
    Object.assign(view.draft, { keyword: '测试', yearMin: 2025, yearMax: 2026, mtypes: ['电视剧'] })
    view.applyFilterDialog()
    await Vue.nextTick()
    assert.deepEqual(view.filtered.value.map(row => row.id), ['tv'])
    assert.equal(view.activeFilterCount.value, 3)
    assert(view.events.some(([event, value]) => event === 'update:page' && value === 1))
    view.clearFilters()
    assert.equal(view.filtered.value.length, 4)
  } finally { view.dispose() }
})

test('黑名单分页随共享每页条数改变，并在统一页脚中跳页和复位', () => {
  const props = Vue.reactive({ api: {}, pageSize: 10, page: 2 })
  const view = component('BlacklistView', props, ['rows', 'paged', 'pageCount', 'mediaName'])
  const page = component('Page', { api: {}, initialView: 'blacklist', show_switch: false },
    ['view', 'blacklistPage', 'blacklistCount', 'managePage', 'jumpTo', 'doJump', 'onRowsChange'])
  try {
    view.rows.value = Array.from({ length: 26 }, (_, id) => ({ id, title: `剧集 ${id}`, type: '电视剧', season: 0 }))
    assert.equal(view.pageCount.value, 3)
    assert.equal(view.paged.value[0].id, 10)
    props.pageSize = 12
    assert.equal(view.paged.value[0].id, 12)
    assert.equal(view.mediaName(view.paged.value[0]), '剧集 12 · S00')
    assert.equal(page.view.value, 'blacklist')
    page.blacklistCount.value = 3
    page.jumpTo.value = 3
    page.doJump()
    assert.equal(page.blacklistPage.value, 3)
    assert.equal(page.managePage.value, 1)
    page.onRowsChange()
    assert.equal(page.blacklistPage.value, 1)
  } finally { view.dispose(); page.dispose() }
})

function overviewResponse(overrides = {}) {
  return { code: 0, enabled: true, counts: { history: 0, subscriptions: 2, paused: 1, blacklist: 3 },
    stats: { total: 0, by_status: {} }, providers: [{ provider_id: 'douban', enabled: true }],
    running: [{ provider_id: 'douban', processed: 4 }], recent: [], ...overrides }
}

test('仪表盘零历史时仍显示当前订阅、黑名单与来源运行状态', async () => {
  const requests = []
  const view = component('Dashboard', { api: { get: async url => { requests.push(url); return overviewResponse() } }, config: {}, allowRefresh: false },
    ['fetchData', 'hasData', 'metrics', 'providers', 'running', 'historyCount', 'stopRefresh'])
  try {
    await view.fetchData()
    assert.equal(view.hasData.value, true)
    assert.equal(view.historyCount.value, 0)
    assert.deepEqual(view.metrics.value.map(metric => metric.count), [2, 3, 0])
    assert.equal(view.providers.value.length, 1)
    assert.equal(view.running.value[0].processed, 4)
    assert(requests[0].includes('/dashboard?lang='))
  } finally { view.stopRefresh(); view.dispose() }
})

test('仪表盘刷新失败保留最近成功数据并显示错误', async () => {
  let count = 0
  const view = component('Dashboard', { api: { get: async () => ++count === 1 ? overviewResponse() : { code: 1, message: '读取失败' } }, config: {}, allowRefresh: false },
    ['fetchData', 'hasData', 'counts', 'error', 'loading', 'stopRefresh'])
  try {
    await view.fetchData()
    await view.fetchData()
    assert.equal(view.hasData.value, true)
    assert.equal(view.counts.value.blacklist, 3)
    assert(view.error.value.includes('读取失败'))
    assert.equal(view.loading.value, false)
  } finally { view.stopRefresh(); view.dispose() }
})

test('仪表盘不重复发出在途请求，卸载后不采纳迟到响应', async () => {
  const request = deferred()
  let calls = 0
  const view = component('Dashboard', { api: { get: () => { calls++; return request.promise } }, config: {}, allowRefresh: false },
    ['fetchData', 'hasData', 'stopRefresh'])
  try {
    const pending = view.fetchData()
    await view.fetchData()
    assert.equal(calls, 1)
    view.stopRefresh()
    request.resolve(overviewResponse())
    await pending
    assert.equal(view.hasData.value, false)
  } finally { view.stopRefresh(); view.dispose() }
})

test('仪表盘自动刷新在请求结束后调度，暂停与卸载清理定时器', async () => {
  const timers = new Map()
  let seq = 0
  const props = Vue.reactive({ api: { get: async () => overviewResponse() }, config: { attrs: { refresh: 300 } }, allowRefresh: true })
  const view = component('Dashboard', props, ['fetchData', 'stopRefresh'], {
    setTimeout: (fn, delay) => { const id = ++seq; timers.set(id, { fn, delay }); return id },
    clearTimeout: id => timers.delete(id),
  })
  try {
    await view.fetchData()
    assert.equal(timers.size, 1)
    assert.equal([...timers.values()][0].delay, 300000)
    props.allowRefresh = false
    await Vue.nextTick()
    assert.equal(timers.size, 0)
    props.allowRefresh = true
    await Vue.nextTick()
    assert.equal(timers.size, 1)
    await [...timers.values()][0].fn()
    assert.equal(timers.size, 1)
    view.stopRefresh()
    assert.equal(timers.size, 0)
  } finally { view.stopRefresh(); view.dispose() }
})

test('仪表盘结果分布包含旧状态，最近订阅明确显示特别篇与剧集组', async () => {
  const view = component('Dashboard', { api: { get: async () => overviewResponse({ counts: { history: 5 }, stats: { by_status: { subscribed: 2, already_handled: 1 } } }) }, config: {}, allowRefresh: false },
    ['fetchData', 'segments', 'mediaName', 'stopRefresh'])
  try {
    await view.fetchData()
    assert.equal(view.segments.value.sum, 5)
    assert.equal(view.segments.value.rows.find(row => row.key === 'other').count, 2)
    assert.equal(view.mediaName({ title: '测试剧', type: '电视剧', season: 0, episode_group: 'group-a' }), '测试剧 · S00 · 剧集组: group-a')
  } finally { view.stopRefresh(); view.dispose() }
})
