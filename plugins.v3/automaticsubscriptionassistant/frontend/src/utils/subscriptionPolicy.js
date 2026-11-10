export const MEDIA_TYPES = ['电影', '电视剧', '音乐']
export const COMMON_FIELDS = ['include', 'exclude', 'sites', 'downloader', 'save_path', 'filter_groups', 'search_interval', 'best_version']
const videoFields = ['quality', 'resolution', 'effect', 'search_imdbid']
const musicFields = ['audio_quality', 'audio_format', 'min_bitrate', 'min_bit_depth', 'min_sample_rate']
export const policyFields = type => [...COMMON_FIELDS, ...(type === '音乐' ? musicFields : videoFields), ...(type === '电视剧' ? ['best_version_full'] : [])]
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value)
export function normalizeSubscriptionPolicy(raw) {
  if (raw == null) return { enabled: false, configs: {} }
  if (!object(raw) || Object.keys(raw).some(k => !['enabled', 'configs'].includes(k)) || typeof (raw.enabled === undefined ? false : raw.enabled) !== 'boolean' || !object(raw.configs === undefined ? {} : raw.configs)) throw new Error('订阅规则配置格式无效')
  const configs = {}
  for (const [type, value] of Object.entries(raw.configs || {})) {
    if (!MEDIA_TYPES.includes(type) || !object(value) || Object.keys(value).some(k => !policyFields(type).includes(k))) throw new Error('订阅规则含不支持的字段')
    for (const [key, v] of Object.entries(value)) {
      if (['best_version', 'best_version_full', 'search_imdbid'].includes(key)) {
        if (v != null && ![true, false, 0, 1].includes(v)) throw new Error('订阅模式格式无效')
      } else if (key === 'sites') {
        if (!Array.isArray(v) || v.some(id => !Number.isSafeInteger(id) || id <= 0)) throw new Error('订阅站点必须为有效 ID 列表')
      } else if (key === 'filter_groups') {
        if (!Array.isArray(v) || v.length > 100 || v.some(name => typeof name !== 'string' || !name.trim() || name.length > 200)) throw new Error('过滤规则组格式无效')
      } else if (['search_interval', 'min_bitrate', 'min_bit_depth', 'min_sample_rate'].includes(key)) {
        if (v != null && (!Number.isSafeInteger(v) || v < 1 || key === 'search_interval' && v > 8760)) throw new Error('订阅数值格式或范围无效')
      } else if (v != null && (typeof v !== 'string' || v.length > 4096)) throw new Error('订阅设置必须为文本')
    }
    if (value.best_version_full && !value.best_version) throw new Error('全集洗版需要同时开启洗版订阅')
    configs[type] = JSON.parse(JSON.stringify(value))
  }
  return { enabled: raw.enabled ?? false, configs }
}
export function subscriptionMediaTypes(providerId, rule = {}) {
  if (['spotify', 'applemusic', 'netease', 'qqmusic'].includes(providerId)) return ['音乐']
  if (providerId === 'mikan') return ['电视剧']
  const category = rule.media_type !== 'all' && rule.media_type || rule.category
  if (category === 'movie' || rule.chart === 'movie-box') return ['电影']
  if (category === 'tv' || rule.chart === 'web-heat') return ['电视剧']
  return ['电影', '电视剧']
}
