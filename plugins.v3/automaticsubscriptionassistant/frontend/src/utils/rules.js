let ruleSequence = 0
export function createRuleId(cryptoSource = globalThis.crypto) {
  try {
    if (typeof cryptoSource?.randomUUID === 'function') return cryptoSource.randomUUID()
    if (typeof cryptoSource?.getRandomValues === 'function') {
      const bytes = cryptoSource.getRandomValues(new Uint8Array(16))
      return `rule-${Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('')}`
    }
  } catch { /* An unavailable browser crypto API must not block creating a rule. */ }
  ruleSequence += 1
  return `rule-${Date.now().toString(36)}-${ruleSequence.toString(36)}-${Math.random().toString(36).slice(2)}`
}

export function visibleField(field, rule) {
  return Object.entries(field.visible_when || {}).every(([key, allowed]) => allowed.includes(rule[key]))
}
export function fieldOptions(field, rule) {
  return field.options_by ? (field.options_by.values?.[rule[field.options_by.key]] || []) : (field.options || [])
}
export function ruleValues(fields, rule) {
  const values = Object.fromEntries(fields.map(f => [f.key, JSON.parse(JSON.stringify(rule[f.key] ?? f.default ?? null))]))
  return Object.fromEntries(fields.filter(f => visibleField(f, values)).map(f => {
    let value = values[f.key]
    if (f.kind === 'number' || f.kind === 'float') value = value === '' || value == null ? null : Number(value)
    else if (Array.isArray(value)) value = [...new Set(value)].sort()
    else if (typeof value === 'string') value = value.trim()
    return [f.key, value]
  }))
}
export function ruleSignature(fields, rule) {
  return JSON.stringify(ruleValues(fields, rule))
}
export function invalidFields(fields, rule) {
  const values = ruleValues(fields, rule)
  return fields.filter(f => visibleField(f, values)).filter(f => {
    const v = values[f.key]
    if (f.required && (v == null || v === '' || (Array.isArray(v) && !v.length))) return true
    if (f.kind === 'number' || f.kind === 'float') {
      return typeof rule[f.key] === 'boolean' || v == null || !Number.isFinite(v) || (f.kind === 'number' && !Number.isInteger(v)) ||
        (f.minimum != null && v < f.minimum) || (f.maximum != null && v > f.maximum)
    }
    if (f.kind === 'select') return !fieldOptions(f, values).some(o => o.value === v)
    if (f.kind === 'multi-select') return !Array.isArray(v) || v.some(x => !fieldOptions(f, values).some(o => o.value === x))
    if (typeof v !== 'string' || v.length > 2048) return true
    if (f.key === 'url' && v) {
      try { return !['http:', 'https:'].includes(new URL(v).protocol) } catch { return true }
    }
    return false
  })
}
export function ruleSummary(fields, rule) {
  const values = ruleValues(fields, rule)
  return fields.filter(f => visibleField(f, values) && (!f.advanced || values[f.key]) &&
    values[f.key] !== '' && values[f.key] !== 0 && (!Array.isArray(values[f.key]) || values[f.key].length))
    .map(f => {
      const value = values[f.key]
      const options = fieldOptions(f, values)
      const title = v => options.find(o => o.value === v)?.title ?? v
      return `${f.label}：${Array.isArray(value) ? value.map(title).join(' / ') : title(value)}`
    }).join(' · ')
}
