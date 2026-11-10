<template>
  <div class="asa-subscription-policy" :class="{ 'asa-subscription-policy--rule': ruleLevel }">
    <div class="asa-subscription-policy__head">
      <div class="asa-subscription-policy__copy"><div class="asa-subscription-policy__label">{{ label }}</div><p>{{ ruleLevel ? t('ruleHint') : t('sourceHint') }}</p></div>
      <v-switch :model-value="policy.enabled" :disabled="!!policyError" :aria-label="label" density="compact" hide-details inset color="primary" @update:model-value="toggle" />
    </div>
    <v-alert v-if="policyError" type="warning" variant="tonal" density="compact">{{ policyError }}</v-alert>
    <div class="asa-subscription-policy__settings">
      <div class="asa-subscription-policy__copy"><div class="asa-subscription-policy__label">{{ t('configure') }}</div><p>{{ t('configureHint') }}</p></div>
      <div class="asa-subscription-policy__types">
        <v-btn v-for="type in types" :key="type" :disabled="!!policyError" variant="outlined" class="asa-subscription-policy__trigger" @click="openEditor(type)">
          <v-icon :icon="policy.configs[type] ? 'mdi-check-circle-outline' : 'mdi-tune-variant'" start />
          <span>{{ mediaLabel(type) }}</span><v-icon icon="mdi-chevron-right" end />
        </v-btn>
      </div>
    </div>
    <v-dialog v-model="open" max-width="640" scrollable>
      <v-card class="asa-subscription-policy__dialog">
        <v-card-title class="asa-subscription-policy__title"><v-icon icon="mdi-clipboard-list-outline" size="20" />{{ mediaLabel(mediaType) }} · {{ label }}</v-card-title>
        <v-card-text class="asa-subscription-policy__body">
          <p class="asa-subscription-policy__hint">{{ t('localHint') }}</p>
          <v-alert v-if="optionsError" type="warning" variant="tonal" density="compact" class="mb-3">
            {{ t('optionsUnavailable') }}
            <v-btn variant="text" size="small" prepend-icon="mdi-refresh" :loading="optionsLoading" @click="loadOptions">{{ t('retry') }}</v-btn>
          </v-alert>
          <v-alert v-if="error" type="error" variant="tonal" density="compact" class="mb-3">{{ error }}</v-alert>
          <FilterPanel class="asa-subscription-policy__fields" :state="form" :fields="basicFields" stacked />
          <v-expansion-panels v-model="advancedOpen" variant="accordion" class="asa-subscription-policy__advanced">
            <v-expansion-panel :title="t('advanced')"><v-expansion-panel-text>
              <FilterPanel class="asa-subscription-policy__fields" :state="form" :fields="advancedFields" stacked />
            </v-expansion-panel-text></v-expansion-panel>
          </v-expansion-panels>
        </v-card-text>
        <v-card-actions><v-btn variant="text" @click="resetForm">{{ t('reset') }}</v-btn><v-spacer /><v-btn variant="text" @click="open = false">{{ t('cancel') }}</v-btn><v-btn color="primary" variant="flat" @click="apply">{{ t('apply') }}</v-btn></v-card-actions>
      </v-card>
    </v-dialog>
  </div>
</template>
<script setup>
import { computed, getCurrentInstance, inject, onBeforeUnmount, reactive, ref, watch } from 'vue'
import FilterPanel from './FilterPanel.vue'
import { loadSubscriptionCatalogs, subscriptionPresets } from '../utils/subscriptionCatalogs.js'
import { normalizeSubscriptionPolicy, policyFields, subscriptionMediaTypes } from '../utils/subscriptionPolicy.js'
const props = defineProps({ modelValue: { default: null }, providerId: { type: String, required: true }, rule: { type: Object, default: () => ({}) }, ruleLevel: Boolean, api: { type: [Object, Function], default: () => ({}) } })
const emit = defineEmits(['update:modelValue'])
const sdk = inject('moviepilot:sdk', null)
const instance = getCurrentInstance()
const messages = {
  'zh-CN': { configure:'规则配置', configureHint:'分别配置各媒体类型，保存插件配置后生效。', advanced:'高级设置', retry:'重新获取', blurayOriginal:'蓝光原盘', dolbyVision:'杜比视界', dolbyAtmos:'杜比全景声', hires:'Hi-Res 高解析无损', lossless:'无损（含 Hi-Res）', lossy:'有损', losslessFormats:'全部无损格式', noOptions:'暂无可选项', source: '默认订阅规则', rule: '订阅规则', sourceHint: '为本来源新建订阅提供默认设置；未启用或未配置的媒体类型沿用主程序默认值。', ruleHint: '本条榜单规则命中时优先使用；未启用或未配置的媒体类型使用来源默认规则。', localHint: '只保存到当前插件配置，不修改主程序全局默认规则。应用后仍需保存插件配置。空值沿用主程序的默认行为。', optionsUnavailable: '主程序未提供部分选项接口或读取失败。已保留原值，可手动填写站点 ID、下载器、保存路径和规则组，或稍后重试。', movie:'电影',tv:'电视剧',music:'音乐', quality:'质量', resolution:'分辨率', effect:'特效', audio_quality:'音乐音质', audio_format:'音频格式', min_bitrate:'最低码率（bps）', min_bit_depth:'最低位深（bit）', min_sample_rate:'最低采样率（Hz）', include:'资源包含表达式', exclude:'资源排除表达式', sites:'订阅站点', downloader:'下载器名称', save_path:'保存路径', filter_groups:'过滤规则组', search_interval:'搜索间隔（小时，留空跟随系统）', mode:'订阅模式', inherit:'跟随主程序', normal:'普通订阅', best:'洗版订阅', whole:'全集洗版', search_imdbid:'使用 IMDb ID 搜索', reset:'清空此类型设置', cancel:'取消', apply:'应用', invalid:'请检查订阅规则设置' },
  'zh-TW': { configure:'規則設定', configureHint:'分別設定各媒體類型，儲存外掛設定後生效。', advanced:'進階設定', retry:'重新取得', blurayOriginal:'藍光原盤', dolbyVision:'杜比視界', dolbyAtmos:'杜比全景聲', hires:'Hi-Res 高解析無損', lossless:'無損（含 Hi-Res）', lossy:'有損', losslessFormats:'全部無損格式', noOptions:'暫無可選項', source:'預設訂閱規則',rule:'訂閱規則',sourceHint:'為此來源的新訂閱提供預設值，未設定的類型沿用主程式。',ruleHint:'優先使用此規則的設定；未啟用或未設定的類型回退來源預設值。',localHint:'僅儲存至外掛，不修改主程式預設規則。套用後仍需儲存外掛設定。',optionsUnavailable:'主程式未提供部分選項介面或讀取失敗。原值已保留，可手動填寫或稍後重試。',movie:'電影',tv:'劇集',music:'音樂',quality:'品質',resolution:'解析度',effect:'特效',audio_quality:'音質',audio_format:'音訊格式',min_bitrate:'最低位元率（bps）',min_bit_depth:'最低位元深度',min_sample_rate:'最低取樣率（Hz）',include:'包含運算式',exclude:'排除運算式',sites:'訂閱站點（可輸入 ID）',downloader:'下載器名稱',save_path:'儲存路徑',filter_groups:'篩選規則組（可輸入名稱）',search_interval:'搜尋間隔（小時）',mode:'訂閱模式',inherit:'跟隨主程式',normal:'普通訂閱',best:'洗版訂閱',whole:'全集洗版',search_imdbid:'使用 IMDb ID 搜尋',reset:'清除此類型設定',cancel:'取消',apply:'套用',invalid:'請檢查訂閱設定'},
  'en-US': { configure:'Configure rules', configureHint:'Configure each media type, then save plugin settings.', advanced:'Advanced settings', retry:'Retry', blurayOriginal:'Blu-ray Original', dolbyVision:'Dolby Vision', dolbyAtmos:'Dolby Atmos', hires:'Hi-Res Lossless', lossless:'Lossless (including Hi-Res)', lossy:'Lossy', losslessFormats:'All lossless formats', noOptions:'No options available', source:'Default subscription rules',rule:'Subscription rules',sourceHint:'Defaults for new subscriptions from this source. Unconfigured types use host defaults.',ruleHint:'Override source defaults for this ranking rule. Disabled or unconfigured types use source defaults.',localHint:'Saved only in this plugin. Host defaults are unchanged. Save plugin settings after applying.',optionsUnavailable:'Some host option APIs are unavailable. Existing values are retained; enter values manually or retry later.',movie:'Movie',tv:'TV series',music:'Music',quality:'Quality',resolution:'Resolution',effect:'Effects',audio_quality:'Audio quality',audio_format:'Audio format',min_bitrate:'Minimum bitrate (bps)',min_bit_depth:'Minimum bit depth',min_sample_rate:'Minimum sample rate (Hz)',include:'Include expression',exclude:'Exclude expression',sites:'Sites (or enter IDs)',downloader:'Downloader name',save_path:'Save path',filter_groups:'Rule groups (or enter names)',search_interval:'Search interval (hours)',mode:'Subscription mode',inherit:'Host default',normal:'Normal',best:'Version upgrade',whole:'Whole-season upgrade',search_imdbid:'Search by IMDb ID',reset:'Clear type settings',cancel:'Cancel',apply:'Apply',invalid:'Check subscription settings'},
}
function t(key) { const raw=instance?.appContext?.config?.globalProperties?.$i18n?.locale;const lang=String(raw?.value ?? raw ?? '').toLowerCase();return messages[lang.startsWith('en')?'en-US':/tw|hant|hk/.test(lang)?'zh-TW':'zh-CN'][key] || key }
const label = computed(() => t(props.ruleLevel ? 'rule' : 'source'))
const normalized = computed(() => {
  try { return { value: normalizeSubscriptionPolicy(props.modelValue), error: '' } }
  catch (exc) { return { value: { enabled: false, configs: {} }, error: exc.message } }
})
const policy = computed(() => normalized.value.value)
const policyError = computed(() => normalized.value.error)
const types = computed(() => subscriptionMediaTypes(props.providerId, props.rule))
const mediaType = ref('电影'), open=ref(false), error=ref(''), optionsError=ref(false)
const optionsLoading=ref(false), advancedOpen=ref(null)
const form = reactive({})
const siteOptions=ref([]), downloaderOptions=ref([]), ruleOptions=ref([]), pathOptions=ref([])
let baseline='', sequence=0, disposed=false
const mediaLabel = type => t(type === '音乐' ? 'music' : type === '电视剧' ? 'tv' : 'movie')
function toggle(enabled) { emit('update:modelValue', { ...policy.value, enabled: !!enabled }) }
function loadForm(value={}) {
  Object.keys(form).forEach(key=>delete form[key])
  Object.assign(form, { ...value, sites:[...(value.sites || [])], filter_groups:[...(value.filter_groups || [])], mode:value.best_version==null?'inherit':value.best_version_full?'whole':value.best_version?'best':'normal', imdb:value.search_imdbid?'yes':'inherit' })
}
function openEditor(type) { mediaType.value=type;baseline=JSON.stringify(props.modelValue);loadForm(policy.value.configs[type] || {});error.value='';advancedOpen.value=null;open.value=true;loadOptions() }
function resetForm() { loadForm();error.value='' }
const presets = computed(() => subscriptionPresets(t))
function withCurrent(items, value) {
  const current=Array.isArray(value)?value:[value]
  return [...items,...current.filter(v=>v!=null && v!=='' && !items.some(item=>item.value===v)).map(v=>({title:String(v),value:v}))]
}
const fields = computed(() => {
  const field=(key,type='text',extra={})=>({key,label:t(key),type,...extra})
  const preset=key=>field(key,'combobox',{items:presets.value[key],noDataText:t('noOptions')})
  return [
    ...(mediaType.value==='音乐' ? ['audio_quality','audio_format','min_bitrate','min_bit_depth','min_sample_rate'] : ['quality','resolution','effect']).map(preset),
    field('mode','select',{clearable:false,items:[{title:t('inherit'),value:'inherit'},{title:t('normal'),value:'normal'},{title:t('best'),value:'best'},...(mediaType.value==='电视剧'?[{title:t('whole'),value:'whole'}]:[])]}),
    field('sites','combobox',{multi:true,wide:true,items:siteOptions.value,loading:optionsLoading.value}),
    field('downloader','combobox',{items:downloaderOptions.value,loading:optionsLoading.value}),
    field('save_path','combobox',{items:pathOptions.value,loading:optionsLoading.value}),
    field('include'),field('exclude'),
    field('filter_groups','combobox',{multi:true,wide:true,items:ruleOptions.value,loading:optionsLoading.value}),
    field('search_interval','number',{min:1,max:8760,step:1}),
    ...(mediaType.value!=='音乐'?[field('imdb','select',{clearable:false,items:[{title:t('inherit'),value:'inherit'},{title:t('search_imdbid'),value:'yes'}]})]:[]),
  ].map(f=>f.items?{...f,items:withCurrent(f.items,form[f.key])}:f)
})
const advancedKeys=['include','exclude','filter_groups','search_interval','imdb']
const basicFields=computed(()=>fields.value.filter(f=>!advancedKeys.includes(f.key)))
const advancedFields=computed(()=>fields.value.filter(f=>advancedKeys.includes(f.key)))
function apply() {
  try {
    if (baseline!==JSON.stringify(props.modelValue)) throw new Error('配置已变更，请重新打开弹窗')
    const values={}
    for (const key of policyFields(mediaType.value)) {
      if (['best_version','best_version_full','search_imdbid','sites','filter_groups'].includes(key)) continue
      const value=form[key]
      if (value==null || value==='') continue
      values[key]=['search_interval','min_bitrate','min_bit_depth','min_sample_rate'].includes(key)?Number(value):String(value).trim()
    }
    const sites=(form.sites || []).map(Number)
    const groups=(form.filter_groups || []).map(v=>String(v).trim()).filter(Boolean)
    if (sites.length) values.sites=[...sites]
    if (groups.length) values.filter_groups=[...groups]
    if (form.mode!=='inherit') {values.best_version=form.mode==='normal'?0:1;if(mediaType.value==='电视剧')values.best_version_full=form.mode==='whole'?1:0}
    if(mediaType.value!=='音乐' && form.imdb!=='inherit')values.search_imdbid=form.imdb==='yes'?1:0
    const configs={...policy.value.configs}
    if(Object.keys(values).length)configs[mediaType.value]=values
    else delete configs[mediaType.value]
    const next=normalizeSubscriptionPolicy({...policy.value,configs})
    emit('update:modelValue',next);open.value=false
  } catch(exc) {error.value=exc?.message || t('invalid')}
}
async function loadOptions() {
  const current=++sequence
  optionsLoading.value=true
  const result=await loadSubscriptionCatalogs(props.api,sdk)
  if(disposed || current!==sequence || !open.value)return
  optionsError.value=Object.values(result).some(group=>group.failed)
  siteOptions.value=result.sites.items
  downloaderOptions.value=result.downloaders.items
  ruleOptions.value=result.groups.items
  pathOptions.value=result.directories.items
  optionsLoading.value=false
}
watch(open,value=>{if(!value)sequence++})
onBeforeUnmount(()=>{disposed=true;sequence++})
</script>
<style scoped>
.asa-subscription-policy {min-inline-size:0;}
.asa-subscription-policy__head,.asa-subscription-policy__settings {display:grid;grid-template-columns:minmax(0,1.4fr) minmax(160px,.85fr);align-items:center;gap:18px;padding-block:13px;border-block-start:1px solid rgba(var(--v-theme-on-surface),.12);}
.asa-subscription-policy__head :deep(.v-input) {justify-self:end;flex:0 0 auto;}
.asa-subscription-policy__copy {min-inline-size:0;}
.asa-subscription-policy__label {font-size:.83rem;font-weight:600;line-height:1.2;}
.asa-subscription-policy__copy p {font-size:.7rem;line-height:1.05rem;margin:4px 0 0;color:rgba(var(--v-theme-on-surface),.56);}
.asa-subscription-policy__types {display:flex;flex-direction:column;gap:8px;min-inline-size:0;}
.asa-subscription-policy__trigger {inline-size:100%;justify-content:space-between;text-transform:none;letter-spacing:0;font-weight:500;}
.asa-subscription-policy__trigger span {flex:1;text-align:start;}
.asa-subscription-policy--rule {padding:0 12px;border:1px solid rgba(var(--v-theme-on-surface),.12);border-radius:var(--app-control-radius,8px);}
.asa-subscription-policy--rule .asa-subscription-policy__head {border-block-start:0;}
.asa-subscription-policy__dialog {border-radius:var(--app-surface-radius,12px)!important;}
.asa-subscription-policy__title {display:flex;align-items:center;gap:8px;font-size:1rem;font-weight:700;white-space:normal;}
.asa-subscription-policy__hint {margin:0 0 14px;font-size:.78rem;line-height:1.6;color:rgba(var(--v-theme-on-surface),.6);}
.asa-subscription-policy__fields :deep(.fp--stacked),.asa-subscription-policy__fields.fp--stacked {display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px 16px;}
.asa-subscription-policy__fields :deep(.fp-item--wide) {grid-column:1/-1;}
.asa-subscription-policy__advanced {margin-block-start:16px;}
.asa-subscription-policy__dialog :deep(.v-card-actions) {flex-wrap:wrap;gap:8px;}
.asa-subscription-policy__dialog :deep(.v-card-actions > .v-btn) {margin-inline-start:0;}
@media(max-width:600px) {
  .asa-subscription-policy__settings {grid-template-columns:minmax(0,1fr);gap:8px;}
  .asa-subscription-policy__head {grid-template-columns:minmax(0,1fr) auto;}
  .asa-subscription-policy__fields.fp--stacked {grid-template-columns:minmax(0,1fr);}
}
</style>
