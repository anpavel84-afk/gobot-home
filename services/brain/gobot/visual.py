"""Server presentation orchestration shared by Browser and future device adapters."""
import asyncio
import hashlib
import io
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

from PIL import Image,ImageDraw,ImageFont
from .presentation import Presentation,VisualMetadata,VisualAction,VisualSource,PresentationDecision,VisualIntent,frame_id
from .visual_images import ImageCache,ImageCandidate,CommonsImages,OpenverseImages,SafeImageHTTP,ImageUnavailable,source_config,ROOT,NORMALIZATION_VERSION,FETCH_POLICY_VERSION
from .image_query import DICTIONARY,VERSION as QUERY_VERSION,subject_matches_caption,caption_names_subject,ImageQueryPlanner,canonical_subject

REASONS={
 'image_sources_disabled':'Внешний источник изображений отключён или не настроен. Локальные карточки и схемы доступны.',
 'image_source_contact_required':'Источник фотографий требует публичный контакт оператора. Его можно указать в настройках визуальных ответов.',
 'image_source_access_denied':'Источник отклонил загрузку изображения. Другой снимок не подставлялся.',
 'image_source_rate_limited':'Источник временно ограничил запросы. Повторные загрузки отложены.',
 'image_not_found':'В доступном каталоге не нашлось подходящего изображения по этому названию. Можно уточнить объект или его внешний вид.',
 'private_image_not_available':'Личное изображение не загружено. Семейные фотографии и планы не ищутся в интернете.',
 'image_query_required':'Уточни, какой объект нужно показать.',
 'diagram_source_required':'Уточни элементы схемы или предоставь исходный план. Я не буду придумывать устройство вашей теплицы.',
 'image_request_budget_exceeded':'Достигнут лимит обращений к источнику изображений. Повторные загрузки временно отложены; готовые изображения в кэше доступны.',
 'reviewed_image_changed':'Изображение источника изменилось после проверки. Старый визуальный референс не подставляется без повторной проверки.',
 'image_source_unavailable':'Источник изображений сейчас не смог отдать результат. Попробуй повторить запрос позже.',
 'image_lookup_timeout':'Источник изображений не ответил вовремя. Попробуй повторить запрос позже.',
 'image_network_unavailable':'Не удалось связаться с источником изображений. Проверь соединение и повтори запрос позже.',
 'image_query_ambiguous':'У этого названия несколько значений. Уточни, какой предмет или внешний вид нужно показать, чтобы я не подставил другой объект.',
}

@dataclass
class VisualResult:
    frame:Presentation
    display_text:str
    speech_text:str

class VisualService:
    def __init__(self,cache=None,*,provider_factory=None,config_loader=source_config,fallback_factory=None):
        self.cache=cache or ImageCache();self.intent=PresentationDecision();self.config_loader=config_loader
        self.provider_factory=provider_factory or (lambda cfg:(OpenverseImages if cfg.get('provider')=='openverse' else CommonsImages)(SafeImageHTTP(cfg['user_agent'],budget=self.cache.reserve_request,on_limit=self.cache.delay_source)))
        self.answer_fallback=fallback_factory if provider_factory else (fallback_factory or (lambda:CommonsImages(SafeImageHTTP('GoBotHomeVisual/0.3 (https://github.com/anpavel84-afk/gobot-home)',budget=self.cache.reserve_request,on_limit=self.cache.delay_source))))
        self.catalog=json.loads((Path(__file__).parents[1]/'visual-catalog.json').read_text(encoding='utf-8'))['items']
        self.slots=asyncio.Semaphore(2);self.locks={}

    def available(self):
        from .image_generation import generation_status
        return {'generation':generation_status(),'image_source':self.config_loader().get('provider','disabled'),'configured':bool(self.config_loader()),'query_dictionary':{'installed':DICTIONARY.is_file(),'version':QUERY_VERSION,'local_only':True},'cache_bytes_limit':self.cache.max_bytes,'cache_entries_limit':self.cache.max_entries,'asset_ttl_seconds':self.cache.ttl,'query_ttl_seconds':86400,'failure_ttl_seconds':600,'source_requests_per_minute':8,'source_requests_per_day':80,'public_images_only':True,'weather_source':'not_configured','music_source':'not_configured'}

    def fallback(self,req,title,code,kind='info_card',text=None):
        message=text or REASONS.get(code,'Изображение сейчас недоступно. Попробуй позже; неподтверждённую картинку я не подставляю.')
        frame=Presentation(id=frame_id(req.turn_id,kind),type=kind,title=title,text=message,metadata=VisualMetadata(state='unavailable',reason=code))
        return VisualResult(frame,message,message)

    def generation_usage(self,owner):
        digest=hashlib.sha256(owner.encode()).hexdigest()
        with self.cache.connect() as c:
            exists=c.execute("SELECT 1 FROM sqlite_master WHERE name='generation_attempts' AND type='table'").fetchone()
            rows=c.execute('SELECT provider,count FROM generation_attempts WHERE owner=? AND day=?',(digest,int(time.time()//86400))).fetchall() if exists else []
        return {'day_basis':'UTC','attempts':dict(rows),'includes_failed_attempts':True,'dollar_cost':None}

    async def speculative_sources(self,query,commons,openverse):
        """Give the article resolver a head start; overlap slow sources on cache misses."""
        async def article():
            return commons,await commons.page_images(query,3)
        async def photos():
            candidates=await openverse.search(query,3)
            return openverse,[item for item in candidates if caption_names_subject(query,item.caption)]
        wiki=asyncio.create_task(article())
        tasks={wiki}
        try:
            ready,_=await asyncio.wait(tasks,timeout=.35)
            if ready and not wiki.exception() and wiki.result()[1]:return wiki.result()
            tasks.add(asyncio.create_task(photos()))
            pending=set(tasks)
            while pending:
                ready,pending=await asyncio.wait(pending,return_when=asyncio.FIRST_COMPLETED)
                for task in sorted(ready,key=lambda t:t is not wiki):
                    if not task.exception() and task.result()[1]:return task.result()
            return commons,[]
        finally:
            for task in tasks:task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)

    async def images(self,req,intent,*,cache_only=False):
        if not intent.query:return self.fallback(req,'Какое изображение показать?','image_query_required')
        if re.search(r'https?://|file:|localhost',intent.query,re.I):return self.fallback(req,'Источник изображения','direct_image_url_not_supported',text='Прямые ссылки не загружаются этим инструментом. Опиши объект: поиск работает только через разрешённый источник изображений.')
        if intent.catalog_id is None and re.search(r'raspberry\s*pi\s*[1-9]|рас[пб]ерри\s*пи\s*[1-9]',intent.query,re.I):return self.fallback(req,'Нужен референс конкретной платы','board_revision_not_reviewed',text='Для указанной модели платы ещё нет проверенного изображения в каталоге. Фотографию другой ревизии вместо неё я не подставляю.')
        if re.search(r'\b(?:мо(?:й|я|ё|е|ю|его|ей|их|им|ими|ему|ем|ём)|наш\w*|мам[ауы]|пап[ауы]|доч[ьи]|сын[ауы]?|жен[аыу]|муж[а]?)\b',intent.query,re.I):return self.fallback(req,'Личное изображение','private_image_not_available')
        config=self.config_loader();catalog=self.catalog.get(intent.catalog_id)
        base=[intent.query.casefold().strip(),intent.gallery,config.get('provider'),config.get('contact',''),catalog,NORMALIZATION_VERSION]
        if intent.strict_subject:base+=['answer_subject_v5_grammatical_names']
        if intent.speculative:base+=['prefetch_subject_title_v1']
        def hashed(parts):return hashlib.sha256(json.dumps(parts,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        positive_key=hashed(base);legacy_key=hashed(base+[2]);key=hashed(base+[FETCH_POLICY_VERSION,QUERY_VERSION,DICTIONARY.is_file()])
        # Bound coordination state; active tasks remain protected by the global slots.
        if key not in self.locks:
            if len(self.locks)>=128:self.locks={k:v for k,v in self.locks.items() if v.locked()}
            self.locks.setdefault(key,asyncio.Lock())
        async with self.locks[key]:
            cached=await asyncio.to_thread(self.cache.query,positive_key)
            if not cached or not cached[0]:
                legacy=await asyncio.to_thread(self.cache.query,legacy_key)
                cached=legacy if legacy and legacy[0] else await asyncio.to_thread(self.cache.query,key)
            hit=cached is not None;sent=False
            if cached:records,reason=cached
            elif cache_only:return self.fallback(req,'Иллюстрация','image_not_found')
            else:
                records=[];reason=None
                if not config:reason='image_sources_disabled'
                else:
                    provider=self.provider_factory(config)
                    try:
                        async with self.slots,asyncio.timeout(18):
                            curated=(catalog.get('openverse_images') if config.get('provider')=='openverse' else catalog.get('images')) if catalog else None
                            sent=not bool(curated)
                            hybrid=config.get('provider')=='openverse' and self.answer_fallback is not None and not curated
                            if intent.speculative and not curated and isinstance(provider,CommonsImages):
                                candidates=await provider.page_images(intent.query,3)
                                if not candidates:candidates=await provider.search(intent.query,3)
                            elif hybrid and intent.speculative:
                                common=self.answer_fallback()
                                if hasattr(common,'page_images'):
                                    provider,candidates=await self.speculative_sources(intent.query,common,provider)
                                else:candidates=await provider.search(intent.query,3)
                                if not candidates:
                                    provider=common
                                    query_plan=await asyncio.to_thread(ImageQueryPlanner().plan,intent.query)
                                    candidates=await common.search(query_plan.terms[0],3)
                            elif hybrid:
                                common=self.answer_fallback();candidates=[];resolved=False
                                if re.search('[а-яё]',intent.query,re.I) and hasattr(common,'page_images'):
                                    try:
                                        async with asyncio.timeout(3):candidates=await common.page_images(intent.query,3)
                                    except (ImageUnavailable,TimeoutError):pass
                                    resolved=True
                                    if candidates:provider=common
                                if not candidates:
                                    try:
                                        async with asyncio.timeout(3):candidates=await provider.search(intent.query,3)
                                    except (ImageUnavailable,TimeoutError):candidates=[]
                                    if intent.strict_subject:candidates=[item for item in candidates if item.matched_query==intent.query or subject_matches_caption(intent.query,item.caption)]
                                if not candidates:
                                    provider=common
                                    query_plan=await asyncio.to_thread(ImageQueryPlanner().plan,intent.query)
                                    candidates=await provider.search(query_plan.terms[0],3)
                                    if intent.strict_subject:candidates=[item for item in candidates if subject_matches_caption(intent.query,item.caption)]
                                    if not candidates and not resolved and hasattr(common,'page_images'):candidates=await common.page_images(intent.query,3)
                            else:candidates=[ImageCandidate(**item) for item in curated] if curated else await provider.search(catalog.get('search_query',intent.query) if catalog else intent.query,3)
                            for candidate in candidates[:3]:
                                if intent.speculative and candidate.matched_query!=intent.query and not caption_names_subject(intent.query,candidate.caption):continue
                                if intent.strict_subject and candidate.matched_query!=intent.query and not subject_matches_caption(intent.query,candidate.caption):continue
                                try:
                                    record=await asyncio.to_thread(self.cache.source,candidate.url)
                                    if record and candidate.sha256 and record.get('source_sha256')!=candidate.sha256:record=None
                                    if record is None:
                                        raw,_=await provider.client.get(candidate.url)
                                        record=await asyncio.to_thread(self.cache.put,candidate,raw)
                                    if candidate.matched_query:
                                        record={**record,**{key:getattr(candidate,key) for key in ('matched_query','entity_title','entity_source','entity_exact')}}
                                    if record['asset_id'] not in {r['asset_id'] for r in records}:records.append(record)
                                    if len(records)>=(3 if intent.gallery else 1):break
                                except ImageUnavailable as e:
                                    reason=e.code
                                    if e.code in {'image_request_budget_exceeded','image_source_rate_limited'}:break
                    except ImageUnavailable as e:reason=e.code
                    except TimeoutError:reason='image_lookup_timeout'
                    except asyncio.CancelledError:raise
                    except Exception:reason='image_lookup_unavailable'
                await asyncio.to_thread(self.cache.save_query,key if not records else positive_key,records,reason)
            if records and hit:await asyncio.to_thread(self.cache.save_query,positive_key,records,reason)
        if not records:
            result=self.fallback(req,catalog['title'] if catalog else 'Изображение: '+intent.query[:120],reason or 'image_not_found')
            result.frame.metadata.cache_hit=hit;result.frame.metadata.query_sent_to_source=sent;result.frame.cache_key=key
            if catalog:
                result.frame.subtitle='Объект: '+catalog['title']
                description={'oxheart':'Запрошены томаты сердцевидного типа.','labrador':'Запрошен внешний вид лабрадора-ретривера, породы собак.','raspberry-pi':'Запрошена плата одноплатного компьютера Raspberry Pi.'}.get(intent.catalog_id,'')
                result.display_text+=' '+description;result.frame.text=result.display_text
            return result
        images=[self.cache.public(record) for record in records]
        title=catalog['title'] if catalog else intent.query[:160]
        text=catalog['text'] if catalog else 'Найдены изображения по запросу. Подписи и ссылки ведут к первоисточникам; совпадение конкретной разновидности по одной фотографии не гарантируется.'
        speech=catalog['speech'] if catalog else 'Нашёл изображения по твоему запросу. Ссылки на источники сохранены.'
        frame=Presentation(id=frame_id(req.turn_id,'images'),type='image_gallery' if len(images)>1 else 'image_card',title=title,text=text,images=images,actions=[VisualAction(type='open_image',label='Открыть крупнее',asset_id=images[0].asset_id)],metadata=VisualMetadata(visual_strategy='retrieve',backend=config.get('provider'),cache_hit=hit,query_sent_to_source=sent,approximate_match=catalog.get('approximate_match',False) if catalog else True,selection_basis='curated_visual_review' if catalog else 'source_metadata_search_unverified',reason=reason),source=VisualSource(label=images[0].source.label),expires_at=min(r['expires_at'] for r in records),cache_key=key)
        frame.metadata.backend='wikimedia' if images[0].source.label.startswith('Wikimedia') else 'openverse'
        if records[0].get('entity_title'):
            record=records[0];exact=record['entity_exact']
            frame.metadata.selection_basis='wikimedia_article_image';frame.metadata.approximate_match=not exact
            frame.metadata.facts.update({'entity_title':record['entity_title'],'entity_source':record['entity_source'],'entity_match':'exact_name' if exact else 'topic_overview'})
            frame.title=title+('' if exact else ' · обзор')
            frame.text='Фото к статье «'+record['entity_title']+'».'+('' if exact else ' Конкретная разновидность по этому снимку не подтверждена.')
            text=frame.text
        return VisualResult(frame,text,speech)

    async def handle(self,req,*,active_turns=0):
        intent=self.intent.detect(req.text)
        if not intent:return self.fallback(req,'Визуальный ответ','image_query_required')
        if intent.kind=='image':return await self.images(req,intent)
        if intent.kind=='weather':return self.fallback(req,'Погода','weather_not_configured','weather_card','Погодный источник и место ещё не настроены. Текущую температуру не подставляю.')
        if intent.kind=='music':return self.fallback(req,'Сейчас играет','music_not_configured','music_card','Музыкальный источник не подключён. Сейчас GoBot не получает данные о текущем треке и не управляет плеером.')
        if intent.kind=='status':
            text='GoBot Brain работает. Данные реальной платы пока недоступны.'
            frame=Presentation(id=frame_id(req.turn_id,'status'),type='status_card',title='GoBot Home',text=text,metadata=VisualMetadata(facts={'Brain':'на связи','Активных запросов':str(active_turns),'ESP32':'ещё не подключена'}))
            return VisualResult(frame,text,text)
        if intent.kind=='diagram' and intent.catalog_id=='gobot-pipeline':return await asyncio.to_thread(self.diagram,req)
        if intent.kind=='info':
            from .quality import arithmetic_expression,calculate
            expression=arithmetic_expression(re.sub(r'^.*?карточк\w*\s+(?:результата|ответа)\s*','',req.text,flags=re.I))
            if expression:
                try:value=calculate(expression)
                except Exception:return self.fallback(req,'Расчёт','calculation_not_supported',text='Этот расчёт не поддерживается безопасным калькулятором. Уточни выражение.')
                frame=Presentation(id=frame_id(req.turn_id,'info'),type='info_card',title='Результат вычисления',text=value,metadata=VisualMetadata(reason='deterministic_calculator'))
                return VisualResult(frame,'Получается '+value+'.','Получается '+value+'.')
            return self.fallback(req,'Карточка результата','result_not_specified',text='Уточни, какой результат нужно показать в карточке.')
        return self.fallback(req,'Схема' if intent.kind=='diagram' else 'Карточка ответа','diagram_source_required')

    async def generated(self,req,plan):
        from .device_contract import ScreenPreferences
        from .image_generation import OpenAIImageGenerationAdapter,CodexImageGenerationAdapter,MODEL
        from .visual_subject import PRIVATE_QUERY
        from .visual_prefetch import PRIVATE
        pref=req.screen_preferences or ScreenPreferences()
        if not pref.generation_allowed or pref.generation_mode=='off' or not pref.generation_consent or pref.generation_daily_limit<1:
            return self.fallback(req,'Иллюстрация','image_generation_consent_required')
        if PRIVATE_QUERY.search(req.text) or PRIVATE.search(req.text) or re.search(r'анатоми|эндокрин|лекарств|сердц|диагноз',req.text,re.I):
            return self.fallback(req,'Иллюстрация','verified_diagram_required')
        adapter=CodexImageGenerationAdapter() if pref.generation_provider=='codex' else OpenAIImageGenerationAdapter()
        if pref.generation_provider=='codex':return self.fallback(req,'Иллюстрация',adapter.status()['reason'])
        subject=plan.subject_label or plan.visual_query
        if not subject:return self.fallback(req,'Иллюстрация','public_subject_required')
        owner=hashlib.sha256(req.device_id.encode()).hexdigest()
        key='local:ai:'+hashlib.sha256(json.dumps([owner,subject,MODEL,'1024x1024','low',pref.style],ensure_ascii=False).encode()).hexdigest()
        if len(self.locks)>=128:self.locks={k:v for k,v in self.locks.items() if v.locked()}
        async with self.locks.setdefault(key,asyncio.Lock()),self.slots:
            record=await asyncio.to_thread(self.cache.source,key)
            hit=bool(record);usage={}
            if not record:
                def reserve():
                    with self.cache.connect() as c:
                        c.execute('CREATE TABLE IF NOT EXISTS generation_attempts(owner TEXT,day INTEGER,provider TEXT,count INTEGER,PRIMARY KEY(owner,day,provider))')
                        c.execute('BEGIN IMMEDIATE')
                        day=int(time.time()//86400)
                        row=c.execute('SELECT count FROM generation_attempts WHERE owner=? AND day=? AND provider=?',(owner,day,pref.generation_provider)).fetchone()
                        if row and row[0]>=pref.generation_daily_limit:return False
                        c.execute('INSERT INTO generation_attempts VALUES(?,?,?,1) ON CONFLICT(owner,day,provider) DO UPDATE SET count=count+1',(owner,day,pref.generation_provider))
                        return True
                if not await asyncio.to_thread(reserve):return self.fallback(req,'Иллюстрация','image_generation_daily_limit')
                prompt=('Create a clearly illustrative picture of '+subject+
                        '. Center the subject in the middle 65 percent for a circular screen. No labels or text. '+
                        'This is a conceptual illustration, not documentary evidence. No anatomical or medical diagrams.')
                data,usage=await adapter.generate(prompt,consent=True)
                candidate=ImageCandidate(key,'ИИ-иллюстрация: '+subject,None,'OpenAI · '+MODEL,'AI-generated',None,'GoBot · ИИ-иллюстрация')
                record=await asyncio.to_thread(self.cache.put,candidate,data)
            frame=Presentation(id=frame_id(req.turn_id,'generated'),type='image_card',title=subject+' · ИИ',
                text='Сгенерированная иллюстрация. Достоверность деталей не подтверждена.',images=[self.cache.public(record)],
                metadata=VisualMetadata(synthetic=True,visual_strategy='generate',backend='openai_image_api',cache_hit=hit,
                    generation_provider='openai',generation_model=MODEL,billing_kind='api',generation_usage=usage),
                cache_key=record['asset_id'],expires_at=record['expires_at'])
            return VisualResult(frame,frame.text,'')

    async def attachment(self,req,plan,*,timeout=8,cache_only=False):
        """Optional accompaniment never replaces the model answer or adds TTS captions."""
        try:
            permitted=req.screen_preferences and req.screen_preferences.generation_consent and req.screen_preferences.generation_allowed and req.screen_preferences.generation_daily_limit>0
            async with asyncio.timeout(120 if permitted and not cache_only else timeout):
                if plan.reason=='ai_illustration':
                    generated=await self.generated(req,plan)
                    if generated.frame.images or not re.search(r'планет',req.text,re.I):return generated
                    local_plan=plan.model_copy(update={'reason':'educational_local_illustration','template':'fantasy_planet'})
                    local=await self.attachment(req,local_plan,timeout=8)
                    local.frame.metadata.reason=generated.frame.metadata.reason
                    return local
                if plan.visual_strategy=='generate':
                    from .illustrations import draw_illustration
                    record,title=await asyncio.to_thread(draw_illustration,self.cache,plan.template)
                    frame=Presentation(id=frame_id(req.turn_id,'attachment'),type='rich_answer',title=title,
                        text='Условная иллюстрация к ответу, не фотография и не чертёж в масштабе.',images=[self.cache.public(record)],
                        metadata=VisualMetadata(visual_priority=plan.visual_priority,visual_strategy='generate',synthetic=True,backend='local_procedural',template=plan.template),
                        expires_at=record['expires_at'],cache_key=record['asset_id'])
                    return VisualResult(frame,frame.text,'Подготовил поясняющую иллюстрацию.')
                if req.mode=='mock':return self.fallback(req,'Визуальное сопровождение','diagnostic_no_external_images',text='В диагностическом Mock-режиме внешний поиск не запускается.')
                speculative=plan.reason=='speculative_entity_photo'
                try:
                    async with asyncio.timeout(timeout):
                        result=await self.images(req,VisualIntent('image',query=plan.visual_query,
                            strict_subject=plan.subject_source=='answer' or speculative,speculative=speculative),cache_only=cache_only)
                except TimeoutError:result=self.fallback(req,'Иллюстрация','image_lookup_timeout')
                pref=req.screen_preferences
                if (not result.frame.images and not cache_only and pref and pref.generation_mode in {'missing','helpful'}):
                    generated=await self.generated(req,plan)
                    if generated.frame.images:return generated
                result.frame.metadata.visual_priority=plan.visual_priority;result.frame.metadata.visual_strategy='retrieve'
                if result.frame.images:result.frame.metadata.backend='wikimedia' if result.frame.images[0].source.label.startswith('Wikimedia') else 'openverse'
                if plan.subject_source=='answer':
                    result.frame.metadata.facts.update({'subject':plan.subject_label,'query_basis':'answer_entity','identification':'illustrative_example_not_confirmed_identification'})
                    if result.frame.images:
                        result.frame.title=result.frame.metadata.facts.get('entity_title') or canonical_subject(plan.subject_label)
                        if result.frame.metadata.facts.get('entity_match')=='topic_overview':result.frame.title+=' · обзор'
                        if not result.frame.metadata.facts.get('entity_source'):result.frame.text='Пример объекта, упомянутого в ответе. Подбор по метаданным источника; это не идентификация конкретного экземпляра.'
                if plan.reason=='speculative_entity_photo' and result.frame.images:
                    result.frame.title=plan.subject_label
                    result.frame.text='Иллюстрация к теме ответа. Снимок сам по себе не подтверждает вид или место наблюдения.'
                    if result.frame.metadata.facts.get('entity_match')=='topic_overview':result.frame.title+=' · обзор'
                if plan.visual_query=='Лисичка (род грибов)' and result.frame.images:
                    result.frame.title=plan.subject_label+' · пример рода'
                    result.frame.text='Иллюстрация рода. Место съёмки и местный вид этим снимком не подтверждены.'
                    result.frame.metadata.approximate_match=True
                return result
        except asyncio.CancelledError:raise
        except Exception:
            result=self.fallback(req,'Визуальное сопровождение','optional_visual_unavailable',text='Визуальное сопровождение сейчас недоступно. Текстовый и голосовой ответ продолжаются.')
            result.frame.metadata.visual_priority=plan.visual_priority
            return result

    def timer(self,req,widget):
        payload=widget['payload']
        return Presentation(id=frame_id(req.turn_id,'timer'),type='timer_widget',title='Таймер',text='Отсчёт по серверному дедлайну',metadata=VisualMetadata(deadline=payload['deadline'],duration_ms=payload['duration_ms'],timer_id=payload['timer_id']),actions=[VisualAction(type='timer_cancel',label='Остановить таймер',timer_id=payload['timer_id'])],expires_at=payload['deadline']+86400)

    def diagram(self,req):
        # A real architecture diagram, not a generated photograph or a guessed plan.
        data=io.BytesIO();image=Image.new('RGB',(1000,560),(12,20,26));draw=ImageDraw.Draw(image)
        font_path=Path('C:/Windows/Fonts/segoeui.ttf')
        font=ImageFont.truetype(str(font_path),25) if font_path.exists() else ImageFont.load_default(size=24)
        draw.text((48,36),'GoBot Home · общий серверный контур',fill=(238,245,244),font=font)
        boxes=[(50,130,'Браузер / ESP32'),(550,130,'GoBot Brain + память'),(550,320,'Antigravity / Codex'),(50,320,'OpenAI TTS → звук')]
        for x,y,label in boxes:draw.rounded_rectangle((x,y,x+400,y+110),radius=18,fill=(21,35,44),outline=(163,229,205),width=2);draw.text((x+20,y+35),label,fill=(238,245,244),font=font)
        for start,end in [((450,185),(550,185)),((750,240),(750,320)),((550,375),(450,375))]:
            draw.line((start,end),fill=(163,229,205),width=4)
        draw.text((50,482),'Транспорт разный. Brain, память и маршрутизация общие.',fill=(156,175,183),font=font)
        image.save(data,'JPEG',quality=90)
        candidate=ImageCandidate('local:gobot-pipeline-v1','Схема текущего серверного контура',None,'GoBot Home','Локальная схема',None,'GoBot · локальная схема')
        record=self.cache.source(candidate.url) or self.cache.put(candidate,data.getvalue())
        frame=Presentation(id=frame_id(req.turn_id,'diagram'),type='rich_answer',title='Как устроен GoBot Home',text='Клиенты используют общий Brain, память и маршрутизатор. ESP32 transport ещё предстоит проверить на устройстве.',images=[self.cache.public(record)],metadata=VisualMetadata(synthetic=True,template='gobot_pipeline',backend='local_renderer'),cache_key=record['asset_id'])
        return VisualResult(frame,frame.text,'Подготовил схему общего серверного контура Гобота.')

    def replay(self,data):
        frame=Presentation.model_validate(data)
        if frame.images and any(not self.cache.get(image.asset_id) for image in frame.images):
            frame.metadata.state='expired';frame.metadata.reason='image_cache_expired';frame.images=[];frame.actions=[];frame.text='Изображение уже удалено из кэша. Отправь новый запрос, чтобы загрузить его снова.'
        return frame
