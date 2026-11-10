import asyncio,io,json,time
from pathlib import Path
import httpx,pytest
from PIL import Image
from fastapi.testclient import TestClient
from gobot.presentation import PresentationDecision,Presentation,VisualMetadata,esp32_projection
from gobot.visual_images import ImageCache,ImageCandidate,SafeImageHTTP,CommonsImages,OpenverseImages,ImageUnavailable,normalize
from gobot.visual import VisualService
from gobot.visual_device import ESP32VisualRenderer
from gobot.models import ChatRequest
from gobot.brain import Service,create_app
from gobot.pipeline import voiced_events
from gobot.ui import ImageStore

def jpeg(color='red',size=(700,500)):
    buffer=io.BytesIO();Image.new('RGB',size,color).save(buffer,'JPEG');return buffer.getvalue()

def candidate(index=1):
    return ImageCandidate(f'https://upload.wikimedia.org/wikipedia/commons/a/ab/fixture{index}.jpg','Синтетическая фикстура, не фотография объекта','https://commons.wikimedia.org/wiki/File:Fixture.jpg','Fixture author','CC BY-SA 4.0','https://creativecommons.org/licenses/by-sa/4.0/')

async def no_dns(host):pass

def visuals(tmp_path,calls,*,multiple=False,missing=False):
    def handler(request):
        calls.append(str(request.url))
        if missing:return httpx.Response(403)
        return httpx.Response(200,content=jpeg('red' if 'fixture1' in str(request.url) else 'blue'),headers={'Content-Type':'image/jpeg'})
    class Provider:
        client=SafeImageHTTP('GoBotFixture/1 (fixture@example.test)',transport=httpx.MockTransport(handler),resolver=no_dns)
        async def search(self,query,limit=3):
            return [candidate(1),candidate(2)] if multiple else [candidate(1)]
    return VisualService(ImageCache(tmp_path/'images'),provider_factory=lambda _:Provider(),config_loader=lambda:{'contact':'fixture@example.test','user_agent':'fixture'})

@pytest.mark.parametrize('text,kind,catalog',[
 ('Покажи, как выглядят помидоры Бычье сердце','image','oxheart'),
 ('Покажи, как выглядит лабрадор','image','labrador'),
 ('Покажи картинку Raspberry Pi','image','raspberry-pi'),
 ('Покажи Raspberry Pi Zero','image',None),
 ('Покажи чёрного лабрадора','image',None),
 ('Какая сейчас погода?','weather',None),
 ('Что сейчас играет?','music',None),
 ('Покажи статус системы GoBot','status',None),
 ('Покажи схему голосового конвейера GoBot','diagram','gobot-pipeline'),
 ('Покажи мою теплицу по схеме','diagram',None),
 ('Покажи историю моих разговоров',None,None),
 ('Поставь таймер на 3 минуты',None,None),
 ('Расскажи про лабрадора',None,None),
 ('Не показывай картинки лабрадора',None,None),
 ('Ответь без картинок',None,None),
 ('Можешь показать фото лабрадора?','image','labrador'),
])
def test_visual_intent(text,kind,catalog):
    result=PresentationDecision().detect(text)
    assert (result.kind if result else None)==kind
    if result:assert result.catalog_id==catalog

def test_real_normalization_baseline_limits_and_stripped_metadata(tmp_path):
    cache=ImageCache(tmp_path/'images');record=cache.put(candidate(),jpeg(size=(1300,600)))
    assert Path(record['local_cache_path']).is_file()
    for variant in ['browser','preview','device']:
        data,_=cache.read(record['asset_id'],variant)
        with Image.open(io.BytesIO(data)) as image:
            assert image.format=='JPEG' and not image.info.get('progressive') and not image.getexif()
            if variant=='device':assert image.size==(240,240) and len(data)<=65536
            else:assert max(image.size)<=({'browser':960,'preview':480}[variant])
    public=cache.public(record).model_dump()
    assert 'local_cache_path' not in public and public['mime_type']=='image/jpeg'
    with pytest.raises(KeyError):cache.file('../outside','browser')
    for raw in [b'<svg><script>evil</script></svg>',b'<html>not an image</html>']:
        with pytest.raises(ImageUnavailable):normalize(raw)

def test_cache_hit_ttl_restart_quota_and_eviction(tmp_path):
    clock=[100.0];cache=ImageCache(tmp_path/'images',ttl=10,max_entries=1,clock=lambda:clock[0])
    one=cache.put(candidate(1),jpeg());cache.save_query('q',[one]);assert cache.query('q')[0][0]['asset_id']==one['asset_id']
    assert ImageCache(tmp_path/'images',clock=lambda:clock[0]).get(one['asset_id'])
    two=cache.put(candidate(2),jpeg('blue'));assert not cache.get(one['asset_id'])
    assert not cache.file(one['asset_id'],'browser').exists()
    clock[0]+=11;cache.prune();assert not cache.get(two['asset_id'])
    assert not list((tmp_path/'images').glob('*.jpg'))

def test_image_gallery_cache_no_repeat_download_and_negative_cache(tmp_path):
    async def run():
        calls=[];service=visuals(tmp_path,calls,multiple=True)
        request=ChatRequest(text='Покажи несколько изображений кота',mode='auto')
        one=await service.handle(request);two=await service.handle(request)
        assert one.frame.type=='image_gallery' and len(one.frame.images)==2
        assert not one.frame.metadata.cache_hit and two.frame.metadata.cache_hit and len(calls)==2
        assert not any('ключ' in url for url in calls)
        calls=[];blocked=visuals(tmp_path/'blocked',calls,missing=True)
        one=await blocked.handle(request);two=await blocked.handle(request)
        assert one.frame.metadata.state=='unavailable' and not one.frame.images
        assert 'отклонил' in one.display_text and two.frame.metadata.cache_hit and len(calls)==1
    asyncio.run(run())

def test_missing_contact_private_query_and_no_invented_weather(tmp_path):
    async def run():
        def forbidden(_):raise AssertionError('No source call allowed')
        service=VisualService(ImageCache(tmp_path/'cache'),provider_factory=forbidden,config_loader=lambda:{})
        for text in ['Покажи фото моего дома','Покажи фото мамы','Покажи фото нашей семьи']:
            result=await service.handle(ChatRequest(text=text));assert result.frame.metadata.reason=='private_image_not_available'
        result=await service.handle(ChatRequest(text='Покажи как выглядит лабрадор'))
        assert result.frame.metadata.reason=='image_sources_disabled' and not result.frame.images
        for text,kind in [('Какая погода?','weather_card'),('Что сейчас играет?','music_card')]:
            result=await service.handle(ChatRequest(text=text));assert result.frame.type==kind and result.frame.metadata.state=='unavailable'
            assert not result.frame.metadata.facts
        result=await service.handle(ChatRequest(text='Покажи мою теплицу по схеме'))
        assert not result.frame.images and 'не буду придумывать' in result.display_text
    asyncio.run(run())

@pytest.mark.parametrize('url',[
 'http://upload.wikimedia.org/wikipedia/commons/a/a.jpg',
 'https://127.0.0.1/wikipedia/commons/a/a.jpg',
 'https://upload.wikimedia.org@127.0.0.1/wikipedia/commons/a/a.jpg',
 'https://upload.wikimedia.org.evil.test/wikipedia/commons/a/a.jpg',
 'https://upload.wikimedia.org/wikipedia/commons/a.jpg?next=http://127.0.0.1',
 'https://upload.wikimedia.org/not-a-public-image',
])
def test_image_ssrf_allowlist_no_network(url):
    async def run():
        def forbidden(request):raise AssertionError('Untrusted URL reached transport')
        client=SafeImageHTTP('fixture',transport=httpx.MockTransport(forbidden),resolver=no_dns)
        with pytest.raises(ImageUnavailable):await client.get(url)
    asyncio.run(run())

def test_redirect_mime_size_and_private_dns_denied():
    async def run():
        url=candidate().url
        for response in [httpx.Response(302,headers={'Location':'http://127.0.0.1'}),httpx.Response(200,content=b'fake',headers={'Content-Type':'text/html'}),httpx.Response(200,content=b'x',headers={'Content-Type':'image/jpeg','Content-Length':str(10_000_000)})]:
            client=SafeImageHTTP('fixture',transport=httpx.MockTransport(lambda _:response),resolver=no_dns)
            with pytest.raises(ImageUnavailable):await client.get(url)
        async def private(host):raise ImageUnavailable('image_private_address_denied')
        client=SafeImageHTTP('fixture',resolver=private)
        with pytest.raises(ImageUnavailable,match='private_address'):await client.get(url)
    asyncio.run(run())

def test_commons_metadata_license_plaintext_and_query_only():
    seen=[]
    def handler(request):
        seen.append(request);return httpx.Response(200,json={'query':{'pages':{'1':{'title':'File:Test.jpg','index':1,'imageinfo':[{'mime':'image/jpeg','url':candidate().url,'descriptionurl':candidate().source_url,'extmetadata':{'LicenseShortName':{'value':'CC BY-SA 4.0'},'LicenseUrl':{'value':candidate().license_url},'Artist':{'value':'<b>Author</b>'},'ImageDescription':{'value':'<i>кот</i>'}}}]}}}})
    async def run():
        client=SafeImageHTTP('GoBot fixture',transport=httpx.MockTransport(handler),resolver=no_dns)
        result=await CommonsImages(client).search('кот')
        assert result[0].author=='Author' and result[0].caption=='кот'
        assert set(seen[0].url.params)-{'action','format','generator','gsrnamespace','gsrlimit','gsrsearch','prop','iiprop','iiurlwidth','iiextmetadatafilter'}==set()
        assert seen[0].headers.get('Authorization') is None
    asyncio.run(run())

def test_visual_voice_short_narration_replay_and_persistence(settings,tmp_path,monkeypatch):
    import gobot.brain as brain
    monkeypatch.setattr(brain,'agent_status',lambda *a:{})
    calls=[];spoken=[]
    class Voice:
        async def synthesize(self,text,*a,**kw):spoken.append(text);yield b'\0\0'*10,24000
    async def run():
        service=Service(settings);service.visual=visuals(tmp_path,calls,multiple=True)
        req=ChatRequest(text='Покажи несколько изображений кота',mode='auto',request_id='visual-request')
        events=[e async for e in voiced_events(service,Voice(),req)]
        frame=next(e['data']['presentation'] for e in events if e['type']=='visual_response')
        assert frame['type']=='image_gallery' and events[-1]['type']=='final'
        assert len(spoken)==1 and 'подписи' not in spoken[0].lower()
        with service.memory.connect() as c:
            original=c.execute("SELECT content FROM messages WHERE role='assistant'").fetchone()[0]
            oral=c.execute('SELECT speech_text FROM speech_segments').fetchone()[0]
            assert original!=oral and original==events[-1]['data']['text']
        replay=[e async for e in voiced_events(service,Voice(),req)]
        assert any(e['type']=='visual_response' for e in replay) and not any(e['type']=='audio_chunk' for e in replay)
        assert len(spoken)==1 and len(calls)==2
    asyncio.run(run())

def test_visual_cancel_stops_pending_operations(settings,monkeypatch):
    import gobot.brain as brain
    monkeypatch.setattr(brain,'agent_status',lambda *a:{})
    async def run():
        service=Service(settings);started=asyncio.Event();ended=asyncio.Event()
        async def pending(*a,**kw):
            started.set()
            try:await asyncio.sleep(60)
            finally:ended.set()
        service.visual.handle=pending
        req=ChatRequest(text='Покажи картинку кота',mode='auto');await service.prepare(req)
        async def consume():return [e async for e in service.events(req)]
        task=asyncio.create_task(consume());await started.wait();service.running[req.turn_id].set();events=await asyncio.wait_for(task,2)
        assert ended.is_set() and events[-1].type=='cancelled'
        assert not any(e.type=='sentence_ready' for e in events)
    asyncio.run(run())

def test_local_diagram_device_projection_mcp_and_auth(settings):
    app=create_app(settings);headers={'Authorization':'Bearer '+settings.api_token}
    with TestClient(app) as client:
        req=ChatRequest(text='Покажи схему голосового конвейера GoBot',mode='auto')
        events=client.post('/api/v1/chat',headers=headers,json=req.model_dump()).json()['events']
        frame=Presentation.model_validate(next(e['data']['presentation'] for e in events if e['type']=='visual_response'))
        assert frame.type=='rich_answer' and frame.images
        renderer=ESP32VisualRenderer(app.state.service.visual.cache);compact=renderer.render(frame)
        assert compact['payload']['image']['max_bytes']==65536 and len(json.dumps(compact,ensure_ascii=False))<1500
        from gobot.ui import MockUIRenderer
        gui=MockUIRenderer();gui.enqueue(compact)
        assert not gui.state
        assert gui.gui_tick()['presentation.show']['type']=='rich_answer'
        assert compact['payload']['credit']['author']=='GoBot Home'
        store=ImageStore()
        with pytest.raises(PermissionError):renderer.preview(frame,store,capabilities=set(),user_tool_permission=True)
        with pytest.raises(PermissionError):renderer.preview(frame,store,capabilities={'self.screen.preview_image'},user_tool_permission=False)
        command=renderer.preview(frame,store,capabilities={'self.screen.preview_image'},user_tool_permission=True)
        assert command['payload']['params']['name']=='self.screen.preview_image'
        path='/api/v1/visual/assets/'+frame.images[0].asset_id+'/device.jpg'
        assert client.get(path).status_code==401
        response=client.get(path,headers=headers);assert response.status_code==200 and len(response.content)<=65536
        assert response.headers['Content-Length']==str(len(response.content))

def test_timer_visual_deadline_and_owner_cancel(settings):
    app=create_app(settings);headers={'Authorization':'Bearer '+settings.api_token}
    with TestClient(app) as client:
        request={'text':'Поставь таймер на 3 минуты','mode':'auto','device_id':'owner','request_id':'timer-replay','conversation_id':'timer-conversation'}
        response=client.post('/api/v1/chat',headers=headers,json=request)
        events=response.json()['events'];frame=next(e['data']['presentation'] for e in events if e['type']=='visual_response')
        assert frame['type']=='timer_widget' and 175<=frame['metadata']['deadline']-time.time()<=180
        ident=frame['metadata']['timer_id']
        assert client.post('/api/v1/visual/timer/cancel',headers=headers,json={'device_id':'foreign','timer_id':ident}).status_code==404
        assert client.post('/api/v1/visual/timer/cancel',headers=headers,json={'device_id':'owner','timer_id':ident}).status_code==200
        replay=client.post('/api/v1/chat',headers=headers,json=request).json()['events']
        frame=next(e['data']['presentation'] for e in replay if e['type']=='visual_response')
        assert frame['metadata']['state']=='cancelled' and frame['metadata']['deadline'] is None
        with app.state.service.memory.connect() as c:assert c.execute('SELECT count(*) FROM timers').fetchone()[0]==1

def test_browser_renderer_dom_units():
    import subprocess
    root=Path(__file__).resolve().parents[1]
    result=subprocess.run(['node','tests/browser_visuals.cjs'],cwd=root,capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stderr

def test_partial_contract_and_ready_validation():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):Presentation(id='missing',type='image_card',title='No image')
    assert Presentation(id='partial',type='image_card',title='Loading',metadata=VisualMetadata(state='loading')).images==[]
    with pytest.raises(ValidationError):Presentation(id='missing',type='timer_widget',title='No deadline')

def test_openverse_fixed_thumbnail_and_license_filters_no_credentials():
    seen=[]
    ident='11111111-1111-1111-1111-111111111111'
    def handler(request):
        seen.append(request)
        return httpx.Response(200,json={'results':[
            {'id':ident,'title':'Cat','creator':'Author','foreign_landing_url':'https://www.flickr.com/photos/test/1','license':'by','license_version':'2.0','source':'flickr','url':'http://127.0.0.1/private','thumbnail':'http://127.0.0.1/secret'},
            {'id':'22222222-2222-2222-2222-222222222222','license':'by-nd','license_version':'2.0'},
            {'id':'33333333-3333-3333-3333-333333333333','license':'by','license_version':'2.0','mature':True}]})
    async def run():
        client=SafeImageHTTP('fixture',transport=httpx.MockTransport(handler),resolver=no_dns)
        result=await OpenverseImages(client).search('кота')
        assert len(result)==1 and result[0].url=='https://api.openverse.org/v1/images/'+ident+'/thumb/'
        assert result[0].license=='CC BY 2.0' and seen[0].url.params['q']=='cat'
        assert 'Authorization' not in seen[0].headers
    asyncio.run(run())

def test_rate_budget_backoff_and_curated_image_hash(tmp_path):
    clock=[1000.0];cache=ImageCache(tmp_path/'rate-cache',clock=lambda:clock[0])
    for _ in range(8):assert cache.reserve_request('api.openverse.org')
    assert not cache.reserve_request('api.openverse.org')
    clock[0]+=61;assert cache.reserve_request('api.openverse.org')
    cache.delay_source('api.openverse.org',3600);assert not cache.reserve_request('api.openverse.org')
    clock[0]+=3601;assert cache.reserve_request('api.openverse.org')
    from dataclasses import replace
    with pytest.raises(ImageUnavailable,match='reviewed_image_changed'):cache.put(replace(candidate(),sha256='0'*64),jpeg())

def test_visual_source_settings_are_local_and_fail_closed(settings,tmp_path,monkeypatch):
    from gobot import visual_images,browser
    monkeypatch.setattr(visual_images,'CONTACT',tmp_path/'source.json')
    assert visual_images.source_config()['provider']=='openverse'
    with TestClient(browser.create_browser_app(settings),base_url=browser.ORIGIN,client=('100.120.201.115',111)) as client:
        assert client.get('/api/settings/visual').json()['provider']=='openverse'
        assert client.post('/api/settings/visual',json={'provider':'disabled'}).status_code==403
        headers={'Origin':browser.ORIGIN}
        assert client.post('/api/settings/visual',headers=headers,json={'provider':'disabled'}).status_code==200
        assert not visual_images.source_config()
        assert client.post('/api/settings/visual',headers=headers,json={'provider':'wikimedia','contact':'fixture@example.test'}).status_code==422
        assert client.post('/api/settings/visual',headers=headers,json={'provider':'wikimedia','contact':'fixture@example.test','public_contact_consent':True}).status_code==200
        assert 'fixture@example.test' in visual_images.source_config()['user_agent']
    visual_images.CONTACT.write_text('{invalid',encoding='utf-8');assert not visual_images.source_config()
