import asyncio,importlib.util,json
from pathlib import Path
import httpx,pytest
from gobot.image_query import ImageQueryPlanner
from gobot.visual_images import SafeImageHTTP,OpenverseImages,ImageUnavailable

@pytest.fixture
def planner():
    return ImageQueryPlanner({'велосипед':{'senses':[['bicycle','bike']]},'самолет':{'senses':[['airplane']]},
                             'телескоп':{'senses':[['telescope']]},'коса':{'senses':[['braid'],['scythe']]}})

@pytest.mark.parametrize('query,expected',[
 ('пончик','doughnut'),('пончики','doughnut'),('пончика','doughnut'),
 ('шоколадного пончика','chocolate doughnut'),('красного велосипеда','red bicycle'),
 ('самолеты','airplane'),('телескоп','telescope'),('чёрного лабрадора','black labrador retriever'),
 ('белого кота','white cat'),('Raspberry Pi','Raspberry Pi')])
def test_local_query_plan(query,expected,planner):assert planner.plan(query).terms[0]==expected

def test_ambiguity_and_unknown_modifiers_are_preserved(planner):
    plan=planner.plan('коса');assert plan.ambiguous and plan.terms==('коса',)
    for query in ['неизвестный велосипед','кот на столе','велосипед Пети']:
        assert planner.plan(query).terms==(query,)

def test_bounded_original_language_retry(planner):
    requests=[]
    def handler(request):requests.append(request.url.params['q']);return httpx.Response(200,json={'results':[]})
    async def no_dns(_):pass
    async def run():
        provider=OpenverseImages(SafeImageHTTP('fixture',transport=httpx.MockTransport(handler),resolver=no_dns),planner)
        assert await provider.search('пончика')==[]
        assert requests==['doughnut','пончика']
        with pytest.raises(ImageUnavailable,match='image_query_ambiguous'):await provider.search('коса')
        assert requests[-1]=='коса' and len(requests)==3
    asyncio.run(run())

def test_dictionary_preparation_keeps_provenance_and_senses():
    path=Path(__file__).resolve().parents[1]/'scripts/prepare_visual_dictionary.py'
    spec=importlib.util.spec_from_file_location('dictionary_preparer',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    raw=b'''<TEI xmlns="http://www.tei-c.org/ns/1.0"><teiHeader><availability><p><ref target="https://creativecommons.org/licenses/by-sa/3.0/legalcode"/></p></availability></teiHeader><text><body>'''
    raw+='''<entry><form><orth>велосипед</orth></form><gramGrp><pos>n</pos></gramGrp><sense><cit type="trans"><quote>bicycle</quote><quote>bike</quote></cit></sense></entry></body></text></TEI>'''.encode()
    result=module.build_lexicon(raw)
    assert result['entries']['велосипед']['senses']==[['bicycle','bike']]
    assert result['license']=='CC BY-SA 3.0' and 'Karl Bartel' in result['attribution']
    with pytest.raises(ValueError):module.build_lexicon(b'<!ENTITY evil>')
