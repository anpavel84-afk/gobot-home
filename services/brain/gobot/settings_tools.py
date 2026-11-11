"""Owner-approved conversational preferences, not general agent self-modification."""
import asyncio,re,time
from dataclasses import dataclass
from .device_store import DeviceStore
from .weather import WeatherClient,WeatherError
from .presentation import Presentation,VisualMetadata,VisualSource,frame_id
from .local_tools import ToolResult
from .device_contract import WeatherPreferences

HELP='Могу настроить город для погоды, громкость и голос OpenAI, режим модели, вступления, продолжение разговора, иллюстрации и лицо. Например: «Настрой погоду для моего города», «Громкость 40 процентов», «Выключи вступления».'

def settings_intent(value,context=None):
    """Returns a typed operation; no fuzzy state-changing matches."""
    pending=(context or {}).get('pending_action')
    def op(name,**slots):return {'operation':name,**slots}
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
    match=re.fullmatch(r'(?:настрой|подключи|измени)(?: мне)? (?:(?:службу|инструмент|сервис) )?погод[уы](?: для| в| на)?(?: (?P<city>.+))?',value)
    if match:
        city=match['city']
        if city and not re.search(r'ближайш|наш\w* город|мо\w* город|мо\w* мест|здесь|рядом|автомат',city):return op('weather_find',query=city)
        return op('weather_location')
    if value in {'выключи погоду','удали место для погоды','забудь местоположение для погоды'}:return op('patch',patch={'weather':{'enabled':False,'location_name':'','latitude':None,'longitude':None}})
    weather_value=re.sub(r'[?.!]\s*(?:объясни для семьи|ответь кратко|укажи ограничения)$','',value).strip()
    if re.fullmatch(r'(?:сейчас )?(?:(?:какая|как\w*|покажи|проверь|узнай|посмотри|что).{0,35}погод[ауы]?[^.]*|погода)',weather_value):
        value=weather_value
        if re.search(r'завтра|вчера|недел|прогноз|вечером|утром|ночью',value):return op('weather_unsupported')
        if re.search(r'\b(?:в|для)\s+(?!моем городе\b|нашем городе\b)\S',value):return op('weather_other_place')
        return op('weather_current')
    match=re.fullmatch(r'(?:установи |поставь |сделай )?громкость(?: на)? (\d{1,3})(?:\s*%| процентов| процента| процент)?',value)
    if match:return op('patch',patch={'voice':{'volume':int(match[1])/100}})
    match=re.fullmatch(r'(?:выбери|поставь|измени|смени)(?: мне)? голос(?: openai)?(?: на)? (marin|марин|cedar|седар|сидар|alloy|ash|ballad|coral|echo|sage|shimmer|verse)',value)
    if match:return op('patch',patch={'voice':{'voice':{'марин':'marin','седар':'cedar','сидар':'cedar'}.get(match[1],match[1])}})
    match=re.fullmatch(r'(включи|выключи|отключи) (?:голосовые )?(вступления|озвучку|автоматические иллюстрации|продолжение разговора)',value)
    if match:
        field={'вступления':('feedback','filler_enabled'),'озвучку':('voice','speak'),'автоматические иллюстрации':('screen','automatic_illustrations'),'продолжение разговора':('conversation','followup_enabled')}[match[2]]
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
    def __init__(self,memory,root):self.memory=memory;self.devices=DeviceStore(root);self.weather=WeatherClient();self.weather_locks={}

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
        if operation=='weather_unsupported':return SettingsResult('Сейчас подключена только текущая погода. Прогноз на другое время этим инструментом пока не поддерживается.')
        if operation=='weather_other_place':
            self.pending(req,'weather_location')
            return self.setup_result(req,2,'awaiting_location','Для этого места назовите город и регион. Проверю источник и попрошу подтвердить, прежде чем менять основное место для погоды.',next_action='provide_location',subtitle='Назовите город')
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
        if operation in {'weather_status','weather_current'} and not profile.weather.enabled:
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
        if operation=='weather_current':
            try:weather=await self.weather.current(profile.weather)
            except WeatherError:return SettingsResult('Погодный источник сейчас недоступен или данные устарели. Не буду подставлять выдуманную температуру.',evidence={'abstained':True})
            return self.weather_result(req,profile,weather)
        return SettingsResult('Эта настройка через голос пока не поддерживается. '+HELP)

    def weather_result(self,req,profile,weather):
        text='По данным Open-Meteo для '+profile.weather.location_name+': '+str(weather['temperature']).replace('.',',')+' °C, ощущается как '+str(weather['apparent']).replace('.',',')+' °C. Ветер '+str(weather['wind_kmh']).replace('.',',')+' км/ч.'
        frame=Presentation(id=frame_id(req.turn_id,'weather'),type='weather_card',title='Погода',subtitle=profile.weather.location_name,text=text,
            source=VisualSource(label='Open-Meteo · CC BY 4.0',url='https://open-meteo.com/'),
            metadata=VisualMetadata(backend='open_meteo',facts={k:str(v) for k,v in weather.items()}),expires_at=weather['observed_at']+5400)
        return SettingsResult(text,evidence={'method':'weather_api','verified':True,'canonical_answer':text},frame=frame)
