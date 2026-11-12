"""Apply the bounded display delta to a separate copy of the verified v1 source."""
import argparse
from pathlib import Path
from shutil import copyfile


def main():
    args = argparse.ArgumentParser()
    args.add_argument("checkout", type=Path)
    target = args.parse_args().checkout / "main"
    cpp = (target / "application.cc").read_text()
    header = (target / "application.h").read_text()
    include = '#include "gobot_platform.h"'
    first = cpp.index('            auto payload = cJSON_GetObjectItem(root, "payload");',
                      cpp.index('#if CONFIG_RECEIVE_CUSTOM_MESSAGE'))
    end = cpp.index('#endif', first)
    cpp = cpp[:first] + '''            gobot::Scene scene;
            auto session = gobot::String(root, "session_id", 80);
            if (!session || !gobot::ParseScene(cJSON_GetObjectItem(root, "payload"), scene)) return;
            Schedule([this, display, id = std::string(session), scene = std::move(scene)]() {
                if (!protocol_ || protocol_->session_id() != id || !gobot_turn_.Active()) return;
                gobot_timer_end_ = scene.remaining_ms >= 0 ? gobot::NowMs() + scene.remaining_ms : 0;
                gobot_timer_seconds_ = -1;
                display->SetStatus(scene.title.c_str());
                display->SetChatMessage("system", scene.text.c_str());
            });
''' + cpp[end:]
    marker = "void Application::GoBotPoll() {"
    tick = '''
    if (gobot_timer_end_) {
        const auto now = gobot::NowMs();
        const int seconds = now < gobot_timer_end_ ? (gobot_timer_end_ - now + 999) / 1000 : 0;
        if (seconds != gobot_timer_seconds_) {
            char text[32];
            snprintf(text, sizeof(text), "%d:%02d", seconds / 60, seconds % 60);
            Board::GetInstance().GetDisplay()->SetChatMessage("system", text);
            gobot_timer_seconds_ = seconds;
        }
        if (!seconds) gobot_timer_end_ = 0;
    }'''
    finish = 'SetStatus(gobot_muted_?"Микрофон выключен":"Скажите: ГоБот");'
    if any(cpp.count(s) != 1 for s in (include, marker, finish)) or header.count("gobot::TurnGuard gobot_turn_;") != 1:
        raise ValueError("Expected exact GoBot v1 base")
    cpp = cpp.replace(include, include+'\n#include "gobot_scene.h"').replace(marker, marker+tick)
    cpp = cpp.replace(finish, 'SetStatus(gobot_muted_ ? "Микрофон выключен" : '
                      '(audio_service_.GetWakeWords().empty() ? "ГоБот: требуется калибровка" : "Скажите: ГоБот"));')
    header = header.replace("gobot::TurnGuard gobot_turn_;", "gobot::TurnGuard gobot_turn_;\n"
                            "    uint64_t gobot_timer_end_ = 0;\n    int gobot_timer_seconds_ = -1;")
    for file in (target.parent / "CMakeLists.txt", target / "gobot_build_info.h"):
        value = file.read_text()
        if value.count('"0.1.0-dev-gobot"') != 1:
            raise ValueError("Unexpected firmware version")
        file.write_text(value.replace('"0.1.0-dev-gobot"', '"0.1.1-dev-display"'))
    copyfile(Path(__file__).with_name("gobot_scene.h"), target / "gobot_scene.h")
    (target / "application.cc").write_text(cpp)
    (target / "application.h").write_text(header)


if __name__ == "__main__":
    main()
