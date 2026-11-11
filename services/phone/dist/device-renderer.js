/* Semantic device scenes + canvas renderer. Logical raster is independent of CSS. */
(() => {
  'use strict';
  const avatarFallback=frame=>!!frame&&(frame.metadata?.avatar_fallback===true||
    frame.metadata?.state==='unavailable'&&(/^(?:image_|generation_|optional_visual_|private_image_)/.test(frame.metadata?.reason||'')||frame.metadata?.facts?.visual_fulfillment==='fallback'));
  class SceneManager{
    constructor(profile,clock=()=>Date.now()){this.profile=profile;this.clock=clock;this.turn=null;this.visual=null;this.scene=null;this.state='idle';this.completed=false;this.returnAt=null;}
    newTurn(turn){this.turn=turn;this.visual=null;this.scene=null;this.completed=false;this.returnAt=null;this.state='thinking';this.gallery=[];this.galleryAt=null;}
    frame(frame,turn){if(frame?.metadata?.backend==='answer_map')return false;if(turn!==this.turn||!frame||typeof frame!=='object'||typeof frame.id!=='string')return false;
      if(avatarFallback(frame)){if(this.visual?.images?.length)return false;this.visual=null;this.scene=null;this.gallery=[];this.galleryAt=null;return false;}
      if(frame.metadata?.visual_stage&&this.visual?.metadata?.visual_stage&&(frame.metadata.visual_revision||0)<(this.visual.metadata.visual_revision||0))return false;
      this.visual=frame;this.returnAt=null;
      if(frame.metadata?.facts?.presentation_group==='answer_characters'){
        this.gallery=this.gallery||[];if(!this.gallery.some(item=>item.id===frame.id))this.gallery.push(frame);
        this.galleryAt=this.clock()+5000;
      }
      return true;}
    compose(scene,turn){if(turn!==this.turn||!scene||typeof scene!=='object')return false;if(!scene.preserve_visual||!this.visual)this.scene=scene;return true;}
    finish(turn){if(turn===this.turn)this.completed=true;}
    tick(playing){
      if(this.gallery?.length>1&&this.galleryAt!==null&&this.clock()>=this.galleryAt){
        const index=this.gallery.findIndex(item=>item.id===this.visual?.id);
        this.visual=this.gallery[(index+1)%this.gallery.length];this.galleryAt=this.clock()+5000;
        this.onVisualChanged?.(this.visual,this.turn);
      }
      if(this.visual?.type==='timer_widget'&&this.visual.metadata?.deadline>this.clock()/1000){this.returnAt=null;return;}
      if(this.completed&&!playing&&this.returnAt===null){this.returnAt=this.clock()+this.profile.screen.hold_after_response_seconds*1000;}
      if(this.returnAt!==null&&this.clock()>=this.returnAt&&this.profile.screen.return_to_idle){this.visual=null;this.scene=null;this.returnAt=null;this.completed=false;this.gallery=[];this.galleryAt=null;}
    }
  }
  const defaults={display:{width:240,height:240,safe_inset:35},skin:{skin_id:'classic',face_color:'#a3e5cd',background:'#0c141a',eyes:'default',mouth:'default',animation_intensity:.6,reduced_motion:false,idle_screen:'face'},screen:{hold_after_response_seconds:12,return_to_idle:true}};
  class DeviceRenderer{
    constructor(canvas,profile=defaults){this.canvas=canvas;this.ctx=canvas.getContext('2d');this.image=null;this.imageId=null;this.loadToken=0;this.wallpaper=null;this.setProfile(profile);}
    setProfile(profile){this.profile=profile;this.canvas.width=profile.display.width;this.canvas.height=profile.display.height;}
    load(frame,turn,isCurrent){
      const asset=frame?.images?.[0];
      const path=[asset?.preview_variant,asset?.device_variant].find(value=>{
        const match=/^\/api\/visual\/assets\/([a-f0-9]{64})\/(?:preview|device)\.jpg$/.exec(value||'');
        return match&&(!asset.asset_id||asset.asset_id===match[1]);
      });if(!path)return;
      const token=++this.loadToken,image=new Image();
      image.onload=()=>{if(token===this.loadToken&&isCurrent(turn)){this.image=image;this.imageId=frame.id;this.imageFrame=frame;this.imageTurn=turn;this.imageReadyAt=Date.now();this.imagePadded=path.endsWith('/device.jpg');this.onImageReady?.(frame.id,turn);}};
      image.onerror=()=>{if(token===this.loadToken&&isCurrent(turn))this.onImageError?.(frame.id,turn);};image.src=path;
    }
    clearImage(){this.loadToken++;this.image=null;this.imageId=null;this.imageFrame=null;this.imageTurn=null;this.imagePadded=false;this.presentedId=null;}
    imageFit(frame){
      if(frame?.metadata?.image_fit==='contain'||frame?.type==='rich_answer'||frame?.metadata?.template||frame?.metadata?.diagram_labels?.length||/\.svg(?:$|[?#])/i.test(frame?.images?.[0]?.source?.url||''))return 'contain';
      return 'cover';
    }
    drawFittedImage(frame,fit){
      const image=this.image,asset=frame.images[0];
      const iw=image.naturalWidth||image.width||240,ih=image.naturalHeight||image.height||240;
      let sx=0,sy=0,sw=iw,sh=ih;
      // Compatibility for old scenes with only a padded 240x240 device rendition.
      if(this.imagePadded&&asset.width&&asset.height){
        const scale=Math.min(1,240/Math.max(asset.width,asset.height));
        sw=Math.max(1,Math.round(asset.width*scale));sh=Math.max(1,Math.round(asset.height*scale));
        sx=Math.floor((240-sw)/2);sy=Math.floor((240-sh)/2);
      }
      if(fit==='cover'){
        const side=Math.min(sw,sh);sx+=(sw-side)/2;sy+=(sh-side)/2;
        this.ctx.drawImage(image,sx,sy,side,side,0,0,240,240);
      }else{
        const scale=Math.min(170/sw,140/sh),dw=sw*scale,dh=sh*scale;
        this.ctx.drawImage(image,sx,sy,sw,sh,120-dw/2,107-dh/2,dw,dh);
      }
    }
    loadWallpaper(){const image=new Image();image.onload=()=>{this.wallpaper=image;this.onWallpaperReady?.();};image.src='/api/device/screensaver';}
    text(value,x,y,size=13,max=168,color='#eef5f4'){
      const c=this.ctx;c.font=`${size}px system-ui, sans-serif`;c.textAlign='center';c.fillStyle=color;let text=String(value||'');
      while(text.length&&c.measureText(text).width>max)text=text.slice(0,-2)+'…';c.fillText(text,x,y,max);
    }
    circle(x,y,r,color){const c=this.ctx;c.beginPath();c.fillStyle=color;c.arc(x,y,r,0,Math.PI*2);c.fill();}
    line(points,color,width=2){const c=this.ctx;c.beginPath();c.strokeStyle=color;c.lineWidth=width;c.moveTo(...points[0]);for(const point of points.slice(1))c.lineTo(...point);c.stroke();}
    face(state,level,t){
      const c=this.ctx,p=this.profile.skin,color=p.face_color,soft=p.skin_id==='soft',minimal=p.skin_id==='minimal';
      const reduced=p.reduced_motion||window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches;
      const motion=reduced?0:p.animation_intensity,blink=motion&&Math.sin(t/1900)>.995;
      const eye=p.eyes==='default'?(minimal?'line':soft?'round':'oval'):p.eyes;
      for(const x of [83,157]){
        if(state==='error'){this.line([[x-9,91],[x+9,109]],'#ffb3a9',4);this.line([[x+9,91],[x-9,109]],'#ffb3a9',4);continue;}
        if(state==='muted'||state==='offline'){this.line([[x-12,100],[x+12,100]],'#9cafb7',4);continue;}
        c.fillStyle=color;c.beginPath();
        if(eye==='line'||blink){this.line([[x-12,100],[x+12,100]],color,5);continue;}
        c.ellipse(x,100,soft?15:11,eye==='round'?15:19,0,0,Math.PI*2);c.fill();
      }
      if(state==='speaking'&&level>.003){c.beginPath();c.ellipse(120,143,18,reduced||!motion?6:Math.min(20,3+level*65*motion),0,0,Math.PI*2);c.fillStyle=color;c.fill();}
      else if(p.mouth==='neutral')this.line([[103,145],[137,145]],color,4);
      else {c.beginPath();c.strokeStyle=color;c.lineWidth=4;c.arc(120,128,p.mouth==='small'?14:26,.15*Math.PI,.85*Math.PI);c.stroke();}
      const label={idle:'ГоБот',listening:'Слушаю',recognizing:'Распознаю речь',thinking:'Думаю',speaking:'',error:'Ошибка',muted:'Микрофон выключен',offline:'Нет соединения'}[state]||'';
      this.text(label,120,190,13,150,color);
      if(state==='listening'){c.beginPath();c.strokeStyle=color;c.lineWidth=2;c.arc(120,120,104+motion*Math.sin(t/250)*2,0,Math.PI*2);c.stroke();}
    }
    compactDiagram(template){
      const mint=this.profile.skin.face_color;
      if(template==='fantasy_planet'){
        this.circle(120,123,42,'#5d5dab');this.line([[58,137],[182,113]],'#e5b26d',5);
        this.circle(174,78,7,'#c8d7e7');
      }else if(template==='gobot_pipeline'){
        for(const [x,y,label] of [[73,92,'Клиент'],[167,92,'Brain'],[167,163,'Модель'],[73,163,'Голос']])this.text(label,x,y,12,75);
        this.line([[103,90],[130,90]],mint);this.line([[168,107],[168,139]],mint);this.line([[135,161],[107,161]],mint);
      }else if(['earth_moon','solar_eclipse'].includes(template)){
        const solar=template==='solar_eclipse';this.circle(solar?62:66,116,solar?22:26,solar?'#efbe48':'#3972b7');this.circle(solar?120:174,116,solar?9:13,'#a6abb0');
        if(solar)this.circle(179,116,17,'#3972b7');this.line([[solar?85:97,116],[solar?110:154,116]],mint,2);
        this.text(solar?'Солнце':'Земля',solar?62:66,158,11,65);this.text('Луна',solar?120:174,solar?88:158,11,45);if(solar)this.text('Земля',179,158,11,55);
      }else if(template==='lunar_crater'){
        this.line([[40,119],[68,100],[90,142],[145,142],[170,100],[199,119]],mint,5);this.text('Край',69,85,12,50);this.text('Дно',118,165,12,50);
      }else if(template==='tomato_comparison'){
        const c=this.ctx;c.beginPath();c.moveTo(45,108);c.lineTo(66,94);c.lineTo(90,108);c.lineTo(111,94);c.lineTo(125,111);c.lineTo(84,158);c.closePath();c.fillStyle='#cb6054';c.fill();this.circle(169,125,29,'#cf523c');this.text('Сердцевидный',83,182,10,100);this.text('Округлый',169,182,10,70);
      }else if(template==='tomato_plant'){
        this.line([[120,175],[120,70]],mint,5);for(const [x,y] of [[82,100],[154,126]]){this.line([[120,y+12],[x,y]],mint,3);this.circle(x,y,10,'#31854e');}this.circle(137,146,11,'#cf523c');this.line([[120,175],[97,195]],'#a28660',3);this.line([[120,175],[144,195]],'#a28660',3);
      }else if(template==='volcano'){
        this.line([[45,160],[104,87],[134,87],[195,160]],mint,4);this.line([[120,153],[120,99]],'#e76d3c',9);this.circle(120,161,17,'#cd5335');this.text('Кратер',120,75,12);this.text('Магма',120,195,12);
      }else if(template==='dog_comparison'){
        for(const x of [77,165]){this.circle(x,122,26,'#b99258');this.circle(x-24,136,12,'#b99258');this.circle(x+24,136,12,'#b99258');this.circle(x-9,117,3,'#0c141a');this.circle(x+9,117,3,'#0c141a');}this.text('Лабрадор',76,172,10,80);this.text('Ретривер',165,172,10,80);
      }else{for(let i=0;i<90;i++){const a=i/9,r=3+i*.63;this.circle(120+Math.cos(a)*r,123+Math.sin(a)*r*.6,2,'#99bbd5');}}
      this.text('Условная схема',120,213,10,130,'#9cafb7');
    }
    draw(manager,level=0,t=0){
      const c=this.ctx,p=this.profile;c.setTransform(p.display.width/240,0,0,p.display.height/240,0,0);c.clearRect(0,0,240,240);c.save();c.beginPath();c.arc(120,120,120,0,Math.PI*2);c.clip();c.fillStyle=p.skin.background;c.fillRect(0,0,240,240);
      const inset=Math.max(35,p.display.safe_inset*240/p.display.width),contentScale=(240-2*inset)/170;
      let frame=manager.visual;const state=manager.state;
      const faceOnly=avatarFallback(frame)||frame?.images?.length&&frame.id!==this.imageId&&!(this.imageFrame&&this.imageTurn===manager.turn)||
        !frame&&manager.scene?.source_metadata?.planned_strategy==='retrieve_photo';
      if(faceOnly)frame=null;
      // Keep this turn's previous decoded picture until its refinement decodes.
      if(frame?.images?.length&&frame.id!==this.imageId&&this.imageFrame&&this.imageTurn===manager.turn)frame=this.imageFrame;
      const cover=frame?.images?.length&&this.image&&this.imageId===frame.id&&this.imageFit(frame)==='cover'&&!['offline','error','listening','recognizing'].includes(state);
      if(contentScale<1&&!cover){c.translate(120,120);c.scale(contentScale,contentScale);c.translate(-120,-120);}
      if(faceOnly||['offline','error','listening','recognizing'].includes(state)||state==='muted'&&!frame){this.face(state,level,t);}
      else if(frame?.type==='timer_widget'&&Number.isFinite(frame.metadata?.deadline)){
        const seconds=Math.max(0,Math.ceil(frame.metadata.deadline-Date.now()/1000)),hours=Math.floor(seconds/3600);
        const digits=hours?`${hours}:${String(Math.floor(seconds/60)%60).padStart(2,'0')}:${String(seconds%60).padStart(2,'0')}`:`${String(Math.floor(seconds/60)).padStart(2,'0')}:${String(seconds%60).padStart(2,'0')}`;
        this.text('Таймер',120,77,15);this.text(digits,120,135,hours?30:43,175,p.skin.face_color);this.text(seconds?'Идёт отсчёт':'Время вышло',120,174,12);
      }else if(frame?.type==='weather_card'&&frame.metadata?.state==='ready'&&Number.isFinite(Number(frame.metadata?.facts?.temperature))){
        this.text('Погода',120,62,14,145);this.text(frame.metadata.facts.temperature+' °C',120,116,36,170,p.skin.face_color);
        this.text(frame.subtitle,120,155,12,160);this.text('Open-Meteo',120,181,11,145);
      }else if(frame?.metadata?.backend==='device_setup'){
        this.text('Настройка погоды',120,76,14,155);this.text(frame.subtitle,120,117,13,160,p.skin.face_color);
        this.text('Шаг '+frame.metadata.facts.step+' из '+frame.metadata.facts.steps,120,156,12,145);
      }else if(frame?.metadata?.template&&frame.metadata.synthetic){this.text(frame.title,120,48,12,145);this.compactDiagram(frame.metadata.template);}
      else if(frame?.images?.length&&this.image&&this.imageId===frame.id){c.save();const alpha=!p.skin.reduced_motion&&this.imageReadyAt?Math.min(1,Math.max(0,(Date.now()-this.imageReadyAt)/180)):1;c.globalAlpha=alpha;this.drawFittedImage(frame,this.imageFit(frame));c.restore();c.fillStyle='rgba(12,20,26,.82)';c.fillRect(0,180,240,60);const overview=frame.metadata?.facts?.entity_match==='topic_overview';this.text(frame.metadata?.generation_provider?'ИИ-иллюстрация':overview?frame.metadata.facts.entity_title+' · обзор':frame.title,120,201,12,Math.min(155,240-2*inset));
        if(alpha>=.1&&this.presentedId!==frame.id){this.presentedId=frame.id;this.onImagePresented?.(frame.id,manager.turn);}}
      else if(frame&&!frame.images?.length){this.text(frame.title,120,76,15,165);this.text(frame.metadata?.state==='unavailable'?(frame.metadata?.visual_strategy==='retrieve'||/^image_/.test(frame.metadata?.reason||'')?'Фото недоступно':'Нет данных'):frame.metadata?.state==='cancelled'?'Остановлен':'Готово',120,112,16,165);
        const reason=frame.metadata?.facts?.generation_fallback_reason;
        if(reason){this.text(/consent/.test(reason)?'Нет согласия на ИИ':/daily_limit/.test(reason)?'Лимит ИИ исчерпан':/disabled|policy|mode_off/.test(reason)?'Генерация отключена':'ИИ недоступен',120,146,11,165);this.text('Можно повторить запрос',120,172,10,155);}
        else if(frame.metadata?.reason==='image_delivery_failed'){this.text('Ошибка загрузки фото',120,146,11,165);this.text('Повторите запрос',120,172,10,155);}}
      else if(manager.scene&&['icon','info_card'].includes(manager.scene.scene_type)){
        const payload=manager.scene.visual_payload||{};this.text(payload.icon||'✦',120,107,42,100,p.skin.face_color);this.text(payload.title,120,149,14,170);
        if(manager.scene.visual_subject==='Результат'){const value=(payload.text||'').replace(/^Получается\s+/,'').replace(/\.$/,'');let size=19;while(size>10){c.font=`${size}px system-ui`;if(c.measureText(value).width<=170)break;size--;}c.font=`${size}px system-ui`;this.text(c.measureText(value).width>170?'Подробности в панели':value,120,178,size,170);}
      }else if(state==='idle'&&p.skin.idle_screen==='clock'){this.text(new Date().toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'}),120,130,40,170,p.skin.face_color);}
      else if(state==='idle'&&p.skin.idle_screen==='image'&&this.wallpaper){c.drawImage(this.wallpaper,20,20,200,200);}
      else this.face(state,level,t);
      if(state==='speaking'&&frame)this.circle(120,225,Math.min(5,2+level*12),p.skin.face_color);
      c.restore();
    }
  }
  window.GoBotDeviceRenderer={DeviceRenderer,SceneManager,defaults};
})();
