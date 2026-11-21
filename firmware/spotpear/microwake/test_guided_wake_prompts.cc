#include "guided_wake_prompts.h"
#include <cassert>
#include <cstring>
int main(){
    using guided_wake::at;
    assert(!std::strcmp(at(0).text,"Тишина"));
    assert(!std::strcmp(at(32000).text,"ГоБот"));
    assert(!std::strcmp(at(32000).hint,"ГО · 1/4"));
    assert(!std::strcmp(at(224000).hint,"БОТ · 1/4"));
    assert(!std::strcmp(at(416000).text,"робот"));
    assert(!std::strcmp(at(608000).text,"ГоБот, время?"));
    assert(!std::strcmp(at(688000).text,"ГоБот, погода?"));
    assert(!std::strcmp(at(768000).text,"Тишина"));
    assert(!std::strcmp(at(800000).hint,"Завершаю запись"));
}
