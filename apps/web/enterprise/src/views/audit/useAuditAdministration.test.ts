import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import * as vue from 'vue'
import { fixture, flush } from '@nexus-web/core/test-utils/vueFixture'
function setup(t: Parameters<typeof fixture>[0], fail = false) {
  const f = fixture(t), auth = vue.reactive({ effectiveTenantId:'a', user:{id:'u'} }), context = vue.reactive({revision:0, allowed:true, can(){return this.allowed}})
  let finishRead: (value: unknown) => void = () => {}, finishExport: (value: unknown) => void = () => {}
  const row = {id:'r',actor_user_id:null,action:'tenant.updated',target_type:'tenant',target_id:'a',result:'success',metadata:{value:'text'},created_at:'2026-11-14'}
  const compiled = f.evaluate(readFileSync(new URL('./useAuditAdministration.ts',import.meta.url),'utf8'), {
    vue, '@nexus-web/core/stores/auth':{useAuthStore:()=>auth}, '../../stores/context':{useEnterpriseContext:()=>context},
    'vue-i18n':{useI18n:()=>({t:(key:string)=>key})},
    '@nexus-web/core/api/enterprise-audit':{
      validAuditExportRange:()=>true,
      listEnterpriseAudit:async(tenant:string)=>{if(fail)throw new Error('offline');return tenant==='a'?[{...row}]:new Promise(resolve=>{finishRead=resolve})},
      exportEnterpriseAudit:async()=>new Promise(resolve=>{finishExport=resolve}),
    },
  })
  const s=f.mount({setup(){return compiled.useAuditAdministration()}})
  return {...s,auth,context,row,finishRead:(value:unknown)=>finishRead(value),finishExport:(value:unknown)=>finishExport(value)}
}
test('读取/筛选/详情基于服务端记录，刷新不保留旧详情',async t=>{
 const s=setup(t);await flush();assert.equal(s.vm.loaded,true)
 s.vm.search='no match';assert.equal(s.vm.filteredRows.length,0)
 s.vm.search='tenant';assert.equal(s.vm.filteredRows.length,1)
 s.vm.inspect(s.vm.rows[0]);assert.equal(s.vm.selected.id,'r')
 await s.vm.load();assert.equal(s.vm.selected,null)
})
test('读取失败不当作成功空列表，无权限不显示旧数据',async t=>{
 const s=setup(t,true);await flush();assert.equal(s.vm.loaded,false);assert.equal(s.vm.error,'offline')
 s.context.allowed=false;await flush();assert.equal(s.vm.rows.length,0);assert.equal(s.vm.canRead,false)
})
test('切换企业使迟到列表和导出失效，不能触发旧企业下载',async t=>{
 const s=setup(t);await flush()
 const exporting=s.vm.download();s.auth.effectiveTenantId='b';await flush()
 s.finishExport({});await exporting;assert.equal(s.vm.exported,false)
 s.context.allowed=false;s.finishRead([{...s.row,target_id:'b'}]);await flush()
 assert.equal(s.vm.rows.length,0);assert.equal(s.vm.selected,null)
})
