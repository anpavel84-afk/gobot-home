"""Offline image-query planning. Dictionary lookup is not an LLM translator."""
import json,re,unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from .speech_formatter import morphology

DICTIONARY=Path(__file__).resolve().parents[3]/'vendor/dictionaries/rus-eng.json'
VERSION='freedict-rus-eng-2025.11.23-v1'
# Reviewed physical-object senses override polysemy or gaps in the source data.
ALIASES={'кот':'cat','кошка':'cat','собака':'dog','пес':'dog','орхидея':'orchid',
 'подсолнух':'sunflower','роза':'rose','яблоко':'apple','тигр':'tiger','слон':'elephant',
 'жираф':'giraffe','береза':'birch tree','лабрадор':'labrador retriever','курица':'chicken',
 'пончик':'doughnut','красный':'red','черный':'black',
 'белый':'white','синий':'blue','голубой':'light blue','зеленый':'green',
 'желтый':'yellow','шоколадный':'chocolate',
 'черный лабрадор':'black labrador retriever',
 # Reviewed names: https://parrots.org/encyclopedia/sun-conure/
 'солнечная аратинга':'sun conure','солнечные аратинги':'sun conure'}

def phrase_lemmas(value):
    return tuple(normal(morphology().parse(word)[0].normal_form) if re.search('[а-яё]',word) else word
                 for word in re.findall(r'[\w-]+',normal(value)))

@lru_cache(maxsize=1)
def reviewed_phrase_forms():
    result={}
    for phrase in ALIASES:
        if ' ' in phrase:result.setdefault(phrase_lemmas(phrase),phrase)
    return result

def canonical_subject(value):
    """Normalize inflection against reviewed phrases without dropping modifiers."""
    clean=normal(value)
    if clean in ALIASES:return clean
    return reviewed_phrase_forms().get(phrase_lemmas(clean),value)

def subject_matches_caption(query,caption):
    """Metadata relevance gate; this is not pixel-level species verification."""
    names=list(ImageQueryPlanner().plan(query).terms)
    if any(normal(name)=='sun conure' for name in names):names.append('Aratinga solstitialis')
    words=set(re.findall(r'[a-zа-яё0-9]+',normal(caption)))
    for name in names:
        required=set(re.findall(r'[a-zа-яё0-9]+',normal(name)))-{'the','a','of'}
        if required and required<=words:return True
    return False

def caption_names_subject(query,caption):
    """Automatic scenes need a subject label. An instrument named in a headline
    can just be the instrument that took a picture of something else."""
    names={normal(name) for name in ImageQueryPlanner().plan(query).terms}
    title=normal(caption)
    title=re.sub(r'^(?:dsc|img|pxl)[_ -]?\d+\s*[-:–—]?\s*','',title)
    label=re.split(r'\s+[(]|\s+[·|]|\s+[-–—]\s+',title,maxsplit=1)[0].strip()
    return label in names

def normal(value):return unicodedata.normalize('NFC',value.replace('\u0301','')).casefold().replace('ё','е').strip()

@lru_cache(maxsize=1)
def installed_entries():
    try:
        if DICTIONARY.stat().st_size>8_000_000:return {}
        value=json.loads(DICTIONARY.read_text(encoding='utf-8'))
        if value.get('version')!='FreeDict/WikDict rus-eng 2025.11.23':return {}
        return value['entries'] if isinstance(value.get('entries'),dict) else {}
    except (OSError,ValueError):return {}

@dataclass(frozen=True)
class ImageQueryPlan:
    terms:tuple[str,...]
    basis:str
    ambiguous:bool=False

class ImageQueryPlanner:
    def __init__(self,entries=None):self.entries=entries
    def plan(self,query):
        original=' '.join(query.split())[:180];clean=normal(original)
        entries=self.entries if self.entries is not None else installed_entries()
        if not re.search('[а-я]',clean):return ImageQueryPlan((original,),'original')
        def translation(word):
            if word in ALIASES:return ALIASES[word],False
            row=entries.get(word,{})
            senses=row.get('senses',[])
            if len(senses)>1:return None,True
            term=senses[0][0] if senses and senses[0] else None
            return (term if isinstance(term,str) and re.fullmatch(r"[A-Za-z][A-Za-z '-]{0,79}",term) else None),False
        translated,ambiguous=translation(normal(canonical_subject(clean)))
        if translated:return ImageQueryPlan((translated,original),'local_dictionary')
        if ambiguous:return ImageQueryPlan((original,),'ambiguous_dictionary',True)
        # Preserve every modifier: if any word is unknown, do not drop it to get hits.
        tokens=re.findall(r"[\w-]+",clean);output=[]
        if not tokens or len(tokens)>12:return ImageQueryPlan((original,),'original')
        for token in tokens:
            if not re.search('[а-я]',token):output.append(token);continue
            term,ambiguous=translation(token)
            if not term and not ambiguous:
                parsed=morphology().parse(token)
                for form in parsed:
                    if form.tag.POS not in {'NOUN','ADJF'}:continue
                    lemma=normal(form.normal_form)
                    if lemma in entries or lemma in ALIASES:
                        term,ambiguous=translation(lemma);break
            if not term:return ImageQueryPlan((original,),'ambiguous_dictionary' if ambiguous else 'original',ambiguous)
            output.append(term)
        translated=' '.join(output)
        # Punctuation other than hyphens is meaningful (e.g. names, relations).
        if re.sub(r'[\w\s-]','',clean):return ImageQueryPlan((original,),'original')
        return ImageQueryPlan((translated,original),'local_dictionary')
