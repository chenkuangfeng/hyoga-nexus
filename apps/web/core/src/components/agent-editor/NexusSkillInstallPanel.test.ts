import assert from 'node:assert/strict'
import test from 'node:test'
import { fixture, flush } from '../../test-utils/vueFixture'
import * as helpers from './skillInstall'
test('关闭安装面板后，迟到安装结果不会启动轮询',async t=>{
 const f=fixture(t), calls:string[]=[]
 let finish:(value:unknown)=>void=()=>{}
 const s=f.component(new URL('./NexusSkillInstallPanel.vue',import.meta.url),{'vue-i18n':{useI18n:()=>({})},'tdesign-vue-next':{MessagePlugin:{}},'./skillInstall':helpers,'@nexus-web/core/api/nexus-agents':{uploadSkillBundle:async()=>new Promise(resolve=>{finish=resolve}),getSkillInstallStatus:async()=>{calls.push('poll');return {build_state:'installing'}}}},{tenantId:'t'})
 const pending=s.vm.installUpload(false);s.close();finish({skill:'report',version:'v1',build_state:'installing'});await pending;await flush()
 assert.deepEqual(calls,[])
})
test('卸载后迟到构建状态不会重新安排轮询',async t=>{
 const f=fixture(t);let polls=0,finish:(value:unknown)=>void=()=>{}
 const s=f.component(new URL('./NexusSkillInstallPanel.vue',import.meta.url),{'vue-i18n':{useI18n:()=>({})},'tdesign-vue-next':{MessagePlugin:{}},'./skillInstall':helpers,'@nexus-web/core/api/nexus-agents':{getSkillInstallStatus:async()=>{polls++;return new Promise(resolve=>{finish=resolve})}}},{tenantId:'t'})
 s.vm.result={skill:'report',version:'v1',build_state:'installing'}
 const pending=s.vm.follow();s.close();finish({build_state:'installing'});await pending;t.mock.timers.tick(6000);await flush()
 assert.equal(polls,1)
})
