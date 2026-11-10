// Unit harness only. No real browser, microphone, network, CLI or paid API is used.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const nodes=new Map(),store=new Map();let captures=0;
function element(id){if(!nodes.has(id))nodes.set(id,{value:'',checked:false,disabled:false,textContent:'',hidden:false,options:[],attrs:{},
  classList:{add(){},remove(){}},setAttribute(k,v){this.attrs[k]=v;},append(){},replaceChildren(){},focus(){},scrollIntoView(){}});return nodes.get(id);}
element('stt').value='whisper';element('stt-mode').value='file';element('model').value='mock';
const context={console,crypto:require('node:crypto').webcrypto,performance,AbortController,TextDecoder,URLSearchParams,Blob,setTimeout,clearTimeout,atob,
  document:{getElementById:element,createElement:()=>element('created')},
  localStorage:{getItem:k=>store.get(k)||null,setItem:(k,v)=>store.set(k,v)},
  navigator:{mediaDevices:{getUserMedia(){}}},
  window:{isSecureContext:true,addEventListener(){},AudioContext:class{constructor(){throw new Error('File capture must not initialize playback');}}},
  fetch:async url=>({ok:true,json:async()=>url==='/api/status'?{services:[],backend:{}}:{messages:[]}}),
  GoBotCapture:{async start(options){captures++;return {stop(){options.onStop(new Blob(['fixture'],{type:'audio/wav'}));},cancel(){}}}}
};
vm.createContext(context);vm.runInContext(fs.readFileSync('services/phone/dist/browser.js','utf8'),context);
(async()=>{
  await element('record').onclick();assert.equal(captures,1);assert.equal(element('record').attrs['aria-pressed'],'true');
  // File capture starts even when playback AudioContext would fail to initialize.
  element('record').onclick();assert.equal(element('record').attrs['aria-pressed'],'false');
  await new Promise(resolve=>setTimeout(resolve,10));
  // Unsupported Safari pointer capture must not break the hold microphone handler.
  element('hold').setPointerCapture=()=>{throw new Error('unsupported capture');};
  await element('hold').onpointerdown({preventDefault(){},pointerId:1});assert.equal(captures,2);
  element('hold').onpointerup({preventDefault(){}});
  let starts=0,stops=0;
  context.fixtureAudio={currentTime:0,createBuffer:()=>({duration:.01,getChannelData:()=>new Float32Array(2)}),createBufferSource:()=>({connect(){},start(){starts++;},stop(){stops++;}})};
  vm.runInContext('audio=fixtureAudio;gain={};clearAudio();',context);
  context.chunk={audio_id:'fixture-audio',seq:0,format:'pcm_s16le',sample_rate:24000,pcm:'AAAAAA=='};
  await vm.runInContext('play(chunk,epoch)',context);await vm.runInContext('play(chunk,epoch)',context);assert.equal(starts,1);
  context.chunk.seq=2;await assert.rejects(vm.runInContext('play(chunk,epoch)',context),/audio_sequence_gap/);
  vm.runInContext('clearAudio()',context);assert.equal(stops,1);
  console.log('microphone gesture unit regressions passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
