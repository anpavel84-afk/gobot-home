"""New, never-seen validation-protected synthetic voice for Monika V3.

This generates an INDEPENDENT test speaker, not included in V1/V2/V3
training, using existing CC-BY-SA RHVoice Aleksandr-hq voice assets.
No reuse of held-out TEST audio for training or threshold selection.
"""
import argparse
from pathlib import Path
import synthesize as base

base.SEED=20261121
base.SPLITS={"aleksandr-hq":"test"}
base.POS_TEST=[
    "Мо́ника, когда откроется магазин?",
    "Мо́ника сколько будет пять плюс семь",
    "Мо́ника дай мне совет",
    "Мо́ника, проверь температуру в комнате",
    "Мо́ника можно я задам вопрос",
    "Мо́ника, расскажи о Луне",
    "Мо́ника у нас завтра гости",
    "Мо́ника, поставь будильник на утро",
    "Мо́ника где находятся мои ключи",
    "Мо́ника, сколько дней до нового года",
    "Мо́ника какая будет погода в воскресенье",
    "Мо́ника ты меня слышишь",
    "Мо́ника запиши список покупок",
    "Мо́ника расскажи интересную историю",
    "Мо́ника?",
]
base.NEG_TEST=[
    "Монитор компьютера выключен",
    "Где стоит моник",
    "Моню сегодня видели",
    "Монику пригласили на праздник",
    "Лимонника здесь совсем нет",
    "Следователи задержали маньяка",
    "Новый монитор показывает картинку",
    "Я пошёл к Монике",
    "Вчера Моника приходила в гости",
    "Мы обсуждаем любимый сериал",
    "Моника выступила на сцене",
    "Где находится твой монитор",
    "Моник перестал работать",
    "Они вспоминали Монику",
    "Моня поехал к бабушке",
    "В соседнем доме живёт Моника",
    "Кто-то сказал Монику",
    "Сейчас на улице тихо",
    "Робот включил музыку",
    "Нам пора готовить обед",
    "На столе лежит книга",
    "Слушай, какая сегодня погода",
    "Время уже позднее",
    "Я забыл свою тетрадь",
    "Время идёт очень медленно",
]

_original_say=base.Synth.say
def safe_say(self,text,speed,pitch):
    if self.name!="aleksandr-hq":
        return _original_say(self,text,speed,pitch)
    # RHVoice executable's canonical licensed voice spelling uses lower-case hq.
    import subprocess,tempfile,wave
    import numpy as np
    with tempfile.TemporaryDirectory() as td:
        wav=Path(td)/"voice.wav"
        binary=self.old/"rh-local"/"root"/"usr"/"bin"/"RHVoice-test"
        subprocess.run([str(binary),"-p","Aleksandr-hq",
            "-r",str(100-speed),"-t",str(pitch),"-o",str(wav)],
            input=text.encode("utf8"),env=self.env,
            capture_output=True,check=True,timeout=18)
        with wave.open(str(wav)) as w:
            pcm=base.resample(np.frombuffer(
                w.readframes(w.getnframes()),dtype="<i2"),w.getframerate())
    if len(text)>len(base.TARGET)+3:
        pcm=pcm[:min(len(pcm),int(1.85*16000))]
    if len(pcm)<1600:raise ValueError("short_generated_holdout")
    return pcm
base.Synth.say=safe_say

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--old-tools",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    if a.output.exists():p.error("must_use_new_holdout_directory")
    base.generate(a.old_tools,a.output,60,125)
