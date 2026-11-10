"""Exact conversational closing acts, independent of the selected model."""
import re,time

def closing_intent(text,context=None):
    value=' '.join(re.sub(r'[,.!?:;—–-]+',' ',text.casefold().replace('ё','е')).split())
    value=re.sub(r'^(?:гобот|го бот)\s+','',value)
    if len(value)>120:return None
    direct={
        'нет спасибо','нет благодарю','не надо спасибо','спасибо не надо',
        'нет спасибо не надо','нет спасибо больше ничего','нет спасибо все понятно',
        'нет спасибо мне все понятно','нет спасибо на этом все','нет все спасибо',
        'спасибо все','спасибо это все','все спасибо','на этом все','пока',
        'до свидания','закончим разговор','заверши разговор','давай закончим',
        'больше ничего не нужно','ничего больше не нужно','все понятно спасибо',
        'спасибо больше ничего не нужно','no thanks','no thank you',
    }
    if value in direct:return 'end_conversation'
    ctx=context or {};pending=ctx.get('pending_action')
    if value in {'нет','не надо','отмена'} and pending and pending.get('expires',0)>time.time():
        return 'decline_pending'
    if value not in {'нет','спасибо','благодарю','не надо'}:return None
    messages=[*ctx.get('messages',[]),*ctx.get('recent_dialogue',[])]
    if messages and all(isinstance(row.get('id'),int) for row in messages):messages.sort(key=lambda row:row['id'])
    answers=[row.get('content','') for row in messages if row.get('role')=='assistant']
    if answers and re.search(r'(?:хочешь|хотите|рассказать|расскажу|узнать|продолжить).{0,90}(?:еще|ещё|подробнее|узнать|рассказ|\?)',answers[-1][-400:],re.I):
        return 'end_conversation'
    return None
