"""Ready local Vosk adapter; fail closed for missing pronunciations/vocabulary.
No model download, training, fallback, room recording, or cloud calls at runtime.
"""
import json,re
from pathlib import Path
from host_wake_core import Detection
WAKE_WORDS=('гобот','габот')
STOP_WORD='гоп'
class VocabularyUnavailable(ValueError):pass

class PartialMatcher:
    """Exact first-token stable partial; a candidate policy, not household acceptance."""
    def __init__(self):self.reset()
    def reset(self):self.previous=None;self.stability=0;self.fired=False
    def feed(self,text,*,speaking,final=False):
        words=re.findall(r'[а-яё]+',text.casefold())
        allowed=(STOP_WORD,) if speaking else WAKE_WORDS
        candidate=words[0] if words and words[0] in allowed else None
        self.stability=self.stability+1 if candidate and candidate==self.previous else 1
        self.previous=candidate;event=None
        if candidate and not self.fired and self.stability>=2:
            self.fired=True;event=Detection('stop' if speaking else 'wake')
        if final:self.reset()
        return event

class VoskDetector:
    def __init__(self,model_path):
        from vosk import Model,KaldiRecognizer,SetLogLevel
        path=Path(model_path).resolve()
        if not path.is_dir():raise ValueError('local_model_required_no_download')
        SetLogLevel(-1)
        self.model=Model(str(path))
        self.word_ids={w:self.model.vosk_model_find_word(w) for w in (*WAKE_WORDS,STOP_WORD)}
        missing=[w for w,ident in self.word_ids.items() if ident<0]
        if missing:raise VocabularyUnavailable('required_wake_vocabulary_missing:'+','.join(missing))
        # Full language decoder, not a sole forced wake hypothesis or fuzzy alias.
        self.recognizer=KaldiRecognizer(self.model,16000)
        self.recognizer.SetWords(True);self.recognizer.SetPartialWords(True)
        self.matcher=PartialMatcher()
    def feed(self,pcm,*,speaking):
        final=self.recognizer.AcceptWaveform(pcm)
        result=json.loads(self.recognizer.Result() if final else self.recognizer.PartialResult())
        return self.matcher.feed(result.get('text' if final else 'partial',''),speaking=speaking,final=bool(final))
    def reset(self):self.recognizer.Reset();self.matcher.reset()
