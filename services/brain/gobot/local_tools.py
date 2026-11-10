import re,time
from uuid import uuid4
from dataclasses import dataclass
from .quality import calculate,arithmetic_expression
from .timer_duration import timer_seconds,duration_text

@dataclass
class ToolResult:
    text:str
    widget:dict|None=None
    evidence:dict|None=None

class LocalTools:
    def __init__(self,memory):
        self.memory=memory
        with memory.connect() as c:c.execute('''CREATE TABLE IF NOT EXISTS timers(id TEXT PRIMARY KEY,device_id TEXT,conversation_id TEXT,deadline REAL,status TEXT)''')
    def execute(self,tool,req):
        text=req.text.lower()
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
            if re.search(r'отмени|останови|выключи',text):
                with self.memory.connect() as c:c.execute("UPDATE timers SET status='cancelled' WHERE device_id=? AND status='running'",(req.device_id,))
                return ToolResult('Твои активные таймеры остановлены.')
            seconds=timer_seconds(text)
            if seconds is None:
                if req.remember:
                    with self.memory.connect() as c:
                        c.execute("UPDATE pending_actions SET status='superseded' WHERE owner=? AND conversation_id=? AND status='pending'",(req.device_id,req.conversation_id))
                        c.execute("INSERT INTO pending_actions VALUES(?,?,?,'timer_duration','{}',?,'pending')",(str(uuid4()),req.device_id,req.conversation_id,time.time()+120))
                return ToolResult('На сколько минут или секунд поставить таймер?')
            if not 1<=seconds<=86400:return ToolResult('Таймер можно поставить на время от одной секунды до суток.')
            ident=str(uuid4());deadline=time.time()+seconds
            with self.memory.connect() as c:
                c.execute("INSERT INTO timers VALUES(?,?,?,?,'running')",(ident,req.device_id,req.conversation_id,deadline))
                c.execute("UPDATE pending_actions SET status='completed' WHERE owner=? AND conversation_id=? AND kind='timer_duration' AND expires>? AND status='pending'",(req.device_id,req.conversation_id,time.time()))
            widget={'type':'custom','payload':{'namespace':'gobot.ui','version':1,'command':'timer.start','duration_ms':seconds*1000,'timer_id':ident,'deadline':deadline}}
            return ToolResult('Таймер запущен на '+duration_text(seconds)+'.',widget)
        return ToolResult('Нужное действие пока не настроено.')

async def text_stream(text):
    yield text
