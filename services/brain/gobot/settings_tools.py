"""Owner-approved conversational preferences, not general agent self-modification."""
import asyncio,re,time,uuid
from copy import deepcopy
from dataclasses import dataclass
from .device_store import DeviceStore
from .weather import WeatherClient,WeatherError
from .presentation import Presentation,VisualMetadata,VisualSource,frame_id
from .local_tools import ToolResult
from .device_contract import WeatherPreferences
from .weather_queries import weather_query,weather_followup,weather_request_context,weather_words
from .weather import condition

HELP='Могу настроить город для погоды, громкость и голос OpenAI, режим модели, вступления, продолжение разговора, иллюстрации и лицо. Например: «Настрой погоду для моего города», «Громкость 40 процентов», «Выключи вступления».'

def device_home_context(devices,device_id,client_id):
    """Shared configured home only; no GPS, coordinates or private history."""
    try:
        scope=devices.scoped_owner(device_id,client_id)
        weather=devices.profile(scope).weather
        return {'weather_location_configured':weather.enabled,
                'weather_location':weather.location_name if weather.enabled else None,
                'location_basis':'configured_device_home_not_live_gps'}
    except ValueError:return {'weather_location_configured':False,'location_basis':'device_scope_unavailable'}

def settings_intent(value,context=None):
    """Returns a typed operation; no fuzzy state-changing matches."""
    pending=(context or {}).get('pending_action')
    def op(name,**slots):return {'operation':name,**slots}
    query_pending=(context or {}).get('weather_query_pending')
    normalized=weather_words(value)
    if (context or {}).get('weather_followup') and normalized in {'не надо показывать погоду','не нужно показывать погоду','не показывай погоду','отмени прогноз'}:
        return op('weather_query_cancel')
    if query_pending and query_pending.get('expires',0)>time.time():
        pending_id=query_pending.get('id')
        if normalized in {'нет','нет спасибо','не надо','отмена','отмени','отмени поиск','не надо показывать погоду','не нужно показывать погоду','не показывай погоду'}:
            return op('weather_query_cancel',pending_id=pending_id)
        full_query=weather_query(normalized)
        is_city=bool(re.fullmatch(r'[\wА-Яа-яёЁ ,.-]{2,100}',normalized)) and not re.match(r'^(?:нет|да|что|как|почему|поставь|включи|выключи|расскажи|отмени|стоп|настрой|подключи|измени|завтра|послезавтра|сегодня|сейчас|на|через)\b',normalized)
        if not full_query and query_pending.get('kind')=='weather_query_location' and is_city:
            city=re.sub(r'^(?:я живу в|это|город|в|во)\s+','',normalized)
            return op('weather_query_find',query=city,pending_id=pending_id)
        if not full_query and query_pending.get('kind')=='weather_query_choose':
            choice={'первый':0,'первое':0,'1':0,'второй':1,'второе':1,'2':1,'третий':2,'третье':2,'3':2}.get(normalized)
            if choice is not None:return op('weather_query_choose',index=choice,pending_id=pending_id)
            if is_city:return op('weather_query_choose',choice_text=normalized,pending_id=pending_id)
    followup=weather_followup(value,context)
    if followup:return followup
    if pending and pending.get('expires',0)>time.time() and pending.get('kind','').startswith('weather_'):
        payload=pending.get('payload',{})
        if value in {'нет','нет спасибо','не надо','отмена','отмени','отмени настройку','отмени подключение','не подключай'}:return op('weather_cancel',pending_id=pending['id'])
        if pending['kind']=='weather_connect' and value in {'да','давай','подключи','да подключи','подключай','хорошо','согласен'}:
            return op('weather_begin',pending_id=pending['id'])
        if pending['kind']=='weather_location' and re.fullmatch(r'[\wА-Яа-яёЁ ,.-]{2,100}',value) and not re.match(r'^(?:нет|да|что|как|почему|поставь|включи|выключи|расскажи|отмени|стоп)\b',value):
            return op('weather_find',query=re.sub(r'^(?:я живу в|это|город)\s+','',value))
        if pending['kind']=='weather_confirm' and value in {'да','давай','подтверждаю','проверь и подключи','попробуй еще','повтори','используй этот город','установи это основной точкой','установи этот город основной точкой'}:
            return op('weather_confirm',pending_id=pending['id'],places=payload.get('places',[]),index=0)
        if pending['kind']=='weather_choose':
            choice={'первый':0,'первое':0,'1':0,'второй':1,'второе':1,'2':1,'третий':2,'третье':2,'3':2}.get(value)
            if choice is not None:return op('weather_confirm',pending_id=pending['id'],places=payload.get('places',[]),index=choice)
    if value in {'какие настройки ты можешь менять','что ты можешь настроить','покажи настройки','какие у меня настройки','помоги настроить робота','настрой себя'}:return op('help')
    if re.fullmatch(r'(?:покажи|проверь|какие|где)(?: мои)? настройки погоды|какой город (?:выбран|настроен) для погоды',value):return op('weather_status')
    if re.fullmatch(r'(?:смени|измени|переключи) источник погоды на weather\.com',value):return op('weather_provider_unavailable')
    match=re.fullmatch(r'(?:настрой|подключи|измени)(?: мне)? (?:(?:службу|инструмент|сервис) )?погод[уы](?: для| в| на)?(?: (?P<city>.+))?',value)
    if match:
        city=match['city']
        if city and not re.search(r'ближайш|наш\w* город|мо\w* город|мо\w* мест|здесь|рядом|автомат',city):return op('weather_find',query=city)
        return op('weather_location')
    if value in {'выключи погоду','удали место для погоды','забудь местоположение для погоды'}:return op('patch',patch={'weather':{'enabled':False,'location_name':'','latitude':None,'longitude':None}})
    weather_value=re.sub(r'[?.!]\s*(?:объясни для семьи|ответь кратко|укажи ограничения)$','',value).strip()
    weather=weather_query(weather_value)
    if weather:return weather
    match=re.fullmatch(r'(?:установи |поставь |сделай )?громкость(?: на)? (\d{1,3})(?:\s*%| процентов| процента| процент)?',value)
    if match:return op('patch',patch={'voice':{'volume':int(match[1])/100}})
    match=re.fullmatch(r'(?:выбери|поставь|измени|смени)(?: мне)? голос(?: openai)?(?: на)? (marin|марин|cedar|седар|сидар|alloy|ash|ballad|coral|echo|sage|shimmer|verse)',value)
    if match:return op('patch',patch={'voice':{'voice':{'марин':'marin','седар':'cedar','сидар':'cedar'}.get(match[1],match[1])}})
    match=re.fullmatch(r'(включи|выключи|отключи) (?:голосовые )?(вступления|озвучку|(?:автоматические )?иллюстрации|продолжение разговора)',value)
    if match:
        field={'вступления':('feedback','filler_enabled'),'озвучку':('voice','speak'),'автоматические иллюстрации':('screen','automatic_illustrations'),'иллюстрации':('screen','automatic_illustrations'),'продолжение разговора':('conversation','followup_enabled')}[match[2]]
        return op('patch',patch={field[0]:{field[1]:match[1]=='включи'}})
    match=re.fullmatch(r'(?:слушай продолжение|жди продолжение|продолжай слушать после ответа) (\d{1,2}) секунд',value)
    if match:return op('patch',patch={'conversation':{'followup_seconds':int(match[1]),'followup_enabled':True}})
    match=re.fullmatch(r'(?:смени|измени|поставь|выбери) (?:лицо|скин)(?: на)? (classic|классик|soft|софт|minimal|минимал)',value)
    if match:return op('patch',patch={'skin':{'skin_id':{'классик':'classic','софт':'soft','минимал':'minimal'}.get(match[1],match[1])}})
    match=re.fullmatch(r'(?:включи|выбери|поставь) (быстрый|автоматический|подробный) режим',value)
    if match:return op('patch',patch={'voice':{'mode':{'быстрый':'fast','автоматический':'auto','подробный':'reasoning'}[match[1]]}})
    match=re.fullmatch(r'(?:включи|выбери|поставь) (минимальный|сбалансированный|насыщенный) (?:визуальный )?режим',value)
    if match:return op('patch',patch={'screen':{'style':{'минимальный':'minimal','сбалансированный':'balanced','насыщенный':'rich'}[match[1]]}})
    if re.match(r'^(?:разреши|дай себе|дай полный|отключи защиту|включи платн|открой себе)\b',value):return op('restricted')
    if re.match(r'^(?:настрой|подключи|измени настройки|сделай потише|сделай погромче)\b',value):return op('help')
    return None

@dataclass
class SettingsResult(ToolResult):
    profile:dict|None=None
    frame:Presentation|None=None
    silent:bool=False
    setup:dict|None=None

class SettingsTools:
    def __init__(self,memory,root):
        self.memory=memory;self.devices=DeviceStore(root);self.weather=WeatherClient();self.weather_locks={}
        # Temporary place resolution is server RAM, including when long-term memory is enabled.
        self._weather_queries={}

    @staticmethod
    def _weather_scope(req):
        return (req.device_id,req.conversation_id,req.client_id,getattr(req,'profile_epoch',None))

    def _weather_state(self,req,create=False):
        now=time.time();key=self._weather_scope(req)
        for old in [key for key,value in self._weather_queries.items() if value['expires']<=now]:self._weather_queries.pop(old,None)
        state=self._weather_queries.get(key)
        if state is None and create:
            if len(self._weather_queries)>=128:self._weather_queries.pop(next(iter(self._weather_queries)))
            state={'expires':now+600,'places':{},'pending':None};self._weather_queries[key]=state
        return state

    def clear_weather_query(self,req):
        self._weather_queries.pop(self._weather_scope(req),None)

    def weather_query_context(self,req):
        state=self._weather_state(req);pending=state and state.get('pending')
        if not pending or pending['expires']<=time.time():return {}
        return {'weather_query_pending':deepcopy({k:pending[k] for k in ('id','kind','expires','payload','pending_namespace')})}

    def _set_weather_query_pending(self,req,kind,request,places=None):
        state=self._weather_state(req,True);state['expires']=time.time()+600
        safe=weather_request_context(request)
        pending={'id':str(uuid.uuid4()),'kind':kind,'expires':time.time()+120,'pending_namespace':'weather_query',
            'payload':{'request':safe,'places':[{'index':i,'location_name':place['location_name']} for i,place in enumerate(places or [])],'client_id':req.client_id},
            '_places':list(places or [])}
        state['pending']=pending
        return pending

    def _remember_weather_place(self,req,place,query):
        state=self._weather_state(req,True);state['expires']=time.time()+600
        for ref,saved in state['places'].items():
            if saved['place']==place:
                saved['query']=query or saved['query'];return ref
        if len(state['places'])>=8:state['places'].pop(next(iter(state['places'])))
        ref=str(uuid.uuid4());state['places'][ref]={'place':dict(place),'query':query}
        return ref

    @staticmethod
    def weather_failure(error,method):
        code=str(error)
        messages={
            'weather_source_timeout':'Open-Meteo не ответил вовремя.',
            'weather_provider_rate_limit':'Open-Meteo временно ограничил запросы.',
            'weather_rate_limit':'Достигнут лимит частоты запросов к погодному источнику.',
            'weather_source_unavailable':'Не удалось связаться с Open-Meteo.',
            'weather_source_rejected':'Open-Meteo отклонил погодный запрос.',
            'weather_invalid_data':'Ответ Open-Meteo не прошёл проверку данных.',
            'weather_response_limit':'Ответ Open-Meteo превысил допустимый размер.',
            'weather_data_not_fresh':'Open-Meteo вернул устаревшие текущие данные.',
            'weather_forecast_not_fresh':'Даты прогноза Open-Meteo не соответствуют запрошенному периоду.',
            'weather_forecast_incomplete':'Open-Meteo не вернул весь запрошенный прогноз.',
            'weather_forecast_horizon':'Запрошенный период выходит за доступный прогноз.',
        }
        if code not in messages:code='weather_invalid_data'
        text=messages[code]+(' Прогноз пока не получен.' if method=='weather_forecast_api' else 'Текущая погода пока не получена.')
        return SettingsResult(text,evidence={'method':method,'verified':False,'abstained':True,'reason':code})

    def setup_result(self,req,step,status,text,*,next_action='',subtitle='',reason=None):
        setup={'tool':'weather','provider':'open_meteo','step':step,'total_steps':4,'status':status,'next_action':next_action}
        if reason:setup['reason']=reason
        frame=Presentation(id=frame_id(req.turn_id,'weather-setup-'+status),type='status_card',title='Подключение погоды',subtitle=subtitle,text=text,
            metadata=VisualMetadata(backend='device_setup',state='ready' if status in {'cancelled','ready'} else 'loading',facts={'step':str(step),'steps':'4','setup_status':status}))
        return SettingsResult(text,frame=frame,setup=setup)

    def pending(self,req,kind,payload=None):return self.memory.set_pending(req,kind,{**(payload or {}),'client_id':req.client_id})

    def cancel(self,req):
        pending=self.memory.context(req).get('pending_action')
        if pending and pending['kind'].startswith('weather_') and pending.get('payload',{}).get('client_id')==req.client_id:
            self.memory.settle_pending(req,'declined',pending['id']);return True
        return False

    async def execute(self,req,slots,*,is_current=lambda:True,progress=None):
        if not is_current():return SettingsResult('Операция отменена.',setup={'tool':'weather','status':'cancelled'})
        try:scope=self.devices.scoped_owner(req.device_id,req.client_id)
        except ValueError:return SettingsResult('Для настройки нужен профиль этого устройства. Открой панель GoBot или режим устройства и повтори команду.')
        operation=slots['operation'];profile=self.devices.profile(scope)
        if operation=='help':return SettingsResult(HELP)
        if operation=='restricted':return SettingsResult('Расходы, доступ к файлам и семейные права этой голосовой командой не изменены. Для них нужно подтверждение владельца в панели. Обычные настройки звука, экрана и погоды доступны через диалог.')
        if operation=='weather_provider_unavailable':return SettingsResult('Weather.com пока не подключён: нужен ключ официального API The Weather Company. Сейчас работает Open-Meteo с прогнозом до 16 дней. Могу показать его данные.',evidence={'abstained':True,'verified':False,'reason':'provider_not_configured'})
        if operation=='weather_unsupported':
            if slots.get('reason')=='ambiguous_period':
                return SettingsResult('На какой день показать погоду: сегодня или завтра?',evidence={'abstained':True,'verified':False,'reason':'weather_ambiguous_period'})
            comparison=slots.get('reason') in {'comparison','multiple_places'}
            text='Сравнение погоды нескольких городов пока не подключено. Можно запросить каждый город отдельно.' if comparison else 'Сейчас доступен дневной прогноз до 16 дней вперёд; почасовой прогноз и историческая погода в GoBot пока не подключены. Могу показать завтра, неделю или 16 дней.'
            return SettingsResult(text,evidence={'abstained':True,'verified':False,'reason':'comparison_not_implemented' if comparison else 'weather_'+slots.get('reason','unsupported')})
        if operation=='weather_other_place':
            self._set_weather_query_pending(req,'weather_query_location',{'operation':'weather_current'})
            return SettingsResult('Для какого города показать погоду?',evidence={'abstained':True,'reason':'weather_location_required'})
        if operation=='patch':
            safe={'voice':{'voice','volume','speak','mode'},'screen':{'automatic_illustrations','style'},'skin':{'skin_id'},'feedback':{'filler_enabled'},'conversation':{'followup_enabled','followup_seconds'},'weather':{'enabled','location_name','latitude','longitude'}}
            patch=slots.get('patch')
            if not isinstance(patch,dict) or not patch or any(k not in safe or not isinstance(v,dict) or not set(v)<=safe[k] for k,v in patch.items()) or ('weather' in patch and patch['weather']!={'enabled':False,'location_name':'','latitude':None,'longitude':None}):return SettingsResult('Эта настройка не разрешена голосовому инструменту. Изменение не выполнено.')
            try:
                updated=self.devices.update(scope,slots['patch'])
                # Read back committed values, never claim a model changed a file.
                saved=self.devices.profile(scope)
                assert updated==saved
            except (ValueError,TypeError):return SettingsResult('Значение настройки не подходит. Громкость: от 0 до 100 процентов; продолжение разговора: от 5 до 30 секунд. Изменение не сохранено.')
            names={'voice':'Голос и звук','feedback':'Вступления','screen':'Экран','conversation':'Продолжение разговора','skin':'Лицо','weather':'Погода'}
            text='Сохранено на сервере: '+', '.join(names[k] for k in slots['patch'])+'.'
            return SettingsResult(text,profile=saved.model_dump(),silent=saved.voice.speak is False or saved.voice.volume==0)
        if operation in {'weather_current','weather_forecast','weather_query_find','weather_query_choose','weather_query_cancel'}:
            return await self._weather_read(req,profile,slots,is_current=is_current)
        if operation=='weather_status' and not profile.weather.enabled:
            self.pending(req,'weather_connect')
            return self.setup_result(req,1,'awaiting_permission','Погода ещё не подключена к этому устройству. Могу настроить Open-Meteo: уточним город, проверю данные и сохраню настройки. Подключить?',next_action='confirm_setup',subtitle='Подключить источник?')
        if operation=='weather_cancel':
            self.cancel(req)
            return self.setup_result(req,1,'cancelled','Подключение погоды отменено. Настройки не изменены.',subtitle='Отменено')
        if operation=='weather_begin':
            pending=self.memory.context(req).get('pending_action')
            if not pending or pending['kind']!='weather_connect' or pending['id']!=slots.get('pending_id') or pending.get('payload',{}).get('client_id')!=req.client_id:
                return SettingsResult('Предложение подключения больше не действует. Скажите «подключи погоду».')
            self.pending(req,'weather_location')
            return self.setup_result(req,2,'awaiting_location','Какой город и регион использовать для погоды? Точный домашний адрес не нужен.',next_action='provide_location',subtitle='Назовите город')
        if operation=='weather_location':
            self.pending(req,'weather_location')
            return self.setup_result(req,2,'awaiting_location','Для погоды назовите город и регион. Затем проверю источник. Точный домашний адрес не нужен.',next_action='provide_location',subtitle='Назовите город')
        if operation=='weather_find':
            try:places=await self.weather.locations(slots['query'])
            except WeatherError:
                if not is_current():return SettingsResult('Операция отменена.')
                self.pending(req,'weather_location')
                return self.setup_result(req,2,'source_unavailable','Не удалось проверить город в Open-Meteo. Настройки не изменены. Можно уточнить название или повторить позже.',next_action='provide_location',subtitle='Источник недоступен')
            if not is_current():return SettingsResult('Операция отменена.')
            if not places:
                self.pending(req,'weather_location')
                return self.setup_result(req,2,'awaiting_location','Место не найдено. Назовите ближайший населённый пункт и регион либо название латиницей. Самостоятельно другое место не подставляю.',next_action='provide_location',subtitle='Уточните место')
            self.pending(req,'weather_confirm' if len(places)==1 else 'weather_choose',{'places':places})
            text='Нашёл '+places[0]['location_name']+'. Использовать это место? После подтверждения проверю получение погоды и сохраню настройку.' if len(places)==1 else 'Нашёл несколько мест: '+'; '.join(str(i+1)+': '+p['location_name'] for i,p in enumerate(places))+'. Назовите номер; затем проверю получение погоды.'
            return self.setup_result(req,3,'awaiting_confirmation',text,next_action='confirm_location',subtitle='Подтвердите место')
        if operation=='weather_confirm':
            if len(self.weather_locks)>128:self.weather_locks={k:v for k,v in self.weather_locks.items() if v.locked()}
            async with self.weather_locks.setdefault(scope,asyncio.Lock()):
                pending=self.memory.context(req).get('pending_action')
                if not pending or pending['kind'] not in {'weather_confirm','weather_choose'} or pending['id']!=slots.get('pending_id') or pending.get('payload',{}).get('client_id')!=req.client_id:return SettingsResult('Это подтверждение больше не действует. Назовите город заново.')
                places=pending.get('payload',{}).get('places',[]);index=slots.get('index',-1)
                if type(index) is not int or not 0<=index<len(places):return SettingsResult('Такого варианта нет. Назовите номер из предложенного списка.')
                candidate=WeatherPreferences(**places[index],enabled=True)
                if progress:progress(self.setup_result(req,4,'verifying','Проверяю получение свежих погодных данных.',subtitle='Проверяю источник'))
                try:weather=await self.weather.current(candidate)
                except WeatherError:return self.setup_result(req,4,'verification_failed','Источник не прошёл проверку. Настройки ещё не сохранены. Повторить проверку?',next_action='confirm_location',subtitle='Проверка не пройдена')
                current=self.memory.context(req).get('pending_action')
                if not is_current() or not current or current['id']!=pending['id']:return SettingsResult('Операция отменена. Настройки не изменены.')
                saved=self.devices.update(scope,{'weather':candidate.model_dump()})
                assert self.devices.profile(scope).weather==candidate
                self.memory.settle_pending(req,'completed',pending['id'])
                result=self.weather_result(req,saved,weather)
                result.text='Погода подключена и проверена. Сохранено основное место: '+saved.weather.location_name+'. '+result.text
                result.profile=saved.model_dump();result.evidence['canonical_answer']=result.text
                result.setup={'tool':'weather','provider':'open_meteo','step':4,'total_steps':4,'status':'ready','next_action':'ask_weather'}
                return result
        if operation=='weather_status':return SettingsResult('Для погоды выбран '+profile.weather.location_name+'. Источник — Open-Meteo; домашние датчики не подключены.')
        return SettingsResult('Эта настройка через голос пока не поддерживается. '+HELP)

    async def _weather_read(self,req,profile,slots,*,is_current):
        """Resolve an ephemeral query place; only explicit setup above can save a home."""
        operation=slots['operation'];state=self._weather_state(req)
        if operation=='weather_query_cancel':
            pending=state and state.get('pending')
            if slots.get('pending_id') and (not pending or pending['id']!=slots['pending_id']):
                return SettingsResult('Этот запрос уже не ожидает ответа.',evidence={'abstained':True,'reason':'weather_query_expired'})
            self.clear_weather_query(req)
            return SettingsResult('Поиск погоды отменён.',evidence={'abstained':True,'reason':'weather_query_cancelled'})
        selected=None;place_ref=None
        if operation in {'weather_query_find','weather_query_choose'}:
            pending=state and state.get('pending')
            if not pending or pending['expires']<=time.time() or pending['id']!=slots.get('pending_id'):
                return SettingsResult('Уточнение города больше не действует. Повторите запрос погоды.',evidence={'abstained':True,'reason':'weather_query_expired'})
            request=dict(pending['payload']['request'])
            if operation=='weather_query_choose':
                places=pending['_places'];index=slots.get('index')
                if index is None and isinstance(slots.get('choice_text'),str):
                    choice=weather_words(slots['choice_text'])
                    choice=re.sub(r'^(?:тот что в|который в|в|во)\s+','',choice)
                    choice_words=[re.sub(r'(?:ом|ем|е|а|у|ы|и)$','',word) if len(word)>5 else word for word in choice.split()]
                    def matching_label(place):
                        label=weather_words(place['location_name'])
                        return choice in label or all(len(word)>=4 and any(part.startswith(word) for part in re.findall(r'[а-яa-z-]+',label)) for word in choice_words)
                    matches=[i for i,place in enumerate(places) if matching_label(place)]
                    if len(matches)==1:index=matches[0]
                if type(index) is not int or not 0<=index<len(places):
                    return SettingsResult('Какой вариант выбрать? Назовите номер из списка или регион.',evidence={'abstained':True,'reason':'weather_location_ambiguous'})
                selected=places[index]
            else:
                request['place_query']=slots.get('query','')
                for key in ('place_ref','place_label','timezone'):request.pop(key,None)
        else:request=weather_request_context(slots)
        if request.get('operation') not in {'weather_current','weather_forecast'}:
            return SettingsResult('Повторите запрос погоды.',evidence={'abstained':True,'reason':'weather_query_invalid'})
        query=request.get('place_query');ref=request.get('place_ref')
        if selected is None and ref:
            saved=state and state['places'].get(ref)
            if not saved:
                self._set_weather_query_pending(req,'weather_query_location',{k:v for k,v in request.items() if k not in {'place_ref','place_label','timezone','place_query'}})
                return SettingsResult('Временное место больше не сохранено. Для какого города показать погоду?',evidence={'abstained':True,'reason':'weather_place_expired'})
            selected=saved['place'];query=saved['query'];place_ref=ref
        if selected is None and query:
            if state:
                for saved_ref,saved in state['places'].items():
                    if weather_words(saved['query'])==weather_words(query):
                        selected=saved['place'];place_ref=saved_ref;break
            if selected is None:
                try:places=await self.weather.locations(query)
                except WeatherError as error:
                    if not is_current():return SettingsResult('Запрос отменён.')
                    result=self.weather_failure(error,'weather_geocode_api')
                    result.text=result.text.replace('Текущая погода пока не получена.','Город пока не определён.')
                    return result
                if not is_current():return SettingsResult('Запрос отменён.')
                if not places:
                    self._set_weather_query_pending(req,'weather_query_location',request)
                    return SettingsResult('Место не найдено. Уточните город и регион или название латиницей.',evidence={'abstained':True,'reason':'weather_location_not_found'})
                if len(places)>1:
                    self._set_weather_query_pending(req,'weather_query_choose',request,places)
                    text='Нашёл несколько мест: '+'; '.join(str(i+1)+': '+place['location_name'] for i,place in enumerate(places))+'. Какой вариант выбрать?'
                    return SettingsResult(text,evidence={'abstained':True,'reason':'weather_location_ambiguous'})
                selected=places[0]
        if selected is not None:
            place=WeatherPreferences(enabled=True,**{key:selected[key] for key in ('location_name','latitude','longitude')})
            place_ref=place_ref or self._remember_weather_place(req,selected,query or selected['location_name'])
            request.update({'place_ref':place_ref,'place_query':query or selected['location_name'],'place_label':place.location_name})
        elif profile.weather.enabled:
            place=profile.weather;request['place_label']=place.location_name
        else:
            self._set_weather_query_pending(req,'weather_query_location',request)
            return SettingsResult('Для какого города показать погоду?',evidence={'abstained':True,'reason':'weather_location_required'})
        state=self._weather_state(req)
        if state:state['pending']=None;state['expires']=time.time()+600
        query_profile=profile.model_copy(update={'weather':place})
        try:
            if request['operation']=='weather_forecast':
                args={key:request[key] for key in ('offset','days','weekday','start_date','end_date','calendar_period') if key in request}
                forecast=await self.weather.forecast(place,**args)
                if not is_current():return SettingsResult('Запрос отменён.')
                result=self.forecast_result(req,query_profile,forecast,request)
                request.update({'timezone':forecast['timezone'],'start_date':forecast['days'][0]['date'],'end_date':forecast['days'][-1]['date']})
                for key in ('offset','weekday','calendar_period'):request.pop(key,None)
                request['days']=len(forecast['days'])
            else:
                weather=await self.weather.current(place)
                if not is_current():return SettingsResult('Запрос отменён.')
                result=self.weather_result(req,query_profile,weather,request)
                if weather.get('timezone'):
                    from datetime import datetime
                    from zoneinfo import ZoneInfo
                    request['timezone']=weather['timezone']
                    local_date=datetime.fromtimestamp(weather['observed_at'],ZoneInfo(weather['timezone'])).date().isoformat()
                    request.update({'start_date':local_date,'end_date':local_date})
        except WeatherError as error:
            if not is_current():return SettingsResult('Запрос отменён.')
            return self.weather_failure(error,'weather_forecast_api' if request['operation']=='weather_forecast' else 'weather_api')
        request.setdefault('metric','summary')
        result.evidence['weather_request']=weather_request_context(request)
        return result

    @staticmethod
    def _weather_number(value):
        return format(round(value,1),'g').replace('.',',')

    def weather_result(self,req,profile,weather,request=None):
        request=request or {};metric=request.get('metric','summary');place=profile.weather.location_name
        icon,label=condition(weather['weather_code']);number=self._weather_number
        temperature=lambda value:number(value*9/5+32 if request.get('temperature_unit')=='fahrenheit' else value)
        temperature_unit='°F' if request.get('temperature_unit')=='fahrenheit' else '°C'
        wind=lambda value:number(value/3.6 if request.get('wind_unit')=='m_s' else value)
        wind_unit='м/с' if request.get('wind_unit')=='m_s' else 'км/ч'
        available=True
        if metric=='temperature':
            body='температура '+temperature(weather['temperature'])+' '+temperature_unit+', ощущается как '+temperature(weather['apparent'])+' '+temperature_unit+'.'
        elif metric=='wind':
            body='ветер '+wind(weather['wind_kmh'])+' '+wind_unit+'.'
            body+=(' Порывы до '+wind(weather['gust_kmh'])+' '+wind_unit+'.') if 'gust_kmh' in weather else ' Данных о порывах источник не вернул.'
        elif metric=='humidity':
            available='humidity_percent' in weather
            body='влажность '+number(weather['humidity_percent'])+' процентов.' if available else 'данных о влажности источник не вернул.'
        elif metric=='precipitation':
            available='precipitation_mm' in weather
            body='осадки за текущий интервал '+number(weather['precipitation_mm'])+' мм, '+label+'.' if available else 'данных о количестве текущих осадков источник не вернул.'
        elif metric in {'uv_index','umbrella'}:
            available=False;body='в текущем ответе источника нет '+('УФ-индекса.' if metric=='uv_index' else 'вероятности осадков на день. Для совета о зонте нужен дневной прогноз.')
        else:
            body=label+', '+temperature(weather['temperature'])+' '+temperature_unit+', ощущается как '+temperature(weather['apparent'])+' '+temperature_unit+'. Ветер '+wind(weather['wind_kmh'])+' '+wind_unit+'.'
        text='По данным Open-Meteo для '+place+': '+body
        metadata={'kind':'current','metric':metric,'place':place,'icon':icon,'condition':label}
        if weather.get('timezone'):metadata['timezone']=weather['timezone']
        frame=Presentation(id=frame_id(req.turn_id,'weather'),type='weather_card',title='Погода',subtitle=place,text=text,
            source=VisualSource(label='Open-Meteo · CC BY 4.0',url='https://open-meteo.com/'),
            metadata=VisualMetadata(backend='open_meteo',icon={'sun':'☀','cloud':'☁','partly_cloudy':'⛅','rain':'🌧','storm':'⛈','snow':'❄','fog':'🌫','unknown':'?'}[icon],weather=metadata,facts={k:str(v) for k,v in weather.items()}),expires_at=weather['observed_at']+5400)
        evidence={'method':'weather_api','verified':True,'canonical_answer':text}
        if not available:evidence.update({'abstained':True,'reason':'weather_metric_unavailable'})
        return SettingsResult(text,evidence=evidence,frame=frame)

    def forecast_result(self,req,profile,forecast,request=None):
        from datetime import date
        request=request or {};metric=request.get('metric','summary');place=profile.weather.location_name
        rows=forecast['days'];first=rows[0];last=rows[-1];number=self._weather_number
        display_date=lambda row:date.fromisoformat(row['date']).strftime('%d.%m.%Y')
        temperature=lambda value:number(value*9/5+32 if request.get('temperature_unit')=='fahrenheit' else value)
        temperature_unit='°F' if request.get('temperature_unit')=='fahrenheit' else '°C'
        wind=lambda value:number(value/3.6 if request.get('wind_unit')=='m_s' else value)
        wind_unit='м/с' if request.get('wind_unit')=='m_s' else 'км/ч'
        def line(row):
            prefix='На '+display_date(row)+': '
            if metric=='wind':
                body='ветер до '+wind(row['wind_kmh'])+' '+wind_unit+'.'
                return prefix+body+(' Порывы до '+wind(row['gust_kmh'])+' '+wind_unit+'.' if 'gust_kmh' in row else ' Данных о порывах источник не вернул.')
            if metric=='temperature':return prefix+'температура от '+temperature(row['low'])+' до '+temperature(row['high'])+' '+temperature_unit+'.'
            if metric in {'precipitation','umbrella'}:
                body='вероятность осадков '+number(row['rain_percent'])+' процентов.'
                if 'precipitation_mm' in row:body+=' Количество осадков '+number(row['precipitation_mm'])+' мм.'
                if metric=='umbrella':body+=' Зонт стоит взять.' if row['rain_percent']>=40 else ' Вероятность осадков невысокая; если будете долго на улице, можно взять зонт.'
                return prefix+body
            if metric=='uv_index':return prefix+('УФ-индекс '+number(row['uv_index'])+'.' if 'uv_index' in row else 'данных об УФ-индексе источник не вернул.')
            if metric=='humidity':return prefix+'данных о влажности в дневном прогнозе этого источника нет.'
            return prefix+row['condition']+', от '+temperature(row['low'])+' до '+temperature(row['high'])+' '+temperature_unit+', вероятность осадков '+number(row['rain_percent'])+' процентов, ветер до '+wind(row['wind_kmh'])+' '+wind_unit+'.'
        text='Прогноз Open-Meteo для '+place+'. '
        if len(rows)==1:text+=line(first)
        else:
            text+='Период '+display_date(first)+' — '+display_date(last)+'. '+line(first)
            if metric in {'summary','temperature'}:text+=' В периоде температура от '+temperature(min(r['low'] for r in rows))+' до '+temperature(max(r['high'] for r in rows))+' '+temperature_unit+'.'
            elif metric=='wind':
                text+=' В периоде ветер до '+wind(max(r['wind_kmh'] for r in rows))+' '+wind_unit+'.'
                if all('gust_kmh' in r for r in rows):text+=' Порывы до '+wind(max(r['gust_kmh'] for r in rows))+' '+wind_unit+'.'
            elif metric in {'precipitation','umbrella'}:text+=' Наибольшая дневная вероятность осадков в периоде '+number(max(r['rain_percent'] for r in rows))+' процентов.'
            text+=' Полный прогноз на экране. Дальний прогноз может меняться.'
        metadata={'kind':'forecast','metric':metric,'place':place,'icon':first['icon'],'condition':first['condition'],'timezone':forecast['timezone'],'days':rows}
        facts={'temperature':str(first['high']),'low':str(first['low']),'date':first['date'],'days':str(len(rows)),'rain_percent':str(first['rain_percent']),'wind_kmh':str(first['wind_kmh'])}
        for key in ('gust_kmh','precipitation_mm','uv_index'):
            if key in first:facts[key]=str(first[key])
        frame=Presentation(id=frame_id(req.turn_id,'weather-forecast'),type='weather_card',title='Прогноз погоды',subtitle=place,text=text,
            source=VisualSource(label='Open-Meteo · CC BY 4.0',url='https://open-meteo.com/'),
            metadata=VisualMetadata(backend='open_meteo',weather=metadata,facts=facts),expires_at=forecast['fetched_at']+900)
        evidence={'method':'weather_forecast_api','verified':True,'canonical_answer':text}
        if metric=='humidity' or metric=='uv_index' and not all('uv_index' in row for row in rows):evidence.update({'abstained':True,'reason':'weather_metric_unavailable'})
        return SettingsResult(text,evidence=evidence,frame=frame)
