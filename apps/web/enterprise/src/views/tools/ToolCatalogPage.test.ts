import assert from 'node:assert/strict'
import test from 'node:test'
import { reactive } from 'vue'
import { fixture, flush } from '@nexus-web/core/test-utils/vueFixture'
import * as presentation from '@nexus-web/core/utils/toolPresentation'

function setup(t: Parameters<typeof fixture>[0]) {
  const f=fixture(t)
  const auth=reactive({effectiveTenantId:'a',user:{id:'u'}})
  const context=reactive({revision:0,allowed:true,can:()=>context.allowed})
  const dialogs:Array<{onConfirm:()=>void;hide:()=>void}>=[]
  const writes:string[]=[], disabled=new Set<string>()
  const tools=['sandbox_exec','sandbox_read_file'].map(name=>({name,group:'sandbox',description:'Original',builtin:true,
    read_only:true,requires_approval:false,side_effects:false,risk_level:'low',enabled_in_tenant:true,disabled:false}))
  let fail='', deferred=false, finish:()=>void=()=>{}
  async function write(name:string,off:boolean) {
    writes.push(name)
    if(deferred) await new Promise<void>(resolve=>{finish=resolve})
    if(name===fail) throw new Error('denied')
    if(off) disabled.add(name);else disabled.delete(name)
  }
  const s=f.component(new URL('./ToolCatalogPage.vue',import.meta.url),{
    'vue-i18n':{useI18n:()=>({t:(key:string)=>key,te:()=>false})},
    '@nexus-web/core/stores/auth':{useAuthStore:()=>auth},
    '../../stores/context':{useEnterpriseContext:()=>context},
    '@nexus-web/core/utils/toolPresentation':presentation,
    'tdesign-vue-next':{MessagePlugin:{success:()=>{}},DialogPlugin:{confirm:(options:Record<string,unknown>)=>{
      const dialog={...options,hide:()=>{}} as typeof dialogs[number];dialogs.push(dialog);return dialog
    }}},
    '@nexus-web/core/api/nexus-agents':{
      getAgentToolCatalog:async()=>({tools:tools.map(tool=>({...tool,disabled:disabled.has(tool.name),enabled_in_tenant:!disabled.has(tool.name)})),groups:['sandbox']}),
      disableBuiltinResource:async(_scope:string,_kind:string,name:string)=>write(name,true),
      restoreBuiltinResource:async(_scope:string,_kind:string,name:string)=>write(name,false),
    },
  })
  return {...s,auth,context,dialogs,writes,tools,fail:(name:string)=>{fail=name},defer:()=>{deferred=true},finish:()=>finish()}
}

test('组开关停用前确认，批量保存后所有子项同步，再次开启全部恢复',async t=>{
  const s=setup(t);await flush()
  s.vm.toggleTools(s.vm.sections[0].manageable,false,'group:sandbox','沙箱')
  assert.equal(s.writes.length,0);s.dialogs[0].onConfirm();await flush()
  assert.deepEqual(s.writes,['sandbox_exec','sandbox_read_file'])
  assert.equal(s.vm.sections[0].selected,0)
  s.vm.toggleTools(s.vm.sections[0].manageable,true,'group:sandbox','沙箱');await flush()
  assert.equal(s.vm.sections[0].selected,2)
})
test('批量部分失败后刷新真实状态并显示部分启用，不冒充整组已关闭',async t=>{
  const s=setup(t);await flush();s.fail('sandbox_read_file')
  s.vm.toggleTools(s.vm.sections[0].manageable,false,'group:sandbox','沙箱')
  s.dialogs[0].onConfirm();await flush()
  assert.equal(s.vm.sections[0].selected,1);assert.equal(s.vm.sections[0].partial,true)
  assert.equal(s.vm.error,'toolUi.batchFailed');assert.equal(s.vm.busy,'')
})
test('企业切换时不再提交剩余工具，旧回执不覆盖新企业状态',async t=>{
  const s=setup(t);await flush();s.defer()
  s.vm.toggleTools(s.vm.sections[0].manageable,false,'group:sandbox','沙箱');s.dialogs[0].onConfirm()
  assert.equal(s.writes.length,1)
  s.auth.effectiveTenantId='b';await flush();s.finish();await flush()
  assert.equal(s.writes.length,1)
})
test('撤销维护权限会取消未提交的组确认并阻止后续操作',async t=>{
  const s=setup(t);await flush()
  s.vm.toggleTools(s.vm.sections[0].manageable,false,'group:sandbox','沙箱')
  s.context.allowed=false;await flush();s.dialogs[0].onConfirm();await flush()
  s.vm.toggleTools(s.tools,true,'group:sandbox','沙箱');assert.equal(s.writes.length,0)
})
