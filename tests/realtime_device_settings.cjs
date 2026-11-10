/* Production DOMContentLoaded adapter on a device page without an admin footer. */
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
class Element{
 constructor(tag){this.tag=tag;this.children=[];this.listeners={};this.value='';this.checked=false;this.dataset={};}
 append(...items){this.children.push(...items);for(const n of items)if(n&&typeof n==='object')n.parent=this;}
 addEventListener(kind,callback){this.listeners[kind]=callback;}
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
 console.log('Device settings mounted; B selected; no provider/microphone calls');
})().catch(e=>{console.error(e);process.exitCode=1;});
