import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { fixture } from '../test-utils/vueFixture'
import * as adapter from './knowledge-base/nexusAdapter'
const row={id:'kb',tenant_id:'t',ownership:'enterprise',can_manage:true,shared:false,knowledge_count:0,embedding_model_id:'embed',visibility:'tenant',name:'Library',description:'',type:'document',settings:{custom:{keep:true}},chunking_config:{chunk_size:512,chunk_overlap:80},indexing_strategy:{vector:false,keyword:true,graph:false,wiki:false}}
function setup(t:Parameters<typeof fixture>[0]) {
 const calls:unknown[][]=[];let result:unknown=row
 const api=fixture(t).evaluate(readFileSync(new URL('./knowledge-editor.ts',import.meta.url),'utf8'),{'./knowledge-base/nexusAdapter':adapter,'../utils/request':Object.fromEntries(['get','post','patch'].map(method=>[method,async(...args:unknown[])=>{calls.push([method,...args]);return result}]))})
 return {api,calls,result:(value:unknown)=>{result=value}}
}
test('只接收本企业可管理记录，后台不能编辑个人或共享资源',t=>{
 const {api}=setup(t)
 for(const value of [{...row,tenant_id:'other'},{...row,can_manage:false},{...row,ownership:'personal'},{...row,settings:null},{...row,visibility:'unknown'}])assert.throws(()=>api.editableKnowledgeResponse(value,'t','kb',true),/knowledge_editor_response_invalid/)
 assert.equal(api.editableKnowledgeResponse({...row,ownership:'personal'},'t','kb',false).data.ownership,'personal')
})
test('一次保存完整配置并合并未知快照、分块扩展与图片设置，编辑不更换绑定',async t=>{
 const s=setup(t)
 const payload={name:'Updated',type:'document',vector_store_id:'v',storage_backend_id:'s',embedding_model_id:'embed',chunking_config:{chunk_size:1000,chunk_overlap:0,parser_engine_rules:[],strategy:''},image_processing_config:{pipeline:'smartocr'},wiki_config:{content_instructions:'keep'},auto_tag_config:{enabled:true},synonyms:[['a','b']],visibility:'private'}
 await s.api.updateEditableKnowledge('t','kb',payload,{custom:{keep:true},chunking_config:{extension:'keep'},rerank_config:{enabled:true}},true)
 assert.equal(s.calls.length,1);assert.equal(s.calls[0][0],'patch')
 const body=s.calls[0][2] as { settings: { custom:{keep:boolean}; chunking_config:{extension:string;parser_engine_rules:unknown[]}; image_processing_config:{pipeline:string};rerank_config:{enabled:boolean};wiki_config:{content_instructions:string} };chunking_config:{chunk_overlap:number};visibility:string }
 assert.equal(body.settings.custom.keep,true);assert.equal(body.settings.chunking_config.extension,'keep');assert.equal(body.settings.chunking_config.parser_engine_rules.length,0)
 assert.equal(body.settings.image_processing_config.pipeline,'smartocr');assert.equal(body.settings.rerank_config.enabled,true);assert.equal(body.settings.wiki_config.content_instructions,'keep')
 assert.equal(body.chunking_config.chunk_overlap,0);assert.equal(body.visibility,'private');assert.equal('storage_backend_id' in body,false);assert.equal('vector_store_id' in body,false)
})
test('创建入口决定归属，默认个人与企业分别调用现有接口',async t=>{
 const s=setup(t);await s.api.createEditableKnowledge('t',{name:'Library'},true);assert.equal(s.calls[0][1],'/api/v1/tenants/t/admin/knowledge/bases')
 s.result({...row,ownership:'personal'});await s.api.createEditableKnowledge('t',{name:'Mine'},false);assert.equal(s.calls[1][1],'/api/v1/tenants/t/knowledge/bases')
})
