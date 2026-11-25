/* Production NativeVoice, fake media/provider: no paid calls, no human acoustic claim. */
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
let now=0,serial=0,client,gate=null,signal=0;const timers=new Map(),requests=[],closures=[];
const elements={'realtime-consent':{checked:true},'conversation-engine':{value:'realtime'}};
const track={enabled:false,stop(){this.stopped=true;}},stream={active:true,getTracks:()=>[track],getAudioTracks:()=>[track]};
class Context{constructor(){this.state='running';}async resume(){}async close(){this.state='closed';}createAnalyser(){return {fftSize:256,getByteTimeDomainData:a=>a.fill(signal?132:128)};}createMediaStreamSource(){return {connect(){},disconnect(){}};}}
class Peer{constructor(){this.iceGatheringState='complete';}addTransceiver(){return {sender:{replaceTrack:async()=>{}}};}async createOffer(){return {type:'offer',sdp:'fixture'};}async setLocalDescription(v){this.localDescription=v;}async setRemoteDescription(){}close(){}}
const response=value=>({ok:true,json:async()=>value});
async function fetcher(url,options={}){
 const body=options.body?JSON.parse(options.body):{};requests.push({url,body});
 if(url.endsWith('/status'))return response({automatic_dialogue_version:1,budget:{enabled:true,sessions_remaining:10}});
 if(url.endsWith('/sessions'))return response({configuration_confirmed:true,model:'gpt-realtime-2.1-mini',sdp:'fixture'});
 if(body.action==='listen'&&gate)return new Promise(resolve=>{gate.resolve=()=>resolve(response({accepted:true}));});
 if(body.action==='playback_stopped')client.event({type:'turn_complete',turn_id:client.currentTurn,data:{}});
 return response({accepted:true,hangup_confirmed:true});
}
const window={fetch:fetcher,RTCPeerConnection:Peer,addEventListener(){},GoBotClient:{getSettings:()=>({voice:'marin',volume:.8,remember:false}),conversationId:()=> 'fixture-conversation'},
 goBotDevice:{profile:{conversation:{followup_enabled:true,echo_guard_ms:350,followup_seconds:10}},status(){}},GoBotHooks:{onNativeClosed:e=>closures.push(e)}};
const sandbox={window,navigator:{mediaDevices:{getUserMedia:async()=>stream},locks:{request:async(n,o,f)=>f({})}},document:{hidden:false,addEventListener(){},getElementById:id=>elements[id]||null,createTextNode:t=>t,createElement:()=>({play:async()=>{},pause(){}})},
 AudioContext:Context,EventSource:class{close(){}},crypto:{randomUUID:()=> 'fixture-'+(++serial)},performance:{now:()=>now},AbortController,Uint8Array,Float32Array,requestAnimationFrame(){},
 setTimeout:(fn,ms)=>{const id=++serial;timers.set(id,{fn,ms});return id;},clearTimeout:id=>timers.delete(id),console};
vm.createContext(sandbox);vm.runInContext(fs.readFileSync('services/phone/dist/realtime.js','utf8'),sandbox);
const spin=async predicate=>{for(let i=0;i<100;i++){if(predicate())return;await new Promise(setImmediate);}throw Error('fixture condition timeout');};
const count=action=>requests.filter(r=>r.body.action===action).length;
(async()=>{
 client=new window.GoBotNativeVoice({fetcher,Peer,media:sandbox.navigator.mediaDevices,automaticDialogue:true});
 assert.equal(requests.length,0);assert.equal(client.termination('input_time_limit').error,false);gate={};const initial=client.beginDialogue();await spin(()=>gate.resolve);
 assert.equal(track.enabled,false);await client.beginDialogue();assert.equal(count('listen'),1); // Double tap cannot clear first words.
 gate.resolve();gate=null;await initial;assert(client.listening&&track.enabled);
 for(let i=0;i<3;i++){
  client.event({type:'audio_diagnostic',data:{stage:'server_vad_started'}});assert(track.enabled);
  client.event({type:'audio_diagnostic',data:{stage:'server_audio_committed'}});assert(!track.enabled&&client.thinking);
  client.event({type:'turn_started',turn_id:'turn-'+i,data:{}});
  client.event({type:'playback_buffer_started',data:{response_id:'response-'+i}});
  client.analyser={fftSize:256,getByteTimeDomainData:a=>a.fill(signal?132:128)};
  signal=1;now+=100;client.meter(client.generation);await spin(()=>count('playback_started')===i+1);
  const before=count('listen');await client.beginDialogue();assert.equal(count('listen'),before);assert(!track.enabled); // Accidental tap never interrupts speech.
  client.event({type:'provider_response_done',data:{}});assert(!track.enabled); // Generation done != playback drain.
  client.event({type:'playback_buffer_stopped',data:{response_id:'response-'+i}});
  assert(!track.enabled);signal=0;now+=400;client.meter(client.generation);
  await spin(()=>count('playback_stopped')===i+1&&[...timers.values()].some(t=>t.ms===350));
  assert(!track.enabled);const [id,t]=[...timers].find(([id,t])=>t.ms===350);timers.delete(id);await t.fn();
  assert(client.listening&&track.enabled);assert.equal(count('listen'),before+1);
  client.event({type:'turn_complete',turn_id:'stale-turn',data:{}});assert.equal(timers.size,0);
 }
 assert.equal(requests.filter(r=>r.url.endsWith('/sessions')).length,1);
 assert.equal(count('ptt_start')+count('ptt_end'),0);assert(!requests.some(r=>/transcribe|tts/.test(r.url)));
 client.event({type:'closed',data:{reason:'followup_timeout'}});await client.closing;
 assert(!track.enabled&&!client.ready);assert.equal(closures.at(-1).error,false);assert.equal(count('close'),1);
 // Stop during an outstanding listen ACK must never re-enable old media.
 client=new window.GoBotNativeVoice({fetcher,Peer,media:sandbox.navigator.mediaDevices,automaticDialogue:true});gate={};
 const pending=client.beginDialogue();await spin(()=>gate.resolve);await client.close();gate.resolve();gate=null;await pending;
 assert(!track.enabled&&!client.listening);assert.equal(timers.size,0);
 console.log(JSON.stringify({sessions:1,provider_calls:0,without_second_tap:true,answers:3,automatic_listening:true,drain_before_microphone:true,no_second_stt:true,stop_race_safe:true,acoustic_verified:false}));
})().catch(e=>{console.error(e);process.exitCode=1;});
