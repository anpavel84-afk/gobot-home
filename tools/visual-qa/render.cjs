/* Real production Canvas pixels through Skia, offline. Not Safari/device proof. */
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const {createCanvas,Path2D,GlobalFonts}=require('@napi-rs/canvas');
const root=path.resolve(__dirname,'../..'),dist=path.join(root,'services/phone/dist');
GlobalFonts.registerFromPath(path.join(dist,'noto-sans.ttf'),'Noto Sans');
let now=1700000000000;class Clock extends Date{static now(){return now;}}
const env={window:{matchMedia:()=>({matches:false})},Path2D,Date:Clock,Math,Map,Set,Image:class{}};
vm.createContext(env);for(const name of ['design-data.js','design-primitives.js','device-renderer.js'])vm.runInContext(fs.readFileSync(path.join(dist,name),'utf8'),env);
const {DeviceRenderer,SceneManager,defaults}=env.window.GoBotDeviceRenderer,design=env.window.GoBotDesign;
const pngs=[],drawn=[];
function sample(label,options={}){
 const canvas=createCanvas(240,240),profile=JSON.parse(JSON.stringify(defaults));Object.assign(profile.skin,options.skin||{});
 const manager=new SceneManager(profile,()=>now),renderer=new DeviceRenderer(canvas,profile);
 manager.newTurn('actual-production-fixture');manager.state=options.state||'idle';manager.micActive=!!options.mic;
 if(options.frame){const accepted=manager.frame(options.frame,manager.turn);assert(accepted||options.frame.metadata?.avatar_fallback);}if(options.setup)options.setup(manager,renderer);
 const ctx=canvas.getContext('2d'),text=ctx.fillText.bind(ctx);ctx.fillText=(value,x,y,max)=>{assert(Number.isFinite(x)&&Number.isFinite(y));assert(y>=36&&y<=214);assert(max<=175);drawn.push(String(value));text(value,x,y,max);};
 renderer.draw(manager,options.level||0,options.t??2000);const pixels=ctx.getImageData(0,0,240,240).data;assert.equal(pixels[3],0,'outside circular crop');
 pngs.push({label,canvas});return {canvas,manager,renderer,profile};
}
for(const skin of ['classic','soft','minimal'])for(const item of design.data.expressions)sample(skin+' / '+item.id,{skin:{skin_id:skin,expression:item.id}});
assert.equal(pngs.length,72);const hashes=new Set(pngs.map(p=>require('node:crypto').createHash('sha256').update(p.canvas.toBuffer('image/png')).digest('hex')));assert.equal(hashes.size,53,'53 distinct geometries in the supplied 72-variant catalogue');
for(const state of ['listening','thinking','speaking','offline','error','muted'])sample(state,{state,mic:state==='listening',level:state==='speaking'?.2:0});
const days=Array.from({length:16},(_,i)=>({date:'2026-11-'+String(i+1).padStart(2,'0'),icon:i%2?'sun':'rain',condition:'Дождь',low:18,high:25,rain_percent:70}));
const weather=rows=>({id:'weather',type:'weather_card',subtitle:'Тестовый город',metadata:{state:'ready',facts:{temperature:'-12.5'},weather:{icon:'snow',condition:'Небольшой снег',days:rows}}});
sample('Current / −12.5°',{frame:weather([])});sample('Tomorrow / rain',{frame:weather(days.slice(0,1))});sample('Forecast / 16 days',{frame:weather(days)});
const timer={id:'timer',type:'timer_widget',metadata:{timer_id:'t-1',state:'ready',deadline:now/1000+150,duration_ms:300000}};
const active=sample('Timer / 02:30',{frame:timer});
active.manager.newTurn('another-question');assert.equal(active.manager.activeTimer().id,'timer');
now+=151000;active.manager.tick(false);assert(active.manager.expiredTimer());active.manager.newTurn('new-question');active.manager.finish('new-question');now+=100000;active.manager.tick(false);assert(active.manager.expiredTimer(),'alarm latched across response/idle');
sample('Timer / expired',{frame:{...timer,metadata:{...timer.metadata,state:'expired'}}});
assert(active.manager.dismissTimer());assert(!active.manager.expiredTimer());assert(!active.manager.dismissTimer());
const privateScope=sample('Timer / new scope',{frame:{...timer,metadata:{...timer.metadata,state:'expired'}},setup:manager=>{manager.timers.clear();manager.newTurn('different-person');manager.state='idle';}});assert(!privateScope.manager.expiredTimer());
const speaking=sample('Speaking / actual RMS',{state:'speaking',level:.2});const silent=sample('Speaking / no playback',{state:'speaking',level:0});assert(!speaking.canvas.toBuffer('image/png').equals(silent.canvas.toBuffer('image/png')),'actual playback must affect visible mouth pixels');
const plain=sample('No asset / speaking face',{state:'speaking',level:.1,frame:{id:'missing',type:'image_card',images:[],metadata:{avatar_fallback:true,state:'unavailable',reason:'image_not_found'}}});
assert(!drawn.includes('Фото недоступно'));
const reduced=sample('Reduced motion',{skin:{reduced_motion:true},state:'listening',t:4300});const a=reduced.canvas.toBuffer('image/png');reduced.renderer.draw(reduced.manager,0,9000);assert(a.equals(reduced.canvas.toBuffer('image/png')));
env.window.matchMedia=()=>({matches:true});const systemReduced=sample('System reduced motion',{state:'listening',t:4300});const b=systemReduced.canvas.toBuffer('image/png');systemReduced.renderer.draw(systemReduced.manager,0,9000);assert(b.equals(systemReduced.canvas.toBuffer('image/png')));env.window.matchMedia=()=>({matches:false});
// Every glyph draws real pixels through the shared primitive implementation.
for(const name of Object.keys(design.data.icons)){const c=createCanvas(64,64);assert(design.icon(c.getContext('2d'),name,4,4,56,'#ffffff'));assert(c.getContext('2d').getImageData(0,0,64,64).data.some(v=>v>0),name);}
const out=path.join(root,'run/visual-qa');fs.mkdirSync(out,{recursive:true});
function sheet(items,name,cols=6){const cellW=260,cellH=280,s=createCanvas(cols*cellW,Math.ceil(items.length/cols)*cellH),c=s.getContext('2d');c.fillStyle='#19232b';c.fillRect(0,0,s.width,s.height);c.font='14px "Noto Sans"';c.textAlign='center';for(const [i,item] of items.entries()){const x=(i%cols)*cellW,y=Math.floor(i/cols)*cellH;c.drawImage(item.canvas,x+10,y+4);c.fillStyle='#eef5f4';c.fillText(item.label,x+cellW/2,y+265,cellW-10);}fs.writeFileSync(path.join(out,name),s.toBuffer('image/png'));}
sheet(pngs.slice(0,72),'faces.png');sheet(pngs.slice(72),'states.png',4);
const report={production_renderer:true,offline_skia_raster:true,face_variants:72,distinct_face_rasters:hashes.size,vector_icons:109,scenes:pngs.length-72,expired_timer_latch:true,scope_clear:true,reduced_motion_stable:true,paid_api_calls:0,physical_iphone:false,figma_import:false};
fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report));
