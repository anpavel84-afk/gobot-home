from pathlib import Path
import json,subprocess,shutil,sys
ROOT=Path(__file__).resolve().parents[1]
source=ROOT/'vendor/xiaozhi-server';voice=source/'main/xiaozhi-server'
lock=json.loads((ROOT/'docs/dependencies.lock.json').read_text())['xiaozhi-server']['sha']
assert subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()==lock
patch=ROOT/'services/voice/patches/strict-auth.patch'
check=subprocess.run(['git','-C',str(source),'apply','--check',str(patch)],capture_output=True)
if check.returncode==0:subprocess.run(['git','-C',str(source),'apply',str(patch)],check=True)
else:subprocess.run(['git','-C',str(source),'apply','--reverse','--check',str(patch)],check=True)
for category in ['asr','tts']:
    for adapter in ['gobot_mock','gobot_openai_ru']:
        shutil.copyfile(ROOT/f'services/voice/providers/{category}/{adapter}.py',voice/f'core/providers/{category}/{adapter}.py')
p=voice/'core/providers/llm/gobot';p.mkdir(exist_ok=True)
shutil.copyfile(ROOT/'services/voice/providers/llm/gobot/gobot.py',p/'gobot.py');(p/'__init__.py').touch()
# Empty deny allowlist blocks every physical device until explicit provisioning.
import yaml
keys=json.loads((ROOT/'run/keys.json').read_text())
config={'server':{'ip':'127.0.0.1','port':18783,'http_port':18784,'websocket':'ws://127.0.0.1:18783/xiaozhi/v1/','vision_explain':'http://127.0.0.1:18784/mcp/vision/explain','auth_key':keys['device_secret'],'auth':{'enabled':True,'allowed_devices':[],'expire_seconds':3600}},'read_config_from_api':False,'enable_greeting':False,'enable_wakeup_words_response_cache':False,'mcp_endpoint':None,'plugins':{},'context_providers':[],'selected_module':{'VAD':'SileroVAD','ASR':'GoBotASRNotProvisioned','LLM':'GoBot','TTS':'GoBotTTSNotProvisioned','Memory':'nomem','Intent':'nointent'},'LLM':{'GoBot':{'type':'gobot','brain_url':'http://127.0.0.1:18781','brain_token':keys['api_token'],'device_id':'voice-provisioned'}},'log':{'log_level':'WARNING'},'exit_commands':['заверши разговор']}
# Use a reproducibly sanitized base; recursive upstream merging of {} would retain demo plugin keys.
base=yaml.safe_load(subprocess.check_output(['git','-C',str(source),'show',lock+':main/xiaozhi-server/config.yaml'],text=True,encoding='utf-8'))
def clear_credentials(obj):
    if isinstance(obj,dict):
        for key,value in obj.items():
            if any(part in str(key).lower() for part in ['api_key','auth_key','secret','password','token']):obj[key]=''
            else:clear_credentials(value)
    elif isinstance(obj,list):
        for value in obj:clear_credentials(value)
clear_credentials(base)
base['plugins']={};base['context_providers']=[];base['manager-api']={};base['mcp_endpoint']=None;base['Intent']={'nointent':{'type':'nointent'}};base['Memory']={'nomem':{'type':'nomem'}}
# Unselected remote model configuration is excluded from the generated runtime base.
for category in ['ASR','TTS','LLM']:base[category]={}
(voice/'config.yaml').write_text(yaml.safe_dump(base,allow_unicode=True),encoding='utf-8')
(voice/'data').mkdir(exist_ok=True);(voice/'data/.config.yaml').write_text(yaml.safe_dump(config,allow_unicode=True),encoding='utf-8')
print('Pinned overlay prepared. Production remains blocked until ASR/TTS/device provisioning.')
