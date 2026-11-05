<template>
  <v-dialog :model-value="!!mode" max-width="520" scrollable @update:model-value="!$event && emit('close')">
    <v-card class="asa-transfer">
      <v-card-title class="asa-transfer__title"><v-icon :icon="sharing ? 'mdi-share' : 'mdi-import'" size="20" />{{ sharing ? t('share') : t('import') }}</v-card-title>
      <v-card-text class="asa-transfer__body">
        <p class="asa-transfer__hint">{{ sharing ? t('shareHint') : t('importHint') }}</p>
        <div class="asa-transfer__meta"><span>{{ providerName || providerId }} <code>{{ providerId }}</code></span><span>{{ t('current') }} {{ PLUGIN_VERSION }}</span></div>
        <template v-if="!sharing">
          <input ref="fileInput" class="asa-transfer__file" type="file" accept=".json,application/json" @change="readFile" />
          <v-btn variant="outlined" prepend-icon="mdi-file-upload-outline" :loading="reading" @click="fileInput?.click()">{{ t('file') }}</v-btn>
        </template>
        <v-textarea v-model="text" :readonly="sharing || reading" :label="sharing ? t('shareText') : t('importText')" :aria-label="sharing ? t('shareText') : t('importText')" rows="7" density="compact" variant="outlined" hide-details spellcheck="false" />
        <v-select v-if="!sharing" v-model="importMode" :items="[{title:t('append'),value:'append'},{title:t('replace'),value:'replace'}]" :label="t('importMode')" density="compact" variant="outlined" hide-details />
        <template v-if="preview">
          <div class="asa-transfer__preview">
            <strong>{{ t('preview') }}</strong>
            <span>{{ t('generated') }} {{ preview.pluginVersion }} · {{ preview.createdAt }}</span>
            <span>{{ t('summary', {count:preview.rules.length, added:combined?.added ?? 0, skipped:combined?.skipped ?? 0}) }}</span>
            <details class="asa-transfer__rules">
              <summary>{{ t('rulesPreview') }}</summary>
              <ul><li v-for="(rule,index) in preview.rules" :key="index"><strong>{{ rule.name }}</strong><p>{{ ruleSummary(fields, rule) }}</p></li></ul>
            </details>
          </div>
          <v-alert v-for="(warning,index) in preview.warnings" :key="index" type="warning" density="compact" variant="tonal">{{ message(warning) }}</v-alert>
        </template>
        <v-alert v-if="error" type="error" density="compact" variant="tonal">{{ error }}</v-alert>
        <v-alert v-if="notice" type="success" density="compact" variant="tonal">{{ notice }}</v-alert>
      </v-card-text>
      <v-card-actions>
        <template v-if="sharing">
          <v-btn variant="text" prepend-icon="mdi-download" :disabled="!text" @click="download">{{ t('download') }}</v-btn>
          <v-spacer /><v-btn variant="text" @click="emit('close')">{{ t('close') }}</v-btn><v-btn variant="flat" color="primary" :disabled="!text" @click="copy">{{ t('copy') }}</v-btn>
        </template>
        <template v-else>
          <v-spacer /><v-btn variant="text" @click="emit('close')">{{ t('cancel') }}</v-btn><v-btn color="primary" variant="flat" :disabled="!combined || !!error || reading" prepend-icon="mdi-import" @click="apply">{{ t('import') }}</v-btn>
        </template>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>
<script setup>
import { computed, getCurrentInstance, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { ruleSummary } from '../utils/rules.js'
import { combineImportedRules, inspectRuleShare, MAX_RULE_SHARE_BYTES, PLUGIN_VERSION, serializeRuleShare } from '../utils/ruleTransfer.js'
const props = defineProps({ mode:{type:String,default:''}, providerId:{type:String,required:true}, providerName:{type:String,default:''}, fields:{type:Array,required:true}, rules:{type:Array,required:true} })
const emit = defineEmits(['close','import'])
const text=ref(''), importMode=ref('append'), preview=ref(null), combined=ref(null), error=ref(''), notice=ref(''), reading=ref(false), fileInput=ref(null)
const sharing=computed(()=>props.mode==='share')
const inst=getCurrentInstance()
const locale=computed(()=>{
  const raw=inst?.appContext?.config?.globalProperties?.$i18n?.locale
  const lang=String(raw?.value ?? raw ?? '').toLowerCase()
  return lang.startsWith('en')?'en-US':/tw|hant|hk/.test(lang)?'zh-TW':'zh-CN'
})
const MSG={
  'zh-CN':{
    rulesPreview:'查看待导入规则',import:'导入',share:'分享',current:'当前插件版本',generated:'生成插件版本',file:'选择 JSON 文件',shareText:'规则分享内容',importText:'粘贴规则分享内容',importMode:'导入方式',append:'追加，跳过相同规则',replace:'替换当前规则',preview:'导入校对',summary:'共 {count} 条，新增 {added} 条，跳过重复 {skipped} 条',download:'下载',copy:'复制',close:'关闭',cancel:'取消',copied:'已复制',copyFailed:'复制失败，请手动复制或下载 JSON。',fileFailed:'无法读取文件，请重新选择。',
    shareHint:'分享当前来源的规则，包含未应用的规则草稿；不包含来源通知、代理或调度设置。',importHint:'仅能导入当前来源。导入后仍需在规则管理中应用，再保存插件配置。旧版本会按当前字段校对。',
    sourceMissing:'来源标识缺失，请重新加载配置。',versionMissing:'插件版本信息缺失或无效。',ruleCount:'分享或导入需包含 1–100 条规则，合并后也不能超过 100 条。',tooLarge:'规则分享内容不能超过 1 MiB。',invalidJson:'JSON 内容无效，请检查文件或粘贴内容。',invalidFormat:'这不是有效的自动订阅助手规则分享。',formatVersion:'不支持分享格式版本 {version}，请使用匹配的插件版本。',wrongSource:'规则属于 {source}，只能导入该来源，当前为 {target}。',invalidRule:'第 {index} 条规则条件无效，请校对后重试。',unknownFields:'第 {index} 条含当前版本不支持的字段：{fields}。保留原内容，请校对后重试。',missingFields:'第 {index} 条缺少必填字段：{fields}。请校对后重试。',duplicateRules:'分享内容中存在相同规则，请先整理重复项。',changedField:'字段 {field} 的配置语义已变化，需要先校对原内容。',versionDifferent:'生成版本 {source} 与当前版本 {target} 不同；规则已按当前字段检查，请核对预览。',schemaDifferent:'生成时的字段定义与当前不同，已校验现有字段、选项及范围。',defaultsAdded:'第 {index} 条新增可选字段已补当前默认值：{fields}。',
  },
  'zh-TW':{
    rulesPreview:'檢視待匯入規則',import:'匯入',share:'分享',current:'目前外掛版本',generated:'產生外掛版本',file:'選擇 JSON 檔案',shareText:'規則分享內容',importText:'貼上規則分享內容',importMode:'匯入方式',append:'新增，略過相同規則',replace:'取代目前規則',preview:'匯入校對',summary:'共 {count} 條，新增 {added} 條，略過重複 {skipped} 條',download:'下載',copy:'複製',close:'關閉',cancel:'取消',copied:'已複製',copyFailed:'複製失敗，請手動複製或下載 JSON。',fileFailed:'無法讀取檔案，請重新選擇。',shareHint:'分享目前來源的規則，包含未套用的草稿；不包含通知、代理或排程設定。',importHint:'只能匯入目前來源。匯入後需套用規則，再儲存外掛設定。舊版本會依目前欄位校對。',sourceMissing:'來源標識缺失，請重新載入。',versionMissing:'外掛版本資訊缺失或無效。',ruleCount:'分享或匯入需包含 1–100 條規則，合併後亦不得超過 100 條。',tooLarge:'分享內容不得超過 1 MiB。',invalidJson:'JSON 內容無效。',invalidFormat:'這不是有效的自動訂閱助手規則分享。',formatVersion:'不支援分享格式版本 {version}。',wrongSource:'規則屬於 {source}，只能匯入該來源，目前為 {target}。',invalidRule:'第 {index} 條規則條件無效。',unknownFields:'第 {index} 條包含不支援欄位：{fields}。請校對原內容。',missingFields:'第 {index} 條缺少必填欄位：{fields}。',duplicateRules:'分享內容包含相同規則。',changedField:'欄位 {field} 的設定語義已改變，請先校對。',versionDifferent:'產生版本 {source} 與目前 {target} 不同；已依目前欄位檢查，請核對預覽。',schemaDifferent:'產生時欄位定義不同，已檢查目前欄位、選項與範圍。',defaultsAdded:'第 {index} 條可選欄位已補預設值：{fields}。',
  },
  'en-US':{
    rulesPreview:'Review imported rules',import:'Import',share:'Share',current:'Current plugin version',generated:'Generated with plugin',file:'Choose JSON file',shareText:'Shared rules',importText:'Paste shared rules',importMode:'Import mode',append:'Append, skip duplicates',replace:'Replace current rules',preview:'Import review',summary:'{count} rules; {added} added, {skipped} duplicates skipped',download:'Download',copy:'Copy',close:'Close',cancel:'Cancel',copied:'Copied',copyFailed:'Copy failed. Copy the text manually or download JSON.',fileFailed:'Unable to read file.',shareHint:'Share this source’s rules, including pending drafts. Notifications, proxy and schedules are excluded.',importHint:'Only this source is accepted. Apply the imported rules, then save plugin settings. Older rules are checked against current fields.',sourceMissing:'Missing source ID. Reload settings.',versionMissing:'Missing or invalid plugin version.',ruleCount:'Share/import requires 1–100 rules, including the merged result.',tooLarge:'Shared rules exceed 1 MiB.',invalidJson:'Invalid JSON.',invalidFormat:'Invalid Auto Subscribe rule share.',formatVersion:'Unsupported share format version {version}.',wrongSource:'Rules belong to {source}; they cannot be imported into {target}.',invalidRule:'Invalid conditions in rule {index}.',unknownFields:'Rule {index} uses unsupported fields: {fields}. Review the original data.',missingFields:'Rule {index} is missing required fields: {fields}.',duplicateRules:'Shared rules contain duplicates.',changedField:'Field {field} has changed meaning. Review the original data first.',versionDifferent:'Generated with {source}, current version {target}. Rules passed current field checks; review before importing.',schemaDifferent:'The field definitions differ. Current fields, options and bounds have been checked.',defaultsAdded:'Rule {index} received defaults for optional fields: {fields}.',
  },
}
function t(key,values={}) {return Object.entries(values).reduce((s,[k,v])=>s.replaceAll(`{${k}}`,String(v)),MSG[locale.value][key]||key)}
function message(value) {return t(value.code,value.details)}
function showError(value) {error.value=value?.code?message(value):t('invalidFormat')}
let readSequence=0, alive=true
function inspect() {
  if(sharing.value || !props.mode)return
  error.value='';notice.value='';preview.value=null;combined.value=null
  if(!text.value.trim())return
  try {
    preview.value=inspectRuleShare(text.value,{providerId:props.providerId,fields:props.fields})
    combined.value=combineImportedRules(props.fields,props.rules,preview.value.rules,importMode.value)
  } catch(exc){showError(exc)}
}
watch(()=>[props.mode,props.providerId],()=>{
  readSequence+=1;reading.value=false;text.value='';preview.value=null;combined.value=null;error.value='';notice.value='';importMode.value='append'
  if(props.mode==='share'){
    try{text.value=serializeRuleShare({providerId:props.providerId,providerName:props.providerName,fields:props.fields,rules:props.rules})}catch(exc){showError(exc)}
  }
},{immediate:true})
watch([text,importMode,()=>props.rules,()=>props.fields],inspect,{deep:true})
async function readFile(event) {
  const file=event.target.files?.[0];event.target.value=''
  if(!file)return
  const sequence=++readSequence,source=props.providerId
  reading.value=true;error.value=''
  try {
    if(file.size>MAX_RULE_SHARE_BYTES){text.value='';throw {code:'tooLarge'}}
    const value=await file.text()
    if(alive && sequence===readSequence && source===props.providerId && props.mode==='import')text.value=value
  }catch(exc){
    if(alive && sequence===readSequence){
      text.value='';preview.value=null;combined.value=null
      await nextTick()
      if(alive && sequence===readSequence)error.value=exc?.code?t(exc.code):t('fileFailed')
    }
  }
  finally{if(alive && sequence===readSequence)reading.value=false}
}
function apply(){
  inspect()
  if(!combined.value||error.value)return
  emit('import',combined.value.rules);emit('close')
}
async function copy(){
  notice.value='';error.value=''
  const sequence=readSequence
  try{
    let success=false
    try{if(globalThis.navigator?.clipboard?.writeText){await navigator.clipboard.writeText(text.value);success=true}}catch{/* 普通 HTTP 使用下方传统复制。 */}
    if(!success){
      const area=document.createElement('textarea');area.value=text.value;area.style.position='fixed';area.style.opacity='0';document.body.append(area)
      try{area.select();success=document.execCommand('copy')}finally{area.remove()}
    }
    if(!success)throw Error('copy')
    if(alive&&sequence===readSequence)notice.value=t('copied')
  }catch{if(alive&&sequence===readSequence)error.value=t('copyFailed')}
}
function download(){
  const url=URL.createObjectURL(new Blob([text.value],{type:'application/json;charset=utf-8'}))
  const link=document.createElement('a');link.href=url;link.download=`asa-${props.providerId}-rules-v${PLUGIN_VERSION}.json`;document.body.append(link);link.click();link.remove()
  setTimeout(()=>URL.revokeObjectURL(url),1000)
}
onBeforeUnmount(()=>{alive=false;readSequence+=1})
</script>
<style scoped>
.asa-transfer {border-radius:var(--app-surface-radius,12px) !important;}
.asa-transfer__title {display:flex;align-items:center;gap:8px;font-size:1rem;font-weight:700;}
.asa-transfer__body {display:flex;flex-direction:column;gap:12px;padding-block:12px 6px;}
.asa-transfer__hint {margin:0;color:rgba(var(--v-theme-on-surface),.6);font-size:.78rem;line-height:1.5;}
.asa-transfer__meta,.asa-transfer__preview {display:flex;flex-direction:column;gap:5px;font-size:.78rem;overflow-wrap:anywhere;}
.asa-transfer__meta {color:rgba(var(--v-theme-on-surface),.65);}
.asa-transfer__preview {padding:10px 12px;border:1px solid rgba(var(--v-theme-on-surface),.12);border-radius:var(--app-control-radius,8px);background:rgba(var(--v-theme-on-surface),.03);}
.asa-transfer__rules summary {cursor:pointer;color:rgb(var(--v-theme-primary));}
.asa-transfer__rules ul {list-style:none;padding:0;margin:8px 0 0;display:flex;flex-direction:column;gap:8px;}
.asa-transfer__rules li {padding-block:6px;border-block-start:1px solid rgba(var(--v-theme-on-surface),.1);}
.asa-transfer__rules p {margin:3px 0 0;color:rgba(var(--v-theme-on-surface),.6);line-height:1.5;}
.asa-transfer__file {display:none;}
.asa-transfer :deep(textarea) {font-family:monospace;font-size:.75rem;overflow-wrap:anywhere;}
.asa-transfer :deep(.v-card-actions) {flex-wrap:wrap;}
</style>
