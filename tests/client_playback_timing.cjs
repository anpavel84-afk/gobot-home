// Real shared browser parser/scheduler with a fake AudioContext, no browser/provider.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const nodes=new Map(),posted=[],storage=new Map();let cancelled=false;
class E{constructor(){this.value='';this.checked=false;this.options=[];this.classList={add(){},remove(){}};}append(n){this.options.push(n);}replaceChildren(){}addEventListener(){}setAttribute(){}}
const el=id=>{if(!nodes.has(id))nodes.set(id,new E());return nodes.get(id);};
class Audio{
 constructor(){this.state='running';this.origin=performance.now();this.sampleRate=24000;this.destination={};}get currentTime(){return (performance.now()-this.origin)/1000;}async resume(){}
 createGain(){return {gain:{value:1,setValueAtTime(){},linearRampToValueAtTime(){},cancelScheduledValues(){}},connect(){},disconnect(){}};}
 createBuffer(n,length,rate){const pcm=new Float32Array(length);return {getChannelData:()=>pcm,duration:length/rate};}
 createBufferSource(){const source={connect(){},start:at=>{source.timer=setTimeout(()=>source.onended?.(),Math.max(0,((at||0)-this.currentTime+source.buffer.duration)*1000));},stop(){clearTimeout(source.timer);source.onended?.();}};return source;}
}
storage.set('gobot.voice-settings',JSON.stringify({model:'mock',stt:'mock',tts:'openai',voice:'marin',speak:true,paid:false,paid_stt:false,quota:false,volume:'.8'}));
const sandbox={console,performance,Date,Math,Map,Set,JSON,Promise,Error,AbortController,TextDecoder,Uint8Array,Float32Array,DataView,URLSearchParams,atob,crypto:require('node:crypto').webcrypto,setTimeout,clearTimeout,
 document:{getElementById:el,createElement:()=>new E()},window:{addEventListener(){},AudioContext:Audio,GoBotHooks:{clientKind:'device'}},localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v)},
 fetch:async(url,options={})=>{
  if(url.startsWith('/api/telemetry/')){posted.push(JSON.parse(options.body));return {ok:true,json:async()=>({})};}
  if(url==='/api/chat/stream'){
   const req=JSON.parse(options.body);const quiet=Buffer.alloc(2400),sound=Buffer.alloc(480);sound.writeInt16LE(1200,0);
   const events=[{type:'text_delta',data:{text:'Ответ.'}},...[[0,quiet],[1,sound]].map(([seq,pcm])=>({type:'audio_chunk',data:{audio_id:req.turn_id,seq,format:'pcm_s16le',sample_rate:24000,pcm:pcm.toString('base64')}})),{type:'final',data:{mock:true,provider:'mock'}}];
   let done=false;return {ok:true,body:{getReader:()=>({read:async()=>done?{done:true}:(done=true,{done:false,value:new TextEncoder().encode(events.map(e=>'data: '+JSON.stringify({...e,turn_id:req.turn_id})+'\n\n').join(''))})})}};
  }
  return {ok:true,json:async()=>url==='/api/status'?{services:[],backend:{voice:{tts:{voices:['marin']}}}}:{messages:[]}};
 }};
vm.createContext(sandbox);for(const file of ['turn-trace.js','browser.js'])vm.runInContext(fs.readFileSync('services/phone/dist/'+file,'utf8'),sandbox);
(async()=>{
 el('question').value='Синтетическая проверка';await sandbox.window.GoBotClient.send();await new Promise(r=>setTimeout(r,180));
 const trace=sandbox.window.GoBotClient.trace(),events=trace.snapshot().events;
 const received=events.find(e=>e.name==='first_audio_received'),heard=events.find(e=>e.name==='first_answer_playback');assert(received&&heard);assert(heard.ms-received.ms>=70,'leading silent chunk must not count as first useful output');
 assert.equal(events.filter(e=>e.name==='first_answer_playback').length,1);assert(posted.length<=4,'no telemetry upload per PCM chunk');
 el('question').value='Отменяемый ответ';await sandbox.window.GoBotClient.send();sandbox.window.GoBotClient.stop();await new Promise(r=>setTimeout(r,160));
 assert(!sandbox.window.GoBotClient.trace().events.some(e=>e.name==='first_answer_playback'));
 console.log('Playback fixture: silent payload excluded, actual shared scheduling, one ACK, bounded telemetry and cancellation passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
