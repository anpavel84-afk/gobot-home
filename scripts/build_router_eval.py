"""Versioned synthetic policy evaluation: labels authored independently of router output."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def build():
    facts=['Как звали главного героя фильма «Титаник»?','Почему небо голубое?','Сколько ног у паука?','Что такое радуга?','Почему тает лёд?','Кто написал «Евгения Онегина»?','Что такое электричество?','Как растёт дерево?','Почему кошки мурлычут?','Что такое материк?']
    dialogue=['Привет','Как дела?','Спасибо за помощь','Расскажи сказку','Придумай историю про кота','Объясни ребёнку дружбу','Пожелай доброго утра','Расскажи о временах года','Посоветуй занятие без экрана','Давай поговорим о космосе']
    follow=['А почему?','Объясни подробнее','А что дальше?','Продолжи объяснение','Приведи пример','А если наоборот?','Расскажи проще','А детям это понятно?','Можно подробнее про этот пример?','А какие есть варианты?']
    rare=['Кто был вторым помощником капитана малоизвестного судна?','Назови точную дату открытия редкой рукописи','Мне нужны источники для редкого исторического факта','Уточни биографию малоизвестного моряка','Дай ссылку на оригинал исторической записи']
    current=['Какая погода сейчас?','Кто сейчас руководит этой компанией?','Какой курс доллара?','Расскажи последние новости','Какие актуальные цены на продукты?']
    risks=['Какое лекарство дать ребёнку?','Как рассчитать дозировку лекарства?','Стоит инвестировать все сбережения?','Что делать при утечке газа?','Как заменить электропроводку?']
    memory=['Что мы решили по поводу моей теплицы?','Что мы обсуждали за неделю?','Что я вчера спрашивал?','Верни мой прошлый разговор','Какие мои предпочтения?']
    reason=['Сравни три технические архитектуры','Докажи математическое утверждение','Объясни дифференциальное уравнение','Подготовь подробный технический анализ','Рассмотри оптимизацию распределённой системы']
    files=['Исправь ошибку в моём проекте','Проверь код моего проекта','Проанализируй локальный репозиторий','Измени файлы моего проекта','Удали файл в репозитории']
    data=[]
    def add(category,text,expected,verification=False,gold=None,context=None):
        data.append({'id':f'{category}-{len(data)+1:03d}','synthetic':True,'category':category,'text':text,'context':context or {},'expected':expected,'verification_required':verification,'reference_answer':gold,'quality_criteria':['No unsupported factual claims','No unapproved expensive escalation','Preserve relevant context and access scope'],'reference_kind':'deterministic' if gold is not None else 'policy_label_not_answer_gold'})
    for i in range(20):
        suffix='' if i<10 else ' Объясни простыми словами.'
        variant=['',' Объясни для семьи.',' Ответь кратко.',' Укажи ограничения.'][i//5]
        add('common_fact',facts[i%10]+suffix,'flash',gold='Джек Доусон' if i%10==0 else None)
        add('dialogue',dialogue[i%10]+suffix,'flash')
        add('follow_up',follow[i%10]+suffix,'flash',context={'summary':'Активная тема: радуга и солнечный свет.'})
        add('rare_fact',rare[i%5]+variant,'verification',True)
        add('current_information',current[i%5]+variant,'visual' if i%5==0 else 'verification',True)
        add('high_consequence',risks[i%5]+variant,'verification',True)
        add('personal_memory',memory[i%5]+variant,'memory',True)
        add('reasoning',reason[i%5]+variant,'reasoning')
        add('file_action',files[i%5]+variant,'file_permission')
        add('calculator',f'Сколько будет {127+i} × 43?','calculator',True,str((127+i)*43))
        add('timer',f'Поставь таймер на {i+1} минут','timer')
        add('explicit_model',('Спроси Codex, как он думает об этом' if i%2==0 else 'Спроси Antigravity, как он думает об этом')+' Тема: '+facts[i//2],'codex' if i%2==0 else 'argon')
    path=ROOT/'tests/fixtures/quality-router.json';path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({'description':'240 synthetic policy cases; repeated phrasings are intentional; not real-user/model correctness results','cases':data},ensure_ascii=False,indent=2),encoding='utf-8')
    print('Wrote',len(data),'synthetic policy cases')
if __name__=='__main__':build()
