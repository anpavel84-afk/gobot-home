/* Real admin event handlers with a fake transport; no browser/model calls. */
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
  document.activeElement=null;document.hidden=false;
  const window={matchMedia:()=>({matches:false,addEventListener(){}}),addEventListener(){}};
  const ids=['clock','timer','weather','utilities','memory','expert','visual'];
  const conversation={guidance:'',skills:Object.fromEntries(ids.map(id=>[id,true])),revision:'conversation-1'};
  let revision='profile-1',loseAck=false,failNext=false,ack=false;
  const writes=[],validations=[],history=[];
  const caps=()=>({version:1,settings_revision:conversation.revision,revision:'effective-'+conversation.revision,
    capabilities:Object.fromEntries(ids.map(id=>[id,{enabled:conversation.skills[id],implemented:true,
      state:conversation.skills[id]?'available':'disabled',...(id==='timer'?{display:'unavailable',signal:'unavailable'}:{})}]))});
  function snapshot(){return {ok:true,target:{id:'fixture'},revision,settings:{weather:{enabled:true,provider:'open_meteo',location_name:'Fixture city'},conversation},
    capabilities:caps(),changes:history,observed_at:Date.now()/1000,runtime:{status:'connected',gateway_fresh:true,
      device:{device_protocol_confirmed:true},brain:{sessions:[{ready:true,state:'ready',generation_allowed:true,
        capabilities:caps(),lifecycle:{conversation_settings:{state:ack?'applied':'pending',applied_settings_revision:ack?conversation.revision:null}}}]}}};}
  const memory={available:false,enabled:false,policy:{enabled:false,ttl_seconds:43200,persist:false,summarize:false,background:false,supplement:false}};
  const context={window,document,location:{hash:'#/skills',host:'sophia.test'},Date,Intl,URL,Blob,AbortController,
    crypto:require('node:crypto').webcrypto,setTimeout:()=>1,clearTimeout(){},setInterval(){},
    fetch:async(url,options)=>{
      let value,status=200;
      if(url.endsWith('/snapshot')||url.endsWith('/settings'))value=snapshot();
      else if(url.endsWith('/memory'))value={memory};
      else if(url.endsWith('/changes'))value={ok:true,changes:history};
      else if(url.endsWith('/settings/validate')){
        const body=JSON.parse(options.body);validations.push(body);value={ok:true};
      } else if(url.endsWith('/settings/apply')){
        const body=JSON.parse(options.body);writes.push(body);
        assert.deepEqual(Object.keys(body.patch),['conversation']);
        if(failNext){failNext=false;status=409;value={detail:'revision_conflict'};}
        else {
          assert.equal(body.expected_revision,revision);
          if(body.patch.conversation.guidance!==undefined)conversation.guidance=body.patch.conversation.guidance;
          Object.assign(conversation.skills,body.patch.conversation.skills||{});
          revision='profile-'+(writes.length+1);conversation.revision='conversation-'+(writes.length+1);
          const change={id:body.operation_id,at:Date.now()/1000,before:{},after:{conversation:{guidance_changed_to:{characters:conversation.guidance.length},skills:{...conversation.skills}}}};
          history.unshift(change);value={ok:true,settings:snapshot(),change};
          if(loseAck){loseAck=false;throw new Error('lost_reply');}
        }
      } else throw new Error('unexpected_request '+url);
      const copy=JSON.stringify(value);return {ok:status===200,status,json:async()=>JSON.parse(copy)};
    }};
  vm.createContext(context);
  for(const file of ['catalog.js','admin.js'])vm.runInContext(fs.readFileSync('services/phone/dist/admin/'+file,'utf8'),context);
  const settle=async()=>{for(let i=0;i<5;i++)await new Promise(resolve=>setImmediate(resolve));};
  const get=id=>document.getElementById(id);
  const click=async action=>{const el=new Element();el.dataset.action=action;document.handlers.click({target:el});await settle();};
  const type=async value=>{const el=new Element();el.id='conversation-guidance';el.value=value;document.handlers.input({target:el});await settle();};
  const toggle=async(id,value)=>{const el=new Element();el.dataset.skillEnabled=id;el.checked=value;document.handlers.change({target:el});await settle();};
  await settle();
  assert.equal(writes.length,0);assert(get('main').innerHTML.includes('Телевизор пока не подключён'));
  assert(get('main').innerHTML.includes('сигнал: не подключён'));
  await type('Объясняй коротко. <script>evil()</script>');await toggle('timer',false);
  assert(!get('reviewButton').disabled);get('reviewButton').handlers.click();await settle();
  assert.equal(validations.length,1);assert(get('reviewDialog').open);
  assert(get('reviewContent').innerHTML.includes('&lt;script&gt;'));
  assert(!get('reviewContent').innerHTML.includes('<script>'));
  assert.equal(writes.length,0);
  await click('save-settings');
  assert.equal(writes.length,1);assert.equal(conversation.skills.timer,false);
  assert.deepEqual(writes[0].patch,{conversation:{guidance:'Объясняй коротко. <script>evil()</script>',skills:{timer:false}}});
  assert(get('main').innerHTML.includes('ожидает безопасного момента'));
  assert.equal(get('reviewButton').disabled,true);
  ack=true;await click('refresh');
  assert(get('main').innerHTML.includes('подтверждены текущим голосовым сеансом'));
  await click('guidance-reset');assert(!get('reviewButton').disabled);
  await click('discard');assert.equal(get('reviewButton').disabled,true);
  assert.equal(writes.length,1);
  // A missing HTTP ACK is resolved by the exact durable operation ID, not an auto retry.
  loseAck=true;await type('Новая короткая версия');await click('review');await click('save-settings');
  assert.equal(writes.length,2);assert(get('main').innerHTML.includes('Результат сохранения уточняется'));
  await click('resolve-apply');assert.equal(writes.length,2);assert.equal(get('reviewButton').disabled,true);
  // An independent update blocks saving this draft; it never overwrites the server.
  failNext=true;await type('Черновик другой вкладки');await click('review');await click('save-settings');
  assert.equal(writes.length,3);assert.equal(conversation.guidance,'Новая короткая версия');
  assert(get('reviewError').textContent.includes('Настройки изменились в другой вкладке'));
  assert.equal(get('reviewButton').disabled,true);
  console.log('PASS: owner guidance + skill toggles, escaped review, exact patch, pending/applied ACK, no automatic retry, revision conflict.');
})().catch(error=>{console.error(error);process.exitCode=1;});
