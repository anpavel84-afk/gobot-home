"""Replay the original licensed training speakers; never validation/test voices."""
import hashlib,json,time
from pathlib import Path
SPEAKERS=('denis','espeak-ru','anna','aleksandr')
HARD_PHRASES={'робот','бот','готов','готово','гобой','гогот','говорит','голос','погода','погоди','какой бот','домашний робот','этот робот','вот бот'}

def hard_negatives(root,speakers=SPEAKERS):
    result=[]
    for speaker in speakers:
        folder=Path(root)/speaker
        for item in json.loads((folder/'manifest.json').read_text(encoding='utf-8')):
            if item.get('label')=='negative' and item.get('text','').strip().lower() in HARD_PHRASES:result.append(folder/item['file'])
    if not result:raise ValueError('Missing original hard-negative phrases')
    return result

def corpus(root,speakers=SPEAKERS):
    expanded=('denis','dmitri','espeak-ru','anna','irina')
    if tuple(speakers) not in (SPEAKERS,('denis','dmitri','espeak-ru','anna'),expanded):raise ValueError('Unreviewed replay split')
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
        expected=(75,498) if tuple(speakers)==expanded else (15,198)
        if (len(groups['positive']),len(groups['negative']))!=expected:raise ValueError('Incomplete original training speaker')
        positive.extend(groups['positive']);negative.extend(groups['negative'])
    return positive,negative


def mined_negatives(root,manifest,ident,expires,negative_paths):
    manifest=Path(manifest)
    if manifest.is_symlink() or manifest.name!=ident+'-mined-public-negatives.json' or manifest.stat().st_size>1024*1024:
        raise ValueError('Unexpected local negative-selection artifact')
    data=json.loads(manifest.read_text(encoding='utf-8'))
    train=['denis','dmitri','espeak-ru','anna','irina'];excluded=['aleksandr','elena']
    if (data.get('kind')!='private_teacher_public_train_negatives' or data.get('synthetic_only') is not True or
        data.get('source_sample')!=ident or data.get('training_speakers')!=train or data.get('excluded_speakers')!=excluded or
        data.get('kernel_baseline')!='native_reference' or not time.time()<data.get('expires_at',0)<=expires):
        raise ValueError('Expired or mismatched TRAIN-only selection')
    root=Path(root).resolve();allowed={p.resolve() for p in negative_paths};result=[]
    for speaker in train:
        if hashlib.sha256((root/speaker/'manifest.json').read_bytes()).hexdigest()!=data['corpus_manifest_sha256'][speaker]:
            raise ValueError('Public corpus changed since mining')
    if not 32<=len(data.get('clips',[]))<=128:raise ValueError('Unbounded negative replay count')
    for item in data['clips']:
        relative=Path(item['file'])
        if relative.is_absolute() or '..' in relative.parts or len(relative.parts)!=2 or relative.parts[0] not in train:
            raise ValueError('Non-TRAIN path in negative selection')
        path=root/relative
        if path.is_symlink() or path.resolve() not in allowed or path in result:raise ValueError('Unverified/repeated public negative')
        result.append(path)
    return result
