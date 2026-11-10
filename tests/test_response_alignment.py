"""Grammar-only subject warnings; no ASR, provider or paid classification calls."""
import pytest
from gobot.response_alignment import alignment

@pytest.mark.parametrize('query,answer,expected',[
 ('Какой самый ядовитый паук в Бразилии?','Самым ядовитым плодом в Бразилии считают растение.','suspected_mismatch'),
 ('Какой самый ядовитый паук?','Самый ядовитый паук относится к этому роду.','match'),
 ('Какая самая высокая гора?','Самая высокая гора — Эверест.','match'),
 ('Какая самая высокая гора?','Самая высокая башня находится в городе.','suspected_mismatch'),
 ('Какой самый быстрый поезд?','Самый быстрый самолёт летит над океаном.','suspected_mismatch'),
 ('Какая самая далёкая планета?','Самой далёкой планетой называют Нептун.','match'),
 ('Какое самое большое животное?','Самое большое животное — синий кит.','match'),
 ('Какое самое большое животное?','Самое большое растение растёт в лесу.','suspected_mismatch'),
 ('Сколько живут пауки?','Некоторые пауки живут долго.',None),
 ('Какой самый ядовитый паук?','Phoneutria nigriventer относится к паукам.',None),
 ('Какой самый ядовитый паук?','Я не уверен, какой вид самый опасный.',None),
 ('Не самый высокий дом, а обычный?','Самая высокая гора находится далеко.',None),
])
def test_local_subject_frame_warning_is_conservative(query,answer,expected):
    assert alignment(query,answer)==expected
