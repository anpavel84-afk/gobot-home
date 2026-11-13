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
        with memory.connect() as c:c.execute('''CREATE TABLE IF NOT EXISTS timers(id TEXT PRIMARY KEY,device_id TEXT,conversation_id TEXT,deadline REAL,status TEXT)''')
        with memory.connect() as c:c.execute('CREATE TABLE IF NOT EXISTS timer_action_receipts(owner TEXT,action TEXT,payload_hash TEXT,result TEXT,PRIMARY KEY(owner,action))')
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
    def execute(self,tool,req,slots=None):
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
            with self.memory.connect() as c:rows=c.execute("SELECT id,deadline FROM timers WHERE device_id=? AND status='running' AND deadline>? ORDER BY deadline,id",(req.device_id,time.time())).fetchall()
            with self.target_lock:
                self.timer_targets={k:v for k,v in self.timer_targets.items() if v[0]>time.time()}
                if len(self.timer_targets)>=256:self.timer_targets.pop(next(iter(self.timer_targets)))
                self.timer_targets[self.timer_scope(req)]=(time.time()+120,[r['id'] for r in rows[:5]])
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
            if slots.get('operation')=='cancel':return self.cancel_timer(req,slots.get('target',''))
            seconds=slots.get('seconds')
            if seconds is None:
                self.memory.set_pending(req,'timer_duration')
                return ToolResult('На сколько минут или секунд поставить таймер?',evidence={'method':'timer_state','needs_parameters':True,'missing_slots':['duration']})
            if slots.get('status') not in {None,'validated'}:return ToolResult('Уточни одну длительность таймера без альтернатив и дополнительных команд.')
            if not 1<=seconds<=86400:return ToolResult('Таймер можно поставить на время от одной секунды до суток.')
            return self.start_timer_once(req,seconds)
        return ToolResult('Нужное действие пока не настроено.')

    def start_timer_once(self,req,seconds,action_id=None):
        """An explicit logical action ID, never text/argument similarity, deduplicates."""
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

    def cancel_timer(self,req,target):
        # Numbering is explicitly shown by the status result: increasing deadline.
        with self.memory.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            rows=c.execute("SELECT id,deadline FROM timers WHERE device_id=? AND status='running' AND deadline>? ORDER BY deadline,id",(req.device_id,time.time())).fetchall()
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

async def text_stream(text):
    yield text
