"""Conservative local topic-frame diagnostic, not ASR ground truth or factual verification."""
import re
from .speech_formatter import morphology

def superlative_frame(text):
    words=re.findall(r'[А-Яа-яЁё]+',text[:450])
    morph=morphology()
    for i,word in enumerate(words):
        lemmas={p.normal_form for p in morph.parse(word)}
        if not lemmas&{'самый','наиболее','наименее'}:continue
        if i and words[i-1].casefold()=='не':continue
        adjectives=[]
        for token in words[i+1:i+5]:
            parsed=morph.parse(token)
            adj=next((p for p in parsed if p.tag.POS in {'ADJF','ADJS'}),None)
            noun=next((p for p in parsed if p.tag.POS=='NOUN'),None)
            if adj and (not noun or parsed[0].tag.POS in {'ADJF','ADJS'}):adjectives.append(adj.normal_form)
            elif noun and adjectives:return frozenset(adjectives),noun.normal_form
            else:break
    return None

def alignment(query,answer):
    """Only repeated superlative descriptors with a changed noun raise a warning.

    Different heads can still be related (mountain/volcano); never auto-rewrite speech.
    Missing frames, synonyms and general paraphrases remain unknown, not mismatches.
    """
    requested=superlative_frame(query);spoken=superlative_frame(answer)
    if not requested or not spoken:return None
    if requested[1]==spoken[1]:return 'match'
    if requested[0]==spoken[0]:return 'suspected_mismatch'
    return None
