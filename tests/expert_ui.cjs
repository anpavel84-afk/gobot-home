// Executes the actual expert panel with deterministic DOM/network, no provider or CLI.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
class Element{
 constructor(tag){this.tag=tag;this.children=[];this.value='';this.checked=false;this.hidden=false;this._text='';}
 append(...items){for(const item of items){if(item&&typeof item==='object')item.parent=this;this.children.push(item);}}
 replaceChildren(...items){this.children=[];this._text='';this.append(...items);}
 set textContent(t){this._text=String(t);this.children=[];}get textContent(){return this._text+this.children.map(n=>n.textContent||'').join('');}
 after(item){this.parent?.append(item);}get isConnected(){return !!this.parent;}
}
const main=new Element('main'),controls=new Element('div');main.append(controls);
const events={},requests=[];const doc={createElement:tag=>new Element(tag),querySelector:s=>s==='.device-controls'?controls:main};
const profile={profile:{voice:{expert_quota_consent:false}}};
let resolveStatus=null;
const status={enabled:false,blocked_reasons:['native_experts_disabled','confirmed_adult_profile_required','expert_budget_missing_or_expired'],profiles:[{profile:'SOL_HIGH',requested_label:'Sol High',model:'gpt-6.1-sol',effort:'high',metadata_verified:true,isolation_verified:true}],jobs:[],saved_jobs:[]};
const fetcher=async(url,options={})=>{requests.push([url,options]);if(resolveStatus&&url.startsWith('/api/realtime/experts'))return new Promise(r=>resolveStatus(r));return {ok:true,json:async()=>url==='/api/device/profile'?profile:status};};
let closed=0;const window={GoBotClient:{conversationId:()=> 'conv'},GoBotRealtime:{close:async()=>closed++},addEventListener:(k,f)=>events[k]=f};
vm.runInNewContext(fs.readFileSync('services/phone/dist/expert-ui.js','utf8'),{window,document:doc,fetch:fetcher,encodeURIComponent,Map,console});
(async()=>{
 events.DOMContentLoaded();const panel=window.GoBotExpertUI;await panel.refresh();
 assert(panel.status.textContent.includes('отдельный лимит CLI'));
 assert(panel.select.children.some(x=>x.textContent.includes('gpt-6.1-sol / high')));
 const job={job_id:'job-one',state:'running',expert:status.profiles[0],storage:'confirmed_profile'};
 panel.event({type:'expert_job',data:{job}});assert.equal(panel.cards.size,1);
 panel.event({type:'turn_started',data:{}});assert.equal(panel.cards.size,1);
 panel.event({type:'expert_result',data:{job,result:{actual_executor:job.expert,display_text:'17 — оценка. <script>not executable</script>'},voice_deferred:true}});
 assert(panel.cards.get(job.job_id).body.textContent.includes('<script>'));
 assert(panel.cards.get(job.job_id).text.textContent.includes('не перебивает'));
 panel.event({type:'expert_result',data:{job,result:{actual_executor:job.expert,display_text:'17 — оценка.'}}});assert.equal(panel.cards.size,1);
 let complete;resolveStatus=r=>complete=r;const refresh=panel.refresh();panel.clear();complete({ok:true,json:async()=>({...status,saved_jobs:[{...job,result:{display_text:'private old profile'}}]})});await refresh;
 assert.equal(panel.cards.size,0);assert(!panel.root.textContent.includes('private old profile'));
 resolveStatus=null;panel.consent.checked=true;await panel.consent.onchange();assert.equal(closed,1);
 const write=requests.find(([url,opts])=>url==='/api/device/profile'&&opts.method==='POST');assert(write);assert.equal(JSON.parse(write[1].body).voice.expert_quota_consent,true);
 assert(!requests.some(([url])=>url.includes('/sessions')||url.includes('openai.com')));
 console.log('Expert panel: exact model/effort, blockers, durable card, text-only rendering, stale profile clear, separate consent; no paid calls');
})().catch(e=>{console.error(e);process.exitCode=1;});
