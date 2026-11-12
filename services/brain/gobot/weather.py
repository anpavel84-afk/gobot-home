"""Bounded on-demand Open-Meteo data; no keys, model calls or background polling."""
import asyncio,time,math
import httpx
from datetime import datetime,date,timedelta
from zoneinfo import ZoneInfo

def condition(code):
    if code==0:return 'sun','ясно'
    if code in {1,2}:return 'partly_cloudy','переменная облачность'
    if code==3:return 'cloud','пасмурно'
    if code in {45,48}:return 'fog','туман'
    if code in {51,53,55,56,57}:return 'rain','морось'
    if code in {61,63,65,66,67,80,81,82}:return 'rain','дождь'
    if code in {71,73,75,77,85,86}:return 'snow','снег'
    if code in {95,96,99}:return 'storm','гроза'
    return 'unknown','состояние не определено'

class WeatherError(Exception):pass

class WeatherClient:
    def __init__(self,transport=None,clock=time.time):
        self.transport=transport;self.clock=clock;self.cache={};self.calls=[];self.lock=asyncio.Lock()
    def discard(self,kind,params):
        self.cache.pop((kind,tuple(sorted(params.items()))),None)
    async def data(self,kind,params,ttl):
        key=(kind,tuple(sorted(params.items())));now=self.clock()
        if key in self.cache and now-self.cache[key][0]<ttl:return self.cache[key][1]
        async with self.lock:
            self.calls=[t for t in self.calls if now-t<86400]
            if len(self.calls)>=200 or sum(now-t<60 for t in self.calls)>=8:raise WeatherError('weather_rate_limit')
            self.calls.append(now)
        url='https://geocoding-api.open-meteo.com/v1/search' if kind=='geo' else 'https://api.open-meteo.com/v1/forecast'
        try:
            async with httpx.AsyncClient(transport=self.transport,trust_env=False,follow_redirects=False,timeout=4) as client:
                async with client.stream('GET',url,params=params) as response:
                    response.raise_for_status();raw=bytearray()
                    async for part in response.aiter_bytes():
                        raw.extend(part)
                        if len(raw)>131072:raise WeatherError('weather_response_limit')
            import json
            data=json.loads(raw)
            if not isinstance(data,dict) or data.get('error'):raise WeatherError('weather_invalid_data')
        except httpx.TimeoutException as error:raise WeatherError('weather_source_timeout') from error
        except httpx.HTTPStatusError as error:
            raise WeatherError('weather_provider_rate_limit' if error.response.status_code==429 else 'weather_source_rejected' if error.response.status_code<500 else 'weather_source_unavailable') from error
        except (httpx.HTTPError,ValueError) as error:raise WeatherError('weather_source_unavailable') from error
        if len(self.cache)>=32:self.cache.pop(next(iter(self.cache)))
        self.cache[key]=(now,data);return data
    async def locations(self,name):
        if not 2<=len(name)<=100:raise WeatherError('location_query_invalid')
        data=await self.data('geo',{'name':name,'count':3,'language':'ru','format':'json'},86400)
        out=[]
        for row in data.get('results',[])[:3]:
            try:
                lat=float(row['latitude']);lon=float(row['longitude'])
                if not math.isfinite(lat) or not math.isfinite(lon) or not -90<=lat<=90 or not -180<=lon<=180:continue
                label=', '.join(dict.fromkeys(str(row[k]) for k in ['name','admin1','country'] if row.get(k)))[:160]
                if label:out.append({'location_name':label,'latitude':round(lat,3),'longitude':round(lon,3)})
            except (ValueError,KeyError,TypeError):continue
        return out
    async def current(self,place):
        params={'latitude':place.latitude,'longitude':place.longitude,
            'current':'temperature_2m,apparent_temperature,weather_code,wind_speed_10m',
            'temperature_unit':'celsius','wind_speed_unit':'kmh','timeformat':'unixtime','timezone':'GMT'}
        data=await self.data('weather',params,300)
        try:
            row=data['current'];stamp=float(row['time']);temperature=float(row['temperature_2m']);apparent=float(row['apparent_temperature']);wind=float(row['wind_speed_10m'])
            if not all(math.isfinite(v) for v in [stamp,temperature,apparent,wind]) or not -100<=temperature<=70 or not -120<=apparent<=100 or not 0<=wind<=500:raise ValueError()
            if not -900<=self.clock()-stamp<=5400:raise WeatherError('weather_data_not_fresh')
            return {'temperature':temperature,'apparent':apparent,'wind_kmh':wind,'weather_code':int(row['weather_code']),'observed_at':stamp,'fetched_at':self.clock()}
        except WeatherError:
            self.discard('weather',params);raise
        except (KeyError,TypeError,ValueError):
            self.discard('weather',params);raise WeatherError('weather_invalid_data')

    async def forecast(self,place,*,offset=0,days=7,weekday=None):
        if type(offset) is not int or type(days) is not int or not 0<=offset<=15 or not 1<=days<=16 or offset+days>16:raise WeatherError('weather_forecast_horizon')
        params={'latitude':place.latitude,'longitude':place.longitude,
            'daily':'weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,wind_speed_10m_max',
            'temperature_unit':'celsius','wind_speed_unit':'kmh','forecast_days':16,'timezone':'auto'}
        data=await self.data('weather',params,900)
        try:
            zone=ZoneInfo(data['timezone']);today=datetime.fromtimestamp(self.clock(),zone).date()
            if weekday is not None:
                if type(weekday) is not int or not 0<=weekday<=6:raise ValueError()
                offset=(weekday-today.weekday())%7
            daily=data['daily'];names=['time','weather_code','temperature_2m_min','temperature_2m_max','precipitation_probability_max','wind_speed_10m_max']
            size=len(daily['time'])
            if not 1<=size<=16 or any(len(daily[k])!=size for k in names):raise ValueError()
            rows=[]
            for i in range(size):
                stamp=date.fromisoformat(daily['time'][i]);code=int(daily['weather_code'][i])
                low=float(daily['temperature_2m_min'][i]);high=float(daily['temperature_2m_max'][i]);wind=float(daily['wind_speed_10m_max'][i]);rain=float(daily['precipitation_probability_max'][i])
                if stamp!=today+timedelta(days=i):raise WeatherError('weather_forecast_not_fresh')
                if not all(math.isfinite(v) for v in [low,high,wind,rain]) or not -100<=low<=high<=70 or not 0<=wind<=500 or not 0<=rain<=100:raise ValueError()
                icon,label=condition(code)
                rows.append({'date':stamp.isoformat(),'low':low,'high':high,'rain_percent':rain,'wind_kmh':wind,'weather_code':code,'icon':icon,'condition':label})
            selected=rows[offset:offset+days]
            if len(selected)!=days:raise WeatherError('weather_forecast_incomplete')
            return {'timezone':data['timezone'],'days':selected,'fetched_at':self.clock(),'horizon_days':16}
        except WeatherError:
            self.discard('weather',params);raise
        except (KeyError,TypeError,ValueError,IndexError):
            self.discard('weather',params);raise WeatherError('weather_invalid_data')
