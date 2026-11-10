/* Executes the production client with fake media/network; no API or microphone. */
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const elements={'conversation-engine':{value:'realtime'},'realtime-consent':{checked:true},'realtime-speaker-enabled':{checked:true},'realtime-personalization':{value:'guest'}};
const requests=[],tracks=[],peers=[],callbacks={};let uuid=0,raf=0;
const track={enabled:true,onended:null,stop(){this.stopped=true;}};
class Peer{
 constructor(){this.connectionState='connected';this.iceGatheringState='complete';peers.push(this);}
 addTransceiver(kind){assert.equal(kind,'audio');return {sender:{replaceTrack:async t=>{tracks.push(t);}}};}
 createDataChannel(){throw Error('PROVIDER DATA CHANNEL FORBIDDEN');}
 async createOffer(){return {type:'offer',sdp:'v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n'};}
 async setLocalDescription(v){this.localDescription=v;}
 async setRemoteDescription(v){this.remoteDescription=v;}
 close(){this.closed=true;}
}
class Context{
 constructor(){this.state='running';this.audioWorklet={addModule:async()=>{}};}
 async resume(){}async close(){this.state='closed';}
 createAnalyser(){return {fftSize:512,getByteTimeDomainData:a=>a.fill(128)};}
 createMediaStreamSource(){return {connect(){},disconnect(){}};}
}
const fetcher=async(url,options={})=>{
 requests.push({url,body:typeof options.body==='string'?JSON.parse(options.body):null});
 if(url.endsWith('/status'))return {ok:true,json:async()=>({budget:{enabled:true}})};
 if(url.endsWith('/sessions'))return {ok:true,json:async()=>({configuration_confirmed:true,model:'gpt-realtime-2.1-mini',sdp:'v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n',speaker_readiness:{ready:false}})};
 return {ok:true,json:async()=>({accepted:true,closed:true,hangup_confirmed:true,speaker_segment_id:'segment-fixture'})};
};
const stream={active:true,getAudioTracks:()=>[track],getTracks:()=>[track]};
const window={fetch:fetcher,RTCPeerConnection:Peer,addEventListener:(k,f)=>callbacks[k]=f,
 GoBotClient:{getSettings:()=>({remember:false,speak:true,quota:false,volume:.8}),conversationId:()=> 'same-conversation'},GoBotHooks:{clientKind:'device'}};
const sandbox={window,navigator:{mediaDevices:{getUserMedia:async()=>stream},locks:{request:async(_,__,callback)=>callback({})}},
 document:{hidden:false,getElementById:id=>elements[id]||null,addEventListener:()=>{},createElement:tag=>({autoplay:false,volume:1,pause(){},play:async()=>{}})},
 AudioContext:Context,EventSource:class{close(){this.closed=true;}},crypto:{randomUUID:()=> 'fixture-'+(++uuid)},performance,AbortController,setTimeout,clearTimeout,requestAnimationFrame:()=>raf++,Uint8Array,console};
vm.createContext(sandbox);vm.runInContext(fs.readFileSync('services/phone/dist/realtime.js','utf8'),sandbox);
(async()=>{
 const client=new window.GoBotNativeVoice({fetcher,Peer,media:sandbox.navigator.mediaDevices});
 await client.start();assert(client.ready);assert.equal(track.enabled,false);assert.equal(requests.filter(r=>r.url.endsWith('/sessions')).length,1);
 await client.pttStart();assert.equal(track.enabled,true);client.startedAt=performance.now()-1000;client.speechMs=250;
 await client.pttEnd();assert.equal(track.enabled,false);
 assert.equal(requests.filter(r=>r.body?.action==='ptt_end').length,1);
 await client.pttEnd();assert.equal(requests.filter(r=>r.body?.action==='ptt_end').length,1);
 await client.pttStart();client.startedAt=performance.now()-500;client.speechMs=0;await client.pttEnd();
 assert(requests.some(r=>r.body?.action==='ptt_cancel'));
 assert.equal(requests.filter(r=>r.url.endsWith('/sessions')).length,1);
 await client.close();assert.equal(track.stopped,true);assert.equal(client.id,null);assert(peers.every(p=>p.closed));
 assert(!requests.some(r=>/transcribe|tts|chat\/stream/.test(r.url)));
 assert(requests.every(r=>!r.url.includes('api.openai.com')));
 console.log(JSON.stringify({production_client:true,provider_calls:0,native_session_reused:true,ptt_auto_commit:true,silence_rejected:true,local_mic_cleanup:true,provider_data_channel:false,acoustic_verified:false}));
})().catch(e=>{console.error(e);process.exitCode=1;});
