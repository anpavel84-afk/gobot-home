"""Owner-approved conversational preferences, not general agent self-modification."""
import re,time
from dataclasses import dataclass
from .device_store import DeviceStore
from .weather import WeatherClient,WeatherError
from .presentation import Presentation,VisualMetadata,VisualSource,frame_id
from .local_tools import ToolResult

HELP='Могу настроить город для погоды, громкость и голос OpenAI, режим модели, вступления, продолжение разговора, иллюстрации и лицо. Например: «Настрой погоду для моего города», «Громкость 40 процентов», «Выключи вступления».'

def settings_intent(value,context=None):
    """Returns a typed operation; no fuzzy state-changing matches."""
    pending=(context or {}).get('pending_action')
    def op(name,**slots):return {'operation':name,**slots}
    if pending and pending.get('expires',0)>time.time() and pending.get('kind','').startswith('weather_'):
        payload=pending.get('payload',{})
        if pending['kind']=='weather_location' and re.fullmatch(r'[\wА-Яа-яёЁ ,.-]{2,100}',value) and not re.match(r'^(?:нет|да|что|как|почему|поставь|включи|выключи|расскажи|отмени|стоп)\b',value):
            return op('weather_find',query=value)
        if pending['kind']=='weather_confirm' and value in {'да','подтверждаю','используй этот город','установи это основной точкой','установи этот город основной точкой'}:
            return op('weather_confirm',pending_id=pending['id'],places=payload.get('places',[]),index=0)
        if pending['kind']=='weather_choose':
            choice={'первый':0,'первое':0,'1':0,'второй':1,'второе':1,'2':1,'третий':2,'третье':2,'3':2}.get(value)
            if choice is not None:return op('weather_confirm',pending_id=pending['id'],places=payload.get('places',[]),index=choice)
    if value in {'какие настройки ты можешь менять','что ты можешь настроить','покажи настройки','какие у меня настройки','помоги настроить робота','настрой себя'}:return op('help')
    if re.fullmatch(r'(?:покажи|проверь|какие|где)(?: мои)? настройки погоды|какой город (?:выбран|настроен) для погоды',value):return op('weather_status')
    match=re.fullmatch(r'(?:настрой|подключи|измени)(?: мне)? (?:службу )?погод[уы](?: для| в| на)?(?: (?P<city>.+))?',value)
    if match:
        city=match['city']
        if city and not re.search(r'ближайш|наш\w* город|мо\w* город|мо\w* мест|здесь|рядом|автомат',city):return op('weather_find',query=city)
        return op('weather_location')
    if value in {'выключи погоду','удали место для погоды','забудь местоположение для погоды'}:return op('patch',patch={'weather':{'enabled':False,'location_name':'','latitude':None,'longitude':None}})
    weather_value=re.sub(r'[?.!]\s*(?:объясни для семьи|ответь кратко|укажи ограничения)$','',value).strip()
    if re.fullmatch(r'(?:сейчас )?(?:(?:какая|как\w*|покажи|что).{0,35}погод[ауы]?[^.]*|погода)',weather_value):
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

class SettingsTools:
    def __init__(self,memory,root):self.memory=memory;self.devices=DeviceStore(root);self.weather=WeatherClient()
    async def execute(self,req,slots):
        try:scope=self.devices.scoped_owner(req.device_id,req.client_id)
        except ValueError:return SettingsResult('Для настройки нужен профиль этого устройства. Открой панель GoBot или режим устройства и повтори команду.')
        operation=slots['operation'];profile=self.devices.profile(scope)
        if operation=='help':return SettingsResult(HELP)
        if operation=='restricted':return SettingsResult('Расходы, доступ к файлам и семейные права этой голосовой командой не изменены. Для них нужно подтверждение владельца в панели. Обычные настройки звука, экрана и погоды доступны через диалог.')
        if operation=='weather_unsupported':return SettingsResult('Сейчас подключена только текущая погода. Прогноз на другое время этим инструментом пока не поддерживается.')
        if operation=='weather_other_place':return SettingsResult('Для другого города скажи «настрой погоду для…» и назови город. Не буду подставлять погоду другого места.')
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
            self.memory.set_pending(req,'weather_location')
            return SettingsResult('Погода ещё не настроена. Назови город и регион. Точный адрес не нужен.')
        if operation=='weather_location':
            self.memory.set_pending(req,'weather_location')
            return SettingsResult('Для погоды назови город и регион. Я не определяю домашний адрес по голосу или IP.')
        if operation=='weather_find':
            try:places=await self.weather.locations(slots['query'])
            except WeatherError:return SettingsResult('Не удалось проверить город в погодном источнике. Настройка не изменена. Попробуй позже или уточни название.')
            if not places:return SettingsResult('Город не найден. Назови населённый пункт и регион точнее; настройка не изменена.')
            self.memory.set_pending(req,'weather_confirm' if len(places)==1 else 'weather_choose',{'places':places,'client_id':req.client_id})
            return SettingsResult(('Нашёл '+places[0]['location_name']+'. Использовать для погоды? Скажи «да».' if len(places)==1 else 'Нашёл несколько мест: '+'; '.join(str(i+1)+': '+p['location_name'] for i,p in enumerate(places))+'. Назови номер подходящего места.')+' Название передано геокодеру Open-Meteo; это не подключение домашних датчиков.')
        if operation=='weather_confirm':
            pending=self.memory.context(req).get('pending_action')
            if not pending or pending['id']!=slots.get('pending_id') or pending.get('payload',{}).get('client_id')!=req.client_id:return SettingsResult('Это подтверждение больше не действует. Назови город заново.')
            places=pending.get('payload',{}).get('places',[]);index=slots.get('index',-1)
            if type(index) is not int or not 0<=index<len(places):return SettingsResult('Такого варианта нет. Назови номер из предложенного списка.')
            saved=self.devices.update(scope,{'weather':{**places[index],'enabled':True}})
            self.memory.settle_pending(req,'completed',pending['id'])
            return SettingsResult('Сохранено: погода для '+saved.weather.location_name+'. Источник — Open-Meteo, расчётные погодные данные. Теперь можно спросить: «Какая сейчас погода?»',profile=saved.model_dump())
        if operation=='weather_status':return SettingsResult('Для погоды выбран '+profile.weather.location_name+'. Источник — Open-Meteo; домашние датчики не подключены.')
        if operation=='weather_current':
            try:weather=await self.weather.current(profile.weather)
            except WeatherError:return SettingsResult('Погодный источник сейчас недоступен или данные устарели. Не буду подставлять выдуманную температуру.',evidence={'abstained':True})
            text='По данным Open-Meteo для '+profile.weather.location_name+': '+str(weather['temperature']).replace('.',',')+' °C, ощущается как '+str(weather['apparent']).replace('.',',')+' °C. Ветер '+str(weather['wind_kmh']).replace('.',',')+' км/ч.'
            frame=Presentation(id=frame_id(req.turn_id,'weather'),type='weather_card',title='Погода',subtitle=profile.weather.location_name,text=text,
                source=VisualSource(label='Open-Meteo · CC BY 4.0',url='https://open-meteo.com/'),
                metadata=VisualMetadata(backend='open_meteo',facts={k:str(v) for k,v in weather.items()}),expires_at=weather['observed_at']+5400)
            return SettingsResult(text,evidence={'method':'weather_api','verified':True,'canonical_answer':text},frame=frame)
        return SettingsResult('Эта настройка через голос пока не поддерживается. '+HELP)
