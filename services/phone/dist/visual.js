/* gobot.ui v2 Browser Renderer. No HTML supplied by models is interpreted. */
(() => {
  'use strict';
  const kinds=new Set(['image_card','image_gallery','info_card','timer_widget','weather_card','status_card','music_card','rich_answer']);
  const imagePath=/^\/api\/visual\/assets\/[a-f0-9]{64}\/(browser|preview|device)\.jpg$/;
  const icons={image_card:'↗',image_gallery:'▧',info_card:'✦',timer_widget:'◷',weather_card:'☁',status_card:'◉',music_card:'♫',rich_answer:'◇'};
  const semanticIcons={image_card:'image',image_gallery:'image',info_card:'info',timer_widget:'timer',weather_card:'sun-cloud',status_card:'info',music_card:'music',rich_answer:'book'};
  const weatherGlyphs={sun:'sun',partly_cloudy:'sun-cloud',cloud:'cloud',rain:'rain',snow:'snow',storm:'storm',fog:'fog',wind:'wind',unknown:'question'};
  const node=(tag,text,className)=>{const value=document.createElement(tag);if(text!==undefined)value.textContent=String(text);if(className)value.className=className;return value;};
  function sourceURL(value){try{const url=new URL(value);return url.protocol==='https:'&&['commons.wikimedia.org','creativecommons.org','openverse.org','www.openverse.org','api.openverse.org','flickr.com','www.flickr.com','open-meteo.com'].includes(url.hostname)&&!url.username&&!url.password&&!url.port?url.href:null;}catch(_){return null;}}
  class BrowserVisualRenderer {
    constructor(root,timerRoot=null){this.root=root;this.timerRoot=timerRoot||root;this.intervals=new Set();this.frames=new Map();this.timerCards=new Map();this.currentTimer=null;}
    begin(){if(this.timerRoot===this.root){for(const timer of this.intervals)clearInterval(timer);this.intervals.clear();this.timerCards.clear();this.currentTimer=null;}this.frames.clear();this.root.replaceChildren();this.root.hidden=true;}
    loading(){this.loadingNow=true;if(!this.frames.size){this.root.replaceChildren();this.root.hidden=true;}}
    interrupt(){this.loadingNow=false;if(!this.frames.size){this.root.replaceChildren();this.root.hidden=true;}}
    syncDisplay(text){for(const entry of this.frames.values())entry.body.hidden=!!text&&text.trim()===(entry.frame.text||'').trim();}
    hasTimer(id){return this.timerCards.has(id)||this.currentTimer===id;}
    cancelTimers(ids){for(const id of ids||[]){const timer=this.timerCards.get(id);if(timer){clearInterval(timer.ticker);this.intervals.delete(timer.ticker);timer.output.textContent='Таймер остановлен';timer.frame.metadata.state='cancelled';}}}
    clearScene(){for(const [id,entry] of this.frames){if(entry.frame.metadata?.transient_scene){entry.card.remove();this.frames.delete(id);}}}
    render(frame){
      if(frame?.metadata?.backend==='answer_map')return false;
      if(!frame||frame.namespace!=='gobot.ui'||frame.version!==2||!kinds.has(frame.type)||typeof frame.id!=='string')return false;
      const avatar=frame.metadata?.avatar_fallback||frame.metadata?.transient_scene&&frame.metadata?.visual_stage==='provisional'||
        ['image_card','image_gallery'].includes(frame.type)&&!frame.images?.some(image=>imagePath.test(image?.url||'')&&imagePath.test(image?.preview_variant||''))||frame.metadata?.state==='unavailable'&&
        (/^(?:image_|generation_|optional_visual_|private_image_)/.test(frame.metadata?.reason||'')||frame.metadata?.facts?.visual_fulfillment==='fallback');
      if(avatar){
        for(const [id,entry] of this.frames)if(!entry.decoded&&entry.frame.type!=='timer_widget'){entry.card.remove();this.frames.delete(id);}
        if(!this.frames.size){this.root.replaceChildren();this.root.hidden=true;}this.loadingNow=false;return false;
      }
      // The two stages occupy one scene slot, never an accumulating carousel.
      const stagePrevious=[];
      if(frame.metadata?.visual_stage&&!this.frames.has(frame.id)){
        const incoming=frame.metadata.visual_revision||0;
        for(const [id,entry] of this.frames){
          if(!entry.frame.metadata?.visual_stage)continue;
          if((entry.frame.metadata.visual_revision||0)>incoming)return false;
          stagePrevious.push([id,entry]);
        }
      }
      const existingTimer=frame.type==='timer_widget'&&this.timerCards.get(frame.metadata?.timer_id);
      if(existingTimer){if(frame.metadata.state==='cancelled'){clearInterval(existingTimer.ticker);this.intervals.delete(existingTimer.ticker);existingTimer.output.textContent='Таймер остановлен';existingTimer.frame.metadata.state='cancelled';}return true;}
      if(!stagePrevious.length&&Array.isArray(frame.images)&&frame.images.some(image=>imagePath.test(image?.url||'')))this.clearScene();
      if(this.frames.has(frame.id)&&frame.metadata?.transient_scene){this.clearScene();}
      if(this.frames.has(frame.id))return true;
      this.loadingNow=false;this.root.hidden=false;
      if(!this.frames.size)this.root.replaceChildren();
      const card=node('article',undefined,'visual-card visual-'+frame.type);card.dataset.visualId=frame.id;
      if(frame.metadata?.visual_stage){card.classList?.add('visual-stage-replace');}
      const replaceStage=()=>{for(const [id,entry] of stagePrevious){entry.card.remove();this.frames.delete(id);}card.hidden=false;};
      const header=node('div',undefined,'visual-heading');header.append(window.GoBotDesign?.domIcon(semanticIcons[frame.type])||node('span',frame.metadata?.icon||icons[frame.type],'visual-icon'),node('h3',frame.title||'Визуальный ответ'));card.append(header);
      if(frame.subtitle)card.append(node('p',frame.subtitle,'visual-subtitle'));
      const body=node('p',frame.text||'','visual-body');card.append(body);
      const images=Array.isArray(frame.images)?frame.images.slice(0,4):[];const gallery=node('div',undefined,'visual-gallery');let count=0;
      for(const image of images){
        if(!image||!imagePath.test(image.url||'')||!imagePath.test(image.preview_variant||''))continue;
        const figure=node('figure');const open=node('a');open.href=image.url;open.target='_blank';open.rel='noopener';open.setAttribute('aria-label','Открыть изображение крупнее');
        const img=node('img');img.src=image.preview_variant;img.alt=image.alt||image.caption||frame.title||'Изображение';img.loading=frame.metadata?.visual_stage?'eager':'lazy';img.decoding='async';img.width=480;img.height=360;
        img.onload=()=>{if(this.frames.has(frame.id)){this.frames.get(frame.id).decoded=true;replaceStage();this.onImageReady?.(frame.id,img);}};
        img.onerror=()=>{const entry=this.frames.get(frame.id);if(!entry)return;this.onImageError?.(frame.id);figure.remove();entry.failures=(entry.failures||0)+1;if(entry.failures>=count){card.remove();this.frames.delete(frame.id);if(!this.frames.size){this.root.replaceChildren();this.root.hidden=true;}}};
        open.append(img);figure.append(open);if(image.caption)figure.append(node('figcaption',image.caption));
        const credit=node('p',undefined,'visual-credit');credit.append(node('span',(image.attribution||'')+' · '));
        for(const [label,value] of [[image.source?.label||'Источник',image.source?.url],[image.license||'Лицензия',image.license_url]]){
          const url=sourceURL(value);if(url){const link=node('a',label);link.href=url;link.target='_blank';link.rel='noopener noreferrer';credit.append(link,node('span',' · '));}else if(label)credit.append(node('span',label+' · '));
        }
        credit.append(node('span','Размер изменён; метаданные удалены.'));figure.append(credit);gallery.append(figure);count++;
      }
      if(count){card.append(gallery);card.hidden=true;}
      if(stagePrevious.length){if(count)card.hidden=true;else replaceStage();}
      if(!count&&['image_card','image_gallery'].includes(frame.type))card.append(node('p','Изображение пока не получено.','visual-unavailable'));
      const state=frame.metadata||{};
      if(frame.type==='weather_card'&&state.weather){
        const weather=state.weather,condition=node('div',weather.condition,'weather-condition');const glyph=window.GoBotDesign?.domIcon(weatherGlyphs[weather.icon]||'cloud');if(glyph)condition.append(glyph);card.append(condition);
        if(weather.days?.length){const table=node('table',undefined,'weather-forecast');
          const head=node('tr');for(const label of ['Дата','Погода','°C','Осадки','Ветер'])head.append(node('th',label));table.append(head);
          for(const day of weather.days.slice(0,16)){const row=node('tr');for(const [index,value] of [day.date,day.condition,day.low+'…'+day.high,day.rain_percent+'%',day.wind_kmh+' км/ч'].entries()){const cell=node('td',value);if(index===1){const glyph=window.GoBotDesign?.domIcon(weatherGlyphs[day.icon]||'cloud');if(glyph)cell.append(glyph);}row.append(cell);}table.append(row);}card.append(table);
        }
      }
      if(state.synthetic)card.append(node('small',state.generation_provider?'ИИ-иллюстрация · '+state.generation_provider+' · детали не подтверждены':'Условная иллюстрация · создана локально · не фотография','visual-state'));
      if(state.selection_basis==='source_metadata_search_unverified')card.append(node('small','Результаты поиска по метаданным; точное соответствие объекту не подтверждено.','visual-state'));
      if(frame.type==='timer_widget'&&Number.isFinite(state.deadline)){
        this.currentTimer=state.timer_id||null;const timer=node('output',undefined,'visual-countdown');timer.setAttribute('role','timer');timer.setAttribute('aria-live','off');card.append(timer);
        let ticker;const update=()=>{const seconds=Math.max(0,Math.ceil(state.deadline-Date.now()/1000));timer.textContent=seconds?`${String(Math.floor(seconds/60)).padStart(2,'0')}:${String(seconds%60).padStart(2,'0')}`:'Время вышло';if(!seconds&&ticker){clearInterval(ticker);this.intervals.delete(ticker);state.state='expired';}};
        update();ticker=setInterval(update,250);this.intervals.add(ticker);
        if(state.timer_id)this.timerCards.set(state.timer_id,{ticker,output:timer,card,frame});
        if(typeof state.timer_id==='string'&&/^[a-f0-9-]{36}$/.test(state.timer_id)){
          const cancel=node('button','Остановить таймер','visual-action');cancel.type='button';
          cancel.onclick=async()=>{cancel.disabled=true;try{const response=await fetch('/api/visual/timer/cancel',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({timer_id:state.timer_id})});if(!response.ok)throw Error();clearInterval(ticker);this.intervals.delete(ticker);timer.textContent='Таймер остановлен';state.state='cancelled';}catch(_){cancel.disabled=false;cancel.textContent='Не удалось остановить. Повторить';}};card.append(cancel);
        }
      }
      if(state.facts&&typeof state.facts==='object'){
        const internal=new Set(['presentation_group','entity_title','entity_source','entity_match','subject','query_basis','identification','visual_fulfillment','source_failure_reason','generation_fallback_reason','retrieval_fallback_reason','source_policy']);
        const entries=Object.entries(state.facts).filter(([key])=>!internal.has(key)).slice(0,12);
        if(entries.length){const facts=node('dl',undefined,'visual-facts');for(const [key,value] of entries)facts.append(node('dt',key),node('dd',String(value)));card.append(facts);}
      }
      if(state.state&&state.state!=='ready')card.append(node('small',state.state==='loading'?'Загружается':state.state==='expired'?'Срок истёк':state.state==='cancelled'?'Остановлено':'Данные недоступны','visual-state'));
      if(frame.type==='timer_widget'&&this.timerRoot!==this.root){
        this.timerRoot.hidden=false;this.timerRoot.append(card);if(!this.root.children.length)this.root.hidden=true;
        if(this.timerCards.size>16){const [id,old]=this.timerCards.entries().next().value;clearInterval(old.ticker);this.intervals.delete(old.ticker);old.card.remove();this.timerCards.delete(id);}
      }else this.root.append(card);
      this.frames.set(frame.id,{frame,body,card});return true;
    }
  }
  window.GoBotVisual={BrowserVisualRenderer};
})();
