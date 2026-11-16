"""One50s sample-clock guided capture. C++ prompts and local labels share one plan."""
import argparse,json,math
from pathlib import Path


def steps():
    result=[{'start':0,'end':2,'kind':'silence','text':'Тишина','hint':'Подготовка'}]
    for i in range(8):result.append({'start':2+3*i,'end':5+3*i,'kind':'name','text':'ГоБот','hint':f'ГО · {i+1}/4' if i<4 else f'БОТ · {i-3}/4','stress':'first' if i<4 else 'second','index':i})
    for i,text in enumerate(('робот','готов','погода','какой бот')):result.append({'start':26+3*i,'end':29+3*i,'kind':'negative','text':text,'hint':'Один раз','index':i})
    result.extend([{'start':38,'end':43,'kind':'question','text':'ГоБот, время?','hint':'Одной фразой','index':0},{'start':43,'end':48,'kind':'question','text':'ГоБот, погода?','hint':'Одной фразой','index':1},{'start':48,'end':50,'kind':'silence','text':'Тишина','hint':'Завершаю запись'}])
    return result


def plan():
    return {'schema':'guided_wake8_v1','capture_domain':'mono_pcm16_pre_afe','seconds':50,'sample_rate':16000,'clock':'captured PCM samples, not network or host time','steps':steps(),'training_isolated_indices':[0,1,2,4,5,6],'heldout_isolated_indices':[3,7],'training_question_indices':[],'heldout_question_indices':[0,1],'training_negative_indices':[0,1,2],'heldout_negative_indices':[3],'human_labels_verified':False}


def validate_capture(metadata,seconds,now):
    if metadata.get('protocol')!='guided_wake8' or metadata.get('capture_domain')!='mono_pcm16_pre_afe' or metadata.get('capture_state')!='complete_crc_verified' or metadata.get('physical_start_ack') is not True or metadata.get('owner_reported_completion') is not True or metadata.get('cloud_transfer') is not False:raise ValueError('Completed confirmed guided capture required')
    if seconds!=50 or not math.isfinite(metadata.get('expires_at',0)) or not now<metadata['expires_at']:raise ValueError('Unexpired exact50s sample required')
    if metadata.get('capture_plan')!=plan():raise ValueError('Guided schedule differs from current sample-clock protocol')
    return plan()


def header():
    text='#pragma once\n#include <cstddef>\nnamespace guided_wake {\nstruct Prompt { unsigned start,end; const char* text; const char* hint; };\ninline constexpr Prompt steps[] = {\n'
    for row in steps():text+='    {'+str(row['start']*16000)+','+str(row['end']*16000)+','+json.dumps(row['text'],ensure_ascii=False)+','+json.dumps(row['hint'],ensure_ascii=False)+'},\n'
    text+='};\ninline const Prompt& at(size_t samples) { for(const auto& p:steps) if(samples>=p.start && samples<p.end)return p; return steps[15]; }\n}\n'
    return text


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('output',type=Path);args=parser.parse_args();args.output.write_bytes(header().encode())
