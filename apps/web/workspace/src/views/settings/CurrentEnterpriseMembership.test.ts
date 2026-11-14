import assert from 'node:assert/strict'
import test from 'node:test'
import { reactive } from 'vue'
import { change, fixture, flush } from '@nexus-web/core/test-utils/vueFixture'
function setup(t: Parameters<typeof fixture>[0], role = 'viewer', fail = false, readFail = false) {
 const f=fixture(t),calls:string[]=[],paths:string[]=[]
 let loggedOut=false,readCount=0,finishLeave:((value:unknown)=>void)|undefined
 const auth=reactive({effectiveTenantId:'selected',currentTenantRole:role,user:{id:'u'},logout(){loggedOut=true}})
 const mounted=f.component(new URL('./CurrentEnterpriseMembership.vue',import.meta.url),{
  '@nexus-web/core/stores/auth':{useAuthStore:()=>auth},'vue-router':{useRouter:()=>({replace:async(path:string)=>{paths.push(path)}})},'vue-i18n':{useI18n:()=>({t:(key:string)=>key})},
  '@nexus-web/core/api/enterprise-info':{getEnterpriseInfo:async(id:string)=>{readCount++;if(readFail)throw new Error('offline');return{id,name:'Selected enterprise',description:'',role,status:'active',created_at:'2026-11-14'}}},
  '@nexus-web/core/api/tenant/members':{leaveTenant:async(id:string)=>{calls.push(id);if(fail)throw new Error('conflict');return new Promise(resolve=>{finishLeave=resolve})}},
 })
 return{...mounted,f,auth,calls,paths,loggedOut:()=>loggedOut,readCount:()=>readCount,finish:(value:unknown)=>finishLeave?.(value)}
}
test('普通成员无需读取成员名单，确认后只退出有效企业并在工作台登录',async t=>{
 const s=setup(t);await flush();assert.equal(s.vm.info.id,'selected');assert.equal(s.vm.canLeave,true)
 await s.vm.leave();assert.equal(s.calls.length,0)
 s.vm.openLeave();const pending=s.vm.leave();await s.vm.leave();assert.equal(s.calls.length,1)
 s.finish({success:true});await pending
 assert.deepEqual(s.calls,['selected']);assert.equal(s.loggedOut(),true);assert.deepEqual(s.paths,['/login'])
})
test('任何 owner 都不能退出，不依赖最后一名 owner 的前端推算',async t=>{
 const s=setup(t,'owner');await flush();assert.equal(s.vm.owner,true);assert.equal(s.vm.canLeave,false)
 s.vm.openLeave();s.vm.visible=true;await s.vm.leave();assert.equal(s.calls.length,0)
})
test('退出失败保留确认与错误且可重试',async t=>{
 const s=setup(t,'viewer',true);await flush();s.vm.openLeave();await s.vm.leave()
 assert.equal(s.vm.visible,true);assert.equal(s.vm.busy,false);assert.equal(s.vm.error,'conflict');assert.equal(s.loggedOut(),false)
})
test('切换企业或账号使旧确认和迟到退出结果失效',async t=>{
 const s=setup(t);await flush();s.vm.openLeave();const pending=s.vm.leave()
 s.auth.effectiveTenantId='other';await flush();s.finish({success:true});await pending
 assert.equal(s.loggedOut(),false);assert.deepEqual(s.paths,[]);assert.equal(s.vm.visible,false);assert.equal(s.vm.info.id,'other')
})
test('企业信息变动刷新只读身份，卸载后不再读取',async t=>{
 const s=setup(t);await flush();s.f.emit(change('workspace.update'));t.mock.timers.tick(300);await flush();assert.equal(s.readCount(),2)
 s.close();s.f.emit(change('workspace.update'));t.mock.timers.tick(300);await flush();assert.equal(s.readCount(),2)
})


test('身份详情读取失败不能退出，错误明确且可以刷新重试',async t=>{
 const s=setup(t,'viewer',false,true);await flush()
 assert.equal(s.vm.info,null);assert.equal(s.vm.error,'offline');assert.equal(s.vm.canLeave,false)
 s.vm.openLeave();await s.vm.leave();assert.equal(s.calls.length,0)
})
