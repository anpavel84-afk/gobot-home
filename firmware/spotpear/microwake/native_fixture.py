"""Public synthetic INT8 vectors for an on-device inference parity check.

Not acoustic acceptance. No recordings, training, network or provider calls.
The manifest must explicitly identify every selected source as synthetic.
"""
import argparse, hashlib, json
from pathlib import Path
import numpy as np


def generate(model, corpus, output):
    import tensorflow as tf
    from pymicro_features import MicroFrontend
    manifest=json.loads((corpus/'manifest.json').read_text(encoding='utf-8'))
    selected=[]
    for label in ('positive','negative'):
        group=[item for item in manifest if item['label']==label]
        selected.extend(group[::max(1,len(group)//6)][:6])
    if len(selected)!=12:raise ValueError('Need six public clips per class')
    parts=[];sources=[]
    for item in selected:
        name=item['file'];path=corpus/name
        if Path(name).name!=name or path.is_symlink() or item.get('synthetic') is not True:
            raise ValueError('Only manifest-verified public synthetic input allowed')
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=item['sha256']:raise ValueError('Source hash changed')
        clip=np.frombuffer(raw,'<i2')
        if not 0<len(clip)<=16000*20:raise ValueError('Unbounded clip')
        parts.extend([np.zeros(16000,dtype='<i2'),clip,np.zeros(16000,dtype='<i2')])
        sources.append({'file':name,'sha256':item['sha256'],'label':item['label']})
    audio=np.concatenate(parts);frontend=MicroFrontend();rows=[]
    for at in range(0,len(audio)-159,160):
        result=frontend.process_samples(audio[at:at+160].astype('<i2').tobytes())
        if result.samples_read!=160:raise ValueError('Frontend dropped input')
        if result.features:rows.append(result.features)
    rows=np.asarray(rows,np.float32)
    if len(rows)>12000:raise ValueError('Fixture too large')
    interpreter=tf.lite.Interpreter(model_path=str(model),num_threads=1,
        experimental_op_resolver_type=tf.lite.experimental.OpResolverType.BUILTIN_WITHOUT_DEFAULT_DELEGATES)
    interpreter.allocate_tensors();inp=interpreter.get_input_details()[0];out=interpreter.get_output_details()[0]
    if tuple(inp['shape'])!=(1,3,40) or inp['dtype']!=np.int8 or out['dtype']!=np.uint8:
        raise ValueError('Unsupported firmware inference contract')
    scale,zero=inp['quantization']
    q=np.clip(np.rint(rows/scale)+zero,-128,127).astype(np.int8)
    q=q[:len(q)//3*3];expected=[]
    for at in range(0,len(q),3):
        interpreter.set_tensor(inp['index'],q[None,at:at+3]);interpreter.invoke()
        expected.append(int(interpreter.get_tensor(out['index'])[0,0]))
    if max(expected)<231:raise ValueError('Fixture never exercises high-confidence output')
    output.mkdir(parents=True,exist_ok=False)
    header='#pragma once\n#include <cstdint>\nnamespace gobot_fixture {\n'
    header+='static constexpr int8_t input[] = {'+','.join(map(str,q.reshape(-1)))+'};\n'
    header+='static constexpr uint8_t expected[] = {'+','.join(map(str,expected))+'};\n}\n'
    (output/'gobot_mww_fixture.h').write_text(header,encoding='utf-8')
    result={'synthetic_only':True,'acoustic_acceptance':False,'model_sha256':hashlib.sha256(model.read_bytes()).hexdigest(),
        'sources':sources,'frames':len(q),'invocations':len(expected),'maximum_expected':max(expected),
        'header_sha256':hashlib.sha256(header.encode()).hexdigest(),'provider_calls':0}
    (output/'fixture.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='sources'}))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('model',type=Path);p.add_argument('corpus',type=Path);p.add_argument('output',type=Path)
    a=p.parse_args();generate(a.model,a.corpus,a.output)
