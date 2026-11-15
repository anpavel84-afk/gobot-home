"""Bounded display status, reusing the existing physical scene contract."""
def expert_scene(event):
    job=event.get('job',{});state=job.get('state')
    titles={'awaiting_confirmation':'Подключить Sol?','queued':'Sol: в очереди',
        'running':'Sol разбирается','completed':'Разбор готов','cancelled':'Разбор отменён',
        'timed_out':'Время разбора истекло','failed':'Разбор не получен'}
    if state not in titles:return None
    text='Нужен ваш ответ' if state=='awaiting_confirmation' else 'Sol 6.1 · High'
    return {'type':'custom','payload':{'namespace':'gobot.ui','version':2,
        'command':'presentation.show','id':'expert-'+str(job.get('job_id',''))[:80],
        'type':'status_card','title':titles[state],'text':text,'state':'ready',
        'synthetic':False,'visual_strategy':'render_local'}}
