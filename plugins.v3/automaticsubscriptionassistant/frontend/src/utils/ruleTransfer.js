/** 来源规则的可移植格式及导入校验；不包含代理、通知或来源调度配置。 */
import { createRuleId, invalidFields, ruleSignature, ruleValues, visibleField } from './rules.js'

export const RULE_SHARE_FORMAT = 'moviepilot.automatic-subscription-assistant.rules'
export const RULE_SHARE_VERSION = 1
export const PLUGIN_VERSION = typeof __ASA_PLUGIN_VERSION__ === 'string' ? __ASA_PLUGIN_VERSION__ : ''
export const MAX_RULE_SHARE_BYTES = 1024 * 1024
const pluginId = 'AutomaticSubscriptionAssistant'
const record = value => !!value && typeof value === 'object' && !Array.isArray(value)
const clone = value => JSON.parse(JSON.stringify(value))
const versionPattern = /^\d+\.\d+\.\d+(?:[-+][\w.-]+)?$/

export class RuleTransferError extends Error {
  constructor(code, details = {}) { super(code); this.code = code; this.details = details }
}
function fail(code, details) { throw new RuleTransferError(code, details) }
function assertSource(providerId) {
  if (typeof providerId !== 'string' || !/^[a-z][a-z0-9_-]{0,63}$/.test(providerId)) fail('sourceMissing')
}
function contract(fields) {
  // 仅记录稳定配置语义；显示名称与语言变化不会被当成规则格式变化。
  return fields.map(f => ({
    key: f.key, kind: f.kind, default: f.default ?? null, required: !!f.required,
    minimum: f.minimum ?? null, maximum: f.maximum ?? null,
    values: (f.options || []).map(o => o.value), visibleWhen: f.visible_when || {},
    optionsBy: f.options_by ? { key: f.options_by.key, values: Object.fromEntries(Object.entries(f.options_by.values).map(([key, options]) => [key, options.map(o => o.value)])) } : null,
  }))
}
function sorted(value) {
  if (Array.isArray(value)) return value.map(sorted)
  if (!record(value)) return value
  return Object.fromEntries(Object.keys(value).sort().map(key => [key, sorted(value[key])]))
}
const equal = (a, b) => JSON.stringify(sorted(a)) === JSON.stringify(sorted(b))
function checkedRule(fields, row, index, warnings, { imported = false } = {}) {
  if (!record(row) || typeof row.on !== 'boolean' && row.on !== undefined || typeof row.name !== 'string' || row.name.length > 80) fail('invalidRule', { index: index + 1 })
  const allowed = new Set(['id', 'name', 'on', ...fields.map(f => f.key)])
  const unknown = Object.keys(row).filter(key => !allowed.has(key))
  if (unknown.length) fail('unknownFields', { index: index + 1, fields: unknown.join(', ') })
  const complete = { ...Object.fromEntries(fields.map(f => [f.key, f.default])), ...row }
  const missing = fields.filter(f => visibleField(f, complete) && !Object.hasOwn(row, f.key))
  if (imported) {
    const required = missing.filter(f => f.required)
    if (required.length) fail('missingFields', { index: index + 1, fields: required.map(f => f.label).join(', ') })
    if (missing.length) warnings.push({ code: 'defaultsAdded', details: { index: index + 1, fields: missing.map(f => f.label).join(', ') } })
  }
  if (fields.some(f => Object.hasOwn(row, f.key) && row[f.key] === null) || invalidFields(fields, row).length) fail('invalidRule', { index: index + 1 })
  return { ...ruleValues(fields, row), name: row.name.trim(), on: row.on !== false, id: imported ? createRuleId() : row.id || createRuleId() }
}

export function serializeRuleShare({ providerId, providerName = '', fields, rules, pluginVersion = PLUGIN_VERSION, now = new Date() }) {
  assertSource(providerId)
  if (!versionPattern.test(pluginVersion)) fail('versionMissing')
  if (!Array.isArray(rules) || !rules.length || rules.length > 100) fail('ruleCount')
  const warnings = [], seen = new Set()
  const clean = rules.map((row, index) => {
    const rule = checkedRule(fields, row, index, warnings)
    const key = ruleSignature(fields, rule)
    if (seen.has(key)) fail('duplicateRules')
    seen.add(key)
    // 导入时重建本地标识，分享内容不携带安装实例状态。
    const { id, ...portable } = rule
    return portable
  })
  const payload = { format: RULE_SHARE_FORMAT, formatVersion: RULE_SHARE_VERSION, pluginId, pluginVersion,
    provider: { id: providerId, name: providerName || providerId }, createdAt: now.toISOString(), schema: contract(fields), rules: clean }
  const text = JSON.stringify(payload, null, 2)
  if (new TextEncoder().encode(text).length > MAX_RULE_SHARE_BYTES) fail('tooLarge')
  return text
}

export function inspectRuleShare(text, { providerId, fields, pluginVersion = PLUGIN_VERSION }) {
  assertSource(providerId)
  if (typeof text !== 'string' || new TextEncoder().encode(text).length > MAX_RULE_SHARE_BYTES) fail('tooLarge')
  let payload
  try { payload = JSON.parse(text.replace(/^\uFEFF/, '')) } catch { fail('invalidJson') }
  if (!record(payload) || payload.format !== RULE_SHARE_FORMAT || payload.pluginId !== pluginId) fail('invalidFormat')
  if (payload.formatVersion !== RULE_SHARE_VERSION) fail('formatVersion', { version: payload.formatVersion })
  if (!record(payload.provider) || payload.provider.id !== providerId) fail('wrongSource', { source: String(payload.provider?.id || ''), target: providerId })
  if (typeof payload.pluginVersion !== 'string' || !versionPattern.test(payload.pluginVersion)) fail('versionMissing')
  if (typeof payload.createdAt !== 'string' || !Number.isFinite(Date.parse(payload.createdAt))) fail('invalidFormat')
  if (!Array.isArray(payload.rules) || !payload.rules.length || payload.rules.length > 100) fail('ruleCount')
  if (!Array.isArray(payload.schema) || !payload.schema.every(f => record(f) && typeof f.key === 'string') || new Set(payload.schema.map(f => f.key)).size !== payload.schema.length) fail('invalidFormat')
  const warnings = []
  if (payload.pluginVersion !== pluginVersion) warnings.push({ code: 'versionDifferent', details: { source: payload.pluginVersion, target: pluginVersion } })
  const current = contract(fields)
  if (!equal(payload.schema, current)) warnings.push({ code: 'schemaDifferent', details: {} })
  const old = new Map(payload.schema.map(f => [f.key, f]))
  // 字段类型或默认语义已改变时，拒绝静默转换；保留原文本用于人工校对。
  for (const field of current) {
    const prior = old.get(field.key)
    if (prior && (prior.kind !== field.kind || !equal(prior.default, field.default) || !equal(prior.visibleWhen, field.visibleWhen))) fail('changedField', { field: field.key })
  }
  const seen = new Set()
  const rules = payload.rules.map((row, index) => {
    const rule = checkedRule(fields, row, index, warnings, { imported: true })
    const key = ruleSignature(fields, rule)
    if (seen.has(key)) fail('duplicateRules')
    seen.add(key)
    return rule
  })
  return { provider: clone(payload.provider), pluginVersion: payload.pluginVersion, createdAt: payload.createdAt, rules, warnings }
}

export function combineImportedRules(fields, existing, imported, mode = 'append') {
  if (!['append', 'replace'].includes(mode)) fail('invalidFormat')
  const result = mode === 'replace' ? [] : clone(existing)
  const seen = new Set(result.map(rule => ruleSignature(fields, rule)))
  const ids = new Set(result.map(rule => rule.id).filter(Boolean))
  let skipped = 0
  for (const original of imported) {
    const signature = ruleSignature(fields, original)
    if (seen.has(signature)) { skipped += 1; continue }
    const rule = clone(original)
    do { rule.id = createRuleId() } while (ids.has(rule.id))
    ids.add(rule.id); seen.add(signature); result.push(rule)
  }
  if (result.length > 100) fail('ruleCount')
  return { rules: result, skipped, added: imported.length - skipped }
}
