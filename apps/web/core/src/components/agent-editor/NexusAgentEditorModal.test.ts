import assert from 'node:assert/strict'
import test from 'node:test'
import { fixture, flush } from '../../test-utils/vueFixture'
import * as form from './nexusAgentForm'
import * as groups from './nexusToolGroups'
import * as models from '../../utils/nexusModelCards'
import * as reasoning from '../../utils/reasoningEffort'
import * as skills from './mySkills'
function setup(t: Parameters<typeof fixture>[0], options: {personal?:boolean; deferred?:boolean} = {}) {
 const f=fixture(t), calls:string[]=[], messages:string[]=[]
 let failPublish=true, finish:(value:unknown)=>void=()=>{}
 const agent={id:'a',tenant_id:'t',name:'Helper',description:'',status:'draft',runtime_type:'native',instructions:'prompt',model_profile_version_id:'m',budgets:{},resource_bindings:[],published_version_id:null,version_counter:0,created_at:'',updated_at:''}
 const settings={providers:[{id:'provider',scope:'tenant',name:'Models',models:[{id:'model',version_id:'m',name:'Chat',model_type:'chat',options:{}}]}],defaults:{tenant:{chat:'m'}},can_manage_tenant:true}
 const write=async(kind:string)=>{calls.push(kind);if(options.deferred)return new Promise(resolve=>{finish=resolve});return {...agent}}
 const deps={
  'vue-i18n':{useI18n:()=>({t:(key:string)=>key,te:()=>false})},
  'tdesign-vue-next':{MessagePlugin:Object.fromEntries(['error','warning','success'].map(name=>[name,(message:string)=>messages.push(message)]))},
  '@nexus-web/core/utils/clipboard':{copyWithToast:()=>{}},'@nexus-web/core/utils/reasoningEffort':reasoning,
  '@nexus-web/core/utils/nexusModelCards':models,'./nexusAgentForm':form,'./nexusToolGroups':groups,'./mySkills':skills,
  '@nexus-web/core/api/nexus-models':{getModelSettings:async()=>settings},
  '@nexus-web/core/api/nexus-agents':{getAgentToolCatalog:async()=>({tools:[],default_tools:[]}),getNativeDefaults:async()=>null,listTenantSkills:async()=>[],createNexusAgent:()=>write('personal-create'),updateNexusAgent:()=>write('personal-update'),publishNexusAgent:async(tenant:string)=>{calls.push('publish:'+tenant);if(failPublish)throw new Error('publish failed')}},
  '@nexus-web/core/api/enterprise-agents':{publishEnterpriseAgent:async(tenant:string)=>{calls.push('publish:'+tenant);if(failPublish)throw new Error('publish failed')},createEnterpriseAgent:()=>write('enterprise-create'),updateEnterpriseAgent:()=>write('enterprise-update'),listAgentKnowledgeChoices:async()=>[]},
 }
 const mounted=f.component(new URL('./NexusAgentEditorModal.vue',import.meta.url),deps,{visible:true,tenantId:'t',agentId:null,...(options.personal?{}:{creationScope:'enterprise'})})
 return {...mounted,calls,messages,agent,finish:()=>finish(agent),publishWorks:()=>{failPublish=false}}
}
test('企业创建发布失败保留同一草稿；重试更新而非重复创建',async t=>{
 const s=setup(t);await flush();s.vm.form.name='Helper';s.vm.form.system_prompt='prompt'
 await s.vm.save();assert.deepEqual(s.calls,['enterprise-create','publish:t']);assert.equal(s.vm.agent.id,'a');assert.equal(s.vm.saving,false)
 s.publishWorks();await s.vm.save();assert.deepEqual(s.calls,['enterprise-create','publish:t','enterprise-update','publish:t'])
})
test('卸载后迟到的创建结果不能触发发布和成功提示',async t=>{
 const s=setup(t,{deferred:true});await flush();s.vm.form.name='Helper';s.vm.form.system_prompt='prompt'
 const pending=s.vm.save();assert.deepEqual(s.calls,['enterprise-create']);s.close();s.finish();await pending
 assert.deepEqual(s.calls,['enterprise-create']);assert.equal(s.messages.length,0)
})
test('默认个人流程继续使用个人创建接口，重复提交被拦截',async t=>{
 const s=setup(t,{personal:true,deferred:true});await flush();s.vm.form.name='Helper';s.vm.form.system_prompt='prompt'
 const pending=s.vm.save();await s.vm.save();assert.deepEqual(s.calls,['personal-create'])
 s.finish();await pending;assert.equal(s.calls[1],'publish:t')
})
test('知识库候选不包含已有绑定时，修改选择仍保留不可见绑定',async t=>{
 const s=setup(t);await flush();s.vm.form.knowledge_bases=[{id:'hidden',source_tenant_id:'other'}]
 s.vm.onKnowledgeChange([]);assert.equal(s.vm.form.knowledge_bases[0].id,'hidden')
})

test('切换企业作废待保存草稿，旧响应不得在新企业继续发布',async t=>{
 const s=setup(t,{deferred:true});await flush();s.vm.form.name='Helper';s.vm.form.system_prompt='prompt'
 const pending=s.vm.save();s.vm.$.props.tenantId='other';await flush();s.finish();await pending
 assert.deepEqual(s.calls,['enterprise-create']);assert.equal(s.vm.agent,null);assert.equal(s.vm.form.name,'')
})
