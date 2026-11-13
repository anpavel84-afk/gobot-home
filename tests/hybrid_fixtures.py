import asyncio,json
from datetime import datetime,timedelta,timezone
import httpx
from gobot.brain import Service
from gobot.hybrid import Hybrid
from gobot.hybrid_contract import PreviewInput

NOW=datetime(2026,11,13,12,tzinfo=timezone.utc).timestamp()
def weather_response(request):
    if 'geocoding' in request.url.host:
        return httpx.Response(200,json={'results':[{'name':'Москва','admin1':'Москва','country':'Россия','latitude':55.75,'longitude':37.61}]})
    if 'current' in request.url.params:
        return httpx.Response(200,json={'timezone':'Europe/Lisbon','current':{'time':NOW,'temperature_2m':14.7,'apparent_temperature':14.,'wind_speed_10m':8.,'weather_code':3,'precipitation':0,'relative_humidity_2m':60}})
    today=datetime.fromtimestamp(NOW,timezone.utc).date()
    return httpx.Response(200,json={'timezone':'Europe/Lisbon','daily':{'time':[(today+timedelta(days=i)).isoformat() for i in range(16)],
        'weather_code':[3]*16,'temperature_2m_min':[9.]*16,'temperature_2m_max':[14.7]*16,
        'precipitation_probability_max':[60.]*16,'precipitation_sum':[2.]*16,'wind_speed_10m_max':[8.]*16}})

def make(settings,principal='fixture-owner',peer='fixture-peer'):
    brain=Service(settings);devices=brain.configuration.devices
    profile=devices.profile(principal+'@'+peer)
    devices.update(principal+'@'+peer,{'weather':{'enabled':True,'location_name':'Лиссабон · fixture','latitude':38.72,'longitude':-9.14}})
    brain.configuration.weather.transport=httpx.MockTransport(weather_response);brain.configuration.weather.clock=lambda:NOW
    hybrid=Hybrid(brain);scope=(principal,profile.client_id,None);c=hybrid.open(scope)
    return brain,hybrid,scope,c

async def dispatch(hybrid,scope,conversation,text,**kw):
    op=hybrid.issue(conversation.id,scope)
    return await hybrid.dispatch(PreviewInput(conversation_id=conversation.id,operation_id=op,text=text,**kw),scope)

def timer_count(brain):
    with brain.memory.connect() as db:return db.execute('SELECT count(*) FROM timers').fetchone()[0]
