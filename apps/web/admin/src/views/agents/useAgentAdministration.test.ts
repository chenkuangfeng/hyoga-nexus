import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import * as vue from 'vue'
import { fixture,flush } from '@nexus-web/core/test-utils/vueFixture'
function setup(t:Parameters<typeof fixture>[0]) {
 const f=fixture(t),auth=vue.reactive({effectiveTenantId:'t',user:{id:'u'}}),context=vue.reactive({revision:0,allowed:true,can(){return this.allowed}})
 const calls:string[]=[],dialogs: {onConfirm:()=>Promise<void>}[]=[],row={id:'a',name:'Agent',description:'',can_maintain:true}
 let finish:(value:unknown)=>void=()=>{},fail=false
 const compiled=f.evaluate(readFileSync(new URL('./useAgentAdministration.ts',import.meta.url),'utf8'),{vue,'vue-i18n':{useI18n:()=>({t:(key:string)=>key})},'@nexus-web/core/stores/auth':{useAuthStore:()=>auth},'../../stores/context':{useAdminContext:()=>context},'tdesign-vue-next':{DialogPlugin:{confirm:(options:{onConfirm:()=>Promise<void>})=>{dialogs.push(options);return {hide(){}}}},MessagePlugin:{success(){},info(){}}},'@nexus-web/core/api/enterprise-agents':{listEnterpriseAgents:async(tenant:string)=>{if(fail)throw new Error('offline');if(tenant==='other')return new Promise(resolve=>{finish=resolve});return [{...row}]},archiveEnterpriseAgent:async(tenant:string,id:string)=>{calls.push(tenant+':'+id)}}})
 return {...f.mount({setup(){return compiled.useAgentAdministration()}}),auth,context,calls,dialogs,finish:()=>finish([row]),fail:()=>{fail=true}}
}
test('企业创建入口依赖列表成功和权限，列表刷新保留当前编辑器',async t=>{
 const s=setup(t);await flush();s.vm.open();assert.equal(s.vm.editor,true);await s.vm.load();assert.equal(s.vm.editor,true)
 s.context.allowed=false;await flush();assert.equal(s.vm.editor,false);assert.equal(s.vm.rows.length,0);s.vm.open();assert.equal(s.vm.editor,false)
})
test('归档需确认，失效的旧企业确认不得写入',async t=>{
 const s=setup(t);await flush();s.vm.archive(s.vm.rows[0]);assert.equal(s.calls.length,0)
 s.auth.effectiveTenantId='other';await flush();await s.dialogs[0].onConfirm();assert.equal(s.calls.length,0)
 s.context.allowed=false;s.finish();await flush();assert.equal(s.vm.rows.length,0)
})
test('归档成功刷新，加载失败保留错误且不能创建',async t=>{
 const s=setup(t);await flush();s.vm.archive(s.vm.rows[0]);await s.dialogs[0].onConfirm();assert.deepEqual(s.calls,['t:a'])
 s.fail();await s.vm.load();assert.equal(s.vm.ready,false);assert.equal(s.vm.error,'adminConsole.failed');s.vm.open();assert.equal(s.vm.editor,false)
})
