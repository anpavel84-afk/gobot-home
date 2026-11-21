"""Preserve the complete wake word while adding immediate following speech."""
import numpy as np


def append_speech(word,suffix,rng):
    word=np.asarray(word,dtype=np.float64);suffix=np.asarray(suffix,dtype=np.float64)
    active=np.flatnonzero(np.abs(suffix)>max(20,float(np.max(np.abs(suffix),initial=0))*.025))
    if not len(active):return word.copy()
    suffix=suffix[active[0]:active[-1]+1][:8000]
    rms=lambda x:float(np.sqrt(np.mean(x*x)))
    gain=np.clip(rms(word)/max(1,rms(suffix)),.25,4)
    gap=np.zeros(int(rng.integers(0,321)))
    return np.clip(np.concatenate([word,gap,suffix*gain]),-32768,32767)


def negative_speech_windows(clips,rate=16000):
    """Mine only inside explicitly negative intervals; never infer new labels."""
    result=[clip.copy() for clip in clips]
    width=int(1.6*rate);hop=int(.8*rate)
    for clip in clips:
        windows=[clip[start:start+width] for start in range(0,len(clip)-width+1,hop)]
        if not windows:continue
        levels=[float(np.sqrt(np.mean(window.astype(float)**2))) for window in windows]
        threshold=max(float(np.median(levels))*2,max(levels)*.25)
        result.extend(window.copy() for window,level in zip(windows,levels) if level>=threshold)
    return result
