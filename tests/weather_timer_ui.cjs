/* Production round renderer, with deterministic canvas and clock. Not iPhone. */
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
let now=100000,arcs=0;const texts=[];
class Clock extends Date{static now(){return now;}}
const ctx=new Proxy({measureText:s=>({width:String(s).length*6}),fillText:s=>texts.push(s),arc(){arcs++;}},{get:(o,k)=>k in o?o[k]:(()=>{})});
const env={window:{},Date:Clock,Math,Map,Image:class{}};vm.createContext(env);vm.runInContext(fs.readFileSync('services/phone/dist/device-renderer.js','utf8'),env);
const {DeviceRenderer,SceneManager,defaults}=env.window.GoBotDeviceRenderer;
const manager=new SceneManager(defaults,()=>now),renderer=new DeviceRenderer({getContext:()=>ctx},defaults);
const timer={id:'timer-frame',type:'timer_widget',metadata:{timer_id:'timer-1',deadline:now/1000+15,state:'ready'}};
manager.newTurn('a');manager.frame(timer,'a');manager.state='speaking';renderer.draw(manager,.1,0);
assert(texts.includes('00:15'));now+=4000;texts.length=0;renderer.draw(manager,.1,4000);assert(texts.includes('00:11'));
assert.equal(manager.frame({id:'late-photo',type:'image_card',metadata:{visual_stage:'provisional'},images:[]},'a'),false);
manager.newTurn('b');assert.equal(manager.activeTimer().id,'timer-frame');
const days=Array.from({length:16},(_,i)=>({date:'2026-11-'+String(i+1).padStart(2,'0'),icon:i%2?'sun':'rain',condition:'дождь',low:18,high:25,rain_percent:70}));
manager.frame({id:'weather',type:'weather_card',subtitle:'Synthetic',metadata:{state:'ready',facts:{temperature:'25'},weather:{kind:'forecast',condition:'дождь',icon:'rain',days}}},'b');
texts.length=0;renderer.draw(manager,0,5000);assert(texts.includes('Прогноз · Open-Meteo'));assert(texts.includes('Осадки 70%'));assert(texts.includes('◷ 0:11'));assert(arcs>8);
let expired=0;manager.onTimerExpired=()=>expired++;now+=12000;manager.tick(false);manager.tick(false);assert.equal(expired,1);assert.equal(manager.activeTimer(),undefined);
manager.newTurn('c');const second={...timer,id:'second',metadata:{...timer.metadata,timer_id:'timer-2',deadline:now/1000+100}};manager.frame(second,'c');
manager.frame({...second,metadata:{...second.metadata,state:'cancelled',deadline:null}},'c');assert.equal(manager.activeTimer(),undefined);
for(const kind of ['sun','cloud','partly_cloudy','rain','snow','storm','fog'])assert.doesNotThrow(()=>renderer.weatherIcon(kind));
console.log(JSON.stringify({production_round_renderer:true,countdown_advances:true,persists_between_turns:true,weather_graphics:true,forecast_days:16,local_expiry_once:true,iphone:false}));
