"""API fixtures; a search hit alone must not justify a picture of another entity."""
import asyncio,io,json
from PIL import Image
import pytest
from gobot.visual_images import CommonsImages,ImageCache,ImageCandidate,SafeImageHTTP,ImageUnavailable
from gobot.visual import VisualService
from gobot.presentation import VisualIntent


def metadata():
    return {'query':{'pages':{'1':{'imageinfo':[{
        'thumburl':'https://upload.wikimedia.org/wikipedia/commons/a/ab/Boletus_edulis.jpg',
        'descriptionurl':'https://commons.wikimedia.org/wiki/File:Boletus_edulis.jpg','mime':'image/jpeg',
        'extmetadata':{'LicenseShortName':{'value':'CC BY 3.0'},'LicenseUrl':{'value':'https://creativecommons.org/licenses/by/3.0/'},
                       'ImageDescription':{'value':'Boletus edulis'},'Artist':{'value':'Fixture'}}}]}}}}


class Client:
    def __init__(self,pages):self.pages=pages;self.calls=[]
    async def get(self,url,*,params=None,api=False):
        self.calls.append((url,params))
        if 'wikipedia.org' in url:return json.dumps({'query':{'pages':self.pages}}).encode(),'application/json'
        if api:return json.dumps(metadata()).encode(),'application/json'
        image=io.BytesIO();Image.new('RGB',(300,220),'brown').save(image,'JPEG');return image.getvalue(),'image/jpeg'


def test_ru_article_to_licensed_latin_caption_and_overview():
    client=Client({'bad':{'ns':0,'index':1,'title':'Мухомор вонючий','pageimage':'Amanita.jpg'},
                   'right':{'ns':0,'index':2,'title':'Белый гриб','pageimage':'Boletus_edulis.jpg'}})
    async def run():
        candidates=await CommonsImages(client).page_images('белый гриб еловый')
        assert len(candidates)==1 and candidates[0].caption=='Boletus edulis'
        assert candidates[0].matched_query=='белый гриб еловый' and not candidates[0].entity_exact
        assert candidates[0].entity_title=='Белый гриб'
        assert client.calls[-1][1]['titles']=='File:Boletus_edulis.jpg'
    asyncio.run(run())


@pytest.mark.parametrize('page',[
    {'ns':0,'title':'Белый медведь','pageimage':'bear.jpg'},
    {'ns':0,'title':'Гриб','pageimage':'generic.jpg'},
    {'ns':0,'title':'Белый гриб','pageimage':'fake.jpg','pageprops':{'disambiguation':''}},
    {'ns':1,'title':'Белый гриб','pageimage':'talk.jpg'},
    {'ns':0,'title':'Белый гриб','pageimage':'one.jpg|File:two.jpg'},
])
def test_reject_unrelated_ambiguous_or_injected_filename(page):
    client=Client({'1':page})
    async def run():assert not await CommonsImages(client).page_images('белый гриб еловый')
    asyncio.run(run());assert len(client.calls)==1


def test_cache_keeps_entity_relation_per_query_and_legacy_ids(tmp_path):
    cache=ImageCache(tmp_path/'cache');buffer=io.BytesIO();Image.new('RGB',(240,240),'brown').save(buffer,'JPEG')
    item=ImageCandidate('https://upload.wikimedia.org/wikipedia/commons/a/ab/f.jpg','Boletus edulis',
        'https://commons.wikimedia.org/wiki/File:f.jpg','Fixture','CC BY 3.0','https://creativecommons.org/licenses/by/3.0/')
    record=cache.put(item,buffer.getvalue());cache.save_query('legacy',[record])
    one={**record,'matched_query':'белый гриб еловый','entity_title':'Белый гриб','entity_source':'https://ru.wikipedia.org/wiki/test','entity_exact':False}
    two={**record,'matched_query':'белый гриб','entity_title':'Белый гриб','entity_source':'https://ru.wikipedia.org/wiki/test','entity_exact':True}
    cache.save_query('qualified',[one]);cache.save_query('exact',[two])
    assert cache.query('qualified')[0][0]['entity_exact'] is False
    assert cache.query('exact')[0][0]['entity_exact'] is True
    assert 'matched_query' not in cache.query('legacy')[0][0]


def test_pipeline_preserves_overview_on_cache_hit_without_external_retry(tmp_path):
    client=Client({'1':{'ns':0,'title':'Белый гриб','pageimage':'Boletus_edulis.jpg'}})
    class Primary:
        async def search(self,*a):raise AssertionError('Resolved article must not retry another provider')
    # The request is only used for a turn-bound frame ID.
    from gobot.models import ChatRequest
    async def invoke():
        service=VisualService(ImageCache(tmp_path/'images'),provider_factory=lambda _:Primary(),fallback_factory=lambda:CommonsImages(client),config_loader=lambda:{'provider':'openverse'})
        req=ChatRequest(text='Белые грибы',mode='auto',remember=False);intent=VisualIntent('image',query='белый гриб еловый',strict_subject=True)
        first=await service.images(req,intent);count=len(client.calls);second=await service.images(req,intent)
        assert first.frame.images and first.frame.metadata.facts['entity_match']=='topic_overview'
        assert 'обзор' in first.frame.title and 'не подтверждена' in first.frame.text
        assert second.frame.metadata.cache_hit and len(client.calls)==count
    asyncio.run(invoke())


def test_wikipedia_api_allowlist_does_not_allow_article_or_image_proxy():
    async def run():
        client=SafeImageHTTP('Fixture')
        for url in ('https://ru.wikipedia.org/private','https://en.wikipedia.org/wiki/File:a.jpg','https://evil.wikipedia.org/w/api.php'):
            with pytest.raises(ImageUnavailable):await client.get(url,api=True)
        with pytest.raises(ImageUnavailable):await client.get('https://ru.wikipedia.org/w/api.php')
    asyncio.run(run())
