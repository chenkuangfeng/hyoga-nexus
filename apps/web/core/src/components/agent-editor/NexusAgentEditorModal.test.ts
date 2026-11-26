import assert from 'node:assert/strict'
import test from 'node:test'
import { fixture, flush } from '../../test-utils/vueFixture'
import * as form from './nexusAgentForm'
import * as groups from './nexusToolGroups'
import * as models from '../../utils/nexusModelCards'
import * as reasoning from '../../utils/reasoningEffort'
import * as skills from './mySkills'
import * as presentation from '../../utils/toolPresentation'
import type { AgentToolEntry, AgentToolGroupInfo } from '../../api/nexus-agents'
function setup(t: Parameters<typeof fixture>[0], options: {personal?:boolean; deferred?:boolean; tools?:AgentToolEntry[]; groupInfo?:AgentToolGroupInfo[]} = {}) {
 const f=fixture(t), calls:string[]=[], messages:string[]=[]
 const catalog={tools:options.tools||[],groups:['base','sandbox'],group_info:options.groupInfo||[],default_tools:[],can_enable_tools:true}
 let failPublish=true, finish:(value:unknown)=>void=()=>{}
 const agent={id:'a',tenant_id:'t',name:'Helper',description:'',status:'draft',runtime_type:'native',instructions:'prompt',model_profile_version_id:'m',budgets:{},resource_bindings:[],published_version_id:null,version_counter:0,created_at:'',updated_at:''}
 const settings={providers:[{id:'provider',scope:'tenant',name:'Models',models:[{id:'model',version_id:'m',name:'Chat',model_type:'chat',options:{}}]}],defaults:{tenant:{chat:'m'}},can_manage_tenant:true}
 const write=async(kind:string)=>{calls.push(kind);if(options.deferred)return new Promise(resolve=>{finish=resolve});return {...agent}}
 const deps={
  'vue-i18n':{useI18n:()=>({t:(key:string)=>key,te:()=>false})},
  'tdesign-vue-next':{MessagePlugin:Object.fromEntries(['error','warning','success'].map(name=>[name,(message:string)=>messages.push(message)]))},
  '@nexus-web/core/utils/clipboard':{copyWithToast:()=>{}},'@nexus-web/core/utils/reasoningEffort':reasoning,
  '@nexus-web/core/utils/toolPresentation':presentation,'@nexus-web/core/utils/nexusModelCards':models,'./nexusAgentForm':form,'./nexusToolGroups':groups,'./mySkills':skills,
  '@nexus-web/core/api/nexus-models':{getModelSettings:async()=>settings},
  '@nexus-web/core/api/nexus-agents':{getAgentToolCatalog:async()=>catalog,getNativeDefaults:async()=>null,listTenantSkills:async()=>[],createNexusAgent:()=>write('personal-create'),updateNexusAgent:()=>write('personal-update'),publishNexusAgent:async(tenant:string)=>{calls.push('publish:'+tenant);if(failPublish)throw new Error('publish failed')}},
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

const sandboxInfo: AgentToolGroupInfo = { id:'sandbox',label:'Sandbox',default_enabled:false,locked:false,
 tool_count:3,planned:'',available:true,reason:'' }
function tool(name:string, group='sandbox', enabled=true):AgentToolEntry {
 return {name,group,enabled_in_tenant:enabled,description:'Original description',risk_level:'low',read_only:true,
 requires_approval:false,side_effects:false,builtin:true,disabled:!enabled}
}
test('分组开关同步可绑定工具并保留其他组，保存协议同时携带组门控和绑定',async t=>{
 const tools=[tool('sandbox_exec'),tool('sandbox_read_file'),tool('sandbox_write_file','sandbox',false),tool('todo','base')]
 const s=setup(t,{tools,groupInfo:[sandboxInfo]});await flush();s.vm.form.allowed_tools=['todo']
 s.vm.onGroupSwitch('sandbox',true)
 assert.deepEqual(Array.from(s.vm.form.allowed_tools),['todo','sandbox_exec','sandbox_read_file'])
 assert.equal(s.vm.form.tool_groups_enabled.sandbox,true)
 const draft=form.draftFromForm(s.vm.form,null,null,'t')
 const behavior=draft.budgets.behavior as {tool_groups_enabled:Record<string,boolean>}
 assert.equal(behavior.tool_groups_enabled.sandbox,true)
 assert.ok(draft.resource_bindings.some(binding=>binding.resource_id==='sandbox_exec'))
 s.vm.onGroupSwitch('sandbox',false)
 assert.deepEqual(Array.from(s.vm.form.allowed_tools),['todo'])
 assert.equal(groups.groupEnabled(sandboxInfo,s.vm.form.tool_groups_enabled),false)
})
test('关闭分组中的旧绑定不会因单个子项开启而全部恢复，最后一个子项关闭会关组',async t=>{
 const tools=[tool('sandbox_exec'),tool('sandbox_read_file')]
 const s=setup(t,{tools,groupInfo:[sandboxInfo]});await flush()
 s.vm.form.allowed_tools=['sandbox_exec','sandbox_read_file'];s.vm.form.tool_groups_enabled={sandbox:false}
 assert.equal(s.vm.toolSelected(tools[0]),false)
 s.vm.onToolSwitch(tools[1],true)
 assert.deepEqual(Array.from(s.vm.form.allowed_tools),['sandbox_read_file'])
 assert.equal(s.vm.toolGroups.find((item:{key:string})=>item.key==='sandbox').partial,true)
 s.vm.onToolSwitch(tools[1],false)
 assert.equal(groups.groupEnabled(sandboxInfo,s.vm.form.tool_groups_enabled),false)
 s.vm.onToolSwitch(tool('sandbox_exec','sandbox',false),true)
 assert.equal(s.vm.form.allowed_tools.length,0)
})
test('基础组批量选择不修改始终开启的执行门控',async t=>{
 const base={...sandboxInfo,id:'base',locked:true,default_enabled:true}
 const s=setup(t,{tools:[tool('todo','base')],groupInfo:[base]});await flush()
 s.vm.onGroupSwitch('base',true);assert.equal(s.vm.form.allowed_tools[0],'todo')
 s.vm.onGroupSwitch('base',false);assert.equal(s.vm.form.allowed_tools.length,0)
 assert.equal(groups.groupEnabled(base,s.vm.form.tool_groups_enabled),true)
})
