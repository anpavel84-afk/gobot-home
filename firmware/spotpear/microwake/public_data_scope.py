"""Explicit separation of licensed PUBLIC human background and Owner recordings."""
import hashlib,json
from pathlib import Path
URL='https://openslr.trmal.net/resources/12/dev-clean.tar.gz'
MD5='42e2234ba48799c1f50f24a7926300a1'


def public_training_scope(data):
    if not data.get('public_human_negative_training'):return data.get('human_training') is False and data.get('owner_human_training') is not True
    return (data.get('human_training') is True and data.get('owner_human_training') is False and data.get('public_human_negative_training') is True and
        data.get('public_speech_source_md5')==MD5 and data.get('public_speech_source_url')==URL and data.get('public_speech_license')=='CC-BY-4.0')


def validate_speech_replay(path):
    path=Path(path)
    if path.is_symlink() or path.with_suffix('.json').is_symlink() or not 1024<=path.stat().st_size<=400*1024**2:raise ValueError('Unsafe public speech feature path/size')
    data=json.loads(path.with_suffix('.json').read_text())
    if data.get('schema')!='licensed-public-speech-native-v1' or data.get('license')!='CC-BY-4.0' or data.get('source_url')!=URL or data.get('source_md5')!=MD5 or data.get('owner_audio') is not False or data.get('split')!='training' or data.get('frontend_hop_samples')!=160 or data.get('context_frames')!=204 or not 1000<=data.get('windows',0)<=20000:raise ValueError('Unverified public native speech provenance')
    if len(data.get('speakers',[]))!=32 or len(set(data['speakers']))!=32 or len(data.get('excluded_speakers',[]))!=8 or set(data['speakers'])&set(data['excluded_speakers']):raise ValueError('Public speech speaker leakage')
    if hashlib.sha256(path.read_bytes()).hexdigest()!=data.get('sha256'):raise ValueError('Changed public speech feature array')
    return data
