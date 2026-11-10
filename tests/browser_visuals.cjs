// Deterministic DOM unit tests, not a real Safari/browser or network session.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
class Element{
  constructor(tag){this.tagName=tag;this.children=[];this.dataset={};this.attributes={};this.hidden=false;this._text='';}
  set textContent(value){this._text=String(value);this.children=[];}
  get textContent(){return this._text+this.children.map(child=>child.textContent).join('');}
  append(...children){this.children.push(...children);}
  replaceChildren(...children){this.children=children;this._text='';}
  setAttribute(key,value){this.attributes[key]=String(value);}
}
const all=(root,tag)=>[...(root.tagName===tag?[root]:[]),...root.children.flatMap(c=>all(c,tag))];
let clock=1_700_000_000_000,serial=0;const ticks=new Map(),requests=[];
const sandbox={URL,window:{},document:{createElement:tag=>new Element(tag)},Date:{now:()=>clock},
  setInterval:callback=>{ticks.set(++serial,callback);return serial;},clearInterval:id=>ticks.delete(id),
  fetch:async(url,options)=>{requests.push([url,JSON.parse(options.body)]);return {ok:true};}};
vm.createContext(sandbox);vm.runInContext(fs.readFileSync('services/phone/dist/visual.js','utf8'),sandbox);
const root=new Element('section'),renderer=new sandbox.window.GoBotVisual.BrowserVisualRenderer(root);
const image=(id='a'.repeat(64))=>({asset_id:id,url:`/api/visual/assets/${id}/browser.jpg`,preview_variant:`/api/visual/assets/${id}/preview.jpg`,alt:'Fixture image',caption:'Подпись',attribution:'Test author',source:{label:'Источник',url:'https://commons.wikimedia.org/wiki/File:Test.jpg'},license:'CC BY-SA 4.0',license_url:'https://creativecommons.org/licenses/by-sa/4.0/'});
const frame={namespace:'gobot.ui',version:2,id:'one',type:'image_card',title:'Изображение',text:'Пояснение',images:[image()],metadata:{state:'ready'}};
assert.equal(renderer.render(frame),true);assert.equal(all(root,'img').length,1);assert.equal(all(root,'article').length,1);
assert.equal(renderer.render(frame),true);assert.equal(all(root,'article').length,1);
renderer.render({...frame,id:'facts',metadata:{state:'ready',facts:{entity_source:'INTERNAL',query_basis:'INTERNAL',identification:'INTERNAL','Источник':'доступен'}}});
assert(!root.textContent.includes('INTERNAL'));assert(root.textContent.includes('доступен'));
renderer.begin();renderer.render(frame);
assert.equal(renderer.render({...frame,id:'map',type:'rich_answer',images:[],metadata:{backend:'answer_map',diagram_labels:['Первое понятие']}}),false);
renderer.syncDisplay('Пояснение');assert.equal(renderer.frames.get('one').body.hidden,true);
all(root,'img')[0].onerror();assert.match(root.textContent,/недоступно/);
renderer.begin();renderer.render({...frame,id:'gallery',type:'image_gallery',images:[image(),image('b'.repeat(64))]});assert.equal(all(root,'img').length,2);
renderer.begin();renderer.render({...frame,id:'unsafe',title:'<script>do not run</script>',images:[{...image(),url:'http://127.0.0.1/private'}]});assert.equal(all(root,'img').length,0);assert.match(root.textContent,/<script>/);
renderer.begin();renderer.loading();assert.doesNotThrow(()=>renderer.render({type:'image_card'}));renderer.interrupt();assert.match(root.textContent,/остановлен/);
renderer.begin();renderer.render({...frame,id:'partial',type:'image_gallery',images:[{},null],metadata:{state:'loading'}});assert.match(root.textContent,/пока не получено/);
renderer.begin();const timerId='11111111-1111-1111-1111-111111111111';renderer.render({...frame,id:'timer',type:'timer_widget',images:[],metadata:{state:'ready',deadline:clock/1000+180,timer_id:timerId}});
assert.equal(all(root,'output')[0].textContent,'03:00');assert(renderer.hasTimer(timerId));
(async()=>{await all(root,'button')[0].onclick();assert.equal(all(root,'output')[0].textContent,'Таймер остановлен');assert.equal(requests[0][0],'/api/visual/timer/cancel');assert.equal(requests[0][1].timer_id,timerId);renderer.begin();assert.equal(ticks.size,0);
  const main=new Element('section'),tray=new Element('section'),persistent=new sandbox.window.GoBotVisual.BrowserVisualRenderer(main,tray);
  const persistentFrame={...frame,id:'persistent',type:'timer_widget',images:[],metadata:{state:'ready',deadline:clock/1000+180,timer_id:timerId}};
  persistent.render(persistentFrame);persistent.begin();assert.equal(all(tray,'output')[0].textContent,'03:00');assert.equal(ticks.size,1);
  persistent.render({...frame,id:'next-question'});assert.equal(all(tray,'article').length,1);assert.equal(all(main,'img').length,1);
  persistent.render({...persistentFrame,metadata:{...persistentFrame.metadata,state:'cancelled',deadline:null}});assert.equal(all(tray,'output')[0].textContent,'Таймер остановлен');assert.equal(ticks.size,0);
  for(const type of ['weather_card','music_card','status_card','info_card','rich_answer']){renderer.begin();assert(renderer.render({...frame,id:type,type,images:[],metadata:{state:'unavailable',facts:{'Источник':'не настроен'}}}));assert.match(root.textContent,/Данные недоступны/);}
  console.log('Visual DOM units: card, gallery, partial payload, dedupe, safe paths, countdown, cancel and all 8 types passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
