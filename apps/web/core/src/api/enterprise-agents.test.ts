import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { fixture } from '../test-utils/vueFixture'
const fixtures = new WeakMap<object, ReturnType<typeof fixture>>()
const row = { id:'a', tenant_id:'t', ownership:'enterprise', can_maintain:true, name:'Helper', description:'', status:'draft', runtime_type:'native', instructions:'prompt', published_version_id:null, model_profile_version_id:'m', version_counter:0, budgets:{extension:{keep:true}}, resource_bindings:[{kind:'tool',resource_id:'search',resource_version_id:null,source_tenant_id:'t',config:{keep:true}}], created_at:'', updated_at:'' }
function setup(t: Parameters<typeof fixture>[0], result: unknown = row) {
  const calls: unknown[][] = []
  if (!fixtures.has(t)) fixtures.set(t, fixture(t))
  const api = fixtures.get(t)!.evaluate(readFileSync(new URL('./enterprise-agents.ts', import.meta.url),'utf8'), {'../utils/request':Object.fromEntries(['get','post','put','del'].map(method => [method,async(...args:unknown[])=>{calls.push([method,...args]);return result}]))})
  return {api,calls}
}
test('完整草稿校验保留扩展绑定，拒绝跨企业/个人/错误状态和不完整字段', t => {
  const {api}=setup(t)
  assert.equal(api.enterpriseAgentFromResponse(row,'t').budgets.extension.keep,true)
  for(const input of [{...row,tenant_id:'other'},{...row,ownership:'personal'},{...row,can_maintain:'true'},{...row,version_counter:-1},{...row,status:'unknown'},{...row,resource_bindings:[{}]},{...row,budgets:[]}]) assert.throws(()=>api.enterpriseAgentFromResponse(input,'t'),/agents_response_invalid/)
})
test('企业创建使用 admin 接口，个人记录过滤且跨企业列表整体拒绝',async t=>{
 const s=setup(t);await s.api.createEnterpriseAgent('t',{name:'Helper'})
 assert.equal(s.calls[0][1],'/api/v1/tenants/t/admin/agents')
 const mixed=setup(t,[row,{...row,ownership:'personal'}]);assert.equal((await mixed.api.listEnterpriseAgents('t')).length,1)
 await assert.rejects(setup(t,[{...row,tenant_id:'x'}]).api.listEnterpriseAgents('t'),/agents_response_invalid/)
 await assert.rejects(setup(t,{...row,id:'other'}).api.getEnterpriseAgent('t','a'),/agents_response_invalid/)
})
test('知识库候选保留共享来源，企业编辑器排除个人库且拒绝错误结构',async t=>{
 const kb={id:'k',tenant_id:'other',name:'Shared',description:'',shared:true,knowledge_count:3,ownership:'enterprise'}
 const s=setup(t,{items:[kb,{...kb,id:'p',ownership:'personal'}]})
 assert.equal((await s.api.listAgentKnowledgeChoices('t',true)).length,1)
 assert.equal((await s.api.listAgentKnowledgeChoices('t',false)).length,2)
 assert.equal((await s.api.listAgentKnowledgeChoices('t',true))[0].tenant_id,'other')
 await assert.rejects(setup(t,{items:[{...kb,shared:false}]}).api.listAgentKnowledgeChoices('t',true),/agents_response_invalid/)
})
