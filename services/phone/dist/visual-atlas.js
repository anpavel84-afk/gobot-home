/* Read-only reference viewer. No microphone, service requests or model calls. */
(() => {
  'use strict';const data=window.GoBotDesignData,reference=window.GoBotDesignReference,design=window.GoBotDesign;
  if(!data||!reference||!design)return;const byId=id=>document.getElementById(id);let view='screens';const urls=[];
  const make=(tag,text)=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=text;return node;};
  for(const group of reference.groups){const option=make('option',group.label);option.value=group.id;byId('design-group').append(option);}
  function render(){
    const root=byId('catalog');root.replaceChildren();for(const url of urls)URL.revokeObjectURL(url);urls.length=0;const query=byId('design-search').value.toLocaleLowerCase('ru'),group=byId('design-group').value,skin=byId('design-skin').value;let count=0;
    const entries=view==='screens'?reference.screens:view==='faces'?data.expressions:Object.keys(data.icons).map(id=>({id,title:id}));
    for(const entry of entries){const label=entry.title||entry.label;if(!((entry.id+' '+label).toLocaleLowerCase('ru').includes(query))||view==='screens'&&group&&entry.category!==group)continue;
      const card=make('article');card.append(make('h3',label));
      if(view==='screens'){const img=make('img');img.loading='lazy';img.alt=entry.id+' · демонстрационный экран';img.src=URL.createObjectURL(new Blob([entry.svg],{type:'image/svg+xml'}));urls.push(img.src);card.append(img);}
      else if(view==='faces'){const canvas=make('canvas');canvas.width=240;canvas.height=240;const ctx=canvas.getContext('2d');ctx.fillStyle=data.colors.bg;ctx.fillRect(0,0,240,240);design.face(ctx,skin,entry.id,data.colors.mint);card.append(canvas);}
      else card.append(design.domIcon(entry.id,label));
      card.append(make('p',view==='screens'?entry.id+' · '+entry.layout+' · демо':view==='faces'?skin+' · '+entry.id:entry.id));root.append(card);count++;
    }byId('design-count').textContent='Показано: '+count;byId('design-group').hidden=view!=='screens';byId('design-skin').hidden=view!=='faces';
  }
  for(const button of document.querySelectorAll('[data-view]'))button.onclick=()=>{view=button.dataset.view;render();};
  for(const id of ['design-search','design-group','design-skin'])byId(id).addEventListener('input',render);render();
  window.addEventListener('pagehide',()=>{for(const url of urls)URL.revokeObjectURL(url);urls.length=0;});
})();
