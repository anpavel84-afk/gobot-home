/* Server-persisted prototype appearance; previews never call speech or a model. */
(() => {
  'use strict';const byId=id=>document.getElementById(id);let profile,renderer,manager;
  function draft(){
    return {...profile,skin:{...profile.skin,skin_id:byId('skin-id').value,face_color:byId('skin-color').value,background:byId('skin-background').value,
      expression:byId('skin-expression')?.value||'auto',eyes:byId('skin-eyes').value,mouth:byId('skin-mouth').value,animation_intensity:Number(byId('skin-intensity').value),reduced_motion:byId('skin-reduced').checked,idle_screen:byId('skin-idle').value},
      screen:{automatic_illustrations:byId('screen-auto').checked,visual_strategy:byId('screen-visual-strategy').value,style:byId('screen-style').value,prefer_real_photos:byId('screen-photos').checked,
        generation_allowed:byId('screen-generation').checked,generation_mode:byId('image-generation-mode').value,generation_provider:byId('image-generator').value,source_preference:byId('screen-source-preference').value,visual_source_policy:byId('screen-source-policy').value,generation_consent:byId('image-generation-consent').checked,generation_daily_limit:Number(byId('image-generation-limit').value),thematic_icons:byId('screen-icons').checked,hold_after_response_seconds:Number(byId('screen-hold').value),return_to_idle:byId('screen-return').checked},
      feedback:{enabled:byId('feedback-enabled').checked,filler_enabled:byId('feedback-filler').checked,quiet:byId('feedback-quiet').checked,threshold_ms:Number(byId('feedback-delay').value),volume:Number(byId('feedback-volume').value)},
      conversation:{...profile.conversation,followup_enabled:byId('followup-enabled').checked,followup_seconds:Number(byId('followup-seconds').value)},
      interaction_mode:byId('device-input').value,keep_screen_awake:byId('device-wake-lock').checked};
  }
  function preview(){if(!profile)return;renderer.setProfile(draft());manager.profile=draft();manager.state=byId('skin-state').value;renderer.draw(manager,manager.state==='speaking'?.12:0,performance.now());}
  async function load(){
    const response=await fetch('/api/device/profile');if(!response.ok)throw Error();const data=await response.json();profile=data.profile;
    byId('followup-enabled').checked=profile.conversation.followup_enabled;byId('followup-seconds').value=profile.conversation.followup_seconds;
    const expressions=byId('skin-expression');if(expressions){expressions.replaceChildren();for(const item of [{id:'auto',label:'Автоматически по состоянию'},...(window.GoBotDesign?.data.expressions||[])]){const option=document.createElement('option');option.value=item.id;option.textContent=item.label;expressions.append(option);}expressions.value=profile.skin.expression||'auto';}
    byId('screen-visual-strategy').value=profile.screen.visual_strategy||'question_then_refine';
    byId('screen-source-policy').value=profile.screen.visual_source_policy==='wikimedia_only'?'wikimedia_only':'wikimedia_generate';byId('image-generation-mode').value=profile.screen.generation_mode;byId('image-generator').value=profile.screen.generation_provider;
    byId('image-generation-consent').checked=profile.screen.generation_consent;byId('image-generation-limit').value=profile.screen.generation_daily_limit;byId('screen-source-preference').value=profile.screen.source_preference;
    const capabilities=(await(await fetch('/api/status')).json()).backend?.visual?.generation;
    byId('image-generation-status').textContent=capabilities?'Codex: возможность обнаружена, изоляция генерации ещё не проверена. OpenAI Image API: '+(capabilities.openai?.available?'ключ сохранён; реальные пробы ещё не выполнены.':'нужен API-ключ.'):'Диагностика генератора временно недоступна.';
    const usage=await(await fetch('/api/visual/generation/usage')).json();
    byId('image-generation-status').textContent+=' Попыток Image API сегодня (UTC): '+(usage.attempts?.openai||0)+'. Денежная стоимость недоступна.';
    const openingVoice=byId('voice').value||'marin';const openingStatus=await(await fetch('/api/speech/openings/status/'+openingVoice)).json();byId('speech-openings-status').textContent=openingVoice+': готово '+openingStatus.ready_count+' из '+openingStatus.catalog_count+' вступлений. Denis для ожидания отключён.';
    window.GoBotClient?.feedback?.configure(profile.feedback);
    const f=profile.feedback;byId('feedback-enabled').checked=f.enabled;byId('feedback-filler').checked=f.filler_enabled;byId('feedback-quiet').checked=f.quiet;byId('feedback-delay').value=f.threshold_ms;byId('feedback-volume').value=f.volume;
    for(const [id,value] of Object.entries({'skin-id':profile.skin.skin_id,'skin-color':profile.skin.face_color,'skin-background':profile.skin.background,'skin-eyes':profile.skin.eyes,'skin-mouth':profile.skin.mouth,'skin-intensity':profile.skin.animation_intensity,'skin-idle':profile.skin.idle_screen,'screen-style':profile.screen.style,'screen-hold':profile.screen.hold_after_response_seconds,'device-input':profile.interaction_mode}))byId(id).value=value;
    for(const [id,value] of Object.entries({'skin-reduced':profile.skin.reduced_motion,'screen-auto':profile.screen.automatic_illustrations,'screen-photos':profile.screen.prefer_real_photos,'screen-generation':profile.screen.generation_allowed,'screen-icons':profile.screen.thematic_icons,'screen-return':profile.screen.return_to_idle,'device-wake-lock':profile.keep_screen_awake}))byId(id).checked=value;
    renderer=new GoBotDeviceRenderer.DeviceRenderer(byId('skin-preview'),profile);manager=new GoBotDeviceRenderer.SceneManager(profile);renderer.onWallpaperReady=preview;if(profile.has_screensaver)renderer.loadWallpaper();preview();
    byId('device-settings-status').textContent='Сохранено на домашнем сервере. Голосовая активация «ГоБот» пока не настроена.';
  }
  byId('device-mode-link').addEventListener('click',()=>window.GoBotClient?.saveSettings());
  for(const node of document.querySelectorAll('#device-appearance input,#device-appearance select'))node.addEventListener('input',preview);
  byId('device-save').onclick=async()=>{try{const value=draft();const response=await fetch('/api/device/profile',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({skin:value.skin,screen:value.screen,feedback:value.feedback,conversation:value.conversation,interaction_mode:value.interaction_mode,keep_screen_awake:value.keep_screen_awake})});if(!response.ok)throw Error();await load();}catch(_){byId('device-settings-status').textContent='Не удалось сохранить настройки. Проверь значения.';}};
  byId('device-screensaver-upload').onclick=async()=>{const file=byId('device-screensaver').files[0];if(!file)return;try{if(file.size>2*1024*1024)throw Error();const response=await fetch('/api/device/screensaver',{method:'POST',headers:{'Content-Type':file.type},body:file});if(!response.ok)throw Error();await load();byId('device-settings-status').textContent='Заставка сохранена локально. Это статичная картинка, не анимированное лицо.';}catch(_){byId('device-settings-status').textContent='Нужен JPEG/PNG/WebP до 2 MB и 4 мегапикселей, без анимации.';}};
  byId('device-screensaver-delete').onclick=async()=>{await fetch('/api/device/screensaver',{method:'DELETE'});await load();};
  load().catch(()=>byId('device-settings-status').textContent='Настройки устройства пока недоступны.');
})();
