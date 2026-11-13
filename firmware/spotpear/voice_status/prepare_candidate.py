"""Extend 0.4.3 UI on a COPY. No flashing, enrollment, audio or KWS changes."""
import argparse,hashlib,json
from pathlib import Path

def change(path,old,new):
    data=path.read_text()
    if data.count(old)!=1:raise ValueError(f'Unexpected baseline {path.name}: {old[:50]}')
    path.write_text(data.replace(old,new))

def prepare(root):
    root=Path(root);main=root/'main'
    if '0.4.3-dev-media-ready' not in (root/'CMakeLists.txt').read_text():raise ValueError('Need installed0.4.3 copy')
    change(main/'gobot_scene.h','    std::string title;', '    std::string engine, phase;\n    std::string title;')
    change(main/'gobot_scene.h','    scene.title = title;', '''    if(cJSON_GetObjectItemCaseSensitive(root,"voice_engine")) {
        auto engine=String(root,"voice_engine",1);
        if(!engine || (strcmp(engine,"A") && strcmp(engine,"B") && strcmp(engine,"C"))) return false;
        scene.engine=engine;
    }
    if(cJSON_GetObjectItemCaseSensitive(root,"voice_phase")) {
        auto phase=String(root,"voice_phase",16);
        if(!phase || (strcmp(phase,"connecting") && strcmp(phase,"listening") && strcmp(phase,"thinking") && strcmp(phase,"speaking"))) return false;
        scene.phase=phase;
    }
    scene.title = title;''')
    change(main/'application.h','    bool gobot_access_received_=false,',
        '    std::string gobot_ui_engine_,gobot_ui_phase_;\n    bool gobot_access_received_=false,')
    change(main/'application.cc','                if(scene.weather>=0) {', '''                if(!scene.engine.empty()) gobot_ui_engine_=scene.engine;
                if(!scene.phase.empty()) gobot_ui_phase_=scene.phase;
                if(scene.weather>=0) {''')
    change(main/'application.cc','    page.skin=skin_;', '    page.skin=skin_;page.engine=gobot_ui_engine_;')
    change(main/'application.cc','    if(duplex_started_ || (page.view==View::Ready && duplex_armed_)) {', '''    if(page.view==View::Listening) {
        if(gobot_ui_phase_=="thinking") page.view=View::Thinking;
        else if(gobot_ui_phase_=="connecting") page.view=View::Connecting;
    }
    if(duplex_started_ || (page.view==View::Ready && duplex_armed_)) {''')
    change(main/'application.cc','void Application::GoBotFinish(const char* reason) {',
        'void Application::GoBotFinish(const char* reason) {\n    gobot_ui_engine_.clear();gobot_ui_phase_.clear();')
    ui=main/'touch_screen.h'
    change(ui,'    std::string value, detail, badge;', '    std::string value, detail, badge, engine;')
    change(ui,' && badge==b.badge;', ' && badge==b.badge && engine==b.engine;')
    change(ui,'        int face=0;', '''        const char* engine=p.engine=="A"?"Эксперт A":p.engine=="B"?"Разговор B":p.engine=="C"?"Разговор C":"";
        const uint16_t engine_color=p.engine=="A"?atlas::lilac:atlas::blue;
        int face=0;''')
    change(ui,'            return;\n        }\n        default: break;', '            if(*engine)text(engine,20,engine_color,1,150);\n            return;\n        }\n        default: break;')
    change(ui,'        if(!p.badge.empty()) text(p.badge,35,atlas::amber);',
        '        if(!p.badge.empty()) text(p.badge,35,atlas::amber);\n        if(*engine)text(engine,20,engine_color,1,150);')
    for p in (root/'CMakeLists.txt',main/'gobot_build_info.h'):
        change(p,'0.4.3-dev-media-ready','0.4.4-dev-voice-status-1')
    files=['gobot_scene.h','application.h','application.cc','touch_screen.h','gobot_build_info.h']
    report={'version':'0.4.4-dev-voice-status-1','base':'0.4.3-dev-media-ready','flashed':False,
        'audio_path_changed':False,'wake_to_brain_changed':False,
        'files':{n:hashlib.sha256((main/n).read_bytes()).hexdigest() for n in files}}
    (root/'voice-status-manifest.json').write_text(json.dumps(report,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('copy_of_media_ready',type=Path);a=p.parse_args();prepare(a.copy_of_media_ready)
