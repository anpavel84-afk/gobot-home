"""Acoustic corpus definitions, not runtime text matching. No recording/API."""
VARIANTS = (
    {'id':'ru_first','text':'Го́бот.','stress':'first'},
    {'id':'ru_second','text':'Гобо́т.','stress':'second'},
    {'id':'ru_first_separated','text':'Го́ бот.','stress':'first'},
    {'id':'ru_second_separated','text':'Го бо́т.','stress':'second'},
    {'id':'go_diphthong','text':'Гоу бо́т.','stress':'second'},
)
ONE_PHRASE_SUFFIXES = ('какая погода завтра?','поставь таймер на минуту.',
    'расскажи короткий факт о Луне.','помоги разобраться в сложном вопросе.',
    'проверь последние новости тестовой компании.')

def one_phrase_cases():
    return [{'variant':v['id'],'utterance':v['text'].rstrip('.')+', '+suffix,
        'canonical_wake':'ГоБот','question':suffix,'pause_required':False,
        'synthetic_definition':True,'human_verified':False}
        for v in VARIANTS for suffix in ONE_PHRASE_SUFFIXES]
