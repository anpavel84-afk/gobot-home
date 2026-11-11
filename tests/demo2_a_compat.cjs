const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const events={},requests=[];
class Storage{constructor(){this.map=new Map();}getItem(k){return this.map.get(String(k))??null;}setItem(k,v){this.map.set(String(k),String(v));}removeItem(k){this.map.delete(String(k));}}
class Element{constructor(tag){this.tag=tag;this.children=[];}append(...x){this.children.push(...x);}after(x){this.sibling=x;}}
const storage=new Storage(),sessionStorage=new Storage();
const bVoice=JSON.stringify({voice:'cedar',paid:false});storage.setItem('gobot.voice-settings',bVoice);storage.setItem('gobot.conversation','B-private-conversation');
let restored=0,timerId=0;const timers=new Map();
const controls=new Element('div'),doc={createElement:t=>new Element(t),createTextNode:text=>({textContent:text}),querySelector:()=>controls,getElementById:()=>null};
const window={GoBotClient:{restoreSettings:()=>restored++},goBotDevice:{enabled:false,enable(){this.enabling=true;return new Promise(()=>{});},pause(message){this.enabling=false;this.enabled=false;this.paused=message;}},addEventListener:(k,f)=>events[k]=f};
const fetch=async(url)=>{requests.push(url);return {ok:true,json:async()=>({manual_authorized:true,grant_revision:'revision-1',cli_ready:true,openai_key_configured:true})};};
vm.runInNewContext(fs.readFileSync('services/phone/dist/demo2-a-compat.js','utf8'),{window,document:doc,localStorage:storage,fetch,Set,JSON,Object,String,setTimeout:(fn,ms)=>{timers.set(++timerId,{fn,ms});return timerId;},clearTimeout:id=>timers.delete(id)});
(async()=>{
 assert.equal(storage.getItem('gobot.voice-settings'),null);assert.equal(storage.getItem('gobot.conversation'),null);
 assert.equal(storage.map.get('gobot.voice-settings'),bVoice);
 storage.setItem('gobot.conversation','A-conversation');assert.equal(storage.map.get('gobot.conversation'),'B-private-conversation');
 sessionStorage.setItem('gobot.conversation','session-only');assert.equal(sessionStorage.map.get('gobot.conversation'),'session-only');
 await events.DOMContentLoaded();assert.equal(restored,1);
 assert.equal(JSON.parse(storage.getItem('gobot.voice-settings')).paid_stt,true);assert.equal(storage.getItem('gobot.cli-quota-consent'),'true');
 storage.setItem('gobot.voice-settings',JSON.stringify({paid:false,paid_stt:false,quota:false}));storage.setItem('gobot.cli-quota-consent','false');
 await events.DOMContentLoaded();assert.equal(restored,1);assert.equal(JSON.parse(storage.getItem('gobot.voice-settings')).paid,false);
 assert.equal(storage.getItem('gobot.cli-quota-consent'),'false');assert.equal(storage.map.get('gobot.voice-settings'),bVoice);
 assert(requests.every(x=>x==='/api/demo2/a/readiness'));
 const enabling=window.goBotDevice.enable();assert(window.goBotDevice.enabling);
 [...timers.values()].find(t=>t.ms===18000).fn();await enabling;
 assert(!window.goBotDevice.enabled&&window.goBotDevice.paused.includes('Safari'));assert.equal(timers.size,0);
 console.log('A isolated from B; bound manual grant applied once; local revocation retained; no audio/model/provider calls');
})().catch(e=>{console.error(e);process.exitCode=1;});
