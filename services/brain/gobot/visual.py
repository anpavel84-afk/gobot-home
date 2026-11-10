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
from .presentation import Presentation,VisualMetadata,VisualAction,VisualSource,PresentationDecision,frame_id
from .visual_images import ImageCache,ImageCandidate,CommonsImages,OpenverseImages,SafeImageHTTP,ImageUnavailable,source_config,ROOT,NORMALIZATION_VERSION,FETCH_POLICY_VERSION

REASONS={
 'image_sources_disabled':'Внешний источник изображений отключён или не настроен. Локальные карточки и схемы доступны.',
 'image_source_contact_required':'Источник фотографий требует публичный контакт оператора. Его можно указать в настройках визуальных ответов.',
 'image_source_access_denied':'Источник отклонил загрузку изображения. Другой снимок не подставлялся.',
 'image_source_rate_limited':'Источник временно ограничил запросы. Повторные загрузки отложены.',
 'image_not_found':'Подходящее изображение с подтверждённым источником и лицензией не найдено.',
 'private_image_not_available':'Личное изображение не загружено. Семейные фотографии и планы не ищутся в интернете.',
 'image_query_required':'Уточни, какой объект нужно показать.',
 'diagram_source_required':'Уточни элементы схемы или предоставь исходный план. Я не буду придумывать устройство вашей теплицы.',
 'image_request_budget_exceeded':'Достигнут лимит обращений к источнику изображений. Повторные загрузки временно отложены; готовые изображения в кэше доступны.',
 'reviewed_image_changed':'Изображение источника изменилось после проверки. Старый визуальный референс не подставляется без повторной проверки.',
 'image_source_unavailable':'Источник изображений сейчас не смог отдать результат. Попробуй повторить запрос позже.',
 'image_lookup_timeout':'Источник изображений не ответил вовремя. Попробуй повторить запрос позже.',
 'image_network_unavailable':'Не удалось связаться с источником изображений. Проверь соединение и повтори запрос позже.',
}

@dataclass
class VisualResult:
    frame:Presentation
    display_text:str
    speech_text:str

class VisualService:
    def __init__(self,cache=None,*,provider_factory=None,config_loader=source_config):
        self.cache=cache or ImageCache();self.intent=PresentationDecision();self.config_loader=config_loader
        self.provider_factory=provider_factory or (lambda cfg:(OpenverseImages if cfg.get('provider')=='openverse' else CommonsImages)(SafeImageHTTP(cfg['user_agent'],budget=self.cache.reserve_request,on_limit=self.cache.delay_source)))
        self.catalog=json.loads((Path(__file__).parents[1]/'visual-catalog.json').read_text(encoding='utf-8'))['items']
        self.slots=asyncio.Semaphore(2);self.locks={}

    def available(self):
        return {'image_source':self.config_loader().get('provider','disabled'),'configured':bool(self.config_loader()),'cache_bytes_limit':self.cache.max_bytes,'cache_entries_limit':self.cache.max_entries,'asset_ttl_seconds':self.cache.ttl,'query_ttl_seconds':86400,'failure_ttl_seconds':600,'source_requests_per_minute':8,'source_requests_per_day':80,'public_images_only':True,'weather_source':'not_configured','music_source':'not_configured'}

    def fallback(self,req,title,code,kind='info_card',text=None):
        message=text or REASONS.get(code,'Изображение сейчас недоступно. Попробуй позже; неподтверждённую картинку я не подставляю.')
        frame=Presentation(id=frame_id(req.turn_id,kind),type=kind,title=title,text=message,metadata=VisualMetadata(state='unavailable',reason=code))
        return VisualResult(frame,message,message)

    async def images(self,req,intent):
        if not intent.query:return self.fallback(req,'Какое изображение показать?','image_query_required')
        if re.search(r'https?://|file:|localhost',intent.query,re.I):return self.fallback(req,'Источник изображения','direct_image_url_not_supported',text='Прямые ссылки не загружаются этим инструментом. Опиши объект: поиск работает только через разрешённый источник изображений.')
        if intent.catalog_id is None and re.search(r'raspberry\s*pi\s*[1-9]|рас[пб]ерри\s*пи\s*[1-9]',intent.query,re.I):return self.fallback(req,'Нужен референс конкретной платы','board_revision_not_reviewed',text='Для указанной модели платы ещё нет проверенного изображения в каталоге. Фотографию другой ревизии вместо неё я не подставляю.')
        if re.search(r'\b(?:мо(?:й|я|ё|е|ю|его|ей|их|им|ими|ему|ем|ём)|наш\w*|мам[ауы]|пап[ауы]|доч[ьи]|сын[ауы]?|жен[аыу]|муж[а]?)\b',intent.query,re.I):return self.fallback(req,'Личное изображение','private_image_not_available')
        config=self.config_loader();catalog=self.catalog.get(intent.catalog_id);key=hashlib.sha256(json.dumps([intent.query.casefold().strip(),intent.gallery,config.get('provider'),config.get('contact',''),catalog,NORMALIZATION_VERSION,FETCH_POLICY_VERSION],ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        # Bound coordination state; active tasks remain protected by the global slots.
        if key not in self.locks:
            if len(self.locks)>=128:self.locks={k:v for k,v in self.locks.items() if v.locked()}
            self.locks.setdefault(key,asyncio.Lock())
        async with self.locks[key]:
            cached=await asyncio.to_thread(self.cache.query,key);hit=cached is not None;sent=False
            if cached:records,reason=cached
            else:
                records=[];reason=None
                if not config:reason='image_sources_disabled'
                else:
                    provider=self.provider_factory(config)
                    try:
                        async with self.slots,asyncio.timeout(18):
                            curated=(catalog.get('openverse_images') if config.get('provider')=='openverse' else catalog.get('images')) if catalog else None
                            candidates=[ImageCandidate(**item) for item in curated] if curated else await provider.search(catalog.get('search_query',intent.query) if catalog else intent.query,3)
                            sent=not bool(curated)
                            for candidate in candidates[:3]:
                                try:
                                    record=await asyncio.to_thread(self.cache.source,candidate.url)
                                    if record and candidate.sha256 and record.get('source_sha256')!=candidate.sha256:record=None
                                    if record is None:
                                        raw,_=await provider.client.get(candidate.url)
                                        record=await asyncio.to_thread(self.cache.put,candidate,raw)
                                    if record['asset_id'] not in {r['asset_id'] for r in records}:records.append(record)
                                    if len(records)>=(3 if intent.gallery else 1):break
                                except ImageUnavailable as e:
                                    reason=e.code
                                    if e.code in {'image_request_budget_exceeded','image_source_rate_limited'}:break
                    except ImageUnavailable as e:reason=e.code
                    except TimeoutError:reason='image_lookup_timeout'
                    except asyncio.CancelledError:raise
                    except Exception:reason='image_lookup_unavailable'
                await asyncio.to_thread(self.cache.save_query,key,records,reason)
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
        speech=catalog['speech'] if catalog else 'Нашёл изображения по твоему запросу. Они показаны на экране.'
        frame=Presentation(id=frame_id(req.turn_id,'images'),type='image_gallery' if len(images)>1 else 'image_card',title=title,text=text,images=images,actions=[VisualAction(type='open_image',label='Открыть крупнее',asset_id=images[0].asset_id)],metadata=VisualMetadata(cache_hit=hit,query_sent_to_source=sent,approximate_match=catalog.get('approximate_match',False) if catalog else True,selection_basis='curated_visual_review' if catalog else 'source_metadata_search_unverified',reason=reason),source=VisualSource(label=images[0].source.label),expires_at=min(r['expires_at'] for r in records),cache_key=key)
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
        frame=Presentation(id=frame_id(req.turn_id,'diagram'),type='rich_answer',title='Как устроен GoBot Home',text='Клиенты используют общий Brain, память и маршрутизатор. ESP32 transport ещё предстоит проверить на устройстве.',images=[self.cache.public(record)],cache_key=record['asset_id'])
        return VisualResult(frame,frame.text,'Показываю схему общего серверного контура Гобота.')

    def replay(self,data):
        frame=Presentation.model_validate(data)
        if frame.images and any(not self.cache.get(image.asset_id) for image in frame.images):
            frame.metadata.state='expired';frame.metadata.reason='image_cache_expired';frame.images=[];frame.actions=[];frame.text='Изображение уже удалено из кэша. Отправь новый запрос, чтобы загрузить его снова.'
        return frame
