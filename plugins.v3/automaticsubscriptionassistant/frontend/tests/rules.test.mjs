import assert from 'node:assert/strict'
import fs from 'node:fs'
import { test } from 'node:test'
import { reactive } from 'vue'
import { fieldOptions, invalidFields, ruleSignature, ruleSummary, ruleValues } from '../src/utils/rules.js'
const specs = JSON.parse(fs.readFileSync(new URL('../src/dev/providerSpecs.json', import.meta.url)))
const fields = id => specs.find(s => s.provider_id === id).options_schema[0].fields

test('规则编辑可读取 Vue 响应式数组，不修改已有规则', () => {
  const row = reactive({ formats:['TV', 'MOVIE'], time:'all', sort:'TRENDING_DESC', name:'动画' })
  const values = ruleValues(fields('anilist'), row)
  assert.deepEqual(values.formats, ['MOVIE', 'TV'])
  values.formats.push('OVA')
  assert.deepEqual([...row.formats], ['TV', 'MOVIE'])
})
test('重复规则忽略名称、开关与选项顺序，并统一数字类型', () => {
  const a = { name:'a', id:'a', formats:['TV','MOVIE'], limit:20 }
  const b = { name:'b', id:'b', on:false, formats:['MOVIE','TV'], limit:'20' }
  assert.equal(ruleSignature(fields('anilist'), a), ruleSignature(fields('anilist'), b))
})
test('季度切换仅保存有效条件，固定年份保留全年选择', () => {
  const a = ruleValues(fields('anilist'), { time:'all', year:2020, season:'FALL' })
  assert.equal(a.year, undefined)
  assert.equal(a.season, undefined)
  const b = ruleValues(fields('anilist'), { time:'fixed', year:2025, season:'ALL' })
  assert.equal(b.year, 2025)
  assert.equal(b.season, 'ALL')
  assert.notEqual(ruleSignature(fields('anilist'), {time:'fixed',year:2025}), ruleSignature(fields('anilist'), {time:'fixed',year:2024}))
})
test('字段校验拒绝非法数字、空形式及无效 RSS，允许可选筛选为空', () => {
  for (const limit of [-1,1.5,'NaN','Infinity','']) assert.ok(invalidFields(fields('anilist'), {limit}).some(f => f.key === 'limit'))
  assert.ok(invalidFields(fields('anilist'), {formats:[]}).some(f => f.key === 'formats'))
  assert.equal(invalidFields(fields('anilist'), {}).length,0)
  assert.ok(invalidFields(fields('douban'), {chart:'custom', url:'javascript:alert(1)'}).some(f=>f.key==='url'))
  assert.equal(invalidFields(fields('douban'), {chart:'custom',url:'https://example.com/rss'}).length,0)
})
test('热门媒体风格随电影剧集切换，不能混用类型选项', () => {
  const fs=fields('popular'), genre=fs.find(f=>f.key==='genres')
  assert.ok(fieldOptions(genre,{category:'movie'}).some(o=>o.value==='28'))
  assert.ok(!fieldOptions(genre,{category:'tv'}).some(o=>o.value==='28'))
  assert.ok(invalidFields(fs,{category:'tv',genres:['28']}).length)
})
test('规则摘要使用选项标签，包含独立条数与过滤阈值', () => {
  const text=ruleSummary(fields('popular'),{category:'tv',genres:['16'],limit:30,min_rating:8})
  assert.match(text,/剧集/);assert.match(text,/动画/);assert.match(text,/30/);assert.match(text,/8/)
})
test('腾讯采用官方分组，网易云提供分类，Spotify 保留两种全球榜', () => {
  const charts=id=>fields(id).find(f=>f.key==='chart').options
  assert.deepEqual(new Set(charts('qqmusic').map(o=>o.group)),new Set(['巅峰榜','地区榜','特色榜','全球榜']))
  assert.equal(charts('netease').length,65)
  assert.ok(charts('netease').every(o=>o.group))
  assert.equal(charts('spotify').length,2)
})

import * as Vue from 'vue'
import * as RuleUtils from '../src/utils/rules.js'
function editor(id, initial) {
  const source=fs.readFileSync(new URL('../src/components/RuleCards.vue',import.meta.url),'utf8')
  const script=source.match(/<script setup>([\s\S]*?)<\/script>/)[1].replace(/^import .*$/mg,'')
  const field=specs.find(s=>s.provider_id===id).options_schema[0]
  const props=Vue.reactive({field,modelValue:JSON.parse(JSON.stringify(initial ?? field.default))})
  const events=[]
  const env={computed:Vue.computed,ref:Vue.ref,watch:Vue.watch,...RuleUtils,getCurrentInstance:()=>null,defineProps:()=>props,defineEmits:()=>((name,value)=>{events.push([name,value]);props.modelValue=value})}
  const scope=Vue.effectScope()
  const result=scope.run(()=>Function(...Object.keys(env),`${script};return {edit,save,toggle,remove,draft,open,error,updateField,rows,openManager,applyRules,managerOpen,workingRows,managerError,search,filteredRows}`)(...Object.values(env)))
  result.openManager()
  return {...result,props,events,dispose:()=>scope.stop()}
}
test('编辑弹窗草稿不污染卡片，保存后保留其它规则并可重新载入',()=>{
  const e=editor('anilist')
  try {
    e.edit(0);e.draft.value.name='Changed';e.draft.value.limit=35
    assert.equal(e.props.modelValue[0].name,'正在流行')
    e.save();e.applyRules();assert.equal(e.props.modelValue[0].name,'Changed');assert.equal(e.props.modelValue[0].limit,35)
    assert.equal(e.props.modelValue[1].name,'本季新番')
    e.openManager();e.edit(0);assert.equal(e.draft.value.limit,35)
    assert.equal(e.events.length,1)
  } finally {e.dispose()}
})
test('新增规则重复时保持弹窗并提示，非法数字也不能提交',()=>{
  const e=editor('anilist')
  try {
    e.edit(-1);e.save();assert.match(e.error.value,/相同规则/);assert.equal(e.open.value,true)
    e.draft.value.limit=-1;e.save();assert.match(e.error.value,/检查/);assert.equal(e.events.length,0)
  } finally {e.dispose()}
})
test('规则启停保留设置，逐个移除后显式保存为空数组',()=>{
  const e=editor('anilist')
  try {
    e.toggle(0,false);e.applyRules();assert.equal(e.props.modelValue[0].on,false)
    assert.equal(e.props.modelValue[0].sort,'TRENDING_DESC')
    e.openManager();e.remove(0);e.remove(0);e.applyRules();assert.deepEqual([...e.props.modelValue],[])
  } finally {e.dispose()}
})
test('切换热门媒体类型会清除旧类型的风格，预设取消不添加卡片',()=>{
  const e=editor('popular')
  try {
    e.edit(-1,{category:'movie',genres:['28']})
    e.updateField(fields('popular').find(f=>f.key==='category'),'tv')
    assert.deepEqual([...e.draft.value.genres],[])
    e.open.value=false;assert.equal(e.events.length,0);assert.equal(e.rows.value.length,2)
  } finally {e.dispose()}
})

test('普通 HTTP 缺少 crypto 或 randomUUID 时仍能生成不同的规则 ID',()=>{
  const values=Array.from({length:200},()=>RuleUtils.createRuleId({}))
  assert.equal(new Set(values).size,values.length)
  assert.ok(values.every(id=>id.length<=80))
  assert.ok(RuleUtils.createRuleId({randomUUID(){throw Error('blocked')}}))
  assert.ok(RuleUtils.createRuleId({getRandomValues(bytes){return bytes.fill(1)}}))
})
test('规则管理弹窗应用前不写回来源，取消后重新打开恢复保存的规则',()=>{
  const e=editor('spotify')
  try {
    e.edit(-1);e.draft.value.limit=21;e.save()
    assert.equal(e.rows.value.length,2);assert.equal(e.props.modelValue.length,1)
    e.managerOpen.value=false;e.openManager()
    assert.equal(e.rows.value.length,1);assert.equal(e.events.length,0)
    e.edit(-1);e.draft.value.limit=21;e.save();e.applyRules()
    assert.equal(e.events.length,1);assert.equal(e.props.modelValue.length,2)
    assert.ok(e.props.modelValue[1].id)
    e.openManager();assert.equal(e.rows.value[1].limit,21)
  } finally {e.dispose()}
})
test('外部配置在规则管理期间变化时，不覆盖新值',()=>{
  const e=editor('spotify')
  try {
    e.edit(-1);e.draft.value.limit=21;e.save()
    e.props.modelValue=[];e.applyRules()
    assert.match(e.managerError.value,/变更/);assert.equal(e.events.length,0)
    assert.equal(e.props.modelValue.length,0)
  } finally {e.dispose()}
})
test('全部十源只提供统一规则入口，苹果猫眼奈飞条件独立选择',()=>{
  assert.equal(specs.length,10)
  for(const spec of specs){
    assert.equal(spec.options_schema[0].kind,'rule-list')
    assert.ok(spec.options_schema.every(f=>f.kind!=='region-media-map'))
  }
  assert.equal(invalidFields(fields('applemusic'),{country:'jp',chart:'itunes-albums',limit:15}).length,0)
  assert.equal(invalidFields(fields('maoyan'),{chart:'web-heat',platform:'tx',media:'variety',limit:10}).length,0)
  assert.equal(invalidFields(fields('netflix'),{dataset:'country',country:'JP',categories:['TV']}).length,0)
  assert.ok(invalidFields(fields('netflix'),{dataset:'country',country:'JP',categories:['TV (English)']}).length)
})

test('搜索规则后编辑和移除仍作用于原规则，应用前不改来源', () => {
  const e=editor('anilist')
  try {
    e.search.value='本季'
    assert.equal(e.filteredRows.value.length,1)
    assert.equal(e.filteredRows.value[0].index,1)
    e.edit(e.filteredRows.value[0].index);e.draft.value.limit=35;e.save()
    assert.equal(e.rows.value[0].limit,undefined)
    assert.equal(e.rows.value[1].limit,35)
    e.remove(e.filteredRows.value[0].index)
    assert.equal(e.rows.value.length,1)
    assert.equal(e.props.modelValue.length,2)
    e.applyRules()
    assert.equal(e.props.modelValue[0].name,'正在流行')
  } finally {e.dispose()}
})
