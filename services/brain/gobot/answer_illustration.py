"""Recover a presentation from this exchange only. Private answer maps stay in the UI event."""
import re

from .presentation import Presentation,VisualMetadata,frame_id
from .speech_formatter import morphology

SOCIAL = re.compile(
    r'(?:(?:ну|гобот|го-бот|слушай|привет|здравствуй(?:те)?|спасибо|пожалуйста|пока|'
    r'доброе утро|добрый (?:день|вечер)|спокойной ночи|как дела|да|нет|ладно|хорошо|окей|ок)'
    r'[\s,.!?—-]*)+', re.I)
def social(text):
    return bool(SOCIAL.fullmatch(text.strip()))


def answer_labels(question,answer):
    """Short noun phrases as written in the answer, ordered by salience, not inferred relations."""
    morph=morphology()
    parsed={}
    def parse(word):
        key=word.casefold()
        if key not in parsed:parsed[key]=morph.parse(key)[0]
        return parsed[key]
    ignored={'вопрос','ответ','случай','пример','дело','способ','часть','суть','пожалуйста','сведение'}
    question_words={parse(word).normal_form for word in re.findall(r'[А-Яа-яЁёA-Za-z]+',question[:300])}
    candidates={}
    pattern=r'[А-Яа-яЁёA-Za-z]+(?:-[А-Яа-яЁёA-Za-z]+)*'
    previous=None
    for match in re.finditer(pattern,answer[:1200]):
        word=match.group();form=parse(word)
        if form.tag.POS=='NOUN' and len(word)>2 and form.normal_form not in ignored:
            label=word
            if previous and answer[previous.end():match.start()]==' ' and parse(previous.group()).tag.POS=='ADJF':
                label=answer[previous.start():match.end()]
            if len(label)<=36:
                rank=(form.normal_form not in question_words,match.start())
                candidates.setdefault(form.normal_form,(rank,label))
        previous=match
    return [label for _,label in sorted(candidates.values())[:3]]


def answer_map(req,answer):
    labels=answer_labels(req.text,answer)
    if not labels:
        # Numeric and very short answers have no noun phrases.
        labels=[' '.join(answer.split())[:48]]
    return Presentation(id=frame_id(req.turn_id,'answer_map'),type='rich_answer',title='Карта ответа',
        text='',metadata=VisualMetadata(visual_strategy='render_local',backend='answer_map',
            reason='concepts_from_this_answer',diagram_labels=labels))
