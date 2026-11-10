/** 与宿主 SubscribeEditDialog 使用相同的预设值和公开选项接口。 */
export function subscriptionPresets(t) {
  const option = (title, value) => ({ title, value })
  const inherit = option(t('inherit'), '')
  return {
    quality: [inherit,
      option(t('blurayOriginal'), 'Blu-?Ray.+VC-?1|Blu-?Ray.+AVC|UHD.+blu-?ray.+HEVC|MiniBD'),
      option('Remux', 'Remux'), option('BluRay', 'Blu-?Ray'), option('UHD', 'UHD|UltraHD'),
      option('WEB-DL', 'WEB-?DL|WEB-?RIP'), option('HDTV', 'HDTV'),
      option('H265', '[Hx].?265|HEVC'), option('H264', '[Hx].?264|AVC')],
    resolution: [inherit, option('4K', '4K|2160p|x2160'), option('1080p', '1080[pi]|x1080'), option('720p', '720[pi]|x720')],
    effect: [inherit, option(t('dolbyVision'), 'Dolby[\\s.]+Vision|DOVI|[\\s.]+DV[\\s.]+'),
      option(t('dolbyAtmos'), 'Dolby[\\s.]*\\+?Atmos|Atmos'), option('HDR', '[\\s.]+HDR[\\s.]+|HDR10|HDR10\\+'), option('SDR', '[\\s.]+SDR[\\s.]+')],
    audio_quality: [inherit, option(t('hires'), 'hires'), option(t('lossless'), 'hires|lossless'), option(t('lossy'), 'lossy')],
    audio_format: [inherit, option(t('losslessFormats'), 'DSD|FLAC|ALAC|APE|WAV|AIFF|PCM'),
      ...['DSD', 'FLAC', 'ALAC', 'APE', 'WAV', 'AIFF', 'PCM', 'MP3', 'AAC', 'OGG', 'OPUS', 'WMA'].map(value => option(value, value))],
    min_bitrate: [128000, 192000, 256000, 320000].map(value => option(`${value / 1000} kbps`, value)),
    min_bit_depth: [16, 24, 32].map(value => option(`${value}-bit`, value)),
    min_sample_rate: [44100, 48000, 88200, 96000, 176400, 192000].map(value => option(`${value / 1000} kHz`, value)),
  }
}

function rows(payload, key) {
  if (payload?.success === false) throw Error(payload.message || 'Option API failed')
  const data = payload?.success === true ? payload.data : payload
  const result = key && !Array.isArray(data) ? data?.[key] : data
  if (!Array.isArray(result) || result.some(row => !row || typeof row !== 'object')) throw Error('Invalid option list')
  return result
}

/** 目录值始终保存路径，同一路径的别名合并展示；对齐宿主下载目录选择器。 */
export function subscriptionDirectories(directories) {
  const aliases = new Map()
  for (const row of directories) {
    const path = (row.downloadPath || row.download_path || row.path || '').trim()
    if (!path) continue
    const names = aliases.get(path) || []
    const name = (row.name || '').trim()
    if (name && name !== path && !names.includes(name)) names.push(name)
    aliases.set(path, names)
  }
  return [...aliases].map(([value, names]) => ({ title: names.length ? `${names.join(' / ')} (${value})` : value, value }))
}

export async function loadSubscriptionCatalogs(api, sdk) {
  const client = typeof api?.get === 'function' ? api : sdk?.api
  const get = async (url, config = {}) => {
    if (typeof client?.get !== 'function') throw Error('API unavailable')
    return client.get(url, { feedback: 'silent', ...config })
  }
  async function catalog(method, url, config, key) {
    if (typeof sdk?.catalogs?.[method] === 'function') {
      try { return rows(await sdk.catalogs[method](), key) }
      catch { /* 旧宿主 SDK 未实现或读取失败时，使用主程序表单的公开接口。 */ }
    }
    return rows(await get(url, config), key)
  }
  const requests = {
    sites: async () => rows(await get('site/rss')).filter(site => site.is_active !== false)
      .map(site => ({ title: site.name, value: site.id })),
    downloaders: async () => rows(await get('download/clients')).map(item => ({ title: item.name, value: item.name })),
    groups: async () => (await catalog('ruleGroups', 'rule/groups', { params: { include_usage: false } }, 'rule_groups'))
      .map(group => ({ title: group.name, value: group.name })),
    directories: async () => subscriptionDirectories(await catalog('downloadDirectories', 'download/paths')),
  }
  const keys = Object.keys(requests)
  const results = await Promise.allSettled(keys.map(key => Promise.resolve().then(requests[key])))
  return Object.fromEntries(results.map((result, index) => [keys[index], result.status === 'fulfilled'
    ? { items: result.value, failed: false } : { items: [], failed: true }]))
}
