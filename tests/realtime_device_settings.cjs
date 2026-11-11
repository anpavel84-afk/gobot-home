/* Production DOMContentLoaded adapter on a device page without an admin footer. */
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
class Element{
 constructor(tag){this.tag=tag;this.children=[];this.listeners={};this.value='';this.checked=false;this.dataset={};}
 append(...items){this.children.push(...items);for(const n of items)if(n&&typeof n==='object')n.parent=this;}
 addEventListener(kind,callback){this.listeners[kind]=callback;}
 setAttribute(key,value){this[key]=value;}
 after(item){if(this.parent){const index=this.parent.children.indexOf(this);this.parent.children.splice(index+1,0,item);item.parent=this.parent;}}
}
const body=new Element('body'),main=new Element('main'),details=new Element('details');body.dataset.conversationEngine='realtime';body.append(main);main.append(details);
const find=(node,id)=>{if(node.id===id)return node;for(const child of node.children||[]){const result=find(child,id);if(result)return result;}return null;};
const events={},requests=[];
const fetcher=async url=>{requests.push(url);return {json:async()=>({profile:{voice:{engine:'legacy',realtime_consent:false,speaker_identity_enabled:true,personalization_mode:'guest'}}})};};
const document={body,hidden:false,getElementById:id=>find(body,id),createElement:tag=>new Element(tag),createTextNode:t=>({textContent:t}),querySelector:s=>s==='main details'?details:s==='main'?main:null,addEventListener(){}};
const window={fetch:fetcher,addEventListener:(name,callback)=>events[name]=callback,GoBotClient:{},RTCPeerConnection:class{}};
vm.runInNewContext(fs.readFileSync('services/phone/dist/realtime.js','utf8'),{window,document,fetch:fetcher,navigator:{mediaDevices:{}},console,setTimeout,clearTimeout});
(async()=>{
 events.DOMContentLoaded();await Promise.resolve();await Promise.resolve();await Promise.resolve();
 assert.equal(document.getElementById('conversation-engine').value,'realtime');
 assert.equal(document.getElementById('realtime-consent').checked,false);
 assert.equal(document.getElementById('realtime-speaker-enabled').checked,true);
 assert.equal(details.children.length,1);
 assert.equal(window.GoBotRealtime.selected(),true);
 assert.deepEqual(requests,['/api/realtime/status','/api/device/profile']);
 const client=window.GoBotRealtime,confirmed=[];client.ready=true;client.sendText=async text=>confirmed.push(text);
 client.event({type:'turn_started',turn_id:'current',data:{}});
 client.event({type:'input_transcript',turn_id:'current',data:{text:'Какой самый ядовитый паук?',confirm_text_allowed:true}});
 assert(document.getElementById('realtime-heard').textContent.includes('паук'));
 const confirm=document.getElementById('realtime-confirm-question');assert.equal(confirm.hidden,false);
 assert.equal(confirmed.length,0);await confirm.onclick();await confirm.onclick();assert.deepEqual(confirmed,['Какой самый ядовитый паук?']);
 client.event({type:'input_transcript',turn_id:'old',data:{text:'Старое личное сообщение',confirm_text_allowed:true}});
 assert.equal(client.lastInputText,'Какой самый ядовитый паук?');
 client.event({type:'turn_started',turn_id:'timer',data:{}});
 client.event({type:'input_transcript',turn_id:'timer',data:{text:'Поставь таймер',confirm_text_allowed:false}});
 assert.equal(confirm.hidden,true);
 client.clearReview();assert.equal(client.lastInputText,'');assert.equal(document.getElementById('realtime-heard').hidden,true);
 console.log('Device settings mounted; B selected; no provider/microphone calls');
})().catch(e=>{console.error(e);process.exitCode=1;});
