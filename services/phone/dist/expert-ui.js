/* Expert cards share GoBot's authenticated channel; this module never launches CLI. */
(() => {
  'use strict';const node=(tag,text)=>{const el=document.createElement(tag);if(text!==undefined)el.textContent=text;return el;};
  const reasons={native_experts_disabled:'Экспертная делегация ещё не включена владельцем',confirmed_adult_profile_required:'Нужен подтверждённый взрослый PIN-профиль',expert_budget_missing_or_expired:'Не задан действующий отдельный лимит CLI',expert_budget_exhausted:'Выделенный лимит CLI использован',expert_budget_other_device:'Лимит выдан другому устройству',expert_quota_consent_required:'Нет отдельного согласия на экспертную квоту',isolation_not_verified:'Изоляция CLI не подтверждена',confirmation_transcript_pending:'Ожидается расшифровка согласия',current_user_confirmation_required:'Нужно согласие на актуальное предложение'};
  const states={awaiting_confirmation:'Ждёт согласия',queued:'В очереди',running:'Эксперт работает',completed:'Разбор готов',failed:'Эксперт завершился с ошибкой',timed_out:'Время ожидания истекло',cancelled:'Отменено',interrupted:'Прервано · автоматически не повторяется'};
  class ExpertPanel{
    constructor(){this.cards=new Map();this.epoch=0;}
    mount(){
      if(this.root)return;
      this.root=node('details');this.root.id='realtime-experts';this.root.className='expert-panel';this.root.append(node('summary','Экспертные задачи'));
      this.status=node('p','Проверяю доступность…');this.status.id='expert-availability';this.root.append(this.status);
      const label=node('label','Предпочтительный эксперт');this.select=node('select');this.select.id='realtime-expert-profile';this.select.append(Object.assign(node('option','Автоматически по задаче'),{value:''}));label.append(this.select);this.root.append(label);
      this.consent=node('input');this.consent.id='realtime-expert-consent';this.consent.type='checkbox';const check=node('label');check.append(this.consent,node('span','Разрешаю экспертную CLI-квоту в отдельном серверном лимите'));this.root.append(check);
      this.root.append(node('p','Обычный разговор идёт без CLI. Один разбор — один эксперт. Текущие факты требуют источников; мнение другой модели не заменяет проверку.'));
      const family=node('a','Выбрать или подтвердить профиль в разделе «Семья»');family.href='/settings/family';this.root.append(family);
      const refresh=node('button','Обновить доступность и готовые разборы');refresh.type='button';refresh.onclick=()=>this.refresh();this.root.append(refresh);
      this.list=node('div');this.root.append(this.list);(document.querySelector('.device-controls')||document.querySelector('main')).after?.(this.root);
      if(!this.root.isConnected)document.querySelector('main')?.append(this.root);
      this.consent.onchange=async()=>{try{await window.GoBotRealtime?.close('Согласие на экспертов изменено. Начните новую беседу.','settings_changed');const r=await fetch('/api/device/profile',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({voice:{expert_quota_consent:this.consent.checked}})});if(!r.ok)throw Error();await this.refresh();}catch(_){this.status.textContent='Не удалось сохранить согласие. Новый эксперт не запускался.';}};
      fetch('/api/device/profile').then(r=>r.json()).then(d=>{this.consent.checked=d.profile?.voice?.expert_quota_consent===true;}).catch(()=>{});
      void this.refresh();
    }
    clear(){this.epoch++;this.cards.clear();this.list?.replaceChildren();}
    async refresh(){
      const epoch=this.epoch;
      try{
        const conversation=window.GoBotClient?.conversationId?.();const r=await fetch('/api/realtime/experts'+(conversation?'?conversation_id='+encodeURIComponent(conversation):''));if(!r.ok)throw Error();const data=await r.json();if(epoch!==this.epoch)return;
        this.status.textContent=data.enabled?'Эксперты доступны после согласия на конкретную задачу.':(data.blocked_reasons||[]).map(x=>reasons[x]||x).join('. ');
        const selected=this.select.value;this.select.replaceChildren(Object.assign(node('option','Автоматически по задаче'),{value:''}));
        for(const profile of data.profiles||[]){const option=node('option',profile.requested_label+' · '+profile.model+' / '+profile.effort+(profile.isolation_verified?'':' · изоляция не подтверждена'));option.value=profile.profile;option.disabled=!profile.metadata_verified;this.select.append(option);}this.select.value=selected||'';
        for(const job of data.jobs||[])this.job(job);
        for(const job of data.saved_jobs||[]){this.job(job);if(job.result)this.result(job,job.result,true);}
      }catch(_){if(epoch===this.epoch)this.status.textContent='Статус экспертов временно недоступен. Обычный разговор остаётся доступен.';}
    }
    job(job){
      if(!job?.job_id||!this.list)return;
      let entry=this.cards.get(job.job_id);
      if(!entry){const card=node('article'),title=node('h4'),text=node('p'),detail=node('details'),summary=node('summary','Полный результат'),body=node('pre');detail.append(summary,body);detail.hidden=true;card.append(title,text,detail);this.list.append(card);entry={card,title,text,detail,body};this.cards.set(job.job_id,entry);}
      const who=job.expert||job.result?.actual_executor||{};
      entry.title.textContent=(states[job.state]||job.state)+' · '+(who.requested_label||who.profile||'Эксперт');
      entry.text.textContent=[who.model,who.effort,job.error?(reasons[job.error]||job.error):'',job.storage==='temporary_session'?'Результат только в текущей сессии':''].filter(Boolean).join(' · ');
    }
    result(job,result,deferred=false){
      if(!job?.job_id||!result?.display_text)return;
      const data={...job,state:'completed',expert:job?.expert||result.actual_executor};this.job(data);const entry=this.cards.get(job.job_id);if(!entry)return;
      entry.detail.hidden=false;entry.body.textContent=result.display_text;
      if(deferred)entry.text.textContent+=' · Сохранён для просмотра; текущую реплику не перебивает';
    }
    event(item){if(item.type==='expert_job')this.job(item.data.job);if(item.type==='expert_result')this.result(item.data.job,item.data.result,item.data.voice_deferred);}
  }
  const panel=new ExpertPanel();window.GoBotExpertUI=panel;window.addEventListener('DOMContentLoaded',()=>panel.mount());
})();
