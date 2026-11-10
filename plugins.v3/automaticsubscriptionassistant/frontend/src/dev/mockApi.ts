import providerSpecs from './providerSpecs.json'

/**
 * 仅供本地开发壳（App.vue / yarn dev）预览三组件的内存 Mock API。
 *
 * 该文件不被联邦暴露、也不被任何生产组件 import，仅进入开发壳 index-*.js 产物
 * （构建时不上传）。数据结构严格镜像后端 /providers、/status、/history、/run。
 */

interface Option {
  group?: string
  title: string
  value: string
}

interface FieldSpec {
  key: string
  label: string
  kind: string
  default?: unknown
  hint?: string
  advanced?: boolean
  options?: Option[]
  fields?: FieldSpec[]
  presets?: Record<string, unknown>[]
  minimum?: number
  maximum?: number
  required?: boolean
  visible_when?: Record<string, unknown[]>
  options_by?: { key: string, values: Record<string, Option[]> }
}

interface ProviderSpec {
  provider_id: string
  provider_name: string
  default_cron: string
  notice?: string
  options_schema: FieldSpec[]
  filters_schema: FieldSpec[]
}

interface HistoryRecord {
  unique: string
  provider: string
  title: string
  year: string
  type: string
  poster: string | null
  season: number | null
  status: string
  reason: string | null
  time: string
}

interface Subscribe {
  provider: string
  provider_name: string
  id: number
  name: string
  year: string
  type: string
  state: string
  poster: string | null
  season: number | null
  date: string
}

interface Stats {
  total: number
  by_status: Record<string, number>
  by_provider: Record<string, number>
}

export interface MockApi {
  get(url: string): Promise<unknown>
  post(url: string, body?: Record<string, any>): Promise<unknown>
}

const PROVIDER_SPECS: ProviderSpec[] = providerSpecs as ProviderSpec[]

const POSTERS: string[] = Array.from({ length: 18 }, (_, i) => `https://picsum.photos/seed/asa${i + 1}/240/360`)
const TITLES: Array<[string, string, string]> = [
  ['沙丘 第二部', '2024', '电影'], ['奥本海默', '2023', '电影'], ['幕府将军', '2024', '电视剧'],
  ['三体', '2024', '电视剧'], ['间谍过家家', '2023', '电视剧'], ['周处除三害', '2024', '电影'],
  ['坠落的审判', '2023', '电影'], ['繁花', '2023', '电视剧'], ['我的阿勒泰', '2024', '电视剧'],
  ['哥斯拉大战金刚2', '2024', '电影'], ['沙赞', '2024', '电视剧'], ['疯狂动物城2', '2025', '电影'],
]
const STATUS_POOL: string[] = [
  'subscribed', 'subscribed', 'subscribed', 'media_exists', 'media_exists',
  'subscription_exists', 'filtered', 'unrecognized', 'error',
]
const REASONS: Record<string, string> = {
  filtered: '评分 6.4 < 阈值 7.0',
  unrecognized: 'TMDB 未匹配到该标题',
  error: '识别请求超时',
}
const PROVIDER_IDS: string[] = PROVIDER_SPECS.map(s => s.provider_id)
const PROVIDER_NAME: Record<string, string> = Object.fromEntries(PROVIDER_SPECS.map(s => [s.provider_id, s.provider_name]))

function pad(n: number): string { return String(n).padStart(2, '0') }

function buildHistory(count: number): HistoryRecord[] {
  const out: HistoryRecord[] = []
  for (let i = 0; i < count; i++) {
    const [title, year, type] = TITLES[i % TITLES.length]
    const status = STATUS_POOL[i % STATUS_POOL.length]
    const provider = PROVIDER_IDS[i % PROVIDER_IDS.length]
    const hasPoster = i % 7 !== 5 // 少数无海报以验证占位
    out.push({
      unique: `mock-${i}`,
      provider,
      title: `${title}${i >= TITLES.length ? ' ' + (Math.floor(i / TITLES.length) + 1) : ''}`,
      year,
      type,
      poster: hasPoster ? POSTERS[i % POSTERS.length] : null,
      season: type === '电视剧' ? (i % 3) + 1 : null,
      status,
      reason: REASONS[status] || null,
      time: `2026-07-${pad(13 - (i % 12))} ${pad(9 + (i % 12))}:${pad((i * 7) % 60)}:00`,
    })
  }
  return out
}

let HISTORY: HistoryRecord[] = buildHistory(58)

// 订阅管理 mock 列表（镜像后端 /subscribes 的字段：id/name/year/type/state/date/poster/season）
const SUB_STATES: string[] = ['R', 'R', 'R', 'S', 'P', 'N']
function buildSubs(count: number): Subscribe[] {
  const out: Subscribe[] = []
  for (let i = 0; i < count; i++) {
    const [title, year, type] = TITLES[i % TITLES.length]
    out.push({
      id: i + 1,
      provider: PROVIDER_SPECS[i % PROVIDER_SPECS.length].provider_id,
      provider_name: PROVIDER_SPECS[i % PROVIDER_SPECS.length].provider_name,
      name: `${title}${i >= TITLES.length ? ' ' + (Math.floor(i / TITLES.length) + 1) : ''}`,
      year, type,
      state: SUB_STATES[i % SUB_STATES.length],
      poster: i % 6 !== 4 ? POSTERS[i % POSTERS.length] : null,
      season: type === '电视剧' ? (i % 3) + 1 : null,
      date: `2026-07-${pad(13 - (i % 12))}`,
    })
  }
  return out
}
let SUBSCRIBES: Subscribe[] = buildSubs(43)

// 发行年份闭区间判断（镜像后端 _year_in_range）
function yearOk(year: string, ymin: number | null, ymax: number | null): boolean {
  if (ymin == null && ymax == null) return true
  const y = parseInt(year, 10)
  if (!Number.isFinite(y)) return false
  if (ymin != null && y < ymin) return false
  if (ymax != null && y > ymax) return false
  return true
}

function computeStats(): Stats {
  const by_status: Record<string, number> = {}
  const by_provider: Record<string, number> = {}
  HISTORY.forEach(r => {
    by_status[r.status] = (by_status[r.status] || 0) + 1
    by_provider[r.provider] = (by_provider[r.provider] || 0) + 1
  })
  return { total: HISTORY.length, by_status, by_provider }
}

const ENABLED: Record<string, boolean> = { douban: true, maoyan: true, popular: false, mikan: true, netflix: false }

function delay<T>(value: T, ms = 320): Promise<T> {
  return new Promise(resolve => setTimeout(() => resolve(value), ms))
}

function parseQuery(url: string): Record<string, string> {
  const q = url.split('?')[1] || ''
  const params: Record<string, string> = {}
  q.split('&').filter(Boolean).forEach(pair => {
    const [k, v] = pair.split('=')
    params[k] = decodeURIComponent(v || '')
  })
  return params
}

// 开发壳用轻量本地化（镜像后端 core/i18n 的思路：源中文串 -> 译文）。
// 仅覆盖 mock spec 里出现的串，够开发壳 en/zh-TW 截图连贯即可。
const TEXT: Record<string, Record<string, string>> = {
  苹果音乐榜单: { 'zh-TW': '蘋果音樂榜單', 'en-US': 'Apple Music Charts' },
  豆瓣榜单: { 'zh-TW': '豆瓣榜單', 'en-US': 'Douban Rankings' },
  猫眼榜单: { 'zh-TW': '貓眼榜單', 'en-US': 'Maoyan Rankings' },
  热门媒体: { 'zh-TW': '熱門媒體', 'en-US': 'Popular Media' },
  'Mikan 季度新番': { 'zh-TW': 'Mikan 季度新番', 'en-US': 'Mikan Seasonal Anime' },
  奈飞榜单: { 'zh-TW': '奈飛榜單', 'en-US': 'Netflix Top 10' },
  内置榜单: { 'zh-TW': '內建榜單', 'en-US': 'Rank lists' },
  使用代理抓取: { 'zh-TW': '使用代理抓取', 'en-US': 'Use proxy' },
  'RSSHub 基址': { 'zh-TW': 'RSSHub 基址', 'en-US': 'RSSHub base URL' },
  '自定义 RSS 地址': { 'zh-TW': '自訂 RSS 位址', 'en-US': 'Custom RSS URLs' },
  '评分 ≥': { 'zh-TW': '評分 ≥', 'en-US': 'Rating ≥' },
  '年份 ≥': { 'zh-TW': '年份 ≥', 'en-US': 'Year ≥' },
  媒体类型: { 'zh-TW': '媒體類型', 'en-US': 'Media type' },
  榜单类型: { 'zh-TW': '榜單類型', 'en-US': 'List type' },
  播放平台: { 'zh-TW': '播放平台', 'en-US': 'Platform' },
  每榜条数: { 'zh-TW': '每榜條數', 'en-US': 'Items per list' },
  分类: { 'zh-TW': '分類', 'en-US': 'Category' },
  获取条数: { 'zh-TW': '取得條數', 'en-US': 'Fetch count' },
  '订阅人次 ≥': { 'zh-TW': '訂閱人次 ≥', 'en-US': 'Subscribers ≥' },
  年份: { 'zh-TW': '年份', 'en-US': 'Year' },
  季度: { 'zh-TW': '季度', 'en-US': 'Season' },
  '补全 bgm.tv id': { 'zh-TW': '補全 bgm.tv id', 'en-US': 'Resolve bgm.tv id' },
  抓取全球榜: { 'zh-TW': '抓取全球榜', 'en-US': 'Fetch global list' },
  全球数据源: { 'zh-TW': '全球資料源', 'en-US': 'Global dataset' },
  全球榜类别: { 'zh-TW': '全球榜類別', 'en-US': 'Global categories' },
  '国家/地区 × 媒体类型': { 'zh-TW': '國家/地區 × 媒體類型', 'en-US': 'Region × media type' },
  '国家/地区榜': { 'zh-TW': '國家/地區榜', 'en-US': 'Country lists' },
  '每榜取前 N': { 'zh-TW': '每榜取前 N', 'en-US': 'Top N per list' },
  使用代理: { 'zh-TW': '使用代理', 'en-US': 'Use proxy' },
  使用代理访问: { 'zh-TW': '使用代理存取', 'en-US': 'Use proxy' },
  富元数据模式: { 'zh-TW': '富元資料模式', 'en-US': 'Rich metadata' },
  并发线程数: { 'zh-TW': '並發執行緒數', 'en-US': 'Concurrency' },
  周更缓存: { 'zh-TW': '週更快取', 'en-US': 'Weekly cache' },
  全部: { 'zh-TW': '全部', 'en-US': 'All' },
  电影: { 'zh-TW': '電影', 'en-US': 'Movies' },
  电视剧: { 'zh-TW': '電視劇', 'en-US': 'TV Series' },
  剧集: { 'zh-TW': '劇集', 'en-US': 'TV Series' },
  动漫: { 'zh-TW': '動漫', 'en-US': 'Anime' },
  热门电影: { 'zh-TW': '熱門電影', 'en-US': 'Popular Films' },
  热门电视剧: { 'zh-TW': '熱門電視劇', 'en-US': 'Popular TV' },
  '豆瓣 TOP250': { 'zh-TW': '豆瓣 TOP250', 'en-US': 'Top 250' },
  近期热门综艺: { 'zh-TW': '近期熱門綜藝', 'en-US': 'Popular Variety' },
  电影票房: { 'zh-TW': '電影票房', 'en-US': 'Box Office' },
  网播热度: { 'zh-TW': '網播熱度', 'en-US': 'Streaming Heat' },
  网络剧: { 'zh-TW': '網路劇', 'en-US': 'Web Series' },
  综艺: { 'zh-TW': '綜藝', 'en-US': 'Variety' },
  全网: { 'zh-TW': '全網', 'en-US': 'All platforms' },
  腾讯: { 'zh-TW': '騰訊', 'en-US': 'Tencent' },
  爱奇艺: { 'zh-TW': '愛奇藝', 'en-US': 'iQIYI' },
  芒果: { 'zh-TW': '芒果', 'en-US': 'Mango TV' },
  优酷: { 'zh-TW': '優酷', 'en-US': 'Youku' },
  当前: { 'zh-TW': '當前', 'en-US': 'Current' },
  春: { 'zh-TW': '春', 'en-US': 'Spring' },
  夏: { 'zh-TW': '夏', 'en-US': 'Summer' },
  秋: { 'zh-TW': '秋', 'en-US': 'Autumn' },
  冬: { 'zh-TW': '冬', 'en-US': 'Winter' },
  最新周榜: { 'zh-TW': '最新週榜', 'en-US': 'Latest weekly' },
  '史上最热(不分周)': { 'zh-TW': '史上最熱(不分週)', 'en-US': 'All-time popular' },
  英语电影: { 'zh-TW': '英語電影', 'en-US': 'Films (English)' },
  非英语电影: { 'zh-TW': '非英語電影', 'en-US': 'Films (Non-English)' },
  英语剧集: { 'zh-TW': '英語劇集', 'en-US': 'TV (English)' },
  非英语剧集: { 'zh-TW': '非英語劇集', 'en-US': 'TV (Non-English)' },
  美国: { 'zh-TW': '美國', 'en-US': 'United States' },
  日本: { 'zh-TW': '日本', 'en-US': 'Japan' },
  韩国: { 'zh-TW': '韓國', 'en-US': 'South Korea' },
  中国台湾: { 'zh-TW': '中國台灣', 'en-US': 'Taiwan' },
}

function _L(text: string, lang: string): string {
  if (!lang || lang === 'zh-CN' || !text) return text
  return (TEXT[text] && TEXT[text][lang]) || text
}

function localizeSpec(spec: ProviderSpec, lang: string): ProviderSpec {
  if (!lang || lang === 'zh-CN') return spec
  const loc = (f: FieldSpec): FieldSpec => ({
    ...f,
    label: _L(f.label, lang),
    fields: f.fields?.map(loc),
    presets: f.presets?.map(p => ({ ...p, name: _L(String(p.name || ''), lang) })),
    options: f.options ? f.options.map(o => ({ ...o, title: _L(o.title, lang) })) : f.options,
  })
  return {
    ...spec,
    provider_name: _L(spec.provider_name, lang),
    options_schema: (spec.options_schema || []).map(loc),
    filters_schema: (spec.filters_schema || []).map(loc),
  }
}

export function createMockApi(initialConfig: Record<string, any> = {}): MockApi {
  const defaults = () => ({ global: { enabled: false, username: '自动订阅助手', exist_ok: true, history_keep: 0, onlyonce: false, clear: false },
    providers: Object.fromEntries(PROVIDER_SPECS.map(s => [s.provider_id, { enabled: false, notify: false, cron: s.default_cron,
      options: Object.fromEntries(s.options_schema.map(f => [f.key, JSON.parse(JSON.stringify(f.default))])), filters: {} }])) })
  let config = defaults()
  config.global = { ...config.global, ...initialConfig.global }
  for (const [pid, raw] of Object.entries(initialConfig.providers || {})) {
    const source = raw as Record<string, any>
    config.providers[pid] = { ...config.providers[pid], ...source, options: { ...config.providers[pid]?.options, ...source.options } }
  }
  let blacklist: Record<string, any>[] = []
  return {
    get(url: string): Promise<unknown> {
      const path = url.split('?')[0]
      const lang = parseQuery(url).lang || 'zh-CN'
      if (path === 'site/rss') return delay({ success: true, data: [{ id: 1, name: '预览站点', is_active: true }] })
      if (path === 'download/paths') return delay({ success: true, data: [{ name: '预览下载目录', download_path: '/downloads', save_path: '/downloads', storage: 'local' }] })
      if (path === 'download/clients') return delay({ success: true, data: [{ name: '预览下载器' }] })
      if (path === 'rule/groups') return delay({ success: true, data: { rule_groups: [{ name: '预览规则组' }] } })
      if (path.endsWith('/blacklist')) return delay({ code: 0, list: blacklist.slice(), total: blacklist.length })
      if (path.endsWith('/providers')) {
        return delay({ providers: PROVIDER_SPECS.map(s => localizeSpec(s, lang)) })
      }
      if (path.endsWith('/dashboard')) {
        const stats = computeStats()
        return delay({
          code: 0, enabled: true, stats, running: [],
          providers: PROVIDER_SPECS.map(s => ({ provider_id: s.provider_id, provider_name: _L(s.provider_name, lang), enabled: !!ENABLED[s.provider_id] })),
          counts: { history: stats.total, subscriptions: SUBSCRIBES.length, paused: SUBSCRIBES.filter(row => row.state === 'S').length, blacklist: blacklist.length },
          recent: HISTORY.filter(row => row.status === 'subscribed').slice(0, 5),
        })
      }
      if (path.endsWith('/status')) {
        return delay({
          enabled: true,
          providers: PROVIDER_SPECS.map(s => ({
            provider_id: s.provider_id,
            provider_name: _L(s.provider_name, lang),
            enabled: !!ENABLED[s.provider_id],
            cron: s.default_cron,
          })),
          stats: computeStats(),
        })
      }
      if (path.endsWith('/history')) {
        const p = parseQuery(url)
        // 逗号分隔多值：留空=不过滤
        const inSet = (v: string, csv?: string): boolean => { const s = (csv || '').split(',').filter(Boolean); return !s.length || s.includes(v) }
        const kw = (p.keyword || '').trim().toLowerCase()
        const ymin = p.year_min ? parseInt(p.year_min, 10) : null
        const ymax = p.year_max ? parseInt(p.year_max, 10) : null
        const list = HISTORY.filter(r =>
          inSet(r.provider, p.provider) && inSet(r.status, p.status) && inSet(r.type, p.mtype) &&
          (!kw || String(r.title || '').toLowerCase().includes(kw)) &&
          yearOk(r.year, ymin, ymax))
        const total = list.length
        const page = Math.max(1, parseInt(p.page, 10) || 1)
        const count = Math.max(1, parseInt(p.count, 10) || 24)
        const start = (page - 1) * count
        return delay({ list: list.slice(start, start + count), total, page, count })
      }
      if (path.endsWith('/subscribes')) {
        return delay({ list: SUBSCRIBES.slice(), total: SUBSCRIBES.length })
      }
      if (path.endsWith('/config')) {
        return delay({ code: 0, config: JSON.parse(JSON.stringify(config)) })
      }
      return delay({})
    },
    post(url: string, body?: Record<string, any>): Promise<unknown> {
      if (url.endsWith('/config/reset')) {
        if (body?.confirmed !== true) return delay({ code: 1, message: '请先确认还原配置' })
        config = defaults()
        return delay({ code: 0, config: JSON.parse(JSON.stringify(config)) })
      }
      if (url.endsWith('/config')) {
        config = JSON.parse(JSON.stringify(body))
        return delay({ code: 0 })
      }
      // 仅开发壳的内存演示，生产识别与防重复行为由后端管线负责。
      if (url.endsWith('/history/supplement')) {
        const original = HISTORY.find(row => row.unique === body?.unique)
        if (!original || !body?.media?.title) return delay({ code: 1, message: '缺少历史或媒体信息' })
        const media = body.media
        const season = media.type === '电视剧' ? media.season : null
        if (SUBSCRIBES.some(row => row.name === media.title && row.type === media.type && row.year === media.year && row.season === season)) {
          return delay({ code: 0, created: false, status: 'subscription_exists', message: '订阅已存在' })
        }
        const id = Math.max(0, ...SUBSCRIBES.map(row => row.id)) + 1
        const time = new Date().toISOString().replace('T', ' ').slice(0, 19)
        SUBSCRIBES.unshift({ id, name: media.title, type: media.type, year: media.year || '', season, state: 'R', poster: original.poster, date: time })
        HISTORY.unshift({ ...original, unique: `manual:${id}`, title: media.title, year: media.year || '', type: media.type, season, status: 'subscribed', reason: null, time })
        return delay({ code: 0, created: true, status: 'subscribed', subscribe_id: id }, 600)
      }
      if (url.endsWith('/blacklist/add') || url.endsWith('/subscribes/block')) {
        const blocking = url.endsWith('/subscribes/block')
        const targets = blocking ? SUBSCRIBES.filter(row => (body?.ids || []).includes(row.id))
          : [body?.kind === 'history' ? HISTORY.find(row => row.unique === body?.unique)
            : body?.kind === 'subscription' ? SUBSCRIBES.find(row => row.id === body?.id) : body?.media]
        const ok_ids: number[] = []
        targets.filter(Boolean).forEach((media: any) => {
          blacklist.unshift({ ...media, id: crypto.randomUUID(), title: media.title || media.name,
            season: body?.scope === 'season' ? Number(media.season) : null, time: new Date().toLocaleString() })
          if (blocking) ok_ids.push(media.id)
        })
        if (blocking) SUBSCRIBES = SUBSCRIBES.filter(row => !ok_ids.includes(row.id))
        return delay({ code: 0, ok: ok_ids.length, failed: 0, ok_ids, failed_ids: [] })
      }
      if (url.endsWith('/blacklist/delete')) {
        blacklist = blacklist.filter(row => !(body?.ids || []).includes(row.id))
        return delay({ code: 0 })
      }
      if (url.endsWith('/run')) {
        const spec = PROVIDER_SPECS.find(s => s.provider_id === body?.provider_id)
        return delay({ code: 0, message: `${spec?.provider_name || body?.provider_id} 已触发，将在 3 秒后运行` }, 500)
      }
      if (url.endsWith('/providers/test')) {
        const sample = TITLES[0][0]
        return delay({ code: 0, ok: true, count: 3, sample, message: `连通正常，取到示例：${sample}` }, 700)
      }
      if (url.endsWith('/history/delete')) {
        HISTORY = HISTORY.filter(r => r.unique !== body?.unique)
        return delay({ code: 0, message: '删除成功' })
      }
      if (url.endsWith('/history/batch-delete')) {
        const ids = new Set<string>(body?.uniques || [])
        HISTORY = HISTORY.filter(r => !ids.has(r.unique))
        return delay({ code: 0, message: `已删除 ${ids.size} 条`, removed: ids.size })
      }
      if (url.endsWith('/history/recognize')) {
        const rec = HISTORY.find(r => r.unique === body?.unique)
        if (!rec) return delay({ code: 1, message: '未找到该记录' })
        rec.status = 'subscribed'   // 开发壳模拟：重新识别成功 → 已订阅
        rec.reason = null
        return delay({ code: 0, status: 'subscribed', message: '重新识别完成' }, 600)
      }
      if (url.endsWith('/subscribes/delete')) {
        const ids = new Set<number>(body?.ids || [])
        SUBSCRIBES = SUBSCRIBES.filter(s => !ids.has(s.id))
        return delay({ code: 0, message: '已退订' })
      }
      if (url.endsWith('/subscribes/state')) {
        const ids = new Set<number>(body?.ids || [])
        SUBSCRIBES = SUBSCRIBES.map(s => (ids.has(s.id) ? { ...s, state: body?.state } : s))
        return delay({ code: 0, message: '已更新' })
      }
      return delay({ code: 0 })
    },
  }
}

export { PROVIDER_NAME }
