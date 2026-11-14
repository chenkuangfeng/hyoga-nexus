import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { fixture } from '../test-utils/vueFixture'
const base = {id:'kb',tenant_id:'t',ownership:'enterprise',shared:false,name:'Library',description:'',type:'document',visibility:'tenant',knowledge_count:3,can_manage:true}
const maintainer = {user_id:'u',display_name:'User',email:null,granted_by:'actor',granted_at:'2026-11-14'}
function setup(t: Parameters<typeof fixture>[0]) {
 let response:unknown={items:[]};const calls:unknown[][]=[]
 const api=fixture(t).evaluate(readFileSync(new URL('./enterprise-knowledge.ts',import.meta.url),'utf8'),{'../utils/request':Object.fromEntries(['get','post','del'].map(method=>[method,async(...args:unknown[])=>{calls.push([method,...args]);return response}]))})
 return {api,calls,result:(value:unknown)=>{response=value}}
}
test('企业目录校验可见范围、权限和计数，排除个人与外部共享库',async t=>{
 const s=setup(t);s.result({items:[base,{...base,id:'personal',ownership:'personal'},{...base,id:'shared',tenant_id:'other',shared:true}]})
 assert.equal((await s.api.listEnterpriseKnowledgeBases('t')).length,1)
 assert.equal(s.api.enterpriseBaseFromResponse({...base,visibility:'scoped'},'t').visibility,'scoped')
 for(const input of [{...base,tenant_id:'other'},{...base,can_manage:'true'},{...base,type:'unknown'},{...base,knowledge_count:-1},{...base,visibility:'all'},{...base,shared:true}]) assert.throws(()=>s.api.enterpriseBaseFromResponse(input,'t'),/enterprise_knowledge_response_invalid/)
 s.result({items:[base,base]});await assert.rejects(s.api.listEnterpriseKnowledgeBases('t'),/enterprise_knowledge_response_invalid/)
 s.result({items:[{...base,tenant_id:'other',shared:false}]});await assert.rejects(s.api.listEnterpriseKnowledgeBases('t'),/enterprise_knowledge_response_invalid/)
})
test('管理员列表保留可空姓名邮箱，拒绝重复成员或错误授权字段',t=>{
 const {api}=setup(t)
 assert.equal(api.knowledgeMaintainersFromResponse({items:[maintainer]})[0].email,null)
 for(const value of [{items:[maintainer,maintainer]},{items:[{...maintainer,granted_at:null}]},{items:[{...maintainer,display_name:42}]},[]])assert.throws(()=>api.knowledgeMaintainersFromResponse(value),/enterprise_knowledge_response_invalid/)
})
test('指定和撤销采用原管理接口，新增响应必须包含目标成员',async t=>{
 const s=setup(t);s.result({items:[maintainer]})
 await s.api.addKnowledgeMaintainer('t/a','kb/b','u');await s.api.removeKnowledgeMaintainer('t/a','kb/b','u/a')
 assert.equal(s.calls[0][1],'/api/v1/tenants/t%2Fa/admin/knowledge/bases/kb%2Fb/maintainers')
 assert.equal((s.calls[0][2] as {user_id:string}).user_id,'u')
 assert.equal(s.calls[1][1],'/api/v1/tenants/t%2Fa/admin/knowledge/bases/kb%2Fb/maintainers/u%2Fa')
 s.result({items:[]});await assert.rejects(s.api.addKnowledgeMaintainer('t','kb','u'),/enterprise_knowledge_response_invalid/)
})
