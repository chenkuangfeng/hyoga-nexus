import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import * as vue from 'vue'
import { fixture } from '../../test-utils/vueFixture'
test('目标变动及卸载后拒绝旧异步链继续请求',async t=>{
 const f=fixture(t),host={scope:'a',scopeKey(){return this.scope},isCurrent:()=>true};let finish:(value:unknown)=>void=()=>{},writes=0
 const compiled=f.evaluate(readFileSync(new URL('./scopedApi.ts',import.meta.url),'utf8'),{vue,'./host':{useKnowledgeEditorHost:()=>host}})
 const s=f.mount({setup(){return {api:compiled.useScopedApi({read:async()=>new Promise(resolve=>{finish=resolve}),write:async()=>{writes++}})}}})
 const pending=s.vm.api.read();host.scope='b';finish({});await assert.rejects(pending,/scope_expired/)
 await assert.rejects(s.vm.api.write(),/scope_expired/);assert.equal(writes,0)
 host.scope='a';s.close();await assert.rejects(s.vm.api.write(),/scope_expired/)
})
