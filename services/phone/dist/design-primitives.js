/* Shared vector vocabulary for the existing Canvas and DOM renderers.
   Data is generated from reviewed SVG. No eval, fetched SVG or model markup. */
(() => {
  'use strict';
  const data=window.GoBotDesignData;if(!data)return;
  const cache=new Map();
  const path=d=>{if(!cache.has(d))cache.set(d,new Path2D(d));return cache.get(d);};
  function vector(ctx,asset,x,y,w,h,color){
    if(!asset||typeof Path2D==='undefined')return false;
    const [vx,vy,vw,vh]=asset.viewBox,scale=Math.min(w/vw,h/vh);
    ctx.save();ctx.translate(x+(w-vw*scale)/2,y+(h-vh*scale)/2);ctx.scale(scale,scale);ctx.translate(-vx,-vy);
    for(const item of asset.paths){
      const shape=path(item.d);ctx.lineCap=item['stroke-linecap']||'round';ctx.lineJoin=item['stroke-linejoin']||'round';
      if(item.fill!=='none'){ctx.fillStyle=color;ctx.fill(shape);}
      if(item.stroke&&item.stroke!=='none'){ctx.strokeStyle=color;ctx.lineWidth=Number(item['stroke-width']||1);ctx.stroke(shape);}
    }
    ctx.restore();return true;
  }
  const icon=(ctx,name,x,y,size=32,color=data.colors.mint)=>vector(ctx,data.icons[name]||data.icons.info,x,y,size,size,color);
  function face(ctx,skin,emotion,color,{blink=false,mouth=null,eyes='default',mouthStyle='default'}={}){
    const nodes=data.faces[skin+'-'+emotion]||data.faces[skin+'-neutral'];if(!nodes||typeof Path2D==='undefined')return false;
    ctx.save();ctx.translate(40,45);
    for(const node of nodes){
      const isEye=node.name.startsWith('Eye'),isMouth=node.name.startsWith('Mouth');
      if(isMouth&&mouth!==null)continue;
      if(isEye&&(blink||eyes!=='default'))continue;
      if(isMouth&&mouthStyle!=='default')continue;
      const tone=(node.color||node.fill)==='mint'?color:(data.colors[node.color||node.fill]||color);
      ctx.save();ctx.globalAlpha=node.opacity??1;ctx.fillStyle=tone;ctx.strokeStyle=tone;
      if(node.kind==='svg')vector(ctx,node.vector,node.x,node.y,node.w,node.h,tone);
      else {ctx.beginPath();if(node.kind==='ellipse')ctx.ellipse(node.x+node.w/2,node.y+node.h/2,node.w/2,node.h/2,0,0,Math.PI*2);
        else if(ctx.roundRect)ctx.roundRect(node.x,node.y,node.w,node.h,node.r||0);else ctx.rect(node.x,node.y,node.w,node.h);
        if(node.fill)ctx.fill();if(node.stroke){ctx.lineWidth=node.sw;ctx.stroke();}}
      ctx.restore();
    }
    ctx.fillStyle=color;ctx.strokeStyle=color;
    if(blink||eyes!=='default')for(const x of [50,110]){ctx.beginPath();ctx.lineWidth=5;ctx.lineCap='round';
      if(blink||eyes==='line'){ctx.moveTo(x-10,60);ctx.lineTo(x+10,60);ctx.stroke();}
      else {ctx.ellipse(x,60,eyes==='round'?14:10,eyes==='round'?14:18,0,0,Math.PI*2);ctx.fill();}}
    if(mouth!==null){ctx.beginPath();ctx.ellipse(80,105,18,Math.max(3,mouth),0,0,Math.PI*2);ctx.fill();}
    else if(mouthStyle!=='default'){ctx.beginPath();ctx.lineWidth=4;ctx.lineCap='round';ctx.moveTo(62,103);
      if(mouthStyle==='neutral')ctx.lineTo(98,103);else ctx.quadraticCurveTo(80,mouthStyle==='small'?117:130,98,103);ctx.stroke();}
    ctx.restore();return true;
  }
  function domIcon(name,label=''){
    if(typeof document==='undefined'||!document.createElementNS)return null;
    const asset=data.icons[name];if(!asset)return null;
    const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox',asset.viewBox.join(' '));svg.setAttribute('class','gobot-vector-icon');
    svg.setAttribute('aria-hidden',label?'false':'true');if(label){svg.setAttribute('role','img');svg.setAttribute('aria-label',label);}
    for(const item of asset.paths){const p=document.createElementNS(ns,'path');p.setAttribute('d',item.d);svg.append(p);}return svg;
  }
  window.GoBotDesign={data,vector,icon,face,domIcon};
})();
