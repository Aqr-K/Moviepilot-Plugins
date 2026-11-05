import assert from 'node:assert/strict'
import fs from 'node:fs'
import { test } from 'node:test'
import { combineImportedRules, inspectRuleShare, MAX_RULE_SHARE_BYTES, serializeRuleShare } from '../src/utils/ruleTransfer.js'
import { ruleValues } from '../src/utils/rules.js'
const specs=JSON.parse(fs.readFileSync(new URL('../src/dev/providerSpecs.json',import.meta.url)))
const version='3.4.0'
function source(id='applemusic'){
  const spec=specs.find(s=>s.provider_id===id),field=spec.options_schema[0]
  return {providerId:id,providerName:spec.provider_name,fields:field.fields,rules:field.default,pluginVersion:version}
}
const exported = id => JSON.parse(serializeRuleShare(source(id)))
const inspect=(payload,id='applemusic',extra={})=>inspectRuleShare(JSON.stringify(payload),{...source(id),...extra})
const errorCode=code=>error=>error.code===code

test('全部来源分享往返保留配置与启停，标记来源、版本和格式，不包含运行配置',()=>{
  for(const spec of specs){
    const settings=source(spec.provider_id)
    const text=serializeRuleShare(settings),payload=JSON.parse(text)
    assert.equal(payload.pluginId,'AutomaticSubscriptionAssistant')
    assert.equal(payload.pluginVersion,version)
    assert.equal(payload.formatVersion,1)
    assert.equal(payload.provider.id,spec.provider_id)
    assert.ok(payload.createdAt)
    assert.equal(payload.rules[0].id,undefined)
    assert.equal(payload.notify,undefined);assert.equal(payload.proxy,undefined);assert.equal(payload.cron,undefined)
    const imported=inspectRuleShare(text,settings)
    assert.deepEqual(imported.rules.map(r=>ruleValues(settings.fields,r)),settings.rules.map(r=>ruleValues(settings.fields,r)))
    assert.ok(imported.rules.every(r=>r.id))
    assert.equal(imported.warnings.length,0)
  }
})
test('异源、未知格式、未来格式版本、缺失插件版本和非法时间拒绝导入',()=>{
  assert.throws(()=>inspect(exported('spotify')),errorCode('wrongSource'))
  for(const [key,value,code] of [['format','other','invalidFormat'],['pluginId','other','invalidFormat'],['formatVersion',2,'formatVersion'],['pluginVersion',null,'versionMissing'],['createdAt','invalid','invalidFormat']]){
    const p=exported();p[key]=value;assert.throws(()=>inspect(p),errorCode(code))
  }
})
test('同源旧插件版本可复用，有明确版本校对提示，导入重建 ID',()=>{
  const p=exported();p.pluginVersion='3.3.0';p.rules[0].id='external-id';p.rules[0].on=false
  const result=inspect(p)
  assert.equal(result.rules[0].on,false)
  assert.notEqual(result.rules[0].id,'external-id')
  assert.ok(result.warnings.some(w=>w.code==='versionDifferent'&&w.details.source==='3.3.0'))
})
test('旧字段移除、类型或默认值变化拒绝静默忽略；新增可选字段补值并提示',()=>{
  const p=exported();p.rules[0].retiredCountry='jp'
  assert.throws(()=>inspect(p),errorCode('unknownFields'))
  for(const kind of ['kind','default','visibleWhen']){
    const p=exported(),field=p.schema.find(f=>f.key==='country')
    field[kind]=kind==='kind'?'number':kind==='default'?'jp':{chart:['itunes-albums']}
    assert.throws(()=>inspect(p),errorCode('changedField'))
  }
  const settings=source(),extra={key:'minimumYear',label:'Year',kind:'number',default:0,minimum:0,maximum:2200}
  const upgraded=inspect(exported(), 'applemusic',{fields:[...settings.fields,extra]})
  assert.equal(upgraded.rules[0].minimumYear,0)
  assert.ok(upgraded.warnings.some(w=>w.code==='schemaDifferent'))
  assert.ok(upgraded.warnings.some(w=>w.code==='defaultsAdded'))
  assert.throws(()=>inspect(exported(),'applemusic',{fields:[...settings.fields,{...extra,required:true}]}),errorCode('missingFields'))
})
test('值与当前选项、范围、条件字段同步校验，保留原规则不被修改',()=>{
  for(const [field,value] of [['country','xx'],['chart','invalid'],['limit',0],['limit',101],['limit',true],['on','false'],['name','x'.repeat(81)],['limit',null]]){
    const p=exported();p.rules[0][field]=value
    assert.throws(()=>inspect(p),errorCode('invalidRule'))
  }
  const p=exported('netflix');p.rules[0].dataset='country';p.rules[0].country='JP'
  assert.throws(()=>inspect(p,'netflix'),errorCode('invalidRule'))
  const valid=exported();const saved=JSON.stringify(valid);inspect(valid)
  assert.equal(JSON.stringify(valid),saved)
})
test('追加跳过语义重复，替换仅保留导入规则，超过总数上限原配置不变',()=>{
  const settings=source(),incoming=inspect(exported()).rules
  const current=[{...incoming[0],name:'renamed',id:'existing'}]
  const merged=combineImportedRules(settings.fields,current,incoming)
  assert.equal(merged.added,0);assert.equal(merged.skipped,1);assert.equal(merged.rules[0].id,'existing')
  const second=[{...incoming[0],country:'jp',id:'existing'}]
  const added=combineImportedRules(settings.fields,current,second)
  assert.equal(added.rules.length,2);assert.notEqual(added.rules[1].id,'existing')
  const replaced=combineImportedRules(settings.fields,current,second,'replace')
  assert.equal(replaced.rules.length,1);assert.equal(replaced.rules[0].country,'jp')
  const hundred=Array.from({length:100},(_,i)=>({...incoming[0],country:'us',limit:i+1,id:`id-${i}`}))
  assert.throws(()=>combineImportedRules(settings.fields,hundred,[{...incoming[0],country:'jp'}]),errorCode('ruleCount'))
  assert.equal(hundred.length,100);assert.equal(current.length,1)
})
test('拒绝畸形、超大与重复规则，接受带 BOM 的 JSON',()=>{
  assert.throws(()=>inspectRuleShare('broken',source()),errorCode('invalidJson'))
  assert.throws(()=>inspectRuleShare('x'.repeat(MAX_RULE_SHARE_BYTES+1),source()),errorCode('tooLarge'))
  const p=exported();p.rules.push({...p.rules[0],name:'different name'})
  assert.throws(()=>inspect(p),errorCode('duplicateRules'))
  const empty=exported();empty.rules=[]
  assert.throws(()=>inspect(empty),errorCode('ruleCount'))
  assert.throws(()=>serializeRuleShare({...source(),providerId:''}),errorCode('sourceMissing'))
  assert.throws(()=>serializeRuleShare({...source(),pluginVersion:''}),errorCode('versionMissing'))
  assert.equal(inspectRuleShare('\uFEFF'+JSON.stringify(exported()),source()).rules.length,1)
})

import * as Vue from 'vue'
import * as Transfer from '../src/utils/ruleTransfer.js'
function dialog(mode='import'){
  const sourceText=fs.readFileSync(new URL('../src/components/RuleTransferDialog.vue',import.meta.url),'utf8')
  const script=sourceText.match(/<script setup>([\s\S]*?)<\/script>/)[1].replace(/^import .*$/mg,'')
  const input=source(),props=Vue.reactive({mode,providerId:input.providerId,providerName:input.providerName,fields:input.fields,rules:input.rules})
  const events=[],cleanup=[]
  const env={computed:Vue.computed,ref:Vue.ref,watch:Vue.watch,nextTick:Vue.nextTick,getCurrentInstance:()=>null,onBeforeUnmount:fn=>cleanup.push(fn),defineProps:()=>props,defineEmits:()=>((...args)=>events.push(args)),...Transfer,PLUGIN_VERSION:version,serializeRuleShare:value=>serializeRuleShare({...value,pluginVersion:version}),inspectRuleShare:(text,value)=>inspectRuleShare(text,{...value,pluginVersion:version})}
  const scope=Vue.effectScope()
  const result=scope.run(()=>Function(...Object.keys(env),`${script};return {text,importMode,preview,combined,error,notice,reading,readFile,apply,inspect}`)(...Object.values(env)))
  return {...result,props,events,dispose:()=>{cleanup.forEach(fn=>fn());scope.stop()}}
}
test('分享弹窗输出真实来源，导入追加/替换预览并只提交规则草稿',async()=>{
  const share=dialog('share'),importer=dialog()
  try {
    assert.equal(JSON.parse(share.text.value).provider.id,'applemusic')
    importer.text.value=share.text.value;await Vue.nextTick()
    assert.equal(importer.combined.value.skipped,1)
    importer.importMode.value='replace';await Vue.nextTick()
    assert.equal(importer.combined.value.rules.length,1)
    importer.apply()
    assert.deepEqual(importer.events.map(([event])=>event),['import','close'])
    assert.equal(importer.props.rules.length,1)
    const incoming=JSON.parse(share.text.value);incoming.provider.id='spotify'
    importer.text.value=JSON.stringify(incoming);await Vue.nextTick()
    assert.match(importer.error.value,/spotify/);assert.equal(importer.combined.value,null)
  }finally{share.dispose();importer.dispose()}
})
test('导入文件在关闭、切换来源及卸载后返回，不再写入文本或草稿',async()=>{
  for(const action of ['close','source','unmount']){
    const d=dialog();let resolve
    const pending=new Promise(done=>{resolve=done})
    const event={target:{files:[{size:10,text:()=>pending}],value:'selected'}}
    const reading=d.readFile(event)
    assert.equal(event.target.value,'');assert.equal(d.reading.value,true)
    if(action==='close')d.props.mode=''
    else if(action==='source')d.props.providerId='spotify'
    else d.dispose()
    await Vue.nextTick();resolve(serializeRuleShare(source()));await reading
    assert.equal(d.text.value,'');assert.equal(d.events.length,0)
    if(action!=='unmount')d.dispose()
  }
})
test('过大的文件不能沿用之前预览，导入按钮无可用结果',async()=>{
  const d=dialog()
  try{
    d.text.value=serializeRuleShare(source());await Vue.nextTick()
    assert.ok(d.combined.value)
    await d.readFile({target:{files:[{size:MAX_RULE_SHARE_BYTES+1}],value:'large'}})
    await Vue.nextTick()
    assert.equal(d.text.value,'');assert.equal(d.combined.value,null)
    assert.match(d.error.value,/1 MiB/)
  }finally{d.dispose()}
})
