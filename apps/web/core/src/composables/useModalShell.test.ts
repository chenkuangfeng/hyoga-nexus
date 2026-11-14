import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import * as vue from 'vue'
import { fixture } from '../test-utils/vueFixture'
test('卸载和目标重置会销毁旧未保存确认，迟到确认不能关闭后续编辑器',t=>{
 const f=fixture(t),dialogs:{onConfirm:()=>void}[]=[],state=vue.ref('clean');let closed=0,destroyed=0
 const module=f.evaluate(readFileSync(new URL('./useModalShell.ts',import.meta.url),'utf8'),{vue,'vue-i18n':{useI18n:()=>({t:(key:string)=>key})},'tdesign-vue-next':{DialogPlugin:{confirm:(options:{onConfirm:()=>void})=>{dialogs.push(options);return {destroy(){destroyed++}}}}},'../utils/unsavedChanges':{registerUnsavedChanges:()=>()=>{}}})
 const s=f.mount({setup(){return module.useModalShell({visible:()=>true,snapshot:()=>state.value,close:()=>{closed++}})}})
 state.value='changed';s.vm.requestClose();s.vm.cancelPending();dialogs[0].onConfirm();assert.equal(closed,0)
 s.vm.requestClose();s.close();dialogs[1].onConfirm();assert.equal(closed,0);assert.equal(destroyed,2)
})
