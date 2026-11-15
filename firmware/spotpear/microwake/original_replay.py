"""Replay the original licensed training speakers; never validation/test voices."""
import hashlib,json
from pathlib import Path
SPEAKERS=('denis','espeak-ru','anna','aleksandr')
HARD_PHRASES={'робот','бот','готов','готово','гобой','говорит','голос','погода','погоди','какой бот','домашний робот','этот робот','вот бот'}

def hard_negatives(root,speakers=SPEAKERS):
    result=[]
    for speaker in speakers:
        folder=Path(root)/speaker
        for item in json.loads((folder/'manifest.json').read_text(encoding='utf-8')):
            if item.get('label')=='negative' and item.get('text','').strip().lower() in HARD_PHRASES:result.append(folder/item['file'])
    if not result:raise ValueError('Missing original hard-negative phrases')
    return result

def corpus(root,speakers=SPEAKERS):
    if tuple(speakers) not in (SPEAKERS,('denis','dmitri','espeak-ru','anna')):raise ValueError('Unreviewed replay split')
    root=Path(root).resolve();positive=[];negative=[]
    for speaker in speakers:
        directory=root/speaker
        if directory.is_symlink():raise ValueError('Replay speaker must be local')
        manifest=json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
        seen=set();groups={'positive':[],'negative':[]}
        for item in manifest:
            name=item['file'];path=directory/name
            if (Path(name).name!=name or name in seen or not name.endswith('.pcm') or
                item.get('speaker')!=speaker or item.get('synthetic') is not True or
                item.get('label') not in groups or path.is_symlink()):raise ValueError('Invalid replay manifest')
            if hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:raise ValueError('Replay PCM hash mismatch')
            seen.add(name);groups[item['label']].append(path)
        if len(groups['positive'])!=15 or len(groups['negative'])!=198:raise ValueError('Incomplete original training speaker')
        positive.extend(groups['positive']);negative.extend(groups['negative'])
    return positive,negative
