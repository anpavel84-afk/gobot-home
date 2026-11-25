/* Exercise actual admin handlers, offline archive reads and uncertain writes. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class Element {
  constructor(){this.handlers={};this.dataset={};this.open=false;this.disabled=false;this.innerHTML='';this.textContent='';
    this.classList={add(){},remove(){},contains(){return false;},toggle(){}};}
  addEventListener(kind,fn){this.handlers[kind]=fn;} showModal(){this.open=true;} close(){this.open=false;}
  focus(){} setAttribute(){} closest(){return this;} getAttribute(){return null;}
}
(async()=>{
  const elements=new Map(),document=new Element();
  document.getElementById=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
  document.querySelector=()=>document.getElementById('workspace');document.querySelectorAll=()=>[];
  document.createElement=()=>({click(){}});
  document.activeElement=null;document.hidden=false;
  const window={matchMedia:()=>({matches:false,addEventListener(){}}),addEventListener(){}};
  const policy={write_enabled:false,read_enabled:false,retention_days:0,timezone:'America/Sao_Paulo'};
  const state={available:true,policy,revision:0,generation:0,counts:{turns:3,messages:6,topics:2,blocks:2,backlog:0},
    oldest_at:1795200000,newest_at:1795300000,last_write_at:1795300000,last_error:null,
    storage:'sqlite_plaintext_windows_acl',coverage:'since_enabled',private_archive:false,
    read_effective:false,lookup_blocked_by_skill:false};
  const writes=[],reads=[],receipts=new Map();
  let loseReply=false,dropBeforeCommit=false,denyNext=false,reportBlob=null;
  class ReportURL extends URL {static createObjectURL(blob){reportBlob=blob;return 'blob:fixture';}static revokeObjectURL(){}}
  const context={window,document,location:{hash:'#/privacy',host:'sophia.test'},
    Date,Intl,URL:ReportURL,Blob,AbortController,crypto:require('node:crypto').webcrypto,
    setTimeout:()=>1,clearTimeout(){},setInterval(){},
    fetch:async(url,options)=>{
      let value,status=200;
      if(url==='/api/sophia/admin/snapshot'){
        value={target:{id:'fixture'},revision:'profile-1',settings:{weather:{enabled:false,provider:'open_meteo',location_name:''}},
          changes:[],observed_at:Date.now()/1000,runtime:{status:'unavailable',brain:{sessions:[]}}};
      } else if(url==='/api/sophia/admin/memory'){
        status=409;value={detail:'voice_device_not_connected'};
      } else {
        assert(url.startsWith('/api/sophia/admin/archive'));
        if(options.method==='POST'){
          const body=JSON.parse(options.body);writes.push(body);
          assert.deepEqual(Object.keys(body).sort(),(body.action==='clear'?['action','confirm','expected_revision','operation_id']:['action','expected_revision','operation_id','values']).sort());
          assert(Number.isInteger(body.expected_revision));assert.match(body.operation_id,/^[A-Za-z0-9_-]{16,80}$/);
          if(dropBeforeCommit){dropBeforeCommit=false;throw new Error('request_not_delivered');}
          if(denyNext){denyNext=false;status=409;value={detail:'archive_change_requires_idle'};}
          else if(receipts.has(body.operation_id)){
            const saved=receipts.get(body.operation_id);assert.deepEqual(body,saved.body);
            value={accepted:true,archive:{...state,operation:{...saved.receipt,replayed:true}},observed_at:Date.now()/1000};
          } else if(body.expected_revision!==state.revision){status=409;value={detail:'archive_revision_conflict'};}
          else {
            if(body.action==='configure'){
              assert.deepEqual(Object.keys(body.values).sort(),Object.keys(policy).sort());Object.assign(policy,body.values);
            } else {assert.equal(body.confirm,true);state.counts={turns:0,messages:0,topics:0,blocks:0,backlog:0};}
            state.revision++;state.generation++;state.read_effective=policy.read_enabled&&!state.lookup_blocked_by_skill;
            const receipt={id:body.operation_id,applied_revision:state.revision,replayed:false};
            receipts.set(body.operation_id,{body,receipt});
            if(loseReply){loseReply=false;throw new Error('reply_lost_after_commit');}
            value={accepted:true,archive:{...state,operation:receipt},observed_at:Date.now()/1000};
          }
        } else {
          reads.push(url);const operationId=new URL(url,'https://fixture.invalid').searchParams.get('operation_id');
          const saved=operationId&&receipts.get(operationId);
          value={archive:{...state,...(operationId?{operation:saved?{...saved.receipt,replayed:true}:null}:{})},observed_at:Date.now()/1000};
        }
      }
      const copy=JSON.stringify(value);return {ok:status===200,status,json:async()=>JSON.parse(copy)};
    }};
  vm.createContext(context);
  for(const name of ['catalog.js','admin.js'])vm.runInContext(fs.readFileSync('services/phone/dist/admin/'+name,'utf8'),context);
  const settle=async()=>{for(let i=0;i<5;i++)await new Promise(resolve=>setImmediate(resolve));};
  const get=id=>document.getElementById(id);
  const click=async action=>{const element=new Element();element.dataset.action=action;document.handlers.click({target:element});await settle();};
  const toggle=async(key,checked)=>{const element=new Element();element.dataset.archiveField=key;element.checked=checked;document.handlers.change({target:element});await settle();};
  const input=async(key,value)=>{const element=new Element();element.dataset.archiveField=key;element.value=String(value);document.handlers.input({target:element});await settle();};
  const disabled=key=>new RegExp('<input[^>]*id="archive-'+key+'"[^>]*\\bdisabled\\b').test(get('main').innerHTML);
  await settle();
  assert(get('main').innerHTML.includes('Архив разговоров этой колонки'));
  assert(get('main').innerHTML.includes('До удаления'));assert(get('main').innerHTML.includes('3</dd>'));
  assert(!disabled('write_enabled'));assert.equal(writes.length,0);
  await click('export-report');
  const report=JSON.parse(await reportBlob.text());
  assert.equal(report.contains_location,false);assert(!JSON.stringify(report).includes('America/Sao_Paulo'));
  assert.deepEqual(report.conversation_archive.counts,state.counts);
  await toggle('write_enabled',true);await toggle('read_enabled',true);
  assert.equal(get('reviewButton').textContent,'Проверить архив');assert.equal(get('reviewButton').disabled,false);
  get('reviewButton').handlers.click();await settle();assert(get('settingsDialog').open);
  assert(get('dialogContent').innerHTML.includes('Выключение записи или поиска не удаляет'));assert.equal(writes.length,0);
  await click('archive-apply');assert.equal(writes.length,1);assert.equal(policy.write_enabled,true);
  assert.equal(policy.read_enabled,true);assert(!get('settingsDialog').open);
  await click('archive-clear');assert(get('dialogContent').innerHTML.includes('Личные архивы Family'));
  await click('close-dialog');assert.equal(writes.length,1);
  await toggle('write_enabled',false);await click('archive-review');await click('archive-apply');
  assert.equal(state.counts.turns,3);assert.equal(policy.read_enabled,true);
  state.lookup_blocked_by_skill=true;state.read_effective=false;await click('archive-refresh');
  assert(get('main').innerHTML.includes('Умение «Обращение к памяти» выключено'));
  assert(get('main').innerHTML.includes('Запись архива этим не выключается'));
  assert.equal(state.counts.turns,3);
  loseReply=true;await toggle('write_enabled',true);await click('archive-review');await click('archive-apply');
  const lost=writes.at(-1);assert.equal(policy.write_enabled,true);assert(disabled('write_enabled'));
  assert(get('toast').textContent.includes('Подтверждение операции с архивом не получено'));
  const count=writes.length;await click('archive-refresh');
  assert.equal(writes.length,count);assert(reads.at(-1).includes(lost.operation_id));assert(!disabled('write_enabled'));
  await click('archive-clear');await click('archive-clear-confirm');assert.equal(state.counts.turns,0);
  assert.equal(writes.at(-1).confirm,true);
  // A definitely unreceived operation is retried only by an explicit click,
  // retaining its identity and original revision to protect newer data.
  dropBeforeCommit=true;await toggle('read_enabled',false);await click('archive-review');await click('archive-apply');
  const missed=writes.at(-1);await click('archive-refresh');assert(disabled('read_enabled'));
  assert(get('main').innerHTML.includes('Повторить тот же запрос'));
  await click('archive-retry');assert.deepEqual(writes.at(-1),missed);assert.equal(policy.read_enabled,false);
  // Concurrent edits and invalid days must stop a new write.
  await toggle('read_enabled',true);state.revision++;policy.timezone='UTC';await click('archive-refresh');
  assert(disabled('read_enabled'));assert(get('main').innerHTML.includes('На сервере другая версия'));
  await click('archive-discard');assert(!disabled('read_enabled'));
  const retention=new Element();retention.dataset.archiveRetention='';retention.value='days';
  document.handlers.change({target:retention});await settle();
  await input('retention_days',-1);assert.equal(get('reviewButton').disabled,true);
  await input('retention_days',30);assert.equal(get('reviewButton').disabled,false);
  denyNext=true;await click('archive-review');await click('archive-apply');
  assert(get('main').innerHTML.includes('Сейчас идёт разговор'));assert(disabled('write_enabled'));
  assert.equal(policy.retention_days,0);await click('archive-refresh');assert(!disabled('write_enabled'));
  console.log('PASS: offline archive UI, separate recording/lookup, reviewed CAS, explicit clear, exact lost-reply receipt, bounded manual retry, concurrent edit and retention validation.');
})().catch(error=>{console.error(error);process.exitCode=1;});
