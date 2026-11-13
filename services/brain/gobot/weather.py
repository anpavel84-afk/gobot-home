"""Bounded on-demand Open-Meteo data; no keys, model calls or background polling."""
import asyncio,time,math
import httpx
from datetime import datetime,date,timedelta
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError

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
        params={'name':name,'count':3,'language':'ru','format':'json'}
        data=await self.data('geo',params,86400)
        if not isinstance(data.get('results',[]),list):
            self.discard('geo',params);raise WeatherError('weather_invalid_data')
        out=[]
        for row in data.get('results',[])[:3]:
            try:
                if not isinstance(row,dict):continue
                lat=float(row['latitude']);lon=float(row['longitude'])
                if not math.isfinite(lat) or not math.isfinite(lon) or not -90<=lat<=90 or not -180<=lon<=180:continue
                label=', '.join(dict.fromkeys(str(row[k]) for k in ['name','admin1','country'] if row.get(k)))[:160]
                if label:out.append({'location_name':label,'latitude':round(lat,3),'longitude':round(lon,3)})
            except (ValueError,KeyError,TypeError):continue
        return out
    async def current(self,place):
        params={'latitude':place.latitude,'longitude':place.longitude,
            'current':'temperature_2m,apparent_temperature,weather_code,wind_speed_10m,wind_gusts_10m,relative_humidity_2m,precipitation',
            'temperature_unit':'celsius','wind_speed_unit':'kmh','timeformat':'unixtime','timezone':'auto'}
        data=await self.data('weather',params,300)
        try:
            row=data['current'];stamp=float(row['time']);temperature=float(row['temperature_2m']);apparent=float(row['apparent_temperature']);wind=float(row['wind_speed_10m'])
            if not all(math.isfinite(v) for v in [stamp,temperature,apparent,wind]) or not -100<=temperature<=70 or not -120<=apparent<=100 or not 0<=wind<=500:raise ValueError()
            if not -900<=self.clock()-stamp<=5400:raise WeatherError('weather_data_not_fresh')
            result={'temperature':temperature,'apparent':apparent,'wind_kmh':wind,'weather_code':int(row['weather_code']),'observed_at':stamp,'fetched_at':self.clock()}
            for source,target,maximum in [('wind_gusts_10m','gust_kmh',600),('relative_humidity_2m','humidity_percent',100),('precipitation','precipitation_mm',1000)]:
                if row.get(source) is not None:
                    number=float(row[source])
                    if not math.isfinite(number) or not 0<=number<=maximum:raise ValueError()
                    result[target]=number
            if data.get('timezone'):
                ZoneInfo(data['timezone']);result['timezone']=data['timezone']
            return result
        except WeatherError:
            self.discard('weather',params);raise
        except (KeyError,TypeError,ValueError,ZoneInfoNotFoundError):
            self.discard('weather',params);raise WeatherError('weather_invalid_data')

    async def forecast(self,place,*,offset=0,days=7,weekday=None,start_date=None,end_date=None,calendar_period=None):
        if type(offset) is not int or type(days) is not int or not 0<=offset<=15 or not 1<=days<=16 or offset+days>16:raise WeatherError('weather_forecast_horizon')
        params={'latitude':place.latitude,'longitude':place.longitude,
            'daily':'weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum,wind_speed_10m_max,wind_gusts_10m_max,uv_index_max',
            'temperature_unit':'celsius','wind_speed_unit':'kmh','forecast_days':16,'timezone':'auto'}
        data=await self.data('weather',params,900)
        try:
            zone=ZoneInfo(data['timezone']);today=datetime.fromtimestamp(self.clock(),zone).date()
            if start_date is not None:
                selected_start=date.fromisoformat(start_date)
                offset=(selected_start-today).days
                if end_date is not None:days=(date.fromisoformat(end_date)-selected_start).days+1
            elif calendar_period=='next_week':
                offset=7-today.weekday();days=7
            elif calendar_period=='next_weekend':
                offset=(5-today.weekday())%7
                if today.weekday()==5:offset+=7
                days=2
            elif calendar_period is not None:raise ValueError()
            elif weekday is not None:
                if type(weekday) is not int or not 0<=weekday<=6:raise ValueError()
                offset=(weekday-today.weekday())%7
                if weekday==5 and days==2 and today.weekday()==6:offset=0;days=1
            if not 0<=offset<=15 or not 1<=days<=16 or offset+days>16:raise WeatherError('weather_forecast_horizon')
            daily=data['daily'];names=['time','weather_code','temperature_2m_min','temperature_2m_max','precipitation_probability_max','wind_speed_10m_max']
            size=len(daily['time'])
            if not 1<=size<=16 or any(len(daily[k])!=size for k in names):raise ValueError()
            rows=[]
            for i in range(size):
                stamp=date.fromisoformat(daily['time'][i])
                if stamp!=today+timedelta(days=i):raise WeatherError('weather_forecast_not_fresh')
                # Sources may omit the last forecast day while tomorrow is complete.
                # Validate calendar continuity globally, numerical facts only for the
                # requested window. Missing requested values still fail, never zero-fill.
                if not offset<=i<offset+days:continue
                code=int(daily['weather_code'][i])
                low=float(daily['temperature_2m_min'][i]);high=float(daily['temperature_2m_max'][i]);wind=float(daily['wind_speed_10m_max'][i]);rain=float(daily['precipitation_probability_max'][i])
                if not all(math.isfinite(v) for v in [low,high,wind,rain]) or not -100<=low<=high<=70 or not 0<=wind<=500 or not 0<=rain<=100:raise ValueError()
                icon,label=condition(code)
                result={'date':stamp.isoformat(),'low':low,'high':high,'rain_percent':rain,'wind_kmh':wind,'weather_code':code,'icon':icon,'condition':label}
                for source,target,maximum in [('wind_gusts_10m_max','gust_kmh',600),('precipitation_sum','precipitation_mm',1000),('uv_index_max','uv_index',30)]:
                    values=daily.get(source)
                    if values is not None:
                        if not isinstance(values,list) or len(values)!=size:raise ValueError()
                        if values[i] is not None:
                            number=float(values[i])
                            if not math.isfinite(number) or not 0<=number<=maximum:raise ValueError()
                            result[target]=number
                rows.append(result)
            selected=rows
            if len(selected)!=days:raise WeatherError('weather_forecast_incomplete')
            return {'timezone':data['timezone'],'days':selected,'fetched_at':self.clock(),'horizon_days':16}
        except WeatherError:
            self.discard('weather',params);raise
        except (KeyError,TypeError,ValueError,IndexError,ZoneInfoNotFoundError):
            self.discard('weather',params);raise WeatherError('weather_invalid_data')
