/* Production C client with fake media/network. No API calls or acoustic claim. */
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const requests=[],closures=[],playback=[],callbacks={},elements={'conversation-engine':{value:'live'}};let serial=0,track,terminalReason=null;
class Peer{constructor(){this.connectionState='connected';}createDataChannel(){return {};}addTrack(){}async createOffer(){return {sdp:'synthetic-sdp'};}async setLocalDescription(v){this.localDescription=v;}async setRemoteDescription(v){this.remoteDescription=v;}close(){this.connectionState='closed';}}
class Context{constructor(){this.state='running';}async resume(){}async close(){}createAnalyser(){return {fftSize:512,getFloatTimeDomainData:a=>a.fill(0)};}createMediaStreamSource(){return {connect(){},disconnect(){}};}}
const fetch=async(url,options={})=>{const body=options.body?JSON.parse(options.body):null;requests.push({url,body});return {ok:true,json:async()=>url.includes('/sessions/')&&url.endsWith('/status')?{closed:!!terminalReason,reason:terminalReason,final_usage_confirmed:true}:url.endsWith('/status')?{enabled:true}:url.endsWith('/sessions')?{model:'gpt-live-1',delegation:'client',configuration_confirmed:true,sdp:'synthetic-answer'}:{accepted:true,closed:true}};};
const window={fetch,addEventListener:(k,v)=>callbacks[k]=v,GoBotNativeVoice:{prototype:{async acquire(){this.releaseLock=()=>{};},async gather(){}}},
 GoBotClient:{getSettings:()=>({voice:'marin',remember:false,volume:.8}),conversationId:()=> 'synthetic-conversation',applyNativeEvent(){}},GoBotHooks:{onNativeClosed:v=>closures.push(v),onLivePlayback:v=>playback.push(v)}};
const sandbox={window,navigator:{mediaDevices:{getSupportedConstraints:()=>({}),getUserMedia:async()=>{track={enabled:true,getSettings:()=>({}),stop(){this.stopped=true;}};return {getAudioTracks:()=>[track],getTracks:()=>[track]};}}},
 document:{getElementById:id=>elements[id],addEventListener(){},createElement:()=>({muted:false,pause(){},play:async()=>{}})},AudioContext:Context,RTCPeerConnection:Peer,AbortController,EventSource:class{close(){}},performance,crypto:{randomUUID:()=> 'command-'+(++serial)},requestAnimationFrame(){},setTimeout,clearTimeout,Float32Array,console};
vm.createContext(sandbox);vm.runInContext(fs.readFileSync('services/phone/dist/live.js','utf8'),sandbox);
(async()=>{
 const c=window.GoBotLive;await c.start();assert(c.ready&&track.enabled);assert.equal(requests.filter(r=>r.url.endsWith('/sessions')).length,1);
 c.currentTurn='current';c.event({type:'text_delta',turn_id:'current',data:{text:'Синтетический ответ'}});assert(track.enabled,'Full duplex must keep input enabled during output');
 c.event({type:'local_tool_status',data:{state:'running',tool:'timer'}});assert(c.toolPending&&playback.at(-1).pending&&track.enabled);
 c.event({type:'local_tool_status',data:{state:'completed',tool:'timer',has_widget:true}});assert(!c.toolPending&&!playback.at(-1).pending);
 c.event({type:'local_tool_status',data:{state:'running',tool:'settings'}});assert(c.toolPending);
 c.event({type:'local_tool_status',data:{state:'failed',tool:'settings'}});assert(!c.toolPending&&!playback.at(-1).pending);
 await c.stopSpeech();assert(c.output.muted&&track.enabled);assert.equal(c.output.srcObject,null);assert(!requests.some(r=>r.body?.action==='end'));
 await c.toggleMute();assert(!track.enabled);await c.toggleMute();assert(track.enabled);
 c.event({type:'closing',data:{reason:'idle_timeout'}});assert(!track.enabled&&c.output.muted);
 c.event({type:'closed',data:{reason:'idle_timeout',final_usage_confirmed:true}});await c.closing;assert.equal(closures.at(-1).error,false);assert(track.stopped);
 await c.start();const a=c.close(),b=c.close();assert.equal(a,b);await a;
 assert.equal(requests.filter(r=>r.body?.action==='end').length,1);assert.equal(c.id,null);
 await c.start();terminalReason='idle_timeout';await c.transportEnded('webrtc_failed');
 assert(!track.enabled&&track.stopped);assert.equal(closures.at(-1).reason,'idle_timeout');assert.equal(closures.at(-1).error,false);
 assert.equal(requests.filter(r=>r.body?.action==='end').length,1);
 assert(requests.every(r=>!r.url.includes('api.openai.com')));assert(!requests.some(r=>/transcribe|tts|chat\/stream/.test(r.url)));
 assert(!requests.some(r=>['response.create','input_audio_buffer.commit','ptt_end'].includes(r.body?.action)));
 console.log(JSON.stringify({production_live_client:true,full_duplex:true,stop_distinct_from_end:true,normal_idle:true,duplicate_close:false,provider_calls:0,acoustic_verified:false}));
})().catch(e=>{console.error(e);process.exitCode=1;});
