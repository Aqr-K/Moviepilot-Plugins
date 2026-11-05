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
    inject: () => null,
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

function sidebarHistory(api, exports) {
  return component('Page', { api, sidebar: true, initialView: 'history', show_switch: false }, exports,
    { window: { innerWidth: 1280 } })
}
const historyRows = (start, count) => Array.from({ length: count }, (_, i) => ({ unique: `history-${start + i}`, title: `剧集 ${start + i}` }))

test('侧栏滚动加载保留已有卡片，合并重叠项并阻止同页并发请求', async () => {
  const next = deferred()
  const requests = []
  const page = sidebarHistory({ get: url => {
    requests.push(url)
    return requests.length === 1 ? Promise.resolve({ list: historyRows(1, 24), total: 80 }) : next.promise
  } }, ['fetchHistory', 'loadMoreHistory', 'items', 'historyHasMore', 'historyLoadedPage'])
  try {
    await page.fetchHistory()
    const pending = page.loadMoreHistory()
    await page.loadMoreHistory()
    assert.equal(requests.length, 2)
    assert.match(requests[1], /page=2&count=24/)
    assert.equal(page.items.value.length, 24)
    next.resolve({ list: historyRows(24, 24), total: 80 })
    await pending
    assert.equal(page.items.value.length, 47)
    assert.equal(page.items.value[0].unique, 'history-1')
    assert.equal(page.historyLoadedPage.value, 2)
    assert.equal(page.historyHasMore.value, true)
  } finally { page.dispose() }
})

test('滚动加载失败保留卡片，重试使用同一页而不是跳过失败页', async () => {
  for (const failure of [new Error('临时失败'), { code: 1, message: '临时失败' }]) {
    const requests = []
    const page = sidebarHistory({ get: async url => {
      requests.push(url)
      if (requests.length === 2) {
        if (failure instanceof Error) throw failure
        return failure
      }
      return { list: historyRows(requests.length === 1 ? 1 : 25, 24), total: 48 }
    } }, ['fetchHistory', 'loadMoreHistory', 'items', 'historyMoreError', 'historyHasMore'])
    try {
      await page.fetchHistory()
      await page.loadMoreHistory()
      assert.equal(page.items.value.length, 24)
      assert.match(page.historyMoreError.value, /临时失败/)
      await page.loadMoreHistory()
      assert.equal(requests[1], requests[2])
      assert.equal(page.items.value.length, 48)
      assert.equal(page.historyMoreError.value, '')
      assert.equal(page.historyHasMore.value, false)
    } finally { page.dispose() }
  }
})


test('筛选重置后，旧的滚动请求不能追加到新结果中', async () => {
  const old = deferred()
  const requests = []
  const page = sidebarHistory({ get: url => {
    requests.push(url)
    if (requests.length === 2) return old.promise
    return Promise.resolve(requests.length === 1 ? { list: historyRows(1, 24), total: 80 }
      : { list: [{ unique: 'filtered', title: '筛选后' }], total: 1 })
  } }, ['fetchHistory', 'loadMoreHistory', 'items', 'filters', 'historyHasMore'])
  try {
    await page.fetchHistory()
    const pending = page.loadMoreHistory()
    page.filters.statuses.push('subscribed')
    await page.fetchHistory()
    old.resolve({ list: historyRows(25, 24), total: 80 })
    await pending
    assert.match(requests[2], /status=subscribed/)
    assert.match(requests[2], /page=1&count=24/)
    assert.deepEqual(page.items.value.map(item => item.unique), ['filtered'])
    assert.equal(page.historyHasMore.value, false)
  } finally { page.dispose() }
})

test('后端返回空页或整页重复记录后停止继续加载', async () => {
  for (const response of [{ list: [], total: 80 }, { list: historyRows(1, 24), total: 80 }]) {
    let requests = 0
    const page = sidebarHistory({ get: async () => ++requests === 1 ? { list: historyRows(1, 24), total: 80 } : response },
      ['fetchHistory', 'loadMoreHistory', 'historyHasMore'])
    try {
      await page.fetchHistory()
      await page.loadMoreHistory()
      assert.equal(page.historyHasMore.value, false)
      await page.loadMoreHistory()
      assert.equal(requests, 2)
    } finally { page.dispose() }
  }
})

test('手机侧栏和桌面详情页继续按页查询，不启用连续加载', async () => {
  for (const [sidebar, width] of [[true, 390], [false, 1280]]) {
    const requests = []
    const page = component('Page', { api: { get: async url => { requests.push(url); return { list: historyRows(1, 10), total: 100 } } },
      sidebar, initialView: 'history' }, ['fetchHistory', 'loadMoreHistory', 'page', 'sidebarDesktop'], { window: { innerWidth: width } })
    try {
      page.page.value = 3
      await page.fetchHistory()
      assert.equal(page.sidebarDesktop.value, false)
      assert.match(requests[0], /page=3&count=10/)
      await page.loadMoreHistory()
      assert.equal(requests.length, 1)
    } finally { page.dispose() }
  }
})

test('管理和黑名单逐批呈现，筛选与显示模式切换重置可见范围', async () => {
  for (const name of ['SubscribeView', 'BlacklistView']) {
    const props = Vue.reactive({ api: {}, progressive: true, pageSize: 24, page: 2 })
    const view = component(name, props, ['rows', 'paged', 'loadMore', 'filters', 'visibleCount'])
    try {
      view.rows.value = Array.from({ length: 60 }, (_, id) => ({ id, title: `剧集 ${id}`, name: `剧集 ${id}` }))
      await Vue.nextTick()
      assert.equal(view.paged.value[0].id, 0)
      assert.equal(view.paged.value.length, 24)
      view.loadMore()
      assert.equal(view.paged.value.length, 48)
      view.filters.keyword = '剧集 59'
      await Vue.nextTick()
      assert.deepEqual(view.paged.value.map(item => item.id), [59])
      assert.equal(view.visibleCount.value, 24)
      view.filters.keyword = ''
      props.progressive = false
      await Vue.nextTick()
      assert.equal(view.paged.value[0].id, 24)
      assert.equal(view.paged.value.length, 24)
    } finally { view.dispose() }
  }
})

test('连续加载观察器在报错和卸载时释放，迟到回调不重复触发加载', async () => {
  const observers = []
  let unmount
  class Observer {
    constructor(callback, options) { this.callback = callback; this.options = options; this.disconnected = false; observers.push(this) }
    observe() {}
    disconnect() { this.disconnected = true }
  }
  const props = Vue.reactive({ progressive: true, count: 24, loading: false, hasMore: true, error: '' })
  const list = component('ProgressiveList', props, ['scrollRef', 'sentinelRef'], {
    IntersectionObserver: Observer, onBeforeUnmount: callback => { unmount = callback },
  })
  try {
    list.scrollRef.value = { scrollTop: 0 }
    list.sentinelRef.value = {}
    await Vue.nextTick()
    const observer = observers.at(-1)
    assert(observer)
    assert.equal(observer.options.root, list.scrollRef.value)
    observer.callback([{ isIntersecting: true }])
    assert.equal(list.events.length, 1)
    props.error = '加载失败'
    await Vue.nextTick()
    assert.equal(observer.disconnected, true)
    observer.callback([{ isIntersecting: true }])
    assert.equal(list.events.length, 1)
    props.error = ''
    await Vue.nextTick()
    await Vue.nextTick()
    const retry = observers.at(-1)
    assert.notEqual(retry, observer)
    unmount()
    assert.equal(retry.disconnected, true)
    retry.callback([{ isIntersecting: true }])
    assert.equal(list.events.length, 1)
  } finally { unmount?.(); list.dispose() }
})

test('订阅卡片向宿主管理入口只传操作和订阅 ID，保存后才刷新列表', async () => {
  const requests = []
  const gets = []
  const view = component('SubscribeView', { api: { get: async url => { gets.push(url); return { list: [] } } }, pageSize: 12, page: 1 },
    ['runNative', 'error'], { inject: () => async request => { requests.push(request); return { success: true } } })
  try {
    await view.runNative('edit', { id: 7, media_source: 'wrong', media_id: 'wrong' })
    assert.equal(requests[0].action, 'edit')
    assert.equal(requests[0].subscriptionId, 7)
    assert(!('media_id' in requests[0]))
    assert.equal(gets.length, 0)
    await requests[0].onChanged()
    assert.deepEqual(gets, ['plugin/AutomaticSubscriptionAssistant/subscribes?lang=zh-CN'])
    assert(view.events.some(([event]) => event === 'changed'))
  } finally { view.dispose() }
})

test('同一卡片原生操作不并发提交，取消确认不显示错误', async () => {
  const pending = deferred()
  let calls = 0
  const view = component('SubscribeView', { api: {}, pageSize: 12, page: 1 }, ['runNative', 'error', 'nativePending'],
    { inject: () => () => { calls++; return pending.promise } })
  try {
    const request = view.runNative('reset', { id: 7 })
    await view.runNative('reset', { id: 7 })
    assert.equal(calls, 1)
    assert(view.nativePending.has(7))
    pending.resolve({ success: false, cancelled: true })
    await request
    assert.equal(view.error.value, '')
    assert.equal(view.nativePending.size, 0)
  } finally { view.dispose() }
})

test('旧宿主明确提示新增原生能力缺失，并保留原有暂停和取消订阅流程', async () => {
  const view = component('SubscribeView', { api: {}, pageSize: 12, page: 1 }, ['runNative', 'error', 'confirm'])
  try {
    await view.runNative('edit', { id: 7 })
    assert.match(view.error.value, /主程序/)
    await view.runNative('pause', { id: 7 })
    assert.equal(view.confirm.kind, 'pause')
    assert.deepEqual(view.confirm.ids, [7])
    await view.runNative('delete', { id: 7 })
    assert.equal(view.confirm.kind, 'delete')
  } finally { view.dispose() }
})

test('原生 API 失败展示错误，视图卸载后保存回调不再刷新', async () => {
  let request
  let unmount
  let gets = 0
  const view = component('SubscribeView', { api: { get: async () => { gets++; return { list: [] } } }, pageSize: 12, page: 1 },
    ['runNative', 'error'], {
      inject: () => async value => { request = value; return { success: false, message: '无权编辑此订阅' } },
      onBeforeUnmount: callback => { unmount = callback },
    })
  try {
    await view.runNative('edit', { id: 7 })
    assert.equal(view.error.value, '无权编辑此订阅')
    unmount()
    await request.onChanged()
    assert.equal(gets, 0)
  } finally { view.dispose() }
})

const supplementTarget = { unique: 'original', title: '测试剧', year: '2026', type: '电视剧', season: 0,
  media_source: 'douban', media_id: 'old-id', episode_group: 'special-group' }
function supplementDialog(api, exports, overrides) {
  return component('SupplementDialog', { api, target: supplementTarget, modelValue: true },
    ['resetForm', ...exports], overrides)
}

test('补充编辑显式保留特别篇和剧集组，清空身份后不携带旧来源 ID', () => {
  const dialog = supplementDialog({}, ['media', 'subscription', 'buildRequest'])
  try {
    dialog.resetForm()
    assert.equal(dialog.buildRequest().media.season, 0)
    assert.equal(dialog.buildRequest().media.episode_group, 'special-group')
    dialog.media.media_source = null
    dialog.media.media_id = ''
    dialog.media.title = '新片名'
    Object.assign(dialog.subscription, { search_interval: '6', quality: 'WEB-?DL', total_episode: '12', start_episode: '3', mode: 'best', exist_ok: false })
    const request = dialog.buildRequest()
    assert.equal(request.media.media_source, null)
    assert.equal(request.media.media_id, '')
    assert.equal(request.media.title, '新片名')
    assert.equal(request.subscription.search_interval, 6)
    assert.equal(request.subscription.start_episode, 3)
    assert.equal(request.subscription.best_version, 1)
    assert.equal(request.exist_ok, false)
    assert(!('username' in request.subscription))
  } finally { dialog.dispose() }
})

test('补充编辑拒绝空标题、不完整媒体身份和小数季号，不发送创建请求', async () => {
  let requests = 0
  const dialog = supplementDialog({ post: async () => { requests++; return {} } }, ['media', 'submit', 'feedback'])
  try {
    dialog.resetForm()
    dialog.media.title = ''
    await dialog.submit()
    assert(dialog.feedback.value)
    dialog.resetForm()
    dialog.media.media_id = ''
    await dialog.submit()
    assert(dialog.feedback.value)
    dialog.resetForm()
    dialog.media.season = '2.5'
    await dialog.submit()
    assert(dialog.feedback.value)
    assert.equal(requests, 0)
  } finally { dialog.dispose() }
})

test('补充编辑只提交一次，实际创建成功后通知刷新并关闭', async () => {
  const pending = deferred()
  const requests = []
  const dialog = supplementDialog({ post: (...args) => { requests.push(args); return pending.promise } }, ['submit', 'busy'])
  try {
    dialog.resetForm()
    const first = dialog.submit()
    await dialog.submit()
    assert.equal(dialog.busy.value, true)
    assert.equal(requests.length, 1)
    assert.equal(requests[0][0], 'plugin/AutomaticSubscriptionAssistant/history/supplement')
    pending.resolve({ code: 0, created: true, status: 'subscribed', subscribe_id: 77 })
    await first
    assert(dialog.events.some(([event]) => event === 'changed'))
    assert(dialog.events.some(([event, value]) => event === 'update:modelValue' && value === false))
  } finally { dialog.dispose() }
})

test('未创建、验证失败或网络失败均保留补充表单，展示原因供修改重试', async () => {
  for (const result of [
    { code: 0, created: false, status: 'blacklisted', message: '已加入黑名单' },
    { code: 1, message: '设置不正确' },
    new Error('网络失败'),
  ]) {
    const dialog = supplementDialog({ post: async () => { if (result instanceof Error) throw result; return result } },
      ['submit', 'media', 'feedback', 'busy'])
    try {
      dialog.resetForm()
      await dialog.submit()
      assert.equal(dialog.media.title, '测试剧')
      assert(dialog.feedback.value)
      assert.equal(dialog.busy.value, false)
      assert(!dialog.events.some(([event]) => event === 'update:modelValue'))
    } finally { dialog.dispose() }
  }
})

test('选项支持宿主 envelope，晚到响应不能覆盖重新打开后的选项', async () => {
  const old = deferred()
  let sites = 0
  const dialog = supplementDialog({ get: async url => {
    if (url === 'site/rss') return ++sites === 1 ? old.promise : { success: true, data: [{ id: 2, name: '新站点' }] }
    if (url === 'download/clients') return { success: true, data: [{ name: 'client' }] }
    return { success: true, data: { rule_groups: [{ name: 'rules' }] } }
  } }, ['loadOptions', 'siteOptions', 'downloaderOptions', 'ruleOptions'])
  try {
    const first = dialog.loadOptions()
    await dialog.loadOptions()
    old.resolve({ success: true, data: [{ id: 1, name: '旧站点' }] })
    await first
    assert.deepEqual(dialog.siteOptions.value, [{ title: '新站点', value: 2 }])
    assert.deepEqual(dialog.downloaderOptions.value, [{ title: 'client', value: 'client' }])
    assert.deepEqual(dialog.ruleOptions.value, [{ title: 'rules', value: 'rules' }])
  } finally { dialog.dispose() }
})

test('补充编辑卸载后不处理迟到创建响应', async () => {
  const pending = deferred()
  let unmount
  const dialog = supplementDialog({ post: () => pending.promise }, ['submit'], { onBeforeUnmount: callback => { unmount = callback } })
  try {
    dialog.resetForm()
    const request = dialog.submit()
    unmount()
    pending.resolve({ code: 0, created: true })
    await request
    assert.equal(dialog.events.length, 0)
  } finally { dialog.dispose() }
})

test('订阅管理卡片显示榜单来源，缺失来源时不冒充插件名', () => {
  const view = component('SubscribeView', { api: {}, pageSize: 12, page: 1 }, ['cardLines'])
  try {
    const source = item => view.cardLines(item).find(line => line.label === '榜单来源')
    assert.equal(source({ provider: 'douban', provider_name: '豆瓣榜单' }).value, '豆瓣榜单')
    assert.equal(source({ provider: 'extension-rank' }).value, 'extension-rank')
    assert.equal(source({}).value, '未知')
    assert.equal(source({}).icon, 'mdi-rss')
  } finally { view.dispose() }
})

test('订阅来源使用当前语言，旧请求不会覆盖较新来源结果', async () => {
  const first = deferred(), second = deferred()
  const requests = []
  const view = component('SubscribeView', { api: { get: url => { requests.push(url); return requests.length === 1 ? first.promise : second.promise } }, pageSize: 12, page: 1 },
    ['fetchSubs', 'rows', 'loading'], { getCurrentInstance: () => ({ appContext: { config: { globalProperties: { $i18n: { locale: 'en-US' } } } } }) })
  try {
    const old = view.fetchSubs(), current = view.fetchSubs()
    assert(requests.every(url => url.endsWith('/subscribes?lang=en-US')))
    second.resolve({ list: [{ id: 7, provider: 'netflix', provider_name: 'Netflix Top 10' }] })
    await current
    first.resolve({ list: [{ id: 7, provider: 'douban', provider_name: 'Douban Rankings' }] })
    await old
    assert.equal(view.rows.value[0].provider, 'netflix')
    assert.equal(view.loading.value, false)
  } finally { view.dispose() }
})

const rankedSubscriptions = () => [
  { id: 1, name: '测试剧 第一季', provider: 'douban', provider_name: '豆瓣榜单', type: '电视剧', year: '2025', state: 'R' },
  { id: 2, name: '测试剧 第二季', provider: 'netflix', provider_name: '奈飞榜单', type: '电视剧', year: '2026', state: 'S' },
  { id: 3, name: '测试电影', provider: 'douban', provider_name: '豆瓣榜单', type: '电影', year: '2024', state: 'R' },
  { id: 4, name: '其他剧', provider: 'mikan', provider_name: 'Mikan 季度新番', type: '电视剧', year: '2026', state: 'R' },
  { id: 5, name: '未知归属', provider: null, type: '电影', year: '2026', state: 'R' },
  { id: 6, name: '旧版订阅', type: '电影', year: '2026', state: 'P' },
]

function rankedSubscriptionView(exports, overrides = {}) {
  return component('SubscribeView', { api: { get: async () => ({ list: rankedSubscriptions() }) }, pageSize: 1, page: 1 },
    ['fetchSubs', 'filters', 'filtered', 'providerItems', 'activeFilterCount', ...exports], overrides)
}

test('订阅来源多选与其他条件组合过滤，全选仅选中匹配的榜单订阅', async () => {
  const view = rankedSubscriptionView(['pageCount', 'selectAll', 'selected', 'filterFields', 'clearFilters'])
  try {
    await view.fetchSubs()
    assert.deepEqual(view.providerItems.value.map(item => item.title), ['豆瓣榜单 (2)', '奈飞榜单 (1)', 'Mikan 季度新番 (1)', '未知 (2)'])
    const field = view.filterFields.value.find(item => item.key === 'providers')
    assert.equal(field.multi, true)
    assert.equal(field.label, '榜单来源')
    view.filters.providers = ['douban', 'netflix']
    assert.deepEqual(view.filtered.value.map(item => item.id), [1, 2, 3])
    assert.equal(view.pageCount.value, 3)
    assert.equal(view.activeFilterCount.value, 1)
    Object.assign(view.filters, { keyword: '测试剧', mtype: '电视剧', statuses: ['R'], yearMin: 2025, yearMax: 2026 })
    assert.deepEqual(view.filtered.value.map(item => item.id), [1])
    view.selectAll()
    assert.deepEqual([...view.selected], [1])
    const unknown = view.providerItems.value.find(item => item.title === '未知 (2)').value
    view.clearFilters()
    view.filters.providers = [unknown]
    assert.deepEqual(view.filtered.value.map(item => item.id), [5, 6])
    view.filters.providers = []
    assert.equal(view.filtered.value.length, 6)
  } finally { view.dispose() }
})

test('榜单来源草稿可取消，应用后复位页码，重置与清除不会留下旧来源', async () => {
  const view = rankedSubscriptionView(['draft', 'filterDialog', 'openFilterDialog', 'applyFilterDialog', 'resetDraft', 'clearFilters'])
  try {
    await view.fetchSubs()
    view.filters.providers = ['douban']
    await Vue.nextTick()
    view.openFilterDialog()
    view.draft.providers.push('netflix')
    view.filterDialog.value = false
    assert.deepEqual(view.filters.providers, ['douban'])
    view.openFilterDialog()
    assert.deepEqual(view.draft.providers, ['douban'])
    view.draft.providers = ['netflix']
    const before = view.events.length
    view.applyFilterDialog()
    await Vue.nextTick()
    assert.deepEqual(view.filters.providers, ['netflix'])
    assert.equal(view.activeFilterCount.value, 1)
    assert(view.events.slice(before).some(([event, page]) => event === 'update:page' && page === 1))
    view.openFilterDialog()
    view.resetDraft()
    assert.deepEqual(view.draft.providers, [])
    assert.deepEqual(view.filters.providers, ['netflix'])
    view.applyFilterDialog()
    assert.deepEqual(view.filters.providers, [])
    view.filters.providers = ['douban']
    view.clearFilters()
    assert.equal(view.activeFilterCount.value, 0)
    view.openFilterDialog()
    assert.deepEqual(view.draft.providers, [])
  } finally { view.dispose() }
})

test('榜单名称本地化更新后，已选来源仍按稳定 ID 匹配', async () => {
  const i18n = Vue.reactive({ locale: 'zh-CN' })
  const view = component('SubscribeView', { api: { get: async url => ({ list: rankedSubscriptions().map(row => ({
    ...row, provider_name: url.endsWith('lang=en-US') && row.provider === 'douban' ? 'Douban Rankings' : row.provider_name,
  })) }) }, pageSize: 12, page: 1 }, ['fetchSubs', 'filters', 'filtered', 'providerItems'],
    { getCurrentInstance: () => ({ appContext: { config: { globalProperties: { $i18n: i18n } } } }) })
  try {
    await view.fetchSubs()
    view.filters.providers = ['douban']
    i18n.locale = 'en-US'
    await Vue.nextTick()
    await Promise.resolve()
    await Vue.nextTick()
    assert.equal(view.providerItems.value[0].title, 'Douban Rankings (2)')
    assert.deepEqual(view.filtered.value.map(row => row.id), [1, 3])
  } finally { view.dispose() }
})

test('sidebar hides configuration even when show_switch defaults true', () => {
  const page = component('Page', { api: {}, sidebar: true, show_switch: true }, ['tabDefs', 'onTab', 'view'])
  try {
    assert.deepEqual(page.tabDefs.value.map(tab => tab.key), ['history', 'manage', 'blacklist'])
    const before = page.view.value
    page.onTab('config')
    assert.equal(page.view.value, before)
    assert.deepEqual(page.events, [])
  } finally { page.dispose() }
})

test('plugin dialog keeps configuration entry', () => {
  const page = component('Page', { api: {}, sidebar: false, show_switch: true }, ['tabDefs', 'onTab'])
  try {
    assert(page.tabDefs.value.some(tab => tab.key === 'config'))
    page.onTab('config')
    assert.deepEqual(page.events.at(-1), ['switch'])
  } finally { page.dispose() }
})

test('source notifications initialize independently and persist with configuration', () => {
  const config = component('Config', { api: {}, initialConfig: {
    global: { notify: true }, providers: { douban: { notify: true }, netflix: { notify: false } },
  } }, ['config', 'providerSpecs', 'ensureProviderConfig', 'saveConfig', 'notifyingCount', 'changedCount', 'snapshot', 'flatten', 'loading', 'configurationBlocked'])
  try {
    const ids = ['douban', 'popular', 'mikan', 'netflix', 'maoyan']
    config.providerSpecs.value = ids.map(provider_id => ({ provider_id, default_cron: '0 8 * * *' }))
    config.providerSpecs.value.forEach(config.ensureProviderConfig)
    config.snapshot.value = config.flatten(config.config)
    assert.equal(config.config.global.notify, undefined)
    assert.equal(config.config.providers.douban.notify, true)
    assert.equal(config.config.providers.netflix.notify, false)
    assert.equal(config.config.providers.mikan.notify, false)
    assert.equal(config.notifyingCount.value, 1)
    config.config.providers.mikan.notify = true
    assert.equal(config.changedCount.value, 1)
    assert.equal(config.notifyingCount.value, 2)
    config.loading.value = false
    config.configurationBlocked.value = false
    config.saveConfig()
    const payload = config.events.find(event => event[0] === 'save')[1]
    assert.equal(payload.providers.douban.notify, true)
    assert.equal(payload.providers.netflix.notify, false)
    assert.equal(payload.providers.mikan.notify, true)
    assert.equal(payload.providers.maoyan.notify, false)
    assert.equal(config.changedCount.value, 0)
  } finally { config.dispose() }
})

test('music history can be supplemented with artists and entity type', () => {
  const view = component('SupplementDialog', { api: {}, modelValue: true, target: {
    unique: 'music:1', title: 'Song', type: '音乐', music_type: 'recording', artists: ['Artist'],
  } }, ['resetForm', 'buildRequest', 'media', 'mediaFields', 'subscriptionFields'])
  try {
    view.resetForm()
    const request = view.buildRequest()
    assert.equal(request.media.type, '音乐')
    assert.equal(request.media.music_type, 'recording')
    assert.deepEqual(request.media.artists, ['Artist'])
    assert(!view.subscriptionFields.value.some(field => field.key === 'resolution'))
    assert(view.mediaFields.value.some(field => field.key === 'artistsText'))
    view.media.artistsText = ''
    assert.throws(() => view.buildRequest())
  } finally { view.dispose() }
})

test('music blacklist sends structured artists and supports the music type', async () => {
  const requests = []
  const view = component('BlacklistDialog', { modelValue: true, target: {}, api: {
    post: async (url, body) => { requests.push(body); return { code: 0 } },
  } }, ['form', 'save', 'types'])
  try {
    Object.assign(view.form, { title: 'Song', type: '音乐', music_type: 'recording', artistsText: 'A, B' })
    assert(view.types.value.some(option => option.value === '音乐'))
    await view.save()
    assert.deepEqual(requests[0].media.artists, ['A', 'B'])
    assert.equal(requests[0].media.music_type, 'recording')
  } finally { view.dispose() }
})

test('旧平铺来源配置不自动启用新默认规则，首次配置仍提供独立预设', () => {
  const spec={provider_id:'anilist',default_cron:'15 8 * * *',options_schema:[{key:'rules',kind:'rule-list',default:[{name:'正在流行',sort:'TRENDING_DESC'}]},{key:'proxy',kind:'switch',default:false}],filters_schema:[]}
  const config=component('Config',{initialConfig:{providers:{anilist:{options:{charts:[]},filters:{vote:8}}}}},['ensureProviderConfig','config','preservedProviders','providerIssues'])
  const fresh=component('Config',{initialConfig:{}},['ensureProviderConfig','config','preservedProviders','providerIssues'])
  try {
    config.ensureProviderConfig(spec)
    assert.deepEqual([...config.preservedProviders.anilist.options.charts], [])
    assert.equal(config.preservedProviders.anilist.filters.vote, 8)
    assert.ok(config.providerIssues.anilist)
    assert.equal(config.config.providers.anilist.enabled, false)
    fresh.ensureProviderConfig(spec)
    assert.equal(fresh.config.providers.anilist.options.rules[0].name,'正在流行')
    fresh.config.providers.anilist.options.rules[0].name='changed'
    assert.equal(spec.options_schema[0].default[0].name,'正在流行')
  } finally {config.dispose();fresh.dispose()}
})

test('插件页面打开不读取旧入口页签，也不跨窗口写入黑名单目标', () => {
  const storage = { getItem: key => key === 'asa.pageView' ? 'blacklist' : null, setItem: () => { throw new Error('unexpected persistence') } }
  const page = component('Page', { api: {}, show_switch: true }, ['view', 'onTab'], { localStorage: storage })
  const config = component('Config', { initialConfig: {} }, ['onTab', 'navigationView'], { localStorage: storage })
  try {
    assert.equal(page.view.value, 'history')
    page.onTab('config')
    assert.ok(page.events.some(([name]) => name === 'switch'))
    config.onTab('blacklist')
    assert.equal(config.navigationView.value, 'blacklist')
    assert.equal(config.events.some(([name]) => name === 'switch'), false)
    const reopened = component('Config', { initialConfig: {} }, ['navigationView'], { localStorage: storage })
    try { assert.equal(reopened.navigationView.value, '') } finally { reopened.dispose() }
  } finally { page.dispose(); config.dispose() }
})

test('配置页优先读取后端迁移结果，语言刷新不覆盖未保存编辑', async () => {
  const old = { providers: { douban: { options: { ranks: ['tv-hot'] }, filters: { vote: 8 } } } }
  const migrated = { global: { enabled: true }, providers: { douban: { enabled: true,
    options: { rules: [{ id: 'migrated', chart: 'tv-hot', vote: 8 }] }, filters: {} } } }
  const spec = { provider_id: 'douban', options_schema: [{ key: 'rules', kind: 'rule-list', default: [] }], filters_schema: [] }
  let reads = 0
  const config = component('Config', { initialConfig: old, api: { get: async url => {
    if (url.endsWith('/config')) { reads++; return { code: 0, config: migrated } }
    return { providers: [spec] }
  } } }, ['loadProviders', 'config', 'saveConfig', 'configurationBlocked'])
  try {
    await config.loadProviders()
    assert.equal(config.configurationBlocked.value, false)
    assert.equal(config.config.providers.douban.options.rules[0].vote, 8)
    config.config.providers.douban.options.rules[0].vote = 9
    await config.loadProviders()
    assert.equal(reads, 1)
    assert.equal(config.config.providers.douban.options.rules[0].vote, 9)
    config.saveConfig()
    assert.equal(config.events.find(event => event[0] === 'save')[1].providers.douban.options.rules[0].vote, 9)
    assert.deepEqual(old.providers.douban.options.ranks, ['tv-hot'])
  } finally { config.dispose() }
})

for (const outcome of ['failed', 'unavailable', 'legacy']) test(`配置升级 ${outcome} 时保留旧字段且来源仍可渲染`, async () => {
  const old = { providers: { douban: { options: { ranks: ['tv-hot'] }, filters: { vote: 8 } } } }
  const config = component('Config', { initialConfig: old, api: { get: async url => {
    if (url.endsWith('/config')) {
      if (outcome === 'unavailable') throw new Error('offline')
      return outcome === 'failed' ? { code: 1, message: '备份失败', config: old } : { code: 0, config: old }
    }
    return { providers: [{ provider_id: 'douban', options_schema: [{ key: 'rules', kind: 'rule-list', default: [] }], filters_schema: [] }] }
  } } }, ['loadProviders', 'config', 'saveConfig', 'configurationBlocked', 'error', 'providerSpecs', 'providerIssues', 'preservedProviders'])
  try {
    await config.loadProviders()
    assert.equal(config.configurationBlocked.value, outcome === 'unavailable')
    assert.equal(config.providerSpecs.value.length, 1)
    assert.ok(config.providerIssues.douban)
    assert.deepEqual([...config.preservedProviders.douban.options.ranks], ['tv-hot'])
    assert.equal(config.preservedProviders.douban.filters.vote, 8)
    config.saveConfig()
    if (outcome === 'unavailable') assert.equal(config.events.filter(event => event[0] === 'save').length, 0)
    else assert.deepEqual(config.events.find(event => event[0] === 'save')[1].providers.douban, old.providers.douban)
  } finally { config.dispose() }
})

test('来源标签刷新失败后重试也不覆盖已加载的配置草稿', async () => {
  let configReads = 0
  let failProviders = false
  const config = component('Config', { initialConfig: {}, api: { get: async url => {
    if (url.endsWith('/config')) { configReads++; return { config: { providers: { douban: { options: { rules: [] } } } } } }
    if (failProviders) throw new Error('offline')
    return { providers: [{ provider_id: 'douban', options_schema: [{ key: 'rules', kind: 'rule-list', default: [] }], filters_schema: [] }] }
  } } }, ['loadProviders', 'config', 'configurationBlocked'])
  try {
    await config.loadProviders()
    config.config.providers.douban.options.rules.push({ id: 'draft', chart: 'tv-hot' })
    failProviders = true
    await config.loadProviders()
    assert.equal(config.configurationBlocked.value, true)
    failProviders = false
    await config.loadProviders()
    assert.equal(config.configurationBlocked.value, false)
    assert.equal(configReads, 1)
    assert.equal(config.config.providers.douban.options.rules[0].id, 'draft')
  } finally { config.dispose() }
})

test('来源配置读取失败仍展示全部来源，维护按钮可独立还原', async () => {
  const specs = JSON.parse(fs.readFileSync(new URL('../src/dev/providerSpecs.json', import.meta.url), 'utf8'))
  const defaults = { global: { enabled: false, onlyonce: false, clear: false }, providers: Object.fromEntries(specs.map(s => [s.provider_id, {
    enabled: false, notify: false, cron: s.default_cron,
    options: Object.fromEntries(s.options_schema.map(f => [f.key, f.default])), filters: {},
  }])) }
  const posts = []
  const view = component('Config', { initialConfig: { providers: { netflix: { options: { limit: 50 } } } }, api: {
    get: async url => { if (url.includes('/providers')) return { providers: specs }; throw new Error('config unavailable') },
    post: async (url, body) => { posts.push([url, body]); return { code: 0, config: defaults } },
  } }, ['loadProviders', 'providerSpecs', 'groups', 'configurationBlocked', 'resetTarget', 'restoreDefaults', 'config', 'providerIssues', 'preservedProviders', 'changedCount'])
  try {
    await view.loadProviders()
    assert.equal(view.providerSpecs.value.length, 10)
    assert.equal(view.groups.value.filter(g => !g.heading).length, 11)
    assert.equal(view.configurationBlocked.value, true)
    view.resetTarget.value = 'all'
    await view.restoreDefaults()
    assert.deepEqual(posts, [['plugin/AutomaticSubscriptionAssistant/config/reset', { confirmed: true }]])
    assert.equal(view.configurationBlocked.value, false)
    assert.equal(view.config.global.enabled, false)
    assert.equal(Object.keys(view.config.providers).length, 10)
    assert.equal(Object.keys(view.providerIssues).length, 0)
    assert.equal(Object.keys(view.preservedProviders).length, 0)
    assert.equal(view.changedCount.value, 0)
    assert.equal(view.resetTarget.value, '')
  } finally { view.dispose() }
})

test('单来源异常保留原件，其他来源可编辑保存；单独还原只修改该来源草稿', async () => {
  const bad = { enabled: true, options: { rules: [{ chart: 'unknown', limit: 50 }] } }
  const valid = { enabled: true, cron: '0 8 * * *', options: { rules: [] }, filters: {} }
  const specs = ['netflix', 'douban'].map(provider_id => ({ provider_id, default_cron: '0 8 * * *', options_schema: [{ key: 'rules', kind: 'rule-list', default: [{ name: 'Default', limit: 10 }] }], filters_schema: [] }))
  const view = component('Config', { initialConfig: {}, api: { get: async url => url.includes('/providers') ? { providers: specs } : { code: 0, config: { providers: { netflix: bad, douban: valid } }, provider_errors: { netflix: 'unknown chart' } } } },
    ['loadProviders', 'config', 'providerSpecs', 'providerIssues', 'saveConfig', 'resetTarget', 'restoreDefaults', 'changedCount'])
  try {
    await view.loadProviders()
    assert.equal(view.providerSpecs.value.length, 2)
    assert.equal(view.providerIssues.netflix, 'unknown chart')
    view.config.providers.douban.cron = '0 9 * * *'
    view.saveConfig()
    let payload = view.events.filter(event => event[0] === 'save').at(-1)[1]
    assert.deepEqual(payload.providers.netflix, bad)
    assert.equal(payload.providers.douban.cron, '0 9 * * *')
    view.resetTarget.value = 'netflix'
    await view.restoreDefaults()
    assert.equal(view.providerIssues.netflix, undefined)
    assert.equal(view.config.providers.netflix.enabled, false)
    assert.equal(view.config.providers.douban.cron, '0 9 * * *')
    assert(view.changedCount.value > 0)
    view.saveConfig()
    payload = view.events.filter(event => event[0] === 'save').at(-1)[1]
    assert.equal(payload.providers.netflix.options.rules[0].name, 'Default')
  } finally { view.dispose() }
})

test('恢复失败时保留当前配置和草稿，确认弹窗保持打开', async () => {
  const view = component('Config', { initialConfig: { global: { username: 'Keep user' } }, api: { post: async () => ({ code: 1, message: 'disk full' }) } },
    ['resetTarget', 'restoreDefaults', 'config', 'resetError', 'resetBusy'])
  try {
    view.resetTarget.value = 'all'
    await view.restoreDefaults()
    assert.equal(view.config.global.username, 'Keep user')
    assert.equal(view.resetTarget.value, 'all')
    assert.equal(view.resetError.value, 'disk full')
    assert.equal(view.resetBusy.value, false)
  } finally { view.dispose() }
})
