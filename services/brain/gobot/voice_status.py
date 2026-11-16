"""Shared bounded voice-state scene. Older displays ignore the extra fields."""
def voice_status(engine,phase):
    labels={'A':'Эксперт A','B':'Разговор B','C':'Разговор C'}
    titles={'connecting':'Подключаюсь','listening':'Слушаю','thinking':'Обдумываю','speaking':'Отвечаю'}
    if engine not in labels or phase not in titles:raise ValueError('invalid_voice_status')
    return {'type':'custom','payload':{'namespace':'gobot.ui','version':2,'command':'presentation.show',
        'type':'status_card','title':titles[phase],'text':labels[engine],
        'voice_engine':engine,'voice_phase':phase}}
