import assert from 'node:assert/strict'
import fs from 'node:fs'
import { test } from 'node:test'
import * as Vue from 'vue'
import * as Policy from '../src/utils/subscriptionPolicy.js'
import * as Catalogs from '../src/utils/subscriptionCatalogs.js'
import { inspectRuleShare, serializeRuleShare } from '../src/utils/ruleTransfer.js'

const policy = (configs = {}, enabled = true) => ({ enabled, configs })
const clone = value => JSON.parse(JSON.stringify(value))
const script = fs.readFileSync(new URL('../src/components/SubscriptionPolicy.vue', import.meta.url), 'utf8').match(/<script setup>([\s\S]*?)<\/script>/)[1].replace(/^import .*$/mg, '')
function editor(initial = null, api = {}, sdk = null) {
  const props = Vue.reactive({ modelValue: initial, providerId: 'douban', rule: {}, ruleLevel: false, api })
  const events = [], cleanup = []
  const env = { computed: Vue.computed, reactive: Vue.reactive, ref: Vue.ref, watch: Vue.watch, ...Policy, ...Catalogs, getCurrentInstance: () => null, inject: () => sdk,
    onBeforeUnmount: fn => cleanup.push(fn), defineProps: () => props,
    defineEmits: () => ((event, value) => { events.push([event, value]); props.modelValue = value }) }
  const scope = Vue.effectScope()
  const result = scope.run(() => Function(...Object.keys(env), `${script};return {toggle,openEditor,apply,resetForm,form,open,fields,basicFields,advancedFields,types,optionsError,error,policyError,loadOptions,siteOptions,ruleOptions,pathOptions}`)(...Object.values(env)))
  return { ...result, props, events, dispose: () => { cleanup.forEach(fn => fn()); scope.stop() } }
}
const settled = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); await Vue.nextTick() }
function deferred() { let resolve; const promise = new Promise(done => { resolve = done }); return { promise, resolve } }

test('订阅参数按媒体类型白名单校验，拒绝交互、身份、归属与非法值', () => {
  for (const value of [{enabled:null}, {enabled:'false'}, {configs:null}, []]) assert.throws(() => Policy.normalizeSubscriptionPolicy(value))
  for (const invalid of [{show_edit_dialog:true},{media_id:'1'},{username:'admin'},{season:2},{sites:['1']},{search_interval:0},{search_interval:8761},{best_version:'0'},{audio_format:'FLAC'}]) {
    assert.throws(() => Policy.normalizeSubscriptionPolicy(policy({'电影':invalid})))
  }
  assert.throws(() => Policy.normalizeSubscriptionPolicy(policy({'电视剧':{best_version_full:1}})))
  const value=policy({'电影':{best_version:0,sites:[1]},'音乐':{audio_format:'FLAC',min_bit_depth:24}})
  const clean=Policy.normalizeSubscriptionPolicy(value)
  assert.deepEqual(clean,value);clean.configs['电影'].sites.push(2);assert.deepEqual(value.configs['电影'].sites,[1])
})

test('独立弹窗取消不保存，应用按类型隔离，开关切换保留配置', async () => {
  const e=editor(policy({'电影':{quality:'4K'},'电视剧':{resolution:'1080p'}}))
  try {
    e.openEditor('电影');e.form.quality='draft';e.open.value=false;await Vue.nextTick()
    assert.equal(e.events.length,0)
    e.openEditor('电影');assert.equal(e.form.quality,'4K')
    e.form.quality='HD';e.form.sites=['1'];e.form.mode='normal';e.apply()
    assert.equal(e.props.modelValue.configs['电影'].quality,'HD')
    assert.equal(e.props.modelValue.configs['电影'].best_version,0)
    assert.deepEqual([...e.props.modelValue.configs['电影'].sites],[1])
    assert.equal(e.props.modelValue.configs['电视剧'].resolution,'1080p')
    e.toggle(false);assert.equal(e.props.modelValue.enabled,false)
    e.toggle(true);assert.equal(e.props.modelValue.configs['电影'].quality,'HD')
    e.openEditor('电影');e.resetForm();e.apply()
    assert.equal(e.props.modelValue.configs['电影'],undefined)
    assert.equal(e.props.modelValue.configs['电视剧'].resolution,'1080p')
  } finally {e.dispose()}
})

test('宿主缺少选项 API 或同步抛错时给出提示，手动值仍能保存', async () => {
  for (const api of [{},{get:()=>{throw Error('Unavailable')}}]) {
    const e=editor(null,api)
    try {
      e.openEditor('电影');await settled();assert.equal(e.optionsError.value,true)
      e.form.downloader='manual';e.form.sites=['12'];e.form.filter_groups=['HD'];e.apply()
      assert.equal(e.error.value,'');assert.equal(e.props.modelValue.configs['电影'].downloader,'manual')
      assert.deepEqual([...e.props.modelValue.configs['电影'].sites],[12])
    } finally {e.dispose()}
  }
})

test('宿主 SDK 仅用于读取选项，支持 envelope 与原始数组，迟到响应不覆盖新弹窗', async () => {
  const first=deferred();let requests=0
  const e=editor(null,{get:url=>url==='site/rss'? ++requests===1? first.promise : [{id:2,name:'Current'}] : [{name:'Downloader'}]},
    {catalogs:{ruleGroups:async()=>({success:true,data:[{name:'HD'}]}),downloadDirectories:async()=>[{name:'Storage',downloadPath:'/media'}]}})
  try {
    e.openEditor('电影');await settled()
    e.open.value=false;await Vue.nextTick();e.openEditor('电视剧');await settled()
    assert.deepEqual(clone(e.siteOptions.value),[{title:'Current',value:2}])
    assert.equal(e.optionsError.value,false)
    first.resolve([{id:1,name:'Old'}]);await settled()
    assert.deepEqual(clone(e.siteOptions.value),[{title:'Current',value:2}])
    assert.equal(e.pathOptions.value[0].value,'/media');assert.equal(e.ruleOptions.value[0].value,'HD')
  } finally {e.dispose()}
})

test('卸载后忽略选项响应，配置冲突或非法值不覆盖外部新配置', async () => {
  const late=deferred(),e=editor(null,{get:()=>late.promise})
  e.openEditor('电影');await settled();e.dispose();late.resolve([{id:1,name:'Late'}]);await settled()
  assert.equal(e.siteOptions.value.length,0)
  const f=editor(policy({'电影':{quality:'old'}}))
  try {
    f.openEditor('电影');f.props.modelValue=policy({'电影':{quality:'external'}});f.apply()
    assert.ok(f.error.value);assert.equal(f.events.length,0)
    f.openEditor('电影');f.form.search_interval=0;f.apply();assert.ok(f.error.value)
    assert.equal(f.props.modelValue.configs['电影'].quality,'external')
    f.props.modelValue={enabled:true,configs:{'电影':{show_edit_dialog:true}}}
    assert.ok(f.policyError.value)
  } finally {f.dispose()}
})

test('音乐表单隔离音质与影视设置，自动订阅不提供订阅时编辑选项', () => {
  const e=editor()
  try {
    e.props.providerId='spotify';assert.deepEqual(e.types.value,['音乐'])
    e.openEditor('音乐');assert.ok(e.fields.value.some(f=>f.key==='audio_format'))
    assert.ok(!e.fields.value.some(f=>['quality','show_edit_dialog','imdb'].includes(f.key)))
    e.form.audio_format='FLAC';e.form.min_bit_depth='24';e.apply()
    assert.deepEqual(clone(e.props.modelValue.configs['音乐']),{audio_format:'FLAC',min_bit_depth:24})
  } finally {e.dispose()}
})

test('分享与导入保留规则级订阅设置，旧规则无设置时继续使用来源兜底', () => {
  const specs=JSON.parse(fs.readFileSync(new URL('../src/dev/providerSpecs.json',import.meta.url)))
  const field=specs.find(s=>s.provider_id==='anilist').options_schema[0]
  const settings={providerId:'anilist',fields:field.fields,rules:clone(field.default),pluginVersion:'3.4.2'}
  settings.rules[0].subscription=policy({'电影':{quality:'4K'},'电视剧':{best_version:0}})
  const text=serializeRuleShare(settings)
  const imported=inspectRuleShare(text,settings)
  assert.deepEqual(imported.rules[0].subscription,settings.rules[0].subscription)
  assert.equal(imported.rules[1].subscription,undefined)
  const bad=JSON.parse(text);bad.rules[0].subscription.configs['电影'].show_edit_dialog=true
  assert.throws(()=>inspectRuleShare(JSON.stringify(bad),settings))
})
