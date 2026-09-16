/**
 * 仅供本地开发壳（App.vue / yarn dev）预览三组件的内存 Mock API。
 *
 * 该文件不被联邦暴露、也不被任何生产组件 import，仅进入开发壳 index-*.js 产物
 * （构建时不上传）。数据结构严格镜像后端 /providers、/status、/history、/run。
 */

interface Option {
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
  columns?: Option[]
  row_noun?: string
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

const PROVIDER_SPECS: ProviderSpec[] = [
  {
    provider_id: 'douban',
    provider_name: '豆瓣榜单',
    default_cron: '0 8 * * *',
    options_schema: [
      {
        key: 'ranks', label: '内置榜单', kind: 'multi-select', default: ['movie-hot-gaia', 'tv-hot'],
        hint: '选择要抓取的豆瓣内置榜单',
        options: [
          { title: '热门电影', value: 'movie-hot-gaia' },
          { title: '热门电视剧', value: 'tv-hot' },
          { title: '豆瓣 TOP250', value: 'movie-top250' },
          { title: '近期热门综艺', value: 'show-hot' },
        ],
      },
      { key: 'proxy', label: '使用代理抓取', kind: 'switch', default: false, hint: '抓取是否走系统代理' },
      { key: 'rsshub_base', label: 'RSSHub 基址', kind: 'text', default: 'https://rsshub.app', advanced: true, hint: '被封锁时可改为自建实例' },
      { key: 'rss_addrs', label: '自定义 RSS 地址', kind: 'textarea', default: '', advanced: true, hint: '每行一个完整 RSS 地址' },
    ],
    filters_schema: [
      { key: 'vote', label: '评分 ≥', kind: 'float', default: 7.0, hint: '低于此评分的条目将被过滤，≤0 不启用' },
      { key: 'year', label: '年份 ≥', kind: 'number', default: 2020, hint: '早于此年份的条目将被过滤，≤0 不启用' },
      {
        key: 'media_type', label: '媒体类型', kind: 'select', default: 'all',
        options: [
          { title: '全部', value: 'all' },
          { title: '电影', value: 'movie' },
          { title: '电视剧', value: 'tv' },
        ],
      },
    ],
  },
  {
    provider_id: 'maoyan',
    provider_name: '猫眼榜单',
    default_cron: '0 9 * * *',
    notice: '网络电影因数据源已停更（优酷停于 2022、爱奇艺停于 2026-01），暂不支持，已移除。',
    options_schema: [
      { key: 'movie_box', label: '电影票房榜', kind: 'switch', default: true },
      {
        key: 'web_platform_map', label: '网播热度 平台 × 类型', kind: 'region-media-map', default: { all: ['tv'] },
        row_noun: 'platform',
        hint: '按平台分别选择要监听的网播类型（可各不相同）；网络电影仅腾讯视频/爱奇艺/优酷有数据',
        options: [
          { title: '全网', value: 'all' }, { title: '腾讯视频', value: 'tx' },
          { title: '爱奇艺', value: 'iqiyi' }, { title: '优酷', value: 'youku' },
          { title: '乐视', value: 'letv' }, { title: '芒果TV', value: 'mgtv' },
          { title: 'PPTV', value: 'pptv' }, { title: '搜狐', value: 'sohu' },
        ],
        columns: [
          { title: '电视剧+网络剧', value: 'series' }, { title: '电视剧', value: 'tv' },
          { title: '网络剧', value: 'web' }, { title: '综艺', value: 'variety' },
        ],
      },
      { key: 'num', label: '每榜条数', kind: 'number', default: 10 },
      { key: 'proxy', label: '使用代理访问', kind: 'switch', default: false },
    ],
    filters_schema: [
      { key: 'year', label: '年份 ≥', kind: 'number', default: 0 },
      {
        key: 'media_type', label: '媒体类型', kind: 'select', default: 'all',
        options: [{ title: '全部', value: 'all' }, { title: '电影', value: 'movie' }, { title: '电视剧', value: 'tv' }],
      },
    ],
  },
  {
    provider_id: 'popular',
    provider_name: '热门媒体',
    default_cron: '5 1 * * *',
    options_schema: [
      { key: 'movie_enabled', label: '电影订阅', kind: 'switch', default: true },
      {
        key: 'movie_genres', label: '电影风格', kind: 'multi-select', default: [],
        hint: '留空=全部；仅开启电影订阅时生效',
        options: [{ title: '动画', value: '16' }, { title: '动作', value: '28' }, { title: '科幻', value: '878' }, { title: '悬疑', value: '9648' }],
      },
      { key: 'movie_page_cnt', label: '电影获取条数', kind: 'number', default: 30 },
      { key: 'movie_min_rating', label: '电影评分下限(≥)', kind: 'float', default: 0, hint: '0=不限' },
      { key: 'movie_popularity', label: '电影订阅人次(≥)', kind: 'number', default: 0, hint: '0=不限' },
      { key: 'tv_enabled', label: '剧集订阅', kind: 'switch', default: true },
      {
        key: 'tv_genres', label: '剧集风格', kind: 'multi-select', default: [],
        hint: '留空=全部；仅开启剧集订阅时生效',
        options: [{ title: '动画', value: '16' }, { title: '悬疑', value: '9648' }, { title: '真人秀', value: '10764' }, { title: '科幻奇幻', value: '10765' }],
      },
      { key: 'tv_page_cnt', label: '剧集获取条数', kind: 'number', default: 30 },
      { key: 'tv_min_rating', label: '剧集评分下限(≥)', kind: 'float', default: 0, hint: '0=不限' },
      { key: 'tv_popularity', label: '剧集订阅人次(≥)', kind: 'number', default: 0, hint: '0=不限' },
    ],
    filters_schema: [],
  },
  {
    provider_id: 'mikan',
    provider_name: 'Mikan 季度新番',
    default_cron: '0 10 * * 1',
    options_schema: [
      { key: 'year', label: '年份', kind: 'number', default: 0, hint: '0 取当前年' },
      {
        key: 'season', label: '季度', kind: 'select', default: '当前',
        options: [
          { title: '当前', value: '当前' }, { title: '春', value: '春' },
          { title: '夏', value: '夏' }, { title: '秋', value: '秋' }, { title: '冬', value: '冬' },
        ],
      },
      { key: 'resolve_bangumi_id', label: '补全 bgm.tv id', kind: 'switch', default: true, hint: '更准但更慢（每条约 0.6s）' },
      { key: 'proxy', label: '使用代理访问', kind: 'switch', default: false },
    ],
    filters_schema: [
      { key: 'year', label: '年份 ≥', kind: 'number', default: 0 },
    ],
  },
  {
    provider_id: 'netflix',
    provider_name: '奈飞榜单',
    default_cron: '0 11 * * 3',
    options_schema: [
      { key: 'global', label: '抓取全球榜', kind: 'switch', default: true },
      {
        key: 'global_dataset', label: '全球数据源', kind: 'select', default: 'all-weeks-global',
        options: [{ title: '最新周榜', value: 'all-weeks-global' }, { title: '史上最热', value: 'most-popular' }],
      },
      {
        key: 'global_media_types', label: '全球榜类别', kind: 'multi-select',
        default: ['Films (English)', 'Films (Non-English)', 'TV (English)', 'TV (Non-English)'],
        options: [
          { title: '英语电影', value: 'Films (English)' },
          { title: '非英语电影', value: 'Films (Non-English)' },
          { title: '英语剧集', value: 'TV (English)' },
          { title: '非英语剧集', value: 'TV (Non-English)' },
        ],
      },
      {
        key: 'country_selections', label: '国家/地区 × 媒体类型', kind: 'region-media-map', default: {},
        hint: '按地区分别选择要监听的媒体类型（可各不相同）',
        options: [
          { title: '美国', value: 'US' }, { title: '日本', value: 'JP' },
          { title: '韩国', value: 'KR' }, { title: '中国台湾', value: 'TW' },
        ],
        columns: [
          { title: '电影', value: 'Films' }, { title: '剧集', value: 'TV' },
        ],
      },
      { key: 'limit', label: '每榜取前 N', kind: 'number', default: 10 },
      { key: 'proxy', label: '使用代理', kind: 'switch', default: false },
      { key: 'rich_metadata', label: '富元数据模式', kind: 'switch', default: false, hint: '带年份+干净剧名，识别更准' },
      { key: 'max_workers', label: '并发线程数', kind: 'number', default: 5, advanced: true, hint: '富元数据模式下多榜并发数' },
      { key: 'use_cache', label: '周更缓存', kind: 'switch', default: true, advanced: true, hint: '避免同周重复抓取触发风控' },
    ],
    filters_schema: [],
  },
]

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
    options: f.options ? f.options.map(o => ({ ...o, title: _L(o.title, lang) })) : f.options,
    columns: f.columns ? f.columns.map(c => ({ ...c, title: _L(c.title, lang) })) : f.columns,
  })
  return {
    ...spec,
    provider_name: _L(spec.provider_name, lang),
    options_schema: (spec.options_schema || []).map(loc),
    filters_schema: (spec.filters_schema || []).map(loc),
  }
}

export function createMockApi(): MockApi {
  return {
    get(url: string): Promise<unknown> {
      const path = url.split('?')[0]
      const lang = parseQuery(url).lang || 'zh-CN'
      if (path.endsWith('/providers')) {
        return delay({ providers: PROVIDER_SPECS.map(s => localizeSpec(s, lang)) })
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
        return delay({ config: {} })
      }
      return delay({})
    },
    post(url: string, body?: Record<string, any>): Promise<unknown> {
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
