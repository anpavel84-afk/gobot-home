"""Bounded local noun-phrase resolution. Dictionaries enrich search, never gate it.

This is a morphological heuristic, not a semantic model or a probability estimate.
Only public phrases are eligible for external lookup; all results still need grounding.
"""
import re
from .speech_formatter import morphology

GENERIC={'вопрос','ответ','вид','род','герой','персонаж','порода','разновидность','пример',
         'размер','цвет','год','месяц','день','время','жизнь','пожалуйста','смысл',
         'отличие','разница','помощь','факт','подробность','продолжение','сведение'}
VAGUE={'обычный','такой','какой','другой','этот','интересный','новый','некоторый'}
FOLLOWUP=re.compile(r'^(?:а\s+)?(?:расскажи\s+)?(?:ещ[её]|продолж|подробн)|\b(?:об этом|о н[её]м|о ней|до не[её]|почему он[аои]?)\b',re.I)

def noun_phrase(text,*,answer=False):
    """Keep attributive adjectives and genitive dependents, independent of vocabulary.

    The first content clause is preferred. No arbitrary word from the end of an
    answer, suggestions for future topics, full questions or instructions leave host.
    """
    text=text.strip()[:450]
    if answer:
        text=re.split(r'[.!?…\n]',text,maxsplit=1)[0]
        if re.search(r'\b(?:хочешь|можем поговорить|могу рассказать|не знаю|не удалось)\b',text,re.I):return None
    else:
        text=re.sub(r'^(?:(?:гобот|слушай|подскажи|скажи|пожалуйста)[, !]+)+','',text,flags=re.I)
        text=re.sub(r'^(?:а\s+)?(?:расскажи|объясни|поговорим)(?:\s+мне)?\s+(?:о|об|про)\s+','',text,flags=re.I)
    morph=morphology();words=list(re.finditer(r'[А-Яа-яЁёA-Za-z]+(?:-[А-Яа-яЁёA-Za-z]+)*',text))
    forms=[]
    for match in words:
        parsed=morph.parse(match[0]);p=parsed[0]
        # Prefer the adjective interpretation of a substantivized adjective
        # when an immediately following noun can be its head.
        forms.append((match,p,parsed))
    for index,(match,head,variants) in enumerate(forms):
        if head.tag.POS!='NOUN' or head.normal_form in GENERIC:continue
        if any(p.tag.POS=='ADJF' for p in variants) and index+1<len(forms) and forms[index+1][1].tag.POS=='NOUN':continue
        if index:
            adjectives=[p for p in forms[index-1][2] if p.tag.POS=='ADJF']
            if adjectives:
                adj=adjectives[0]
                compatible=[p for p in variants if p.tag.POS=='NOUN' and p.tag.number==adj.tag.number
                            and (adj.tag.number=='plur' or p.tag.gender==adj.tag.gender) and p.tag.case==adj.tag.case]
                if compatible:head=compatible[0]
        if {'Name','Surn','Patr'}&head.tag.grammemes:continue
        if not re.search('[а-яё]',match[0],re.I):continue
        # A word inside a leading location adjunct is not the subject of
        # «В Бразилии растут ...». An explicit «расскажи о ...» was stripped above.
        if index and forms[index-1][1].tag.POS=='PREP' and forms[index-1][0][0].casefold() in {'в','на','при'}:continue
        prefix=[]
        for j in range(index-1,max(-1,index-4),-1):
            prev,form,alternatives=forms[j]
            adj=next((p for p in alternatives if p.tag.POS=='ADJF' and 'Apro' not in p.tag),None)
            if not adj or adj.normal_form in VAGUE or text[prev.end():forms[j+1][0].start()].strip():break
            agreement={'nomn','plur'} if 'Pltm' in head.tag else {'nomn','sing'}|({head.tag.gender} if head.tag.gender else set())
            inflected=adj.inflect(agreement)
            prefix.insert(0,inflected.word if inflected else adj.normal_form)
        nominal=head.inflect({'nomn','plur' if 'Pltm' in head.tag else 'sing'})
        label=' '.join([*prefix,nominal.word if nominal else head.normal_form])
        # Preserve dependent genitive noun groups: «система человека»,
        # «кольца Сатурна», «двигатель внутреннего сгорания».
        tail=[];pending=[];end=match.end()
        for dep,form,alternatives in forms[index+1:index+5]:
            if text[end:dep.start()].strip():break
            if form.tag.POS=='ADJF' and 'Apro' not in form.tag:pending.append(dep[0]);end=dep.end();continue
            genitive=next((p for p in alternatives if p.tag.POS=='NOUN' and 'gent' in p.tag),None)
            if not genitive or {'Name','Surn','Patr'}&genitive.tag.grammemes:break
            tail.extend([*pending,dep[0]]);pending=[];end=dep.end()
        phrase=' '.join([label,*tail]).casefold().replace('ё','е')
        if 2<=len(phrase)<=120 and len(phrase.split())<=8:return phrase
    # Public Latin multiword names use an explicit subject position, not a
    # dictionary. Arbitrary prose or codes cannot become a search query.
    latin=re.fullmatch(r'(?:what is |tell me about )?([A-Za-z][A-Za-z -]{1,70})[?.!]*',text,flags=re.I)
    if latin:return latin[1].strip()
    return None
