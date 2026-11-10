import pytest
from gobot.speech_formatter import SpeechFormatter
from gobot.providers import SentenceBuffer

@pytest.mark.parametrize('display,expected',[
 ('Кэтрин Зета-Джонс (Catherine Zeta-Jones), Зета (Zeta).','Кэтрин Зета-Джонс, Зета.'),
 ('Catherine Zeta-Jones приехала.','Catherine Zeta-Jones приехала.'),
 ('Анна (Mary) — разные имена.','Анна (Mary) — разные имена.'),
 ('Нужно 2 минуты.','Нужно две минуты.'),
 ('До 2 минут, к 2 часам, между 2 домами.','До двух минут, к двум часам, между двумя домами.'),
 ('Цена 22 ₽, масса 2 кг.','Цена двадцать два рубля, масса два килограмма.'),
 ('Объём 2,5 л.','Объём две целых пять десятых литра.'),
 ('Объём 1,1 л.','Объём одна целая одна десятая литра.'),
 ('До 2,5 л.','До двух целых пяти десятых литра.'),
 ('Разница -0,5 м.','Разница минус ноль целых пять десятых метра.'),
 ('В 2026 году.','В две тысячи двадцать шестом году.'),
 ('Дата 10.11.2026.','Дата десятого ноября две тысячи двадцать шестого года.'),
 ('При этом 10 ноября отмечается праздник.','При этом десятого ноября отмечается праздник.'),
 ('Выходной будет уже 15 ноября.','Выходной будет уже пятнадцатого ноября.'),
 ('Сегодня 10 ноября.','Сегодня десятое ноября.'),
 ('Завтра будет 15 ноября.','Завтра будет пятнадцатое ноября.'),
 ('К 10 ноября, до 15 ноября.','К десятому ноября, до пятнадцатого ноября.'),
 ('На 15 ноября назначена встреча.','На пятнадцатое ноября назначена встреча.'),
 ('Перед 15 ноября.','Перед пятнадцатым ноября.'),
 ('10-го ноября 2026 года.','десятого ноября две тысячи двадцать шестого года.'),
 ('С 10 по 15 ноября.','С десятого по пятнадцатое ноября.'),
 ('Между 10 и 15 ноября.','Между десятым и пятнадцатым ноября.'),
 ('Не принимай 2 таблетки (без назначения врача).','Не принимай две таблетки (без назначения врача).'),
 ('**Важно:** [источник](https://example.test) и https://example.test/x','Важно: источник и ссылка на экране'),
 ('GPT ESP32 STT TTS','джи пи ти э эс пи тридцать два эс ти ти ти ти эс'),
])
def test_formatter(display,expected):
    assert SpeechFormatter().format(display)==expected

def test_balanced_streaming_names_and_parentheses():
    chunks=['Кэтрин Зета-Джонс (Cat','herine Zeta-Jones) — актриса. ', 'Вес 2 кг (не ', '3 кг). Далее.']
    buffer=SentenceBuffer();formatter=SpeechFormatter();spoken=[]
    for text in chunks:spoken.extend(formatter.format(s) for s in buffer.feed(text))
    spoken.extend(formatter.format(s) for s in buffer.feed('',final=True))
    assert spoken==['Кэтрин Зета-Джонс — актриса.','Вес два килограмма (не три килограмма).','Далее.']

def test_code_never_becomes_speech_and_dictionary_is_configurable():
    formatter=SpeechFormatter({'GoBot':'Гобот'})
    assert formatter.format('GoBot: ```python\nprint(123)')=='Гобот:'
    assert formatter.format('secret``` Хорошо.')=='Хорошо.'

def test_replayed_final_is_not_synthesized_again(settings):
    import asyncio
    from gobot.brain import Service
    from gobot.models import ChatRequest
    from gobot.pipeline import voiced_events
    spoken=[]
    class Voice:
        async def synthesize(self,text,*a,**kw):spoken.append(text);yield b'\0\0',24000
    async def run():
        service=Service(settings);req=ChatRequest(text='Привет',mode='mock',request_id='audio-request')
        first=[e async for e in voiced_events(service,Voice(),req)];count=len(spoken)
        second=[e async for e in voiced_events(service,Voice(),req)]
        assert len(spoken)==count and not any(e['type']=='audio_chunk' for e in second)
        assert second[-1]['type']=='final' and second[-1]['data']['replayed']
        with service.memory.connect() as c:
            assert c.execute('SELECT count(*) FROM speech_segments').fetchone()[0]==count
    asyncio.run(run())
