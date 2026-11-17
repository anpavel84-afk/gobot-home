"""Synthetic-only Russian Мо́ника wake training corpus, isolated from H0.

Reuses an EXISTING READ-ONLY CPU Piper/RHVoice/espeak installation from the
previous GoBot experiment. Generates NEW sample content under a new root.
No household recordings, no network/provider, no GPU, no H0 mutations.
"""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import os
import subprocess
import tempfile
from pathlib import Path
from math import gcd
import wave
import numpy as np
from scipy.signal import resample_poly

SEED = 20261117
SPLITS = {
    "denis":"train", "dmitri":"train", "anna":"train", "irina":"train",
    "espeak-ru":"train", "aleksandr":"validation", "elena":"test",
}
TARGET="Мо́ника"
# All positive sentences BEGIN with the intended name. A pause is not required
# before the following question: this is a single TTS utterance.
POS_TRAIN = [
 "Мо́ника", "Мо́ника!", "Мо́ника?", "Мо́ника, сколько сейчас времени?",
 "Мо́ника сколько сейчас времени", "Мо́ника, какая сегодня погода?",
 "Мо́ника какая погода за окном", "Мо́ника поставь таймер",
 "Мо́ника, включи музыку", "Мо́ника расскажи про звезды",
 "Мо́ника, открой календарь", "Мо́ника что приготовить на ужин",
 "Мо́ника, напомни мне про встречу", "Мо́ника завтра дождь?",
 "Мо́ника который час", "Мо́ника есть новости",
 "Мо́ника, помоги пожалуйста", "Мо́ника хорошего дня",
 "Мо́ника, расскажи сказку", "Мо́ника, останови музыку",
 "Эй Мо́ника, сколько времени", "Слушай Мо́ника, посмотри погоду",
]
POS_VALID = [
 "Мо́ника, куда мы поедем завтра?", "Мо́ника узнай температуру",
 "Мо́ника, что сегодня в календаре?", "Мо́ника открой прогноз",
 "Мо́ника сколько осталось времени", "Мо́ника, привет",
 "Мо́ника.", "Мо́ника когда рассвет", "Мо́ника спасибо",
]
POS_TEST = [
 "Мо́ника, включи лампу на кухне", "Мо́ника, можно тебя спросить?",
 "Мо́ника напомни полить цветы", "Мо́ника какой сегодня день",
 "Мо́ника, посоветуй книгу", "Мо́ника дай ответ",
 "Мо́ника!", "Мо́ника как дела", "Мо́ника, у нас гости",
]
# These are HARD negatives, deliberately containing confusable sound patterns.
# Some include a non-address mention of Monika. A model that triggers on the
# middle of an unrelated sentence is undesirable in always-on home use.
NEG_COMMON=[
 "Моник", "монитор", "Моня", "Монику", "Монике", "лимонника", "маньяка",
 "монитор работает", "мониторинг сети", "монтажник ушёл", "комика",
 "мантия", "монетка", "мамочка", "молодец", "монотонный",
 "монумент", "монолит", "монета", "малина", "маньяк",
 "Монику давно не видели", "Мы говорили о Монике", "Сегодня Моника дома",
 "Вчера Моника сказала спасибо", "Моника сегодня придёт?",
 "Вот Моника, а вот её подруга", "Кто такая Моника?",
 "Моники сейчас нет", "Она ищет Монику", "Мы обсуждали Монику",
 "У телевизора сидит Моня", "Посмотри на монитор", "Монитор показывает график",
 "Лимонника много в саду", "Он увидел маньяка", "Монитор сломался",
 "Моник опять не включается", "Мониторинг завершён", "Поставь таймер",
 "Сколько сейчас времени?", "Какая сегодня погода?",
 "Только не сегодня", "Что у нас на ужин", "Открой календарь",
 "Включи музыку", "Робот работает", "Доброе утро",
 "Завтра обещают дождь", "Мы собираемся на пляж",
 "Дети рисуют у окна", "Часы показывают восемь",
 "Рядом стоит маленький стол", "Я знаю эту мелодию",
 "На улице совсем тихо", "Посмотри на небо", "Она ещё спит",
 "Давайте поговорим завтра",
]
NEG_VALID=[
 "Монику пригласили в гости", "Куда пропал Моня?", "Я купил новый монитор",
 "Работает мониторинг", "Маньяка задержали", "Где растёт лимонник",
 "В записи упоминалась Моника", "Ты про Монику?", "Проверим экран завтра",
]
NEG_TEST=[
 "Зачем Монике звонить?", "Моник выключился", "Монитор горит всю ночь",
 "В аптеке есть лимонник", "Маньяка никто не видел", "Моня всё слышит",
 "Мы с Моникой обедали", "Я сказал Монику", "Никакого разговора пока",
]
def sha(data:bytes):
    return hashlib.sha256(data).hexdigest()

def resample(raw,rate):
    g=gcd(int(rate),16000)
    result=resample_poly(np.asarray(raw,dtype=np.float32),16000//g,int(rate)//g)
    if result.size<1200 or result.size>16000*16:
        raise ValueError("unexpected_speech_duration")
    return np.clip(np.rint(result),-32768,32767).astype("<i2")

class Synth:
    def __init__(self,old_root:Path,speaker:str):
        self.old=old_root
        self.name=speaker
        self.voice=None
        self.env=dict(os.environ)
        rh=old_root/"rh-local"/"root"
        es=old_root/"espeak-local"/"root"
        self.env.update(
            LD_LIBRARY_PATH=str(rh/"usr"/"lib"/"x86_64-linux-gnu")+":"+str(es/"usr"/"lib"/"x86_64-linux-gnu"),
            RHVOICE_DATA_PATH=str(rh/"usr"/"share"/"RHVoice"),
            RHVOICE_CONFIG_PATH=str(old_root/"reference-home"),
            ESPEAK_DATA_PATH=str(es/"usr"/"lib"/"x86_64-linux-gnu"),
        )
        if speaker in ("denis","dmitri"):
            import onnxruntime
            from piper import PiperVoice
            from piper.config import PiperConfig
            root=old_root/"voices"
            voice=root/f"ru_RU-{speaker}-medium.onnx"
            config=root/f"ru_RU-{speaker}-medium.onnx.json"
            if not voice.is_file() or not config.is_file():
                raise FileNotFoundError("Missing pre-existing licensed CPU Piper voice")
            options=onnxruntime.SessionOptions()
            options.intra_op_num_threads=1
            options.inter_op_num_threads=1
            options.log_severity_level=3
            self.voice=PiperVoice(
                session=onnxruntime.InferenceSession(str(voice),sess_options=options,providers=["CPUExecutionProvider"]),
                config=PiperConfig.from_dict(json.loads(config.read_text())),
            )
    def say(self,text:str,speed:int,pitch:int):
        if self.voice is not None:
            from piper import SynthesisConfig
            chunks=self.voice.synthesize(text,SynthesisConfig(
                length_scale=speed/100.0,noise_scale=.55,noise_w_scale=.7))
            arr=np.concatenate([c.audio_float_array for c in chunks])*32767
            rate=self.voice.config.sample_rate
            pcm=resample(arr,rate)
        elif self.name=="espeak-ru":
            binary=self.old/"espeak-local"/"root"/"usr"/"bin"/"espeak-ng"
            r=subprocess.run([str(binary),"-v","ru","-s",str(round(16500/speed)),
                              "-p",str(50+pitch),"--stdout",text],
                              env=self.env,check=True,capture_output=True,timeout=15)
            with wave.open(io.BytesIO(r.stdout)) as wav:
                pcm=resample(np.frombuffer(wav.readframes(wav.getnframes()),"<i2"),wav.getframerate())
        else:
            binary=self.old/"rh-local"/"root"/"usr"/"bin"/"RHVoice-test"
            with tempfile.TemporaryDirectory() as directory:
                wav=Path(directory)/"out.wav"
                subprocess.run([str(binary),"-p",self.name.title(),"-r",str(100-speed),
                               "-t",str(pitch),"-o",str(wav)],input=text.encode("utf8"),
                               env=self.env,capture_output=True,check=True,timeout=18)
                with wave.open(str(wav)) as w:
                    pcm=resample(np.frombuffer(w.readframes(w.getnframes()),"<i2"),w.getframerate())
        # TRAINING AVOIDS slicing the keyword phonemes from short utterances.
        # Joined utterances retain the first 1.85s (full first word plus question onset).
        # No fixed fake one-second name-end annotation is asserted.
        if len(text)>len(TARGET)+3:
            pcm=pcm[:min(len(pcm),int(1.85*16000))]
        if len(pcm)<1600:
            raise ValueError("synthetic_speech_too_short")
        return pcm

def generate(old_root:Path,output:Path,pos_count:int,neg_count:int):
    rng=np.random.default_rng(SEED)
    output.mkdir(parents=True,exist_ok=False)
    meta={"schema":"monika_mww_synthetic_v1","seed":SEED,"sample_rate_hz":16000,
          "source":"piper/rhvoice/espeak_offline_only","target":"Мо́ника",
          "train_voices":[s for s,split in SPLITS.items() if split=="train"],
          "validation_voices":[s for s,split in SPLITS.items() if split=="validation"],
          "test_voices":[s for s,split in SPLITS.items() if split=="test"],
          "corpus_positive_per_voice":pos_count,
          "corpus_negative_per_voice":neg_count,
          "only_synthetic":True,"owner_audio":False,"paid_calls":0}
    (output/"generation-plan.json").write_text(json.dumps(meta,ensure_ascii=False,indent=2))
    summary=[]
    for speaker,split in SPLITS.items():
        target=output/speaker
        target.mkdir()
        synth=Synth(old_root,speaker)
        positives=POS_TRAIN if split=="train" else POS_VALID if split=="validation" else POS_TEST
        negatives=NEG_COMMON if split=="train" else NEG_VALID if split=="validation" else NEG_TEST
        for label,texts,count in (("positive",positives,pos_count),("negative",negatives,neg_count)):
            rows=[]
            used={}
            for index in range(count):
                text=texts[index%len(texts)]
                counter=used.get(text,0)
                used[text]=counter+1
                speed=(80,90,100,110,120)[counter%5]
                pitch=(-12,-5,0,6,13)[(counter+index)%5]
                pcm=synth.say(text,speed,pitch)
                name=f"{label}-{index:04d}.pcm"
                path=target/name
                path.write_bytes(pcm.tobytes())
                rows.append({"file":name,"speaker":speaker,"split":split,
                             "label":label,"text":text,"speed":speed,"pitch":pitch,
                             "samples":len(pcm),"sha256":sha(pcm.tobytes()),
                             "synthetic":True})
            summary.append({"voice":speaker,"split":split,"label":label,"clips":len(rows)})
            # Keep class-level separate manifest to avoid mutating the input set.
            (target/f"manifest-{label}.json").write_text(json.dumps(rows,ensure_ascii=False,indent=2))
            print(json.dumps(summary[-1]),flush=True)
    (output/"complete.json").write_text(json.dumps({"completed":True,"counts":summary,"paid_calls":0},indent=2))
    print("CORPUS_COMPLETE",len(SPLITS)*(pos_count+neg_count),flush=True)

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--old-tools",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--positives",type=int,default=55)
    p.add_argument("--negatives",type=int,default=100)
    args=p.parse_args()
    if not 20<=args.positives<=500 or not 35<=args.negatives<=1000:
        p.error("bounded synthetic dataset only")
    if args.output.exists():
        p.error("new output only; never overwrite prior corpus")
    generate(args.old_tools,args.output,args.positives,args.negatives)
