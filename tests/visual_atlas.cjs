/* Production read-only atlas behavior; DOM fixture, not browser paint. */
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const nodes=new Map(),active=new Set();let serial=0;
const context=new Proxy({},{get:(o,k)=>o[k]||(()=>{})});
class Element{
 constructor(tag){this.tag=tag;this.children=[];this.dataset={};this.value='';this.listeners={};this.attributes={};this.textContent='';}
 append(...children){this.children.push(...children);}replaceChildren(...children){this.children=children;}
 setAttribute(k,v){this.attributes[k]=v;}addEventListener(k,f){this.listeners[k]=f;}getContext(){return context;}
}
for(const id of ['catalog','design-count','design-group','design-skin','design-search'])nodes.set(id,new Element('div'));nodes.get('design-skin').value='classic';
const buttons=['screens','faces','icons'].map(view=>{const b=new Element('button');b.dataset.view=view;return b;});
const events={},sandbox={window:{addEventListener:(name,handler)=>events[name]=handler},Blob,Path2D:class{},
 URL:{createObjectURL:blob=>{assert.equal(blob.type,'image/svg+xml');const value='blob:fixture-'+(++serial);active.add(value);return value;},revokeObjectURL:url=>assert(active.delete(url))},
 document:{createElement:tag=>new Element(tag),createElementNS:(ns,tag)=>new Element(tag),getElementById:id=>nodes.get(id),querySelectorAll:()=>buttons}};
vm.createContext(sandbox);for(const name of ['design-data.js','design-primitives.js','design-reference.js','visual-atlas.js'])vm.runInContext(fs.readFileSync('services/phone/dist/'+name,'utf8'),sandbox);
assert.equal(nodes.get('catalog').children.length,192);assert.equal(active.size,192);
nodes.get('design-group').value='PR';nodes.get('design-group').listeners.input();assert.equal(nodes.get('catalog').children.length,12);assert.equal(active.size,12);
nodes.get('design-search').value='не существующий объект';nodes.get('design-search').listeners.input();assert.equal(nodes.get('catalog').children.length,0);assert.equal(active.size,0);
nodes.get('design-search').value='';buttons[1].onclick();assert.equal(nodes.get('catalog').children.length,24);assert.equal(active.size,0);
nodes.get('design-skin').value='minimal';nodes.get('design-skin').listeners.input();assert.equal(nodes.get('catalog').children.length,24);
buttons[2].onclick();assert.equal(nodes.get('catalog').children.length,109);
nodes.get('design-group').value='';buttons[0].onclick();assert.equal(active.size,192);events.pagehide();assert.equal(active.size,0);
console.log(JSON.stringify({reference_screens:192,filtered_section:12,expressions_per_skin:24,icons:109,blob_cleanup:true,network_calls:0,microphone:false}));
