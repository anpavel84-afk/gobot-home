#pragma once
#include "touch_atlas.h"
#include <algorithm>
#include <cmath>
#include <string>
#include <vector>

namespace touchui {
enum class View { Ready, Connecting, Listening, Thinking, Speaking, Muted, Offline, Notice, Clock, Timer, Weather };
struct Page {
    View view=View::Ready;
    int skin=0, icon=0;
    bool mouth=false;
    std::string value, detail, badge;
    bool operator==(const Page& b) const {
        return view==b.view && skin==b.skin && icon==b.icon && mouth==b.mouth && value==b.value && detail==b.detail && badge==b.badge;
    }
};
class Screen {
    uint16_t* fb_;
    void pixel(int x,int y,uint16_t color) {
        if ((unsigned)x<240 && (unsigned)y<240) fb_[y*240+x]=color;
    }
    void sprite(int index,int x,int y,uint16_t color,int scale=1) {
        auto s=atlas::sprites[index];
        for(int j=0;j<s.h;j++) for(int i=0;i<s.w;i++) {
            int n=j*s.w+i;
            int a=(atlas::pixels[s.pos+n/2] >> (n%2?0:4)) & 15;
            if(!a) continue;
            const int r=(((color>>11)*a+(atlas::bg>>11)*(15-a))/15);
            const int g=((((color>>5)&63)*a+((atlas::bg>>5)&63)*(15-a))/15);
            const int b=(((color&31)*a+(atlas::bg&31)*(15-a))/15);
            for(int dy=0;dy<scale;dy++) for(int dx=0;dx<scale;dx++)
                pixel(x+(s.x+i)*scale+dx,y+(s.y+j)*scale+dy,(r<<11)|(g<<5)|b);
        }
    }
    void text(const std::string& str,int top,uint16_t color,int scale=1,int width=176) {
        // Keep the whole glyph box inside the circular LCD with an eight-pixel inset.
        const int dy=std::max(std::abs(top-120), std::abs(top+18*scale-120));
        if(dy>=112) return;
        width=std::min(width, 2*int(std::sqrt(112*112-dy*dy))-4);
        std::vector<int> chars;
        int length=0;
        for(size_t i=0;i<str.size();) {
            unsigned c=(unsigned char)str[i++];
            if(c>=128) {
                int more=c<224?1:c<240?2:3;
                c &= more==1?31:more==2?15:7;
                if(i+more>str.size()) break;
                while(more--) c=(c<<6)|((unsigned char)str[i++]&63);
            }
            auto it=std::find(std::begin(atlas::codes),std::end(atlas::codes),c);
            int id=29+(it==std::end(atlas::codes)?31:int(it-std::begin(atlas::codes)));
            int advance=atlas::sprites[id].advance*scale;
            if(length+advance>width) {
                const int dots=29+int(std::find(std::begin(atlas::codes),std::end(atlas::codes),0x2026)-std::begin(atlas::codes));
                while(!chars.empty() && length+atlas::sprites[dots].advance*scale>width) {
                    length-=atlas::sprites[chars.back()].advance*scale;
                    chars.pop_back();
                }
                chars.push_back(dots);length+=atlas::sprites[dots].advance*scale;
                break;
            }
            length+=advance;chars.push_back(id);
        }
        int x=120-length/2;
        for(int id:chars) {sprite(id,x,top,color,scale);x+=atlas::sprites[id].advance*scale;}
    }
public:
    explicit Screen(uint16_t* buf):fb_(buf) {}
    void draw(const Page& p) {
        std::fill_n(fb_,240*240,atlas::bg);
        for(int y=0;y<240;y++) for(int x=0;x<240;x++){
            int d=(x-120)*(x-120)+(y-120)*(y-120);
            if(d>=116*116 && d<117*117) pixel(x,y,0x19a5);
        }
        int face=0;
        uint16_t color=atlas::mint;
        const char* title="Я рядом";
        const char* hint="Коснитесь, чтобы говорить";
        switch(p.view) {
        case View::Connecting:face=2;title="Подключаюсь";hint="Удержание · стоп";break;
        case View::Listening:face=1;color=atlas::blue;title="Слушаю";hint="Касание · отправить";break;
        case View::Thinking:face=2;color=atlas::lilac;title="Обдумываю";hint="Удержание · стоп";break;
        case View::Speaking:face=p.mouth?3:0;title="Отвечаю";hint="Удержание · стоп";break;
        case View::Muted:face=4;color=atlas::amber;title="Микрофон выключен";hint="Удержите для включения";break;
        case View::Offline:face=5;color=atlas::amber;title="Нет связи";hint="Проверить касанием";break;
        case View::Notice:face=2;color=atlas::amber;title=p.value.c_str();hint=p.detail.c_str();break;
        case View::Clock:
        case View::Timer:
        case View::Weather:{
            bool weather=p.view==View::Weather;
            sprite(weather?21+std::clamp(p.icon,0,5):p.view==View::Clock?27:28,99,43,weather?atlas::blue:atlas::mint);
            text(p.value,90,atlas::ink,2,178);
            text(p.detail,153,atlas::ink);
            text(p.view==View::Timer?"Коснитесь":"ГоБот",181,atlas::muted);
            return;
        }
        default: break;
        }
        sprite(std::clamp(p.skin,0,2)*7+face,40,18,color);
        text(title,144,atlas::ink);
        if(p.view==View::Ready) {
            text("Коснитесь, чтобы",168,atlas::muted);
            text("говорить",187,atlas::muted);
        } else if(p.view==View::Muted) {
            text("Удержите",168,atlas::muted);
            text("для включения",187,atlas::muted);
        } else {
            text(hint,169,atlas::muted,1,184);
        }
        if(!p.badge.empty()) text(p.badge,35,atlas::amber);
    }
};
}
