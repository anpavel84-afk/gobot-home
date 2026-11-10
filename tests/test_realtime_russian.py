"""Free data/prompt checks; these tests make no acoustic quality claim."""
import json
from pathlib import Path
import pytest
from gobot.realtime_russian import spoken_fields,RUSSIAN_PRONUNCIATION
from gobot.realtime import INSTRUCTIONS

CASES=json.loads((Path(__file__).parent/'data/realtime-russian-evaluation.json').read_text(encoding='utf-8'))['cases']

def equivalent(text):return text.casefold().replace('ё','е')

@pytest.mark.parametrize('case',[c for c in CASES if c['check']=='deterministic_and_acoustic'],ids=lambda c:c['id'])
def test_curated_exact_data(case):
    result=spoken_fields(case['display_text'],kind=case['kind'])
    variants=case.get('accepted_spoken',[case['expected_spoken']])
    assert equivalent(result['spoken_text']) in [equivalent(v) for v in variants]
    assert result['display_text']==case['display_text']
    assert result['acoustic_pronunciation_verified'] is False

def test_hundred_cases_cover_ten_domains_without_acoustic_claims():
    assert len(CASES)>=100 and len({c['id'] for c in CASES})==len(CASES)
    assert len({c['category'] for c in CASES})==10
    assert all(not c['acoustic_verified'] for c in CASES)
    assert RUSSIAN_PRONUNCIATION in INSTRUCTIONS
    assert 'Russian Pronunciation & Number Grammar:' in INSTRUCTIONS
    assert len(RUSSIAN_PRONUNCIATION)<2000

def test_date_semantics_and_identifier_do_not_guess_from_digit_length():
    result=spoken_fields('Дата события: 10.11.2026',kind='date',value='2026-11-10')
    assert result['spoken_date']=='десятого ноября две тысячи двадцать шестого года'
    assert spoken_fields('2026')['spoken_text']=='две тысячи двадцать шесть'
    assert spoken_fields('2026',kind='identifier')['spoken_text']=='два ноль два шесть'
    with pytest.raises(ValueError):spoken_fields('25:90',kind='time')
    with pytest.raises(ValueError):spoken_fields('private URL',kind='identifier')
