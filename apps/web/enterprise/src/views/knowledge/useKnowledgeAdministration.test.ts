import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import * as vue from 'vue'
import { fixture, flush } from '@nexus-web/core/test-utils/vueFixture'
function setup(t: Parameters<typeof fixture>[0], options:{membersDenied?:boolean;membersFailed?:boolean;listFailed?:boolean;maintainersFailed?:boolean}={}) {
 const f=fixture(t),auth=vue.reactive({effectiveTenantId:'t',user:{id:'actor'}}),context=vue.reactive({revision:0,allowed:true,memberAccess:!options.membersDenied,can(permission:string){return this.allowed&&(permission!=='members:manage'||this.memberAccess)}})
 const kb={id:'kb',tenant_id:'t',name:'Library',description:'',can_manage:true},person={user_id:'u',display_name:'User',email:'u@example.test',granted_by:'actor',granted_at:'date'}
 const calls:string[]=[],dialogs:{onConfirm:()=>Promise<void>}[]=[],pendingReads=new Map<string,(value:unknown)=>void>()
 let maintainers=options.maintainersFailed?null:[person],writeFinish:(value:unknown)=>void=()=>{},deferWrite=false,refreshFailed=false,writeFailed=false
 const compiled=f.evaluate(readFileSync(new URL('./useKnowledgeAdministration.ts',import.meta.url),'utf8'),{
  vue,'vue-i18n':{useI18n:()=>({t:(key:string)=>key})},'@nexus-web/core/stores/auth':{useAuthStore:()=>auth},'../../stores/context':{useEnterpriseContext:()=>context},'tdesign-vue-next':{DialogPlugin:{confirm:(dialog:{onConfirm:()=>Promise<void>})=>{dialogs.push(dialog);return {hide(){}}}}},
  '@nexus-web/core/api/enterprise-members':{listEnterpriseMembers:async()=>{calls.push('members');if(options.membersFailed)throw new Error('offline');return [{user_id:'u',display_name:'User'},{user_id:'v',display_name:'Next',email:'v@example.test'}]}},
  '@nexus-web/core/api/enterprise-knowledge':{
   listEnterpriseKnowledgeBases:async(tenant:string)=>{if(options.listFailed)throw new Error('offline');return tenant==='t'?[{...kb},{...kb,id:'second',name:'Second'}]:[]},
   listKnowledgeMaintainers:async(tenant:string,kb:string)=>{if(refreshFailed||maintainers===null)throw new Error('offline');if(kb==='second')return new Promise(resolve=>{pendingReads.set(kb,resolve)});return maintainers},
   addKnowledgeMaintainer:async(tenant:string,kb:string,user:string)=>{calls.push(`add:${tenant}:${kb}:${user}`);if(writeFailed)throw new Error('denied');if(deferWrite)return new Promise(resolve=>{writeFinish=resolve});return [...(maintainers||[]),{...person,user_id:user}]},
   removeKnowledgeMaintainer:async(tenant:string,kb:string,user:string)=>{calls.push(`remove:${tenant}:${kb}:${user}`);maintainers=[]},
  },
 })
 const s=f.mount({setup(){return compiled.useKnowledgeAdministration()}})
 return {...s,auth,context,calls,dialogs,person,pendingReads,deferWrite:()=>{deferWrite=true},finishWrite:()=>writeFinish([person]),failRefresh:()=>{refreshFailed=true},failWrite:()=>{writeFailed=true}}
}
test('读取管理员并排除已指定成员，新增需确认且使用选中成员稳定 ID',async t=>{
 const s=setup(t);await flush();await s.vm.inspect(s.vm.rows[0]);assert.equal(s.vm.maintainers.length,1);assert.equal(s.vm.memberOptions.length,1)
 s.vm.selectedMember='v';s.vm.add();assert.deepEqual(s.calls,['members']);await s.dialogs[0].onConfirm()
 assert.equal(s.calls[1],'add:t:kb:v');assert.equal(s.vm.maintainers.length,2);assert.equal(s.vm.success,'adminKnowledge.added');assert.equal(s.vm.canAdd,false)
})
test('没有成员权限不请求全员名单，仍可撤销已有管理员',async t=>{
 const s=setup(t,{membersDenied:true});await flush();await s.vm.inspect(s.vm.rows[0]);assert.equal(s.calls.length,0);assert.equal(s.vm.canAdd,false)
 s.vm.remove(s.vm.maintainers[0]);await s.dialogs[0].onConfirm();assert.deepEqual(s.calls,['remove:t:kb:u']);assert.equal(s.vm.maintainers.length,0)
})
test('成员列表失败独立反馈，不阻止撤销；管理员读取失败则禁止修改',async t=>{
 const s=setup(t,{membersFailed:true});await flush();await s.vm.inspect(s.vm.rows[0]);assert.equal(s.vm.membersError,'adminKnowledge.membersFailed');assert.equal(s.vm.editable,true);assert.equal(s.vm.canAdd,false)
 s.vm.remove(s.vm.maintainers[0]);assert.equal(s.dialogs.length,1)
})
test('管理员查询失败不能当作空结果，也不能新增',async t=>{
 const s=setup(t,{maintainersFailed:true});await flush();await s.vm.inspect(s.vm.rows[0]);assert.equal(s.vm.maintainersReady,false);assert.equal(s.vm.panelError,'adminConsole.failed')
 s.vm.selectedMember='v';s.vm.add();assert.equal(s.dialogs.length,0)
})
test('切换企业使旧确认失效，无管理权限后清空目录和面板',async t=>{
 const s=setup(t);await flush();await s.vm.inspect(s.vm.rows[0]);s.vm.remove(s.vm.maintainers[0])
 s.auth.effectiveTenantId='other';await flush();await s.dialogs[0].onConfirm();assert.equal(s.calls.filter(call=>call.startsWith('remove:')).length,0);assert.equal(s.vm.selected,null)
 s.context.allowed=false;await flush();assert.equal(s.vm.rows.length,0)
})
test('快速切换目标拒绝旧响应，卸载时迟到查询同样失效',async t=>{
 const s=setup(t);await flush();const pending=s.vm.inspect(s.vm.rows[1]);await flush();await s.vm.inspect(s.vm.rows[0]);s.pendingReads.get('second')!([]);await pending
 assert.equal(s.vm.selected.id,'kb');assert.equal(s.vm.maintainers.length,1)
 const unmounted=s.vm.inspect(s.vm.rows[1]);await flush();s.close();s.pendingReads.get('second')!([s.person]);await unmounted;assert.equal(s.vm.selected,null)
})
test('提交期间阻止重复操作；账号切换后迟到写入不污染新企业状态',async t=>{
 const s=setup(t);await flush();await s.vm.inspect(s.vm.rows[0]);s.vm.selectedMember='v';s.deferWrite();s.vm.add();const pending=s.dialogs[0].onConfirm()
 s.vm.add();s.vm.closePanel();assert.equal(s.vm.selected.id,'kb');assert.equal(s.dialogs.length,1)
 s.auth.user.id='other';await flush();s.finishWrite();await pending;assert.equal(s.vm.selected,null);assert.equal(s.vm.success,'')
})
test('撤销成功后的刷新失败明确区别于写入失败',async t=>{
 const s=setup(t);await flush();await s.vm.inspect(s.vm.rows[0]);s.vm.remove(s.vm.maintainers[0]);s.failRefresh();await s.dialogs[0].onConfirm()
 assert.equal(s.vm.success,'adminKnowledge.removed');assert.equal(s.vm.panelError,'adminKnowledge.refreshFailed');assert.equal(s.vm.maintainersReady,false)
})
test('新增被拒绝时保留选择与已有管理员，允许修正后重试',async t=>{
 const s=setup(t);await flush();await s.vm.inspect(s.vm.rows[0]);s.vm.selectedMember='v';s.vm.add();s.failWrite();await s.dialogs[0].onConfirm()
 assert.equal(s.vm.selectedMember,'v');assert.equal(s.vm.maintainers.length,1);assert.equal(s.vm.busy,false);assert.equal(s.vm.success,'');assert.equal(s.vm.panelError,'adminConsole.failed')
})
test('目录读取失败不显示为空目录',async t=>{
 const s=setup(t,{listFailed:true});await flush();assert.equal(s.vm.ready,false);assert.equal(s.vm.error,'adminConsole.failed')
})

test('资源本身不可管理时，即使有企业管理权限也不能打开操作面板',async t=>{
 const s=setup(t);await flush();s.vm.rows[0].can_manage=false;await s.vm.inspect(s.vm.rows[0]);assert.equal(s.vm.selected,null);assert.equal(s.calls.length,0)
})
