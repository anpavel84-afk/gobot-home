// Geometry/state/controller fixtures. This is not a real Safari/microphone test.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const nodes=new Map(),listeners=new Map(),images=[],texts=[];
const ctx=new Proxy({measureText:text=>({width:String(text).length*6}),fillText:(text,x,y,max)=>texts.push({text,x,y,max})},{get:(o,k)=>k in o?o[k]:(()=>{})});
class Element{
  constructor(tag){this.tag=tag;this.children=[];this.value='';this.checked=false;this.disabled=false;this.options=[];this.classList={add(){},remove(){}};}
  set id(value){this._id=value;nodes.set(value,this);}get id(){return this._id;}
  append(...children){this.children.push(...children);if(this.tag==='select')this.options.push(...children);}
  addEventListener(){}setAttribute(){}replaceChildren(...children){this.children=children;}getContext(){return ctx;}setPointerCapture(){}toDataURL(){return 'data:image/png;base64,fixture';}
}
const el=id=>{if(!nodes.has(id)){const node=new Element('div');node.id=id;}return nodes.get(id);};
const sandbox={window:{addEventListener:(k,f)=>listeners.set(k,f)},document:{body:new Element('body'),createElement:tag=>new Element(tag),getElementById:el,addEventListener(){}},
  Image:class{constructor(){images.push(this);}},Date,Math,Set,Map,JSON,Promise,Error,AbortController,performance,setTimeout,clearTimeout,setInterval:()=>0,clearInterval(){},requestAnimationFrame(){},
  navigator:{locks:{request:async(name,options,fn)=>fn({name})},mediaDevices:{getUserMedia:async()=>({getTracks:()=>[{stop(){}}]})}},
  fetch:async url=>({ok:true,json:async()=>url==='/api/device/profile'?{profile:sandbox.profile,capabilities:{},activation:{configured:false}}:{timers:[]}})};
vm.createContext(sandbox);vm.runInContext(fs.readFileSync('services/phone/dist/device-renderer.js','utf8'),sandbox);
const api=sandbox.window.GoBotDeviceRenderer;const profile=JSON.parse(JSON.stringify(api.defaults));profile.client_id='browser-device-test';profile.interaction_mode='hold';sandbox.profile=profile;
let now=1000;const manager=new api.SceneManager(profile,()=>now),canvas=new Element('canvas'),renderer=new api.DeviceRenderer(canvas,profile);
manager.newTurn('a');assert(!manager.frame({id:'old'},'old'));assert(manager.frame({id:'photo',type:'image_card',images:[]},'a'));
manager.compose({scene_type:'avatar',preserve_visual:true},'a');assert(manager.visual.id==='photo');manager.finish('a');manager.tick(true);assert(manager.returnAt===null);
manager.tick(false);now+=13000;manager.tick(false);assert.equal(manager.visual,null);
for(const state of ['idle','listening','recognizing','thinking','speaking','error','muted','offline']){manager.state=state;renderer.draw(manager,.12,1000);}
for(const skin of ['classic','soft','minimal']){profile.skin.skin_id=skin;renderer.setProfile(profile);renderer.draw(manager,0,1000);}
for(const template of ['lunar_crater','earth_moon','solar_eclipse','volcano','milky_way','tomato_plant','tomato_comparison','dog_comparison','gobot_pipeline']){manager.visual={id:template,title:'Иллюстрация',metadata:{template,synthetic:true},images:[]};manager.state='thinking';renderer.draw(manager,.1,1500);}
assert.equal(canvas.width,240);assert.equal(canvas.height,240);
manager.visual={id:'overview',title:'Белый гриб еловый · обзор',images:[{}],metadata:{facts:{entity_match:'topic_overview',entity_title:'Белый гриб'}}};
renderer.image={};renderer.imageId='overview';manager.state='thinking';renderer.draw(manager,0,1000);
assert(texts.some(item=>item.text==='Белый гриб · обзор'));renderer.clearImage();manager.visual=null;
assert(!manager.frame({id:'map',type:'rich_answer',metadata:{backend:'answer_map'},images:[]},manager.turn));
manager.visual=null;
manager.newTurn('characters');
for(const id of ['gertie','fantoche','felix'])manager.frame({id,type:'image_card',images:[],metadata:{facts:{presentation_group:'answer_characters'}}},'characters');
const beforeCharacter=manager.visual.id;now+=5100;manager.tick(true);assert.notEqual(manager.visual.id,beforeCharacter);
manager.newTurn('other');assert.equal(manager.gallery.length,0);
for(const text of texts){assert(text.y>=35&&text.y<=215);assert(text.max<=175);}
manager.newTurn('first');renderer.load({id:'stale',images:[{device_variant:'/api/visual/assets/'+'a'.repeat(64)+'/device.jpg'}]},'first',id=>manager.turn===id);manager.newTurn('second');images[0].onload();assert.equal(renderer.image,null);
const imageCount=images.length;renderer.load({id:'unsafe',images:[{device_variant:'http://127.0.0.1/private'}]},'second',()=>true);assert.equal(images.length,imageCount);
// Execute the actual device interaction adapter with a shared-client fixture.
let starts=0,stops=0,sends=0,recording=false;
sandbox.window.GoBotClient={unlockAudio:async()=>{},getSettings:()=>({stt:'mock',speak:false}),stop(){stops++;},startRecording:async()=>{starts++;recording=true;sandbox.window.GoBotHooks.onListening();},endRecording(){recording=false;},cancelRecording(){recording=false;},isRecording:()=>recording,audioSnapshot:()=>({level:0,playing:false}),send:async()=>{sends++;},explain:code=>code};
vm.runInContext(fs.readFileSync('services/phone/dist/device.js','utf8'),sandbox);
(async()=>{
  const app=new sandbox.window.GoBotDeviceApp();await app.init();await app.enable();assert(app.enabled);
  await app.press();assert.equal(starts,1);await app.press();assert.equal(starts,1);app.release();assert(!recording);
  await sandbox.window.GoBotHooks.onTranscript({text:'Таймер на пять минут',utterance_id:'utterance-1'});await sandbox.window.GoBotHooks.onTranscript({text:'Таймер на пять минут',utterance_id:'utterance-1'});assert.equal(sends,1);
  app.turn='new';app.manager.newTurn('new');app.event({type:'visual_response',turn_id:'old',data:{presentation:{id:'late'}}});assert.equal(app.manager.visual,null);
  app.pause('Пауза');assert(!app.enabled);assert.equal(app.manager.state,'muted');assert(!app.releaseLock);
  await sandbox.window.GoBotHooks.onTranscript({text:'Не отправлять после выключения',utterance_id:'late'});assert.equal(sends,1);
  // A failed stop/start must not leave a permanently held face or a silent rejection.
  app.enabled=true;const realStop=sandbox.window.GoBotClient.stop;
  sandbox.window.GoBotClient.stop=()=>{throw new TypeError('Illegal invocation');};
  await app.press();assert(!app.held);assert(app.captureAbort.signal.aborted);assert.equal(app.manager.state,'error');
  sandbox.window.GoBotClient.stop=realStop;
  const realStart=sandbox.window.GoBotClient.startRecording;
  sandbox.window.GoBotClient.startRecording=async()=>false;
  await app.press();assert(!app.held);assert(app.captureAbort.signal.aborted);assert(!recording);
  sandbox.window.GoBotClient.startRecording=realStart;await app.press();assert.equal(starts,2);app.release();app.pause('Готово');
  const pendingFollowup=[];sandbox.setTimeout=callback=>{pendingFollowup.push(callback);return pendingFollowup.length;};
  app.profile.conversation={followup_enabled:true,followup_seconds:12,silence_ms:900,min_speech_ms:300,echo_guard_ms:350};
  app.enabled=true;app.sessionActive=true;app.serverAudioEnded=true;app.answerPlaybackStarted=true;
  app.checkFollowup({playing:true});assert.equal(pendingFollowup.length,0);
  app.checkFollowup({playing:false});assert.equal(pendingFollowup.length,1);
  app.endConversation();const previousStarts=starts;await pendingFollowup.shift()();assert.equal(starts,previousStarts);
  app.sessionActive=true;app.serverAudioEnded=true;app.checkFollowup({playing:false});await pendingFollowup.shift()();
  assert.equal(starts,previousStarts+1);assert(sandbox.window.GoBotHooks.captureOptions.vad);
  app.pause('Окончание теста');
  app.turn='closing';app.manager.newTurn('closing');app.enabled=true;app.sessionActive=true;
  app.event({type:'tool_status',turn_id:'closing',data:{status:'conversation_ended'}});
  app.event({type:'audio_stop',turn_id:'closing',data:{reason:'finished'}});
  app.checkFollowup({playing:false});assert(!app.sessionActive);assert(!app.followupPending);assert(app.conversationEnded);
  for(const reason of ['no_audio','tts_error','cancelled']){
    app.sessionActive=true;app.serverAudioEnded=false;app.audioStreamId='a';app.answerPlaybackStarted=false;
    app.event({type:'audio_stop',turn_id:'closing',data:{audio_id:'a',reason,chunks:0}});
    app.checkFollowup({playing:false,feedback_playing:true});assert(!app.followupPending);assert(!app.sessionActive);
  }
  app.sessionActive=true;app.serverAudioEnded=true;app.answerPlaybackStarted=false;app.checkFollowup({playing:false});assert(!app.followupPending);
  app.answerPlaybackStarted=true;app.checkFollowup({playing:false,feedback_playing:true});assert(!app.followupPending);
  app.serverAudioEnded=false;app.event({type:'audio_stop',turn_id:'old',data:{reason:'finished',chunks:1}});assert(!app.serverAudioEnded);
  console.log('Device units: raster, scenes, capture, followup playback gate, stop and pause passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
