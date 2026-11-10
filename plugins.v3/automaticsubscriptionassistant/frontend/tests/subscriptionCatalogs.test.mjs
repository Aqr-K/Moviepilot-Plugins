import assert from 'node:assert/strict'
import { test } from 'node:test'
import { loadSubscriptionCatalogs, subscriptionDirectories, subscriptionPresets } from '../src/utils/subscriptionCatalogs.js'

test('按主程序接口读取真实选项，站点过滤停用项、规则组关闭 usage 查询、目录按路径去重', async () => {
  const calls=[]
  const api={get:async (url,options)=>{
    calls.push([url,options])
    const data={
      'site/rss':[{id:1,name:'Active',is_active:true},{id:2,name:'Disabled',is_active:false}],
      'download/clients':[{name:'qBittorrent'}],
      'rule/groups':{rule_groups:[{name:'HD'}]},
      'download/paths':[{name:'Films',download_path:'/downloads'},{name:'TV',download_path:'/downloads'}],
    }
    assert.ok(Object.hasOwn(data,url),url)
    return {success:true,data:data[url]}
  }}
  const result=await loadSubscriptionCatalogs(api,null)
  assert.deepEqual(result.sites.items,[{title:'Active',value:1}])
  assert.deepEqual(result.downloaders.items,[{title:'qBittorrent',value:'qBittorrent'}])
  assert.deepEqual(result.groups.items,[{title:'HD',value:'HD'}])
  assert.deepEqual(result.directories.items,[{title:'Films / TV (/downloads)',value:'/downloads'}])
  assert.ok(Object.values(result).every(group=>!group.failed))
  assert.deepEqual(calls.find(([url])=>url==='rule/groups')[1],{feedback:'silent',params:{include_usage:false}})
})

test('SDK 获取失败或格式无效时回退公开接口，单项失败不阻止其它列表与已有值',async()=>{
  const sdk={catalogs:{ruleGroups:()=>{throw Error('Unavailable')},downloadDirectories:async()=>({success:true,data:{wrong:[]}})}}
  const api={get:async url=>{
    if(url==='site/rss')throw Error('Forbidden')
    if(url==='rule/groups')return {rule_groups:[{name:'Current'}]}
    if(url==='download/paths')return [{name:'Configured',download_path:'/real'}]
    return []
  }}
  const result=await loadSubscriptionCatalogs(api,sdk)
  assert.equal(result.sites.failed,true)
  assert.deepEqual(result.groups.items,[{title:'Current',value:'Current'}])
  assert.deepEqual(result.directories.items,[{title:'Configured (/real)',value:'/real'}])
  assert.equal(result.downloaders.failed,false)
})

test('SDK 目录优先使用原生下载路径，保存值不包含别名标签或包装对象',()=>{
  const result=subscriptionDirectories([
    {name:'Movie',downloadPath:'/download',path:'/save'},
    {name:'TV',download_path:'/download'},
    {name:'Movie',downloadPath:'/download'},
    {name:'/other',path:'/other'},
    {name:'No path'},
  ])
  assert.deepEqual(result,[{title:'Movie / TV (/download)',value:'/download'},{title:'/other',value:'/other'}])
})

test('影视和音乐预设保留主程序表达式及标准音频单位，自定义设置不从接口猜测',()=>{
  const presets=subscriptionPresets(key=>key)
  assert.equal(presets.quality.find(v=>v.title==='WEB-DL').value,'WEB-?DL|WEB-?RIP')
  assert.equal(presets.resolution.find(v=>v.title==='4K').value,'4K|2160p|x2160')
  assert.equal(presets.effect.find(v=>v.title==='dolbyVision').value,'Dolby[\\s.]+Vision|DOVI|[\\s.]+DV[\\s.]+')
  assert.equal(presets.audio_quality.find(v=>v.title==='lossless').value,'hires|lossless')
  assert.equal(presets.audio_format.find(v=>v.title==='FLAC').value,'FLAC')
  assert.equal(presets.min_bitrate.find(v=>v.title==='320 kbps').value,320000)
  assert.equal(presets.min_sample_rate.find(v=>v.title==='44.1 kHz').value,44100)
})
