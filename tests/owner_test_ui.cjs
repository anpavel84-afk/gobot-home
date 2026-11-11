const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
class Node{constructor(tag,text=''){this.tag=tag;this.children=[];this.textContent=text;this.value='';}append(...x){this.children.push(...x);}after(x){this.sibling=x;}replaceChildren(...x){this.children=x;}}
const events={},nodes={},requests=[],controls=new Node('div');let closed=0;
const state={authorized:true,enabled:true,policy:{realtime_model:'gpt-realtime-2.1-mini',audio_preset:'baseline',api_estimate_usd_per_day:10,realtime_responses_per_day:500,expert_jobs_per_day:20,image_attempts_per_day:20,enabled:true,experts_enabled:true,images_enabled:true,device_settings_enabled:true},attempts_today:{},estimated_usd_including_pending_reserves:0,readiness:{realtime:{configured:true,implemented:true,acceptance:'synthetic'}}};
const document={createElement:t=>new Node(t),getElementById:k=>nodes[k]||null,querySelector:()=>controls};
const window={addEventListener:(k,f)=>events[k]=f,GoBotRealtime:{id:'active-fixture',close:async()=>closed++},GoBotExpertUI:{refresh:async()=>{}}};
const fetch=async(url,opts={})=>{requests.push([url,opts]);return {ok:true,json:async()=>state};};
vm.runInNewContext(fs.readFileSync('services/phone/dist/owner-test-ui.js','utf8'),{window,document,fetch,performance,JSON,Object,Number});
(async()=>{
 await events.DOMContentLoaded();const panel=window.GoBotOwnerTest;assert(panel.root);assert.equal(panel.model.value,'gpt-realtime-2.1-mini');assert.equal(panel.audio.value,'baseline');
 panel.diagnostic({stage:'gpt_transcribe',text:'SYNTHETIC_PRIVATE'});assert(panel.transcript.textContent.includes('SYNTHETIC_PRIVATE'));
 panel.diagnostic({stage:'answer_delta',text:'answer'});panel.diagnostic({stage:'closed'});assert.equal(panel.transcript.textContent,'');assert.equal(panel.spoken.textContent,'');
 panel.model.value='gpt-realtime-2.1';await panel.save(false);assert.equal(closed,1);
 const writes=requests.filter(([,opts])=>opts.method==='POST');assert.equal(writes.length,1);assert.equal(JSON.parse(writes[0][1].body).realtime_model,'gpt-realtime-2.1');
 assert(requests.every(([url])=>url==='/api/realtime/owner-test'));
 console.log('Owner UI: baseline unchanged, exact model selection, no auto-paid start, transcript cleared on close');
})().catch(e=>{console.error(e);process.exitCode=1;});
