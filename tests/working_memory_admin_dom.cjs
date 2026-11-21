/* Pure JavaScript interaction/state checks when a browser cannot be launched. */
'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

class Element {
  constructor(){this.handlers={};this.dataset={};this.open=false;this.disabled=false;this.innerHTML='';this.textContent='';this.classes=new Set();
    this.classList={add:x=>this.classes.add(x),remove:x=>this.classes.delete(x),contains:x=>this.classes.has(x),toggle:(x,on)=>on?this.classes.add(x):this.classes.delete(x)};}
  addEventListener(kind,fn){this.handlers[kind]=fn;}
  showModal(){this.open=true;} close(){this.open=false;} focus(){} setAttribute(){}
  closest(){return this;} getAttribute(){return null;}
}

(async()=>{
  const elements=new Map(),document=new Element();
  document.getElementById=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
  document.querySelector=()=>document.getElementById('workspace');
  document.querySelectorAll=()=>[];document.activeElement=null;document.hidden=false;
  const window={matchMedia:()=>({matches:false,addEventListener(){}}),addEventListener(){}};
  const writes=[];
  const policy={enabled:true,ttl_seconds:43200,persist:true,summarize:true,background:true,supplement:true};
  const state={available:true,enabled:true,policy,working:{available_exchanges:4,completed_exchanges:3,
    version:7,restored_exchanges:2,persisted:true,summary_kind:'grounded_semantic_working_summary'},
    lookup:{state:'delivered_late',queries:8,useful_results:3,supplements:1,last_lookup_ms:14},
    summary_worker:{last_state:'applied',global_tokens_used_or_reserved:800,daily_token_limit:4000,unknown_usage_attempts:0}};
  let failNext=false,loseAck=false;
  const context={window,document,location:{hash:'#/privacy',host:'sophia.test'},
    Date,Intl,URL,Blob,AbortController,crypto:require('node:crypto').webcrypto,
    setTimeout:()=>1,clearTimeout(){},setInterval(){},
    fetch:async(url,options)=>{
      let value,status=200;
      if(url==='/api/sophia/admin/snapshot')value={target:{id:'fixture'},revision:'one',
        settings:{weather:{enabled:true,provider:'open_meteo',location_name:'Fixture city'}},changes:[],
        observed_at:Date.now()/1000,runtime:{status:'connected',gateway_fresh:true,device:{device_protocol_confirmed:true},
          brain:{sessions:[{ready:true,state:'ready',generation_allowed:true}]}}};
      else {
        assert.equal(url,'/api/sophia/admin/memory');
        if(options.method==='POST'){
          const body=JSON.parse(options.body);writes.push(body);
          if(failNext){failNext=false;status=409;value={detail:'working_memory_change_requires_idle'};}
          else {
            if(body.action==='configure'){
              assert.deepEqual(Object.keys(body).sort(),['action','values']);
              assert.deepEqual(Object.keys(body.values).sort(),Object.keys(policy).sort());
              Object.assign(policy,body.values);state.enabled=policy.enabled;
            } else {assert.deepEqual(body,{action:'clear',confirm:true});state.working.available_exchanges=0;}
            if(loseAck){loseAck=false;throw new Error('network_reply_lost');}
            value={memory:state,accepted:true,observed_at:Date.now()/1000};
          }
        } else value={memory:state,observed_at:Date.now()/1000};
      }
      const copy=JSON.stringify(value);
      return {ok:status===200,status,json:async()=>JSON.parse(copy)};
    }};
  vm.createContext(context);
  for(const filename of ['catalog.js','admin.js'])vm.runInContext(fs.readFileSync('services/phone/dist/admin/'+filename,'utf8'),context);
  const settle=async()=>{for(let i=0;i<5;i++)await new Promise(resolve=>setImmediate(resolve));};
  const get=id=>document.getElementById(id);
  const click=async action=>{const el=new Element();el.dataset.action=action;document.handlers.click({target:el});await settle();};
  const change=async(key,value)=>{const el=new Element();el.dataset.memoryField=key;el.value=String(value);el.checked=value;
    document.handlers.change({target:el});await settle();};
  const disabled=key=>new RegExp('<(?:select|input)[^>]*id="memory-'+key+'"[^>]*\\bdisabled\\b').test(get('main').innerHTML);
  await settle();
  assert.equal(disabled('ttl'),false);
  assert(get('main').innerHTML.includes('800 / 4000 токенов'));assert.equal(writes.length,0);
  await change('ttl_seconds',14400);
  assert.equal(get('reviewButton').disabled,false);assert.equal(get('reviewButton').textContent,'Проверить память');
  get('reviewButton').handlers.click();await settle();
  assert(get('settingsDialog').open);assert(get('dialogContent').innerHTML.includes('12 ч'));
  assert(get('dialogContent').innerHTML.includes('4 ч'));assert.equal(writes.length,0);
  await click('memory-apply');
  assert.equal(policy.ttl_seconds,14400);assert.equal(writes.length,1);
  assert(!get('settingsDialog').open);assert.equal(get('reviewButton').disabled,true);
  await click('memory-clear');await click('close-dialog');assert.equal(writes.length,1);
  await click('memory-clear');await click('memory-clear-confirm');
  assert.equal(writes.length,2);assert.equal(state.working.available_exchanges,0);
  failNext=true;await change('ttl_seconds',3600);await click('memory-review');await click('memory-apply');
  assert.equal(writes.length,3);assert.equal(policy.ttl_seconds,14400);
  assert(disabled('ttl'));assert(get('main').innerHTML.includes('Сейчас идёт разговор'));
  await click('memory-refresh');assert(!disabled('ttl'));
  loseAck=true;await click('memory-review');await click('memory-apply');
  assert.equal(writes.length,4);assert.equal(policy.ttl_seconds,3600);assert(disabled('ttl'));
  assert(get('toast').textContent.includes('Подтверждение изменения памяти не получено'));
  await click('memory-refresh');assert(!disabled('ttl'));assert.equal(get('reviewButton').disabled,true);
  assert.equal(writes.length,4);
  await change('ttl_seconds',86400);policy.ttl_seconds=43200;await click('memory-refresh');
  assert(disabled('ttl'));assert(get('main').innerHTML.includes('Загрузить значения сервера'));
  await click('memory-discard');assert(!disabled('ttl'));assert.equal(get('reviewButton').disabled,true);
  assert.equal(writes.length,4);
  console.log('PASS: memory UI state, reviewed policy, explicit clear, idle refusal, unknown outcome readback, concurrent policy conflict.');
})().catch(error=>{console.error(error);process.exitCode=1;});
