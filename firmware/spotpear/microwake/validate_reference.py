"""Fixed-policy streaming evaluation of public-only reference checkpoints.

Validation/test speakers follow the saved split; no threshold sweep, training,
personal audio, paid service, firmware admission or remote provider access.
"""
import argparse
import hashlib
import json
from pathlib import Path
from evaluate import traces,score
from train_reference import files


def main(corpus,output):
    config=json.loads((output/'config.json').read_text())
    metadata=json.loads((output/'model.json').read_text())
    selected=json.loads((output/'selection.json').read_text())
    if selected['selected']['step']<=0:raise ValueError('Untrained checkpoint')
    if config['human_training'] is not False:raise ValueError('Public-only evaluator')
    if hashlib.sha256((output/'gobot.tflite').read_bytes()).hexdigest()!=metadata['sha256']:raise ValueError('Model hash mismatch')
    train=set(config['training_speakers']);validation=set(config['validation_speakers']);test=set(config['test_speakers'])
    if train&validation or train&test or validation&test:raise ValueError('Speaker split leakage')
    result={'sha256':metadata['sha256'],'window':10,'cutoff':231,'warmup':68,'validation':{},'test':{},
        'human_trials':0,'installed':False,'product_accepted':False,'paid_calls':0}
    for category,speakers in [('validation',sorted(validation)),('test',sorted(test))]:
        files(corpus,tuple(speakers)) # Full manifest and hash verification before inference.
        for speaker in speakers:
            metric=score(traces(output/'gobot.tflite',corpus/speaker,20261114),231,window=10,warmup=68)
            result[category][speaker]=metric
            print(json.dumps({'split':category,'speaker':speaker,**{k:v for k,v in metric.items() if k!='mistakes'}}),flush=True)
    metrics=[value for group in ('validation','test') for value in result[group].values()]
    result['candidate_passed']=all(item['tp']>=.9*item['positive'] and item['false_events']==0 for item in metrics)
    (output/'stream-report.json').write_text(json.dumps(result,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('corpus',type=Path);parser.add_argument('output',type=Path)
    args=parser.parse_args();main(args.corpus,args.output)
