/* Production Live client + unified coordinator + fake media/HTTP. No paid calls. */
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const nodes=new Map(),callbacks={},requests=[],tracks=[],store=new Map();let serial=0;
class E{constructor(){this.children=[];this.dataset={unified:'true',conversationEngine:'live'};this.value='';this.checked=false;}set id(v){this._id=v;nodes.set(v,this);}get id(){return this._id;}append(...x){this.children.push(...x);}after(){}setAttribute(){}closest(){return this;}pause(){}async play(){}}
const el=id=>{if(!nodes.has(id)){const n=new E();n.id=id;}return nodes.get(id);};el('conversation-engine').value='live';
class Peer{constructor(){this.connectionState='connected';}createDataChannel(){return {};}addTrack(){}async createOffer(){return {sdp:'fixture-sdp'};}async setLocalDescription(v){this.localDescription=v;}async setRemoteDescription(){}close(){this.connectionState='closed';}}
class Context{constructor(){this.state='running';}async resume(){}async close(){this.state='closed';}createAnalyser(){return {fftSize:512,getFloatTimeDomainData:a=>a.fill(0)};}createMediaStreamSource(){return {connect(){},disconnect(){}};}}
const fetch=async(url,options={})=>{const body=options.body?JSON.parse(options.body):null;requests.push({url,body});return {ok:true,json:async()=>
 url.endsWith('/readiness')?{manual_authorized:true,grant_revision:'fixture'}:
 url.endsWith('/status')?{enabled:true}:
 url==='/api/live/sessions'?{model:'gpt-live-1',delegation:'client',configuration_confirmed:true,sdp:'fixture-answer',mode_conversation_id:'flow'}:
 url.includes('/modes/')?{active:body.action!=='end',mode:body.action==='live'?'live':'legacy',mode_conversation_id:'flow',provider_closed:true}:
 {closed:true,final_usage_confirmed:true}};};
const window={fetch,addEventListener:(name,cb)=>(callbacks[name]||=[]).push(cb),
 GoBotNativeVoice:{prototype:{async acquire(){this.releaseLock=()=>{};},async gather(){}}},
 GoBotClient:{getSettings:()=>({voice:'marin',remember:false,volume:.8}),conversationId:()=> 'conversation',applyNativeEvent(){},saveSettings(){},
  cancelRecording(){},stop(){},async unlockAudio(){},audioSnapshot:()=>({playing:false,feedback_playing:false}),isRecording:()=>false},
 GoBotHooks:{clientKind:'device'}};
window.goBotDevice={manager:{},profile:{conversation:{}},enabled:false,status(){},pause(){this.enabled=false;},checkFollowup(){this.followupOpened=true;},
 async enable(){if(el('conversation-engine').value==='live')await window.GoBotLive.start();this.enabled=true;}};
window.GoBotHooks.onNativeClosed=()=>window.goBotDevice.enabled=false;
const env={window,fetch,document:{body:new E(),getElementById:el,createElement:()=>new E(),createTextNode:t=>({textContent:t}),querySelector:()=>new E(),addEventListener(){}},
 navigator:{mediaDevices:{getSupportedConstraints:()=>({}),getUserMedia:async()=>{const track={enabled:true,getSettings:()=>({}),stop(){this.stopped=true;}};tracks.push(track);return {getAudioTracks:()=>[track],getTracks:()=>[track]};}}},
 localStorage:{getItem:k=>store.get(k),setItem:(k,v)=>store.set(k,v)},AudioContext:Context,RTCPeerConnection:Peer,EventSource:class{close(){}},AbortController,performance,Float32Array,
 crypto:{randomUUID:()=> 'id-'+(++serial)},setTimeout,clearTimeout,setInterval:()=>0,requestAnimationFrame(){},console};
vm.createContext(env);for(const file of ['live.js','unified.js'])vm.runInContext(fs.readFileSync('services/phone/dist/'+file,'utf8'),env);
const settle=async()=>{for(let i=0;i<12;i++)await new Promise(r=>setImmediate(r));};
(async()=>{
 for(const callback of callbacks.DOMContentLoaded)await callback();
 const app=window.goBotDevice,c=window.GoBotLive,u=window.GoBotUnified;
 await app.enable();assert(c.ready&&app.enabled);assert.equal(u.id,'flow');
 assert.equal(requests.find(r=>r.url==='/api/live/sessions').body.conversation_mode,'unified');
 c.event({type:'conversation_mode_switching',data:{target:'legacy',confirmed:false}});
 assert(!tracks.at(-1).enabled&&c.output.muted);assert.equal(u.mode,'live','Announcement is not completed switch');
 c.event({type:'closing',data:{reason:'mode_switch'}});
 c.event({type:'closed',data:{reason:'mode_switch',final_usage_confirmed:true,mode:{active:true,mode:'legacy',mode_conversation_id:'flow',provider_closed:true}}});
 await c.closing;await settle();
 assert.equal(u.mode,'legacy');assert(app.enabled&&app.followupOpened);assert.equal(c.id,null);assert(tracks[0].stopped);
 assert.equal(u.requestFields().mode_conversation_id,'flow');assert.equal(u.requestFields().remember,false);
 assert.equal(requests.filter(r=>r.url==='/api/live/sessions').length,1);
 await u.change('live');assert.equal(u.mode,'live');assert(c.ready);
 assert.equal(requests.filter(r=>r.url==='/api/live/sessions').length,2);
 assert.equal(requests.filter(r=>r.url==='/api/live/sessions').at(-1).body.mode_conversation_id,'flow');
 await u.end();assert.equal(u.mode,'live');assert.equal(u.id,null);assert(!c.ready);assert(!app.enabled);
 assert.equal(requests.filter(r=>r.url==='/api/live/sessions').length,2,'End cannot open a paid session');
 assert(!requests.some(r=>r.url.includes('api.openai.com')));
 console.log(JSON.stringify({production_live_and_unified:true,C_A_C:true,single_microphone:true,default_reset_without_create:true,provider_calls:0,iphone:false}));
})().catch(e=>{console.error(e);process.exitCode=1;});
