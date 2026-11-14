import assert from 'node:assert/strict'
import test from 'node:test'
import * as vue from 'vue'
import { fixture,flush } from '../../test-utils/vueFixture'
import * as images from '../../utils/imageProcessingConfig'
import * as attrs from '../../utils/imageAttrDisplay'
import * as models from '../../utils/modelDefaults'
function setup(t:Parameters<typeof fixture>[0], options:{personal?:boolean;deferred?:boolean;readFailed?:boolean}={}) {
 const f=fixture(t),auth=vue.reactive({effectiveTenantId:'t',user:{id:'u'},hasRole:()=>true,isLiteMode:false}),calls:string[]=[]
 let finish:(value:unknown)=>void=()=>{},readFailed=!!options.readFailed
 const data={id:'kb',tenant_id:'t',name:'Library',type:'document',can_manage:true,visibility:options.personal?'private':'tenant',settings_snapshot:{custom:{keep:true}},summary_model_id:'chat',embedding_model_id:'embed',indexing_strategy:{vector_enabled:false,keyword_enabled:true},chunking_config:{chunk_size:512,chunk_overlap:0}}
 const listed=[{id:'chat',type:'KnowledgeQA',status:'active',is_default:true},{id:'embed',type:'Embedding',status:'active',is_default:true}]
 const s=f.component(new URL('./KnowledgeBaseEditorModal.vue',import.meta.url),{
  'vue-i18n':{useI18n:()=>({t:(key:string)=>key,te:()=>false})},'tdesign-vue-next':{MessagePlugin:{success(){},error(){},info(){}},DialogPlugin:{confirm:()=>({destroy(){}})}},
  './host':{KNOWLEDGE_EDITOR_HOST:Symbol('host')},
  '../../composables/useModalShell':{useModalShell:(options:{close:()=>void})=>({requestClose:options.close,markClean(){}})},
  '@nexus-web/core/stores/auth':{useAuthStore:()=>auth},'@nexus-web/core/stores/chatResources':{useChatResourcesStore:()=>({allModels:listed,ensureModels:async()=>{}})},
  '@nexus-web/core/stores/editorResources':{useEditorResourcesStore:()=>({ensureStorageEngine:async()=>{},storageConfig:{default_provider:'local'},resolveUsableStorageProvider:()=> 'local'})},
  '../../stores/knowledgeCapabilities':{useKnowledgeCapabilitiesStore:()=>({ensureLoaded:async()=>{},available:()=>true})},
  '../../utils/modelDefaults':models,'../../utils/imageProcessingConfig':images,'../../utils/imageAttrDisplay':attrs,'@nexus-web/core/utils/clipboard':{copyWithToast(){}},'../../config/contextualGuides':{KB_EDITOR_FOCUS_SECTION_EVENT:'kb-focus',markContextualGuideDone(){}},
  '@nexus-web/core/api/knowledge-base/index':{listKnowledgeFiles:async()=>({total:0}),mergeImageActions:()=>({ocr:{on:[]}}),FALLBACK_IMAGE_ATTR_SCHEMA:{attributes:[],default_actions:{ocr:{on:[]}}},fetchImageAttrSchema:async()=>({attributes:[],default_actions:{ocr:{on:[]}}})},
  '@nexus-web/core/api/knowledge-editor':{
   listKnowledgeEditorStorage:async()=>[{id:'builtin',provider:'local',name:'Local'}],
   createEditableKnowledge:async(tenant:string,_body:unknown,enterprise:boolean)=>{calls.push(`create:${tenant}:${enterprise}`);if(options.deferred)return new Promise(resolve=>{finish=resolve});return {success:true,data}},
   getEditableKnowledge:async()=>{calls.push('read');if(readFailed)throw new Error('offline');return {success:true,data}},
   updateEditableKnowledge:async()=>{calls.push('update');return {success:true,data}},
  },
 },{visible:true,tenantId:'t',mode:'create',...(options.personal?{}:{creationScope:'enterprise'})})
 return {...s,auth,calls,finish:()=>finish({success:true,data}),recover:()=>{readFailed=false}}
}
test('企业创建后继续同一记录配置，读取失败不能重复创建',async t=>{
 const s=setup(t,{readFailed:true});await flush();s.vm.formData.name='Library';await s.vm.doSubmit()
 assert.deepEqual(s.calls,['create:t:true','read']);assert.equal(s.vm.savedKbId,'kb');assert.ok(s.vm.loadError)
 await s.vm.doSubmit();assert.equal(s.calls.length,2)
 s.recover();s.vm.retryLoad();await flush();assert.equal(s.vm.loadError,'');await s.vm.doSubmit()
 assert.deepEqual(s.calls,['create:t:true','read','read','update'])
})
test('切换企业后迟到创建不继续读取或污染表单，重复提交被阻止',async t=>{
 const s=setup(t,{deferred:true});await flush();s.vm.formData.name='Library';const pending=s.vm.doSubmit();await s.vm.doSubmit();s.auth.effectiveTenantId='other';s.finish();await pending
 assert.deepEqual(s.calls,['create:t:true']);assert.equal(s.vm.savedKbId,null)
})
test('工作台默认个人创建，创建成功保留 ID 和完整表单',async t=>{
 const s=setup(t,{personal:true});await flush();s.vm.formData.name='Library';await s.vm.doSubmit()
 assert.deepEqual(s.calls,['create:t:false','read']);assert.equal(s.vm.activeKbId,'kb');assert.equal(s.vm.formData.name,'Library');assert.equal(s.vm.formData.chunkingConfig.chunkOverlap,0)
})
