"""Bounded image cache and allowlisted Openverse/Wikimedia clients; no URL proxy."""
import asyncio
import hashlib
import io
import ipaddress
import json
import re
import socket
import sqlite3
import threading
import time
import warnings
from dataclasses import dataclass,replace
from contextlib import contextmanager
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit,urlunsplit,parse_qsl,quote

import httpx
from PIL import Image,ImageOps
from .presentation import VisualImage,VisualSource
from .image_query import ImageQueryPlanner,canonical_subject

ROOT=Path(__file__).resolve().parents[3]
CONTACT=ROOT/'run/visual-source.json'
IMAGE_HOSTS={'upload.wikimedia.org','thumb.wikimedia.org'}
API='https://commons.wikimedia.org/w/api.php'
MAX_DOWNLOAD=8*1024*1024
MAX_PIXELS=16_000_000
NORMALIZATION_VERSION=3
FETCH_POLICY_VERSION=9
LICENSES={'CC BY-SA 4.0','CC BY-SA 3.0','CC BY 4.0','CC BY 3.0','CC0','Public domain'}

class ImageUnavailable(Exception):
    def __init__(self,code):self.code=code;super().__init__(code)

class Plain(HTMLParser):
    def __init__(self):super().__init__();self.parts=[]
    def handle_data(self,value):self.parts.append(value)
def plain(value,limit=500):
    parser=Plain();parser.feed(str(value));return re.sub(r'\s+',' ',' '.join(parser.parts)).strip()[:limit]

def valid_contact(contact):
    if not isinstance(contact,str) or len(contact)>180 or not contact.isascii() or any(c in contact for c in '\r\n'):return False
    if re.fullmatch(r'[A-Za-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}',contact):return True
    if contact.startswith('https://'):
        try:
            u=urlsplit(contact)
            return bool(u.hostname and '.' in u.hostname and not u.username and not u.password and u.port in {None,443} and not u.query and not u.fragment and not any(c.isspace() for c in contact))
        except ValueError:return False
    return False

def source_config():
    default={'provider':'openverse','user_agent':'GoBotHomeVisual/0.3 (personal image viewer)','contact':''}
    try:
        config=json.loads(CONTACT.read_text(encoding='utf-8'));contact=config.get('contact','')
        provider=config.get('provider','wikimedia')
        if provider=='disabled':return {}
        if provider=='openverse':return default
        if provider!='wikimedia' or not valid_contact(contact):return {}
        return {'provider':'wikimedia','contact':contact,'user_agent':'GoBotHomeVisual/0.3 ('+contact+') httpx/'+httpx.__version__}
    except FileNotFoundError:return default
    except (ValueError,OSError):return {}

async def public_dns(host):
    loop=asyncio.get_running_loop()
    try:addresses=await asyncio.wait_for(loop.getaddrinfo(host,443,type=socket.SOCK_STREAM),3)
    except (OSError,TimeoutError):raise ImageUnavailable('image_dns_unavailable') from None
    if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):raise ImageUnavailable('image_private_address_denied')

class SafeImageHTTP:
    def __init__(self,user_agent,*,transport=None,resolver=public_dns,budget=None,on_limit=None):
        self.user_agent=user_agent;self.transport=transport;self.resolver=resolver;self.budget=budget;self.on_limit=on_limit
    async def get(self,url,*,api=False,params=None):
        u=urlsplit(url)
        allowed={'commons.wikimedia.org','ru.wikipedia.org','en.wikipedia.org','api.openverse.org'} if api else IMAGE_HOSTS|{'api.openverse.org'}
        if u.scheme!='https' or u.hostname not in allowed or u.username or u.password or u.port not in {None,443} or u.fragment:raise ImageUnavailable('image_origin_denied')
        if u.hostname=='api.openverse.org':
            if api and u.path!='/v1/images/':raise ImageUnavailable('image_api_path_denied')
            if not api and (not re.fullmatch(r'/v1/images/[a-f0-9-]{36}/thumb/',u.path) or u.query):raise ImageUnavailable('image_path_denied')
        else:
            if api and u.path!='/w/api.php':raise ImageUnavailable('image_api_path_denied')
            if not api and (not u.path.startswith('/wikipedia/commons/') or u.query):raise ImageUnavailable('image_path_denied')
        if self.budget and not await asyncio.to_thread(self.budget,u.hostname):raise ImageUnavailable('image_request_budget_exceeded')
        await self.resolver(u.hostname)
        try:
            # The thumbnail action passes DRF content negotiation before returning
            # binary media. An image-only Accept can produce 406 on cache misses.
            # Accept negotiation never replaces the strict response MIME checks below.
            accept='application/json' if api else '*/*' if u.hostname=='api.openverse.org' else 'image/jpeg,image/png,image/webp'
            async with httpx.AsyncClient(trust_env=False,transport=self.transport,follow_redirects=False,timeout=httpx.Timeout(10,connect=3),headers={'User-Agent':self.user_agent,'Accept-Encoding':'identity','Accept':accept}) as client:
                async with client.stream('GET',url,params=params) as response:
                    if response.status_code==403:raise ImageUnavailable('image_source_access_denied')
                    if response.status_code==429:
                        if self.on_limit:
                            try:delay=int(response.headers.get('retry-after','600'))
                            except ValueError:
                                from email.utils import parsedate_to_datetime
                                try:delay=int(parsedate_to_datetime(response.headers['retry-after']).timestamp()-time.time())
                                except Exception:delay=600
                            await asyncio.to_thread(self.on_limit,u.hostname,max(60,min(delay,86400)))
                        raise ImageUnavailable('image_source_rate_limited')
                    if response.status_code!=200:raise ImageUnavailable('image_source_unavailable')
                    if response.headers.get('content-encoding','identity')!='identity':raise ImageUnavailable('image_content_encoding_denied')
                    mime=response.headers.get('content-type','').split(';')[0].lower()
                    if mime not in ({'application/json'} if api else {'image/jpeg','image/png','image/webp'}):raise ImageUnavailable('image_mime_denied')
                    limit=512*1024 if api else MAX_DOWNLOAD
                    try:
                        if int(response.headers.get('content-length','0'))>limit:raise ImageUnavailable('image_download_too_large')
                    except ValueError:raise ImageUnavailable('invalid_image_length')
                    data=bytearray()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data)>limit:raise ImageUnavailable('image_download_too_large')
                    return bytes(data),mime
        except (ImageUnavailable,asyncio.CancelledError):raise
        except httpx.HTTPError:raise ImageUnavailable('image_network_unavailable') from None

@dataclass(frozen=True)
class ImageCandidate:
    url:str
    caption:str
    source_url:str|None
    author:str
    license:str
    license_url:str|None
    source_label:str='Wikimedia Commons'
    sha256:str|None=None
    matched_query:str|None=None
    entity_title:str|None=None
    entity_source:str|None=None
    entity_exact:bool=True

def entity_words(value):
    from .speech_formatter import morphology
    return {morphology().parse(word)[0].normal_form for word in re.findall(r'[а-яёa-z0-9-]+',value.casefold())}

class CommonsImages:
    def __init__(self,client):self.client=client
    async def search(self,query,limit=3):
        # Search text only, no GoBot context, cookies, family facts or keys.
        clean=re.sub(r'[^\w\sА-Яа-яЁё-]',' ',query)[:180].strip()
        if not clean:return []
        data,_=await self.client.get(API,api=True,params={'action':'query','format':'json','generator':'search','gsrnamespace':6,'gsrlimit':min(limit+2,6),'gsrsearch':clean+' filetype:bitmap','prop':'imageinfo','iiprop':'url|extmetadata|size|mime','iiurlwidth':960,'iiextmetadatafilter':'Artist|LicenseShortName|LicenseUrl|ImageDescription'})
        return self.candidates(data,limit)

    async def page_images(self,query,limit=3):
        """Resolve an article, then license-check its named image on Commons.

        A broader article is an explicitly labelled overview, never an exact
        match to a dropped qualifier. Unrelated search hits are rejected.
        """
        language='ru' if re.search('[а-яё]',query,re.I) else 'en'
        endpoint='https://'+language+'.wikipedia.org/w/api.php'
        data,_=await self.client.get(endpoint,api=True,params={'action':'query','format':'json','generator':'search',
            'gsrsearch':canonical_subject(query)[:180],'gsrnamespace':0,'gsrlimit':3,'prop':'pageimages|pageprops',
            'piprop':'name','ppprop':'disambiguation'})
        try:pages=json.loads(data).get('query',{}).get('pages',{})
        except ValueError:raise ImageUnavailable('invalid_entity_metadata') from None
        requested=await asyncio.to_thread(entity_words,query)
        for page in sorted(pages.values(),key=lambda p:p.get('index',999)):
            title=page.get('title','');filename=page.get('pageimage','')
            if page.get('ns')!=0 or 'disambiguation' in page.get('pageprops',{}) or not filename or '|' in filename or len(filename)>240:continue
            named=await asyncio.to_thread(entity_words,title)
            if not named or not named<=requested or (named!=requested and len(named)<2):continue
            metadata,_=await self.client.get(API,api=True,params={'action':'query','format':'json','titles':'File:'+filename,
                'prop':'imageinfo','iiprop':'url|extmetadata|size|mime','iiurlwidth':960,'iiextmetadatafilter':'Artist|LicenseShortName|LicenseUrl|ImageDescription'})
            candidates=self.candidates(metadata,limit)
            if candidates:
                return [replace(item,matched_query=query,entity_title=title,
                    entity_source='https://'+language+'.wikipedia.org/wiki/'+quote(title.replace(' ','_')),
                    entity_exact=named==requested) for item in candidates]
        return []

    @staticmethod
    def candidates(data,limit=3):
        try:pages=json.loads(data).get('query',{}).get('pages',{})
        except ValueError:raise ImageUnavailable('invalid_image_metadata') from None
        candidates=[]
        for page in sorted(pages.values(),key=lambda row:row.get('index',999)):
            infos=page.get('imageinfo',[])
            if not infos:continue
            info=infos[0];meta=info.get('extmetadata',{})
            license=plain(meta.get('LicenseShortName',{}).get('value',''),80)
            license_url=meta.get('LicenseUrl',{}).get('value','').replace('http://creativecommons.org','https://creativecommons.org')
            if license=='Public domain' and not license_url:
                license_url='https://creativecommons.org/publicdomain/mark/1.0/'
            if license not in LICENSES or not license_url.startswith('https://creativecommons.org/'):continue
            url=info.get('thumburl') or info.get('url','')
            if info.get('mime') in {'image/svg+xml','video/ogg','application/ogg','video/webm'}:
                # Commons renders SVG on its own servers. Fetch only that raster
                # thumbnail, subject to the same DNS, MIME, byte and decode checks.
                thumb=urlsplit(info.get('thumburl',''))
                if (thumb.scheme!='https' or thumb.hostname not in IMAGE_HOSTS
                        or not thumb.path.startswith('/wikipedia/commons/thumb/')
                        or not thumb.path.lower().endswith(('.png','.jpg','.webp'))):continue
            elif info.get('mime') not in {'image/jpeg','image/png','image/webp'}:continue
            # imageinfo now appends analytics to thumb.wikimedia.org URLs. Strip
            # only these observed tracking fields; arbitrary queries stay denied.
            parsed=urlsplit(url);tracking=parse_qsl(parsed.query,keep_blank_values=True)
            expected={'utm_source':{'commons.wikimedia.org'},'utm_campaign':{'imageinfo'},
                      'utm_content':{'thumbnail','thumbnail_unscaled'}}
            if parsed.hostname in IMAGE_HOSTS and tracking and all(v in expected.get(k,()) for k,v in tracking):
                url=urlunsplit((parsed.scheme,parsed.netloc,parsed.path,'',parsed.fragment))
            candidates.append(ImageCandidate(url,plain(meta.get('ImageDescription',{}).get('value',page.get('title','')),300),info.get('descriptionurl',''),plain(meta.get('Artist',{}).get('value',''),400),license,license_url))
            if len(candidates)>=limit:break
        return candidates

class OpenverseImages:
    def __init__(self,client,planner=None):self.client=client;self.planner=planner or ImageQueryPlanner()
    async def search(self,query,limit=3):
        plan=await asyncio.to_thread(self.planner.plan,query)
        for term in dict.fromkeys(plan.terms):
            candidates=await self._search(term,limit)
            if candidates:return candidates
        if plan.ambiguous:raise ImageUnavailable('image_query_ambiguous')
        return []
    async def _search(self,query,limit=3):
        clean=re.sub(r'[^\w\sА-Яа-яЁё-]',' ',query)[:180].strip()
        if not clean:return []
        data,_=await self.client.get('https://api.openverse.org/v1/images/',api=True,params={'q':clean,'page_size':min(limit+2,6),'source':'flickr','license_type':'commercial,modification','mature':'false'})
        try:rows=json.loads(data).get('results',[])
        except ValueError:raise ImageUnavailable('invalid_image_metadata') from None
        candidates=[]
        for item in rows:
            ident=item.get('id','');code=item.get('license');version=item.get('license_version','')
            if item.get('mature') or not re.fullmatch(r'[a-f0-9-]{36}',ident) or code not in {'by','by-sa','cc0','pdm'}:continue
            source_url=item.get('foreign_landing_url','')
            try:VisualSource(label='Openverse source',url=source_url)
            except ValueError:continue
            if version not in {'1.0','2.0','2.5','3.0','4.0'}:continue
            license=('CC '+code.upper()+' '+version) if code in {'by','by-sa'} else 'CC0' if code=='cc0' else 'Public domain'
            license_url='https://creativecommons.org/'+(('licenses/'+code+'/'+version+'/') if code in {'by','by-sa'} else 'publicdomain/'+('zero' if code=='cc0' else 'mark')+'/'+version+'/')
            # Only Openverse's fixed thumbnail endpoint is fetched, never the
            # arbitrary origin URL embedded in search metadata.
            candidates.append(ImageCandidate('https://api.openverse.org/v1/images/'+ident+'/thumb/',plain(item.get('title','Изображение'),300),source_url,plain(item.get('creator',''),400),license,license_url,'Openverse · '+plain(item.get('source',''),80)))
            if len(candidates)>=limit:break
        return candidates

def normalize(data):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error',Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if image.format not in {'JPEG','PNG','WEBP'} or image.width*image.height>MAX_PIXELS or getattr(image,'is_animated',False):raise ImageUnavailable('image_decode_policy_denied')
                image.load();image=ImageOps.exif_transpose(image)
                if image.mode in {'RGBA','LA'} or 'transparency' in image.info:
                    rgba=image.convert('RGBA');base=Image.new('RGBA',rgba.size,(255,255,255,255));image=Image.alpha_composite(base,rgba).convert('RGB')
                else:image=image.convert('RGB')
                variants={}
                for name,size in [('browser',960),('preview',480),('device',240)]:
                    scale=min(1,size/max(image.size));dimensions=(max(1,round(image.width*scale)),max(1,round(image.height*scale)))
                    scaled=image.resize(dimensions,Image.Resampling.LANCZOS)
                    if name=='device':
                        canvas=Image.new('RGB',(240,240),(12,20,26));canvas.paste(scaled,((240-scaled.width)//2,(240-scaled.height)//2));scaled=canvas
                    for quality in (85,70,50,30):
                        buffer=io.BytesIO();scaled.save(buffer,format='JPEG',quality=quality,optimize=True,progressive=False)
                        if name!='device' or buffer.tell()<=65536:break
                    if name=='device' and buffer.tell()>65536:raise ImageUnavailable('device_image_too_large')
                    variants[name]={'bytes':buffer.getvalue(),'width':scaled.width,'height':scaled.height}
                return variants
    except ImageUnavailable:raise
    except Exception:raise ImageUnavailable('image_decode_failed') from None

class ImageCache:
    def __init__(self,root=None,*,ttl=7*86400,max_bytes=128*1024*1024,max_entries=128,clock=time.time):
        self.root=Path(root or ROOT/'data/visual-cache').resolve();self.root.mkdir(parents=True,exist_ok=True)
        self.ttl=ttl;self.max_bytes=max_bytes;self.max_entries=max_entries;self.clock=clock;self.lock=threading.RLock()
        self.db=self.root/'index.sqlite'
        with self.connect() as c:c.executescript('''CREATE TABLE IF NOT EXISTS assets(id TEXT PRIMARY KEY,source_key TEXT UNIQUE,metadata TEXT,size INTEGER,expires REAL,accessed REAL);
CREATE TABLE IF NOT EXISTS queries(id TEXT PRIMARY KEY,assets TEXT,reason TEXT,expires REAL);
CREATE TABLE IF NOT EXISTS source_requests(provider TEXT,created REAL);
CREATE TABLE IF NOT EXISTS source_backoff(provider TEXT PRIMARY KEY,until REAL);''')
        self.prune()
    @contextmanager
    def connect(self):
        c=sqlite3.connect(self.db,timeout=5);c.row_factory=sqlite3.Row
        try:
            with c:yield c
        finally:c.close()
    def file(self,asset,variant):
        if not re.fullmatch(r'[a-f0-9]{64}',asset) or variant not in {'browser','preview','device'}:raise KeyError('asset')
        path=self.root/(asset+'-'+variant+'.jpg')
        if path.is_symlink() or not path.resolve().is_relative_to(self.root):raise KeyError('asset')
        return path
    def get(self,asset):
        with self.lock,self.connect() as c:
            row=c.execute('SELECT * FROM assets WHERE id=? AND expires>?',(asset,self.clock())).fetchone()
            if not row or not all(self.file(asset,v).is_file() for v in ('browser','preview','device')):return None
            c.execute('UPDATE assets SET accessed=? WHERE id=?',(self.clock(),asset))
            return json.loads(row['metadata'])
    def source(self,url):
        with self.connect() as c:row=c.execute('SELECT id FROM assets WHERE source_key=?',(hashlib.sha256(url.encode()).hexdigest(),)).fetchone()
        record=self.get(row[0]) if row else None
        return record if record and record.get('normalization_version')==NORMALIZATION_VERSION else None
    def put(self,candidate,data):
        source_sha=hashlib.sha256(data).hexdigest()
        if candidate.sha256 and candidate.sha256!=source_sha:raise ImageUnavailable('reviewed_image_changed')
        variants=normalize(data);asset=hashlib.sha256(candidate.url.encode()+b'\0v'+str(NORMALIZATION_VERSION).encode()+b'\0'+hashlib.sha256(data).digest()).hexdigest()
        record={'asset_id':asset,'source_url':candidate.source_url,'source_label':candidate.source_label,'source_sha256':source_sha,'remote_url':candidate.url,'caption':candidate.caption,'attribution':candidate.author,'license':candidate.license,'license_url':candidate.license_url,'width':variants['browser']['width'],'height':variants['browser']['height'],'mime_type':'image/jpeg','local_cache_path':str(self.file(asset,'browser')),'created':self.clock(),'expires_at':self.clock()+self.ttl,'variants':{k:{'width':v['width'],'height':v['height'],'bytes':len(v['bytes'])} for k,v in variants.items()}}
        # Validate all remote metadata before writing it or exposing it to clients.
        record['normalization_version']=NORMALIZATION_VERSION
        self.public(record)
        size=sum(len(v['bytes']) for v in variants.values())
        if size>self.max_bytes:raise ImageUnavailable('image_cache_capacity')
        with self.lock:
            existing=self.get(asset)
            if existing:return existing
            with self.connect() as c:
                previous=c.execute('SELECT id FROM assets WHERE source_key=?',(hashlib.sha256(candidate.url.encode()).hexdigest(),)).fetchone()
                if previous and previous[0]!=asset:
                    for variant in ('browser','preview','device'):self.file(previous[0],variant).unlink(missing_ok=True)
                    c.execute('DELETE FROM assets WHERE id=?',(previous[0],))
            self.prune(reserve_bytes=size,reserve_entries=1)
            written=[]
            try:
                for name,value in variants.items():
                    path=self.file(asset,name);temporary=path.with_suffix('.tmp');written.extend([temporary,path]);temporary.write_bytes(value['bytes']);temporary.replace(path)
                with self.connect() as c:c.execute('INSERT OR REPLACE INTO assets VALUES(?,?,?,?,?,?)',(asset,hashlib.sha256(candidate.url.encode()).hexdigest(),json.dumps(record),size,record['expires_at'],self.clock()))
            except Exception:
                for path in written:
                    if path.resolve().is_relative_to(self.root) and not path.is_symlink():path.unlink(missing_ok=True)
                raise ImageUnavailable('image_cache_write_failed') from None
        return record
    @staticmethod
    def public(record):
        asset=record['asset_id'];base='/api/visual/assets/'+asset+'/'
        return VisualImage(asset_id=asset,url=base+'browser.jpg',preview_variant=base+'preview.jpg',device_variant=base+'device.jpg',caption=record['caption'][:400],alt=record['caption'][:400],width=record['width'],height=record['height'],source=VisualSource(label=record['source_label'],url=record['source_url']),attribution=record['attribution'],license=record['license'],license_url=record['license_url'])
    def query(self,key):
        with self.connect() as c:row=c.execute('SELECT * FROM queries WHERE id=? AND expires>?',(key,self.clock())).fetchone()
        if not row:return None
        records=[]
        for reference in json.loads(row['assets']):
            record=self.get(reference if isinstance(reference,str) else reference['asset_id'])
            if record is not None and isinstance(reference,dict):record={**record,**{k:reference[k] for k in ('matched_query','entity_title','entity_source','entity_exact') if k in reference}}
            records.append(record)
        if any(record is None for record in records):return None
        return records,row['reason']
    def save_query(self,key,records,reason=None):
        with self.connect() as c:
            references=[{k:r[k] for k in ('asset_id','matched_query','entity_title','entity_source','entity_exact') if k in r} if r.get('matched_query') else r['asset_id'] for r in records]
            c.execute('INSERT OR REPLACE INTO queries VALUES(?,?,?,?)',(key,json.dumps(references),reason,self.clock()+(86400 if records else 600)))
            c.execute('DELETE FROM queries WHERE id IN (SELECT id FROM queries ORDER BY expires DESC LIMIT -1 OFFSET 256)')
    def prune(self,reserve_bytes=0,reserve_entries=0):
        with self.lock,self.connect() as c:
            rows=c.execute('SELECT * FROM assets ORDER BY accessed').fetchall();total=sum(r['size'] for r in rows);count=len(rows)
            for row in rows:
                if row['expires']>self.clock() and total+reserve_bytes<=self.max_bytes and count+reserve_entries<=self.max_entries:continue
                for variant in ('browser','preview','device'):
                    try:self.file(row['id'],variant).unlink(missing_ok=True)
                    except (OSError,KeyError):pass
                c.execute('DELETE FROM assets WHERE id=?',(row['id'],));total-=row['size'];count-=1
            c.execute('DELETE FROM queries WHERE expires<=?',(self.clock(),))
            known={r[0] for r in c.execute('SELECT id FROM assets')}
            for path in self.root.iterdir():
                match=re.fullmatch(r'([a-f0-9]{64})-(browser|preview|device)\.(jpg|tmp)',path.name)
                if match and not path.is_symlink() and path.resolve().is_relative_to(self.root) and (match[1] not in known or match[3]=='tmp'):
                    path.unlink(missing_ok=True)
    def read(self,asset,variant):
        with self.lock:
            record=self.get(asset)
            if not record:raise KeyError('image_expired_or_missing')
            path=self.file(asset,variant);data=path.read_bytes()
            return data,record

    def reserve_request(self,provider):
        now=self.clock()
        with self.lock,self.connect() as c:
            c.execute('BEGIN IMMEDIATE');c.execute('DELETE FROM source_requests WHERE created<?',(now-86400,))
            blocked=c.execute('SELECT until FROM source_backoff WHERE provider=?',(provider,)).fetchone()
            if blocked and blocked[0]>now:return False
            day=c.execute('SELECT count(*) FROM source_requests WHERE provider=?',(provider,)).fetchone()[0]
            burst=c.execute('SELECT count(*) FROM source_requests WHERE provider=? AND created>?',(provider,now-60)).fetchone()[0]
            if day>=80 or burst>=8:return False
            c.execute('INSERT INTO source_requests VALUES(?,?)',(provider,now));return True

    def delay_source(self,provider,seconds):
        with self.connect() as c:c.execute('INSERT OR REPLACE INTO source_backoff VALUES(?,?)',(provider,self.clock()+seconds))
