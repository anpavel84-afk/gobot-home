// Production canvas geometry only; no microphone, providers or hardware claims.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const draws=[],scales=[],arcs=[],texts=[],images=[];
const ctx=new Proxy({drawImage:(...args)=>draws.push(args),scale:(...args)=>scales.push(args),arc:(...args)=>arcs.push(args),
  measureText:text=>({width:String(text).length*6}),fillText:(...args)=>texts.push(args)},
  {get:(obj,key)=>key in obj?obj[key]:(()=>{})});
const sandbox={window:{},Image:class{constructor(){images.push(this);}},Date,Math};
vm.createContext(sandbox);vm.runInContext(fs.readFileSync('services/phone/dist/device-renderer.js','utf8'),sandbox);
const api=sandbox.window.GoBotDeviceRenderer,profile=JSON.parse(JSON.stringify(api.defaults));
const renderer=new api.DeviceRenderer({getContext:()=>ctx},profile);
const assetId='a'.repeat(64),base='/api/visual/assets/'+assetId;
const frame={id:'photo',type:'image_card',title:'Муравей',images:[{asset_id:assetId,width:400,height:800,preview_variant:base+'/preview.jpg',device_variant:base+'/device.jpg'}],metadata:{}};
function render(width,height,metadata={},padded=false){
  draws.length=scales.length=arcs.length=texts.length=0;
  renderer.image={naturalWidth:width,naturalHeight:height};renderer.imageId=frame.id;renderer.imagePadded=padded;
  renderer.draw({visual:{...frame,metadata},state:'speaking',turn:'current'},0,0);
  return draws[0].slice(1);
}
assert.deepEqual(render(400,800),[0,200,400,400,0,0,240,240]);
assert.deepEqual(render(800,400),[200,0,400,400,0,0,240,240]);
assert.deepEqual(render(480,480),[0,0,480,480,0,0,240,240]);
assert.deepEqual(render(400,800,{image_fit:'contain'}),[0,0,400,800,85,37,70,140]);
assert.deepEqual(render(240,240,{},true),[60,60,120,120,0,0,240,240]);
profile.display.safe_inset=60;
assert.deepEqual(render(400,800),[0,200,400,400,0,0,240,240]);
assert.equal(scales.length,0);assert.equal(arcs[0][2],120);
assert(texts.some(args=>args[0]==='Муравей'&&args[3]<=120));
render(400,800,{image_fit:'contain'});assert.equal(scales.length,1);
assert.equal(renderer.imageFit({...frame,images:[{source:{url:'https://commons.wikimedia.org/wiki/File:Anatomy.svg'}}]}),'contain');
for(const state of ['listening','recognizing','error','offline']){
  draws.length=0;renderer.draw({visual:frame,state,turn:'current'},0,0);assert.equal(draws.length,0);
}
renderer.clearImage();renderer.load(frame,'current',()=>true);
assert.equal(images.at(-1).src,base+'/preview.jpg');images.at(-1).onload();assert(!renderer.imagePadded);
renderer.clearImage();renderer.load({...frame,images:[{...frame.images[0],preview_variant:null}]},'current',()=>true);
assert.equal(images.at(-1).src,base+'/device.jpg');images.at(-1).onload();assert(renderer.imagePadded);
renderer.clearImage();const count=images.length;
renderer.load({...frame,images:[{...frame.images[0],preview_variant:'https://example.test/private',device_variant:base.replace(assetId,'b'.repeat(64))+'/device.jpg'}]},'current',()=>true);
assert.equal(images.length,count);
renderer.load(frame,'old',()=>false);images.at(-1).onload();assert.equal(renderer.image,null);
renderer.load(frame,'current',()=>true);const late=images.at(-1);renderer.clearImage();late.onload();assert.equal(renderer.image,null);
const scene=new api.SceneManager(profile);scene.newTurn('current');
texts.length=0;
renderer.draw({visual:{id:'fallback',type:'info_card',title:'Орёл',images:[],metadata:{state:'unavailable',reason:'image_not_found',visual_strategy:'retrieve',facts:{generation_fallback_reason:'image_generation_policy_denied'}}},state:'thinking',turn:'current'},0,0);
assert(!texts.some(row=>/недоступ|отключена|повторить запрос/i.test(row[0])));
let faces=0;const face=renderer.face.bind(renderer);renderer.face=(...args)=>{faces++;face(...args);};
renderer.draw({visual:{id:'missing',images:[],metadata:{avatar_fallback:true}},state:'speaking',turn:'current'},.08,10);
assert.equal(faces,1,'A missing image must animate the speaking face');
renderer.clearImage();renderer.draw({visual:frame,state:'speaking',turn:'current'},.08,10);
assert.equal(faces,2,'Pending decode must leave the face visible');
assert(!scene.frame({id:'missing',images:[],metadata:{avatar_fallback:true}},'current'));assert.equal(scene.visual,null);
assert(scene.frame({...frame,id:'refined',metadata:{visual_stage:'refined',visual_revision:1}},'current'));
assert(!scene.frame({...frame,metadata:{visual_stage:'provisional',visual_revision:0}},'current'));
assert(!scene.frame({...frame,metadata:{visual_stage:'refined',visual_revision:2}},'old'));
console.log('Circular photo cover, diagram contain, cached variants and stale/unsafe loads passed');
