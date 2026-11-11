/* Real coordinator with fake existing A/C clients. No paid calls or Safari claim. */
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const nodes=new Map(),callbacks={},requests=[],events=[],store=new Map();
class E{constructor(){this.children=[];this.dataset={unified:'true',conversationEngine:'live'};this.value='';}set id(v){this._id=v;nodes.set(v,this);}get id(){return this._id;}append(...v){this.children.push(...v);}after(){}setAttribute(){}closest(){return this;}}
const el=id=>{if(!nodes.has(id)){const n=new E();n.id=id;}return nodes.get(id);};
const window={addEventListener:(k,v)=>callbacks[k]=v,GoBotHooks:{clientKind:'device'},
 GoBotClient:{saveSettings(){},cancelRecording(){events.push('cancel-capture');},stop(){events.push('stop-queue');},async unlockAudio(){},isRecording:()=>false,audioSnapshot:()=>({playing:false,feedback_playing:false})},
 GoBotLive:{id:null,async start(){events.push('start-live');},async close(){events.push('close-live');this.id=null;}},
 goBotDevice:{manager:{},profile:{conversation:{}},enabled:false,pause(){events.push('pause');this.enabled=false;},async enable(){events.push('enable-'+el('conversation-engine').value);this.enabled=true;},checkFollowup(){events.push('followup');},status(v){events.push(v);}}};
const env={window,document:{body:new E(),getElementById:el,createElement:()=>new E(),querySelector:()=>new E(),addEventListener(){}},localStorage:{getItem:k=>store.get(k),setItem:(k,v)=>store.set(k,v)},setInterval:()=>0,setTimeout,console,
 fetch:async(url,options={})=>{const body=options.body?JSON.parse(options.body):null;requests.push({url,body});return {ok:true,json:async()=>url.endsWith('/readiness')?{manual_authorized:false}:{active:body?.action!=='end',mode_conversation_id:'flow',mode:body?.action==='live'?'live':'legacy',provider_closed:true}};}};
vm.createContext(env);vm.runInContext(fs.readFileSync('services/phone/dist/unified.js','utf8'),env);
(async()=>{
 await callbacks.DOMContentLoaded();await new Promise(r=>setImmediate(r));
 const u=window.GoBotUnified;assert.equal(u.mode,'live');assert(!requests.some(x=>x.url.includes('/sessions')));
 const state={active:true,mode:'legacy',mode_conversation_id:'flow',provider_closed:false};
 await u.apply(state);assert.equal(u.mode,'live');assert(!events.includes('enable-legacy'));
 await u.liveClosed({...state,provider_closed:true},true,'mode_switch');
 assert.equal(u.mode,'legacy');assert.equal(u.id,'flow');assert(events.includes('enable-legacy')&&events.includes('followup'));
 assert.equal(window.goBotDevice.profile.conversation.followup_seconds,10);
 assert.equal(u.requestFields().remember,false);
 await u.change('live');assert.equal(u.mode,'live');assert(events.includes('enable-live'));
 await u.apply({...state,provider_closed:true});const before=events.filter(x=>x==='enable-live').length;
 await u.end('idle_timeout');assert.equal(u.mode,'live');assert.equal(u.id,null);
 assert.equal(events.filter(x=>x==='enable-live').length,before,'End must not open a paid C session');
 assert(requests.some(x=>x.body?.action==='end'));
 const failed=events.filter(x=>x==='enable-legacy').length;
 await u.liveClosed({...state,provider_closed:false},false,'mode_switch');
 assert.equal(events.filter(x=>x==='enable-legacy').length,failed,'Unconfirmed close must block A');
 console.log(JSON.stringify({unified_client:true,default_c:true,close_before_a:true,idle_resets_without_start:true,new_paid_calls:0,physical_iphone:false}));
})().catch(e=>{console.error(e);process.exitCode=1;});
