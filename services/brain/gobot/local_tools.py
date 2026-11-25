import re,time,json,hashlib
import threading
from uuid import uuid4
from dataclasses import dataclass
from .quality import calculate,arithmetic_expression
from .timer_duration import duration_text

@dataclass
class ToolResult:
    text:str
    widget:dict|None=None
    evidence:dict|None=None

class LocalTools:
    def __init__(self,memory):
        self.memory=memory;self.timer_targets={};self.target_lock=threading.Lock()
        from .timer_service import TimerService
        self.timers=TimerService(memory)
    @staticmethod
    def timer_scope(req):
        return (req.device_id,req.conversation_id,req.profile_epoch,req.client_id)
    def timer_context(self,req):
        """Only a live, server-owned list snapshot may resolve an ordinal."""
        with self.target_lock:
            snapshot=self.timer_targets.get(self.timer_scope(req))
            if not snapshot or snapshot[0]<=time.time():return {}
            return {'timer_list_expires':snapshot[0],'timer_list_ids':list(snapshot[1])}
    def clear_timer_context(self,req):
        with self.target_lock:self.timer_targets.pop(self.timer_scope(req),None)
    def working_memory(self,req):
        """Current scoped dialogue is available independently of private archives.

        Verification here concerns the provenance of conversation records, not
        whether an assertion previously made by the assistant was factually true.
        """
        from .context_manager import ContextManager
        recall=self.memory.recall(req)
        source_ids=recall.get('source_ids',[])
        context={'messages':recall.get('messages',[]),'summary':recall.get('summary',''),
                 'summary_sources':source_ids,
                 '_memory_meta':{'version':recall.get('context_version',0),
                                 'coverage':recall.get('coverage','partial_working_context')}}
        packet=ContextManager(recent=1000,summary=500).pack(req.text,context,'FAST_CHAT')
        messages=packet['messages'];summary=packet['summary']
        evidence={'method':'memory_source','verified':False,'facts_verified':False,
                  'external_sources_checked':False,'private_archive_checked':False,
                  'scope':'current_conversation','context_version':recall.get('context_version',0),
                  'coverage':recall.get('coverage','partial_working_context'),
                  'source_message_ids':packet['_context_meta']['source_message_ids'],
                  'reason':recall.get('reason','no_relevant_working_context'),
                  'ordinary_conversation_available':True}
        if not recall.get('useful') or not (messages or summary):
            evidence.update(abstained=True,status='not_found',source_records_verified=False)
            return ToolResult('Сейчас не нахожу эту часть разговора в доступном контексте. Уточни тему или напомни, о чём шла речь.',evidence=evidence)
        records=[]
        for item in messages:
            label='Пользователь' if item['role']=='user' else ('Ответ Софии, воспроизведённый пользователю' if item.get('heard') is True else 'Ответ модели; воспроизведение не подтверждено')
            if item.get('content_complete') is False:label+=' (неполный фрагмент)'
            records.append(label+': '+item['content'])
        if summary:records.append('Рабочая сводка с источниками; её покрытие ограничено: '+summary)
        answer='В доступной рабочей памяти найдены материалы этой беседы:\n'+'\n'.join(records)
        evidence.update(status='matched',verified=True,source_records_verified=True,
                        verification_scope='conversation_record_only',
                        canonical_answer=messages[0]['content'] if messages else summary,
                        source_records=[{key:item[key] for key in
                            ('id','turn_id','role','heard','status','content_complete','excerpted') if key in item}
                            for item in messages])
        return ToolResult(answer,evidence=evidence)
    def execute(self,tool,req,slots=None,*,action_id=None,is_current=None):
        text=req.text.lower()
        slots=slots or {}
        if tool=='utility':
            from .quick_utilities import execute
            answer=execute(slots)
            return ToolResult(answer,evidence={'method':'local_utility','verified':True,'canonical_answer':answer})
        if tool=='skill_readiness':
            from .skill_catalogue import unavailable_text
            return ToolResult(unavailable_text(slots.get('category')),evidence={'abstained':True,'verified':False,
                'method':'capability_registry','reason':slots.get('reason') or 'adapter_not_connected',
                'capability':slots.get('capability'),'category':slots.get('category')})
        if tool=='dialogue_end':
            self.memory.settle_pending(req,'cancelled')
            return ToolResult('Хорошо.',evidence={'method':'dialogue_control','verified':True,'canonical_answer':'Хорошо.'})
        if tool=='pending_decline':
            self.memory.settle_pending(req,'declined',slots.get('pending_id'))
            return ToolResult('Действие отменено.')
        if tool=='stop_output':return ToolResult('Остановлено.')
        if tool=='unavailable':return ToolResult('Эта функция пока не подключена. Действие не выполнено.')
        if tool=='clock':
            from datetime import datetime
            now=datetime.now().astimezone();kind=slots['intent']
            weekdays=['понедельник','вторник','среда','четверг','пятница','суббота','воскресенье']
            value=now.strftime('%H:%M') if kind=='clock_time' else weekdays[now.weekday()] if kind=='clock_weekday' else now.strftime('%d.%m.%Y')
            answer=('По времени домашнего сервера сейчас ' if kind=='clock_time' else 'Сегодня ')+value+'.'
            return ToolResult(answer,evidence={'method':'server_clock','verified':True,'canonical_answer':answer,'display':value,'utc_offset':now.strftime('%z'),'as_of':now.isoformat()})
        if tool=='timer_status':
            native=self.native_timer_action(action_id)
            if native:
                self.timers._current(is_current)
                rows=self.timers.current(req)
                self.timers._current(is_current)
            else:
                with self.memory.connect() as c:rows=c.execute("""SELECT t.id,t.deadline FROM timers t
                    LEFT JOIN timer_bindings b ON b.timer_id=t.id WHERE t.device_id=?
                    AND b.scope_key IS NULL AND t.status='running' AND t.deadline>?
                    ORDER BY t.deadline,t.id""",(req.device_id,time.time())).fetchall()
            with self.target_lock:
                self.timer_targets={k:v for k,v in self.timer_targets.items() if v[0]>time.time()}
                if len(self.timer_targets)>=256:self.timer_targets.pop(next(iter(self.timer_targets)))
                self.timer_targets[self.timer_scope(req)]=(time.time()+120,[r['id'] for r in rows[:5]])
            if native:
                listed=[{'timer_id':row['id'],'state':row['status'],
                    'remaining_ms':max(0,round((row['deadline']-time.time())*1000)) if row['status']=='running' else 0} for row in rows[:5]]
                answer=('Твои таймеры: '+'; '.join(str(i+1)+': '+('завершён' if row['status']=='expired' else
                    'осталось '+duration_text(max(1,int(row['deadline']-time.time())))) for i,row in enumerate(rows[:5]))+'.') if rows else 'У тебя нет текущих таймеров.'
                if len(rows)>5:answer+=' Показаны первые пять из '+str(len(rows))+'.'
                return ToolResult(answer,evidence={'method':'timer_state','verified':True,'canonical_answer':answer,
                    'active_count':sum(row['status']=='running' for row in rows),'current_count':len(rows),
                    'timer_ids':[row['id'] for row in rows[:5]],'timers':listed})
            answer=('Таймеры по ближайшему срабатыванию: '+'; '.join(str(i+1)+': '+duration_text(max(1,int(row['deadline']-time.time()))) for i,row in enumerate(rows[:5]))+'.') if rows else 'У тебя нет активных таймеров.'
            return ToolResult(answer,evidence={'method':'timer_state','verified':True,'canonical_answer':answer,'active_count':len(rows),
                'timer_ids':[r['id'] for r in rows[:5]]})
        if tool=='quick_clarify':
            missing=slots.get('missing_slots',[])
            if missing==['domain']:answer='К какой задаче относится эта дата? Например, к прогнозу погоды?'
            elif missing==['duration_unit']:
                self.memory.set_pending(req,'timer_duration',{'quantity':slots.get('duration','')})
                answer='Это секунды, минуты или часы? Уточни длительность таймера с единицей времени.'
            else:answer='Уточни одну команду таймеру: одну длительность без альтернатив или конкретный таймер для отмены.' if slots.get('intent','').startswith('timer_') and slots.get('intent')!='timer_or_stopwatch' else 'Нужен таймер с длительностью или секундомер? Секундомер пока не подключён.'
            return ToolResult(answer,evidence={'needs_parameters':True,'missing_slots':missing,'reason':slots.get('reason') or 'parameters_required'})
        if tool=='quick_help':return ToolResult('Могу назвать время и дату, поставить и показать таймер, проверить погоду и дневной прогноз до 16 дней, перевести единицы или посчитать проценты. Фото и эксперты доступны через разрешённые серверные каналы. Личная история требует подключённого и подтверждённого доступа; в гостевом Live личный архив закрыт.')
        if tool=='calculator':
            try:
                value=calculate(arithmetic_expression(req.text));return ToolResult('Получается '+value+'.',evidence={'method':'calculator','verified':True,'canonical_answer':value})
            except Exception:return ToolResult('Не удалось надёжно выполнить этот расчёт в заданных ограничениях. Уточни выражение.',evidence={'abstained':True})
        if tool=='verification':return ToolResult('Для надёжного ответа требуется проверенный источник. Сейчас подходящий инструмент проверки не подключён, поэтому я не буду выдавать предположение за установленный факт.',evidence={'abstained':True})
        if tool=='file_permission':return ToolResult('Доступ к файлам и командам компьютера не разрешён. Можно обсудить задачу текстом; для работы с файлами нужна отдельная настройка прав и подтверждение владельца.')
        if tool=='home':return ToolResult('Это управление домом ещё не подключено или не разрешено. Команда устройствам не отправлена.')
        if tool=='control':return ToolResult('Остановлено.' if text in {'стоп','остановись','отмена','хватит','отмени'} else 'Сейчас нет действия, ожидающего подтверждения.')
        if tool=='memory':
            if not req.remember:return self.working_memory(req)
            if not req.device_id.startswith('personal:'):return ToolResult('Для персональной истории сначала подтверди профиль PIN-кодом в разделе «Семья».',evidence={'abstained':True})
            if re.search(r'недел|за (?:семь|7) дней',text):
                rows=self.memory.archive.period(req.device_id,time.time()-7*86400,time.time())
            else:rows=self.memory.archive.search(req.device_id,req.text,5)
            rows=[r for r in rows if self.memory.archive.source(req.device_id,r['message_id']) is not None]
            if rows:
                answer='По сохранённым исходным сообщениям: '+'; '.join('[сообщение '+str(row['message_id'])+'] '+row['content'] for row in rows)
                return ToolResult(answer,evidence={'method':'memory_source','verified':True,'canonical_answer':rows[0]['content'],'source_message_ids':[r['message_id'] for r in rows]})
            with self.memory.connect() as c:
                if 'как меня зовут' in text:
                    row=c.execute('SELECT name FROM family_profiles WHERE id=?',(req.device_id.split(':',1)[1],)).fetchone()
                    return ToolResult('Тебя зовут '+row[0]+'.',evidence={'method':'memory_source','verified':True,'canonical_answer':row[0]}) if row else ToolResult('Профиль не найден.',evidence={'abstained':True})
                if not re.search(r'последн|вчера.*спрашивал|что я.*спрашивал',text):return ToolResult('Подходящий оригинал разговора не найден. Уточни тему или время; я не буду восстанавливать цитату по догадке.',evidence={'abstained':True})
                row=c.execute("SELECT m.content FROM messages m JOIN archive_messages a ON a.message_id=m.id WHERE a.owner=? AND a.namespace='production' AND a.status='completed' AND m.role='user' AND m.turn_id!=? ORDER BY m.id DESC LIMIT 1",(req.device_id,req.turn_id)).fetchone()
                return ToolResult('В сохранённой истории последний вопрос был: '+row[0],evidence={'method':'memory_source','verified':True,'canonical_answer':row[0]}) if row else ToolResult('В твоей сохранённой истории пока нет предыдущих вопросов.',evidence={'abstained':True})
        if tool=='timer':
            if slots.get('operation')=='cancel':return self.cancel_timer(req,slots.get('target',''),action_id=action_id,is_current=is_current)
            seconds=slots.get('seconds')
            if seconds is None:
                if self.native_timer_action(action_id):self.native_timer_pending(req,action_id,is_current)
                else:self.memory.set_pending(req,'timer_duration')
                return ToolResult('На сколько минут или секунд поставить таймер?',evidence={'method':'timer_state','executed':False,'needs_parameters':True,'missing_slots':['duration']})
            if slots.get('status') not in {None,'validated'}:return ToolResult('Уточни одну длительность таймера без альтернатив и дополнительных команд.')
            if not 1<=seconds<=86400:return ToolResult('Таймер можно поставить на время от одной секунды до суток.')
            return self.start_timer_once(req,seconds,action_id,is_current=is_current)
        return ToolResult('Нужное действие пока не настроено.')

    @staticmethod
    def native_timer_action(action_id):
        return isinstance(action_id,str) and action_id.startswith('native-timer:')

    def native_timer_pending(self,req,action_id,is_current):
        if action_id!='native-timer:'+req.turn_id or not callable(is_current):raise PermissionError('current_user_command_required')
        self.timers._current(is_current)
        pending=self.memory.set_pending(req,'timer_duration')
        try:self.timers._current(is_current)
        except PermissionError:
            self.memory.settle_pending(req,'cancelled',pending['id'])
            raise

    def start_timer_once(self,req,seconds,action_id=None,*,is_current=None):
        """An explicit logical action ID, never text/argument similarity, deduplicates."""
        if self.native_timer_action(action_id):
            if action_id!='native-timer:'+req.turn_id or not callable(is_current):raise PermissionError('current_user_command_required')
            result=self.timers.start(req,seconds,action_id=action_id,is_current=is_current)
            if not result['executed']:
                answer='У тебя уже 16 текущих таймеров. Убери завершённые или отмени ненужные, затем поставь новый.'
                return ToolResult(answer,evidence={'method':'timer_state','verified':True,'canonical_answer':answer,**result})
            self.clear_timer_context(req);self.memory.settle_pending(req,'completed')
            return ToolResult('Таймер запущен на '+duration_text(result['duration_seconds'])+'.',
                widget={'type':'custom','payload':{'namespace':'gobot.ui','version':1,'command':'timer.start',
                    'duration_ms':result['duration_seconds']*1000,'timer_id':result['timer_id'],'deadline':result['deadline']}},
                evidence={'method':'timer_state','verified':True,**result})
        if type(seconds) not in (int,float) or not 1<=seconds<=86400:raise ValueError('invalid_timer_duration')
        digest=hashlib.sha256(json.dumps([seconds,req.conversation_id,req.client_id,req.profile_epoch]).encode()).hexdigest()
        with self.memory.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            old=c.execute('SELECT payload_hash,result FROM timer_action_receipts WHERE owner=? AND action=?',(req.device_id,action_id)).fetchone() if action_id else None
            if old:
                if old['payload_hash']!=digest:raise ValueError('action_payload_conflict')
                return ToolResult(**json.loads(old['result']))
            ident=str(uuid4());deadline=time.time()+seconds
            c.execute("INSERT INTO timers VALUES(?,?,?,?,'running')",(ident,req.device_id,req.conversation_id,deadline))
            widget={'type':'custom','payload':{'namespace':'gobot.ui','version':1,'command':'timer.start','duration_ms':seconds*1000,'timer_id':ident,'deadline':deadline}}
            data={'text':'Таймер запущен на '+duration_text(seconds)+'.','widget':widget,
                'evidence':{'method':'timer_state','verified':True,'timer_id':ident,'duration_seconds':seconds,'deadline':deadline}}
            if action_id:c.execute('INSERT INTO timer_action_receipts VALUES(?,?,?,?)',(req.device_id,action_id,digest,json.dumps(data)))
        self.clear_timer_context(req);self.memory.settle_pending(req,'completed')
        return ToolResult(**data)

    def cancel_timer(self,req,target,*,action_id=None,is_current=None):
        if self.native_timer_action(action_id):
            if action_id!='native-timer:'+req.turn_id or not callable(is_current):raise PermissionError('current_user_command_required')
            snapshot=self.timer_context(req)
            result=self.timers.cancel(req,target,listed_ids=snapshot.get('timer_list_ids',()),
                action_id=action_id,is_current=is_current)
            if result['executed']:
                self.clear_timer_context(req)
                answer='Все твои текущие таймеры убраны.' if self.timers._target(target)=='all' else 'Выбранный таймер убран.'
                return ToolResult(answer,evidence={'method':'timer_state','verified':True,'canonical_answer':answer,**result})
            if result['reason']=='no_active_timers':
                return ToolResult('У тебя нет текущих таймеров.',evidence={'method':'timer_state','verified':True,**result})
            return ToolResult('Сначала попроси показать таймеры, затем назови номер из списка; можно явно сказать «все таймеры».',
                evidence={'method':'timer_state','needs_parameters':True,'missing_slots':['timer_id'],**result})
        # Numbering is explicitly shown by the status result: increasing deadline.
        with self.memory.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            rows=c.execute("""SELECT t.id,t.deadline FROM timers t LEFT JOIN timer_bindings b ON b.timer_id=t.id
                WHERE t.device_id=? AND b.scope_key IS NULL AND t.status='running'
                AND t.deadline>? ORDER BY t.deadline,t.id""",(req.device_id,time.time())).fetchall()
            value=' '.join(target.lower().split())
            if not rows:return ToolResult('У тебя нет активных таймеров.')
            if value in {'все','все мои','мои все'}:selected=rows
            elif value in {'','мой'}:selected=rows if len(rows)==1 else []
            else:
                ordinal={'первый':1,'второй':2,'третий':3,'четвертый':4,'пятый':5}
                index=ordinal.get(value)
                if index is None and re.fullmatch(r'№?\d+',value):index=int(value.lstrip('№'))
                if index:
                    with self.target_lock:snapshot=self.timer_targets.get(self.timer_scope(req))
                    ident=snapshot[1][index-1] if snapshot and snapshot[0]>time.time() and 0<index<=len(snapshot[1]) else None
                    selected=[r for r in rows if r['id']==ident]
                else:selected=[r for r in rows if r['id']==value]
            if not selected:return ToolResult('Сначала попроси показать таймеры, затем назови номер из списка; можно указать идентификатор или явно сказать «все таймеры».',
                evidence={'method':'timer_state','needs_parameters':True,'missing_slots':['timer_id'],'reason':'timer_selection_required'})
            for row in selected:c.execute("UPDATE timers SET status='cancelled' WHERE id=? AND device_id=? AND status='running'",(row['id'],req.device_id))
        answer='Все твои активные таймеры остановлены.' if value in {'все','все мои','мои все'} else 'Выбранный таймер остановлен.'
        return ToolResult(answer,evidence={'method':'timer_state','verified':True,'canonical_answer':answer,'timer_cancelled_ids':[row['id'] for row in selected]})

    def execute_timer_action(self,req,operation,duration_text=None,target='only',ordinal=None,*,action_id=None,is_current=None):
        """Native semantic action: original user text, server scope and turn ID.

        The conversational model interprets intent; it cannot supply a rewritten
        request, owner, or approval. A normalized duration is accepted only when
        independently verified against the complete server-owned utterance.
        """
        if operation not in ('start','status','cancel') or target not in ('only','all','ordinal'):
            raise ValueError('invalid_timer_action')
        if action_id!='native-timer:'+req.turn_id:raise PermissionError('timer_action_id_required')
        if operation!='status' and not callable(is_current):raise PermissionError('current_user_command_required')
        self.timers._current(is_current)
        value=' '.join(req.text.casefold().replace('ё','е').split())
        verbs=r'(?:став\w*|постав\w*|установ\w*|запус\w*|запуст\w*|включ\w*|засек\w*|отсч\w*)' if operation=='start' else r'(?:отмен\w*|остан\w*|выключ\w*|убер\w*)'
        if operation!='status' and (re.search(r'\b(?:не|нельзя)(?:\s+(?:надо|нужно|следует))?\s+'+verbs+r'\b',value) or
                re.match(r'^(?:(?:софия|гобот)[, ]+)?(?:если\b|допустим\b|представь\b|что\s+(?:будет|случится)\b|(?:что|как)\s+(?:значит|означает|поставить|установить)|(?:расскажи|объясни)[, ]+как|(?:он|она|они)\s+(?:сказал\w*|попросил\w*|написал\w*)\b|(?:повтори|процитируй)\b)',value)):
            raise PermissionError('current_user_command_required')
        if operation=='status':
            if duration_text is not None or target!='only' or ordinal is not None:raise ValueError('invalid_timer_action')
            return self.execute('timer_status',req,action_id=action_id,is_current=is_current)
        if operation=='start':
            if target!='only' or ordinal is not None:raise ValueError('invalid_timer_action')
            from .timer_duration import source_timer_seconds,is_timer_duration_reply,semantic_timer_seconds
            if is_timer_duration_reply(req.text):
                pending=self.memory.context(req).get('pending_action')
                if not pending or pending.get('kind')!='timer_duration' or pending.get('expires',0)<=time.time():
                    raise PermissionError('current_user_command_required')
            if duration_text is None:
                # The current transcript can already contain a complete duration
                # even when the model forgot its optional argument.
                seconds=semantic_timer_seconds(req.text)
                if seconds is None:
                    self.native_timer_pending(req,action_id,is_current)
                    return ToolResult('На сколько минут или секунд поставить таймер?',
                        evidence={'method':'timer_state','executed':False,'needs_parameters':True,'missing_slots':['duration']})
            else:
                seconds=source_timer_seconds(req.text,duration_text)
            if seconds is None or not 1<=seconds<=86400:raise ValueError('invalid_timer_duration')
            return self.start_timer_once(req,seconds,action_id,is_current=is_current)
        if duration_text is not None:raise ValueError('invalid_timer_action')
        if any(char in req.text for char in '«»“”"'):raise PermissionError('current_user_command_required')
        names={1:'первый',2:'второй',3:'третий',4:'четвертый',5:'пятый'}
        has_all=bool(re.search(r'\bвсе\b',value))
        mentioned=[index for index,word in names.items() if re.search(r'(?<!\w)(?:'+word+'|'+str(index)+r')(?!\w)',value)]
        if target=='all':
            if not has_all or ordinal is not None:raise PermissionError('timer_target_source_mismatch')
            selected='все'
        elif target=='ordinal':
            if type(ordinal) is not int or ordinal not in names or mentioned!=[ordinal] or has_all:raise PermissionError('timer_target_source_mismatch')
            selected=str(ordinal)
        else:
            if ordinal is not None or has_all or mentioned:raise PermissionError('timer_target_source_mismatch')
            selected=''
        return self.cancel_timer(req,selected,action_id=action_id,is_current=is_current)

async def text_stream(text):
    yield text
