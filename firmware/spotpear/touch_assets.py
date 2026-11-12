"""Generate a bounded native atlas from the product SVGs and OFL Noto Sans."""
import argparse
import io
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import resvg_py

ROOT = Path(__file__).resolve().parents[2]
DESIGN = ROOT / "design/visual-language"
FACES = ("neutral", "listening", "thoughtful", "speaking", "sleepy", "offline", "speaking-wide")
ICONS = ("sun", "sun-cloud", "cloud", "rain", "snow", "storm", "clock", "timer")


def generate(path):
    tokens = json.loads((DESIGN / "tokens.json").read_text())["colors"]
    sprites, pixels = [], bytearray()
    def add(image, advance=0):
        # Four bit alpha. Skip transparent border; LVGL uses a single RGB565 surface.
        bounds = image.getbbox() or (0, 0, 1, 1)
        alpha = list(image.crop(bounds).getdata())
        offset = len(pixels)
        if len(alpha)%2:
            alpha.append(0)
        pixels.extend((a & 240) | (b >> 4) for a,b in zip(alpha[::2], alpha[1::2]))
        x,y,r,b = bounds
        sprites.append((offset,x,y,r-x,b-y,advance))
    for name in [f"faces/{skin}-{face}" for skin in ("classic","soft","minimal") for face in FACES]+[f"icons/{k}" for k in ICONS]:
        size = 160 if name.startswith("faces") else 42
        image = Image.open(io.BytesIO(resvg_py.svg_to_bytes(svg_path=str(DESIGN / (name+".svg")),width=size,height=size)))
        add(image.convert("RGBA").getchannel("A"))
    chars = list(range(32,127))+list(range(0x410,0x450))+[0x401,0x451,0xb0,0x2026,0x2212,0x2013,0x00b7]
    font = ImageFont.truetype(str(ROOT/"services/phone/dist/noto-sans.ttf"),15)
    for code in chars:
        glyph = Image.new("L",(24,24))
        ImageDraw.Draw(glyph).text((1,0),chr(code),font=font,fill=255)
        add(glyph,round(font.getlength(chr(code))))
    with path.open("w",encoding="ascii") as out:
        out.write("#pragma once\n#include <cstdint>\nnamespace atlas {\n")
        for key in ["bg","mint","blue","ink","muted","amber","coral","lilac"]:
            rgb=int(tokens[key]["value"][1:],16)
            out.write(f"constexpr uint16_t {key}=0x{((rgb>>8)&0xf800)|((rgb>>5)&0x7e0)|((rgb>>3)&31):04x};\n")
        out.write("struct Sprite {uint32_t pos; uint8_t x,y,w,h,advance;};\n")
        out.write("constexpr unsigned char pixels[]={\n")
        for i in range(0,len(pixels),64):
            out.write(",".join(str(b) for b in pixels[i:i+64])+",\n")
        out.write("};\nconstexpr Sprite sprites[]={\n")
        for row in sprites:
            out.write("{"+",".join(map(str,row))+"},\n")
        out.write("};\nconstexpr unsigned codes[]={"+",".join(map(str,chars))+"};\n}\n")

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("output",type=Path)
    generate(parser.parse_args().output)
