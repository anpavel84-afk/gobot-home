"""Bounded on-demand Open-Meteo data; no keys, model calls or background polling."""
import asyncio,time,math
import httpx

class WeatherError(Exception):pass

class WeatherClient:
    def __init__(self,transport=None,clock=time.time):
        self.transport=transport;self.clock=clock;self.cache={};self.calls=[];self.lock=asyncio.Lock()
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
        data=await self.data('weather',{'latitude':place.latitude,'longitude':place.longitude,
            'current':'temperature_2m,apparent_temperature,weather_code,wind_speed_10m',
            'temperature_unit':'celsius','wind_speed_unit':'kmh','timeformat':'unixtime','timezone':'GMT'},300)
        try:
            row=data['current'];stamp=float(row['time']);temperature=float(row['temperature_2m']);apparent=float(row['apparent_temperature']);wind=float(row['wind_speed_10m'])
            if not all(math.isfinite(v) for v in [stamp,temperature,apparent,wind]) or not -100<=temperature<=70 or not -120<=apparent<=100 or not 0<=wind<=500:raise ValueError()
            if not -900<=self.clock()-stamp<=5400:raise WeatherError('weather_data_not_fresh')
            return {'temperature':temperature,'apparent':apparent,'wind_kmh':wind,'weather_code':int(row['weather_code']),'observed_at':stamp,'fetched_at':self.clock()}
        except (KeyError,TypeError,ValueError):raise WeatherError('weather_invalid_data')
