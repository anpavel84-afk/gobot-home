// Full shared browser.js -> STT fixture -> automatic SSE send. No paid/network calls.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const nodes=new Map(),store=new Map(),requests=[];let captures=0;
const ctx=new Proxy({measureText:s=>({width:String(s).length*6})},{get:(o,k)=>k in o?o[k]:(()=>{})});
class E{constructor(tag){this.tag=tag;this.children=[];this.options=[];this.value='';this.checked=false;this.classList={add(){},remove(){}};this.textContent='';}set id(v){this._id=v;nodes.set(v,this);}get id(){return this._id;}append(...children){this.children.push(...children);if(this.tag==='select'){this.options.push(...children);if(!this.value)this.value=children[0].value;}}replaceChildren(...c){this.children=c;}addEventListener(){}setAttribute(){}getContext(){return ctx;}setPointerCapture(){}}
function el(id){if(!nodes.has(id)){const n=new E('div');n.id=id;}return nodes.get(id);}
class Audio{constructor(){this.state='running';this.destination={};this.sampleRate=24000;}createBuffer(n,len,rate){return {getChannelData:()=>new Float32Array(len),duration:len/rate};}async resume(){this.state='running';}createGain(){return {gain:{value:1},connect(){},disconnect(){}};}createAnalyser(){return {fftSize:256,connect(){},getByteTimeDomainData:data=>data.fill(128)};}}
store.set('gobot.voice-settings',JSON.stringify({model:'mock',stt:'mock',tts:'openai',voice:'marin',speak:false,paid:false,paid_stt:false,quota:false,volume:'.8'}));
const env={console,Date,Math,Set,Map,Uint8Array,Uint8ClampedArray,Float32Array,DataView,JSON,Promise,Error,AbortController,TextDecoder,URLSearchParams,Blob,atob,performance,setTimeout,clearTimeout,crypto:require('node:crypto').webcrypto,
 document:{body:new E('body'),createElement:t=>new E(t),getElementById:el,addEventListener(){}},
 window:{isSecureContext:true,addEventListener(){},AudioContext:Audio},
 navigator:{locks:{request:async(n,o,cb)=>cb({name:n})},mediaDevices:{getUserMedia:async()=>({getTracks:()=>[{stop(){}}]})}},
 localStorage:{getItem:k=>store.get(k)||null,setItem:(k,v)=>store.set(k,v)},setInterval:()=>0,clearInterval(){},requestAnimationFrame(){},Image:class{},
 GoBotCapture:{async start(options){captures++;return {stop(){options.onStop(new Blob(['fixture'],{type:'audio/wav'}));},cancel(){}}}},
 fetch:async(url,options={})=>{
   if(url==='/api/chat/stream'){
     const body=JSON.parse(options.body);requests.push(body);const events=[{type:'tool_status',data:{provider:'mock',route:'FAST_CHAT'}},{type:'text_delta',data:{text:'Диагностический ответ.'}},{type:'final',data:{text:'Диагностический ответ.',mock:true,provider:'mock'}}].map(item=>({...item,turn_id:body.turn_id,conversation_id:body.conversation_id}));
     let read=false;return {ok:true,body:{getReader:()=>({read:async()=>read?{done:true}:(read=true,{done:false,value:new TextEncoder().encode(events.map(item=>'data: '+JSON.stringify(item)+'\n\n').join(''))})})}};
   }
   return {ok:true,json:async()=>url==='/api/device/profile'?{profile:env.profile,capabilities:{},activation:{configured:false}}:url==='/api/status'?{services:[],backend:{voice:{tts:{voices:['marin']}}}}:url.startsWith('/api/audio/transcribe')?{text:'Синтетический вопрос',provider:'mock',stt_ms:0}:url==='/api/device/timers'?{timers:[]}:{messages:[]}};
 }};
vm.createContext(env);for(const file of ['turn-trace.js','device-renderer.js','device.js','browser.js'])vm.runInContext(fs.readFileSync('services/phone/dist/'+file,'utf8'),env);
env.profile=JSON.parse(JSON.stringify(env.window.GoBotDeviceRenderer.defaults));env.profile.client_id='browser-device-fixture';env.profile.interaction_mode='hold';
(async()=>{
 const app=new env.window.GoBotDeviceApp();await app.init();await app.enable();assert(app.enabled);
 const conversation=store.get('gobot.conversation');await app.press();app.release();
 for(let i=0;i<30&&!requests.length;i++)await new Promise(r=>setTimeout(r,5));
 assert.equal(captures,1);assert.equal(requests.length,1);assert.equal(requests[0].client_kind,'device');assert(requests[0].utterance_id);assert.equal(requests[0].conversation_id,conversation);assert.equal(requests[0].speak,false);assert.equal(requests[0].paid_tts_consent,false);
 await new Promise(r=>setTimeout(r,10));assert.equal(requests.length,1);app.pause('Готово');
 console.log('Shared client device vertical fixture: hold -> STT -> auto-send, one turn, same conversation and no new permissions passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
