"""Build an eight-screen reference sheet from preview_touch.cc's gzipped RGB565 output."""
import argparse
import gzip
import io
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
import resvg_py

ROOT = Path(__file__).resolve().parents[2]
SCREENS = ("PR-01","PR-02","PR-04","PR-05","PR-12","SY-01","WN-01","TM-03")


def compare(source, destination):
    frames = np.frombuffer(gzip.decompress(source.read_bytes()), "<u2").reshape(len(SCREENS),240,240)
    canvas = Image.new("RGB", (1024,1096), (14,23,30))
    font = ImageFont.truetype(str(ROOT/"services/phone/dist/noto-sans.ttf"), 14)
    draw = ImageDraw.Draw(canvas)
    for i, (code, pixels) in enumerate(zip(SCREENS,frames)):
        image = Image.fromarray(np.dstack(((pixels>>11)*255//31, ((pixels>>5)&63)*255//63,
                                          (pixels&31)*255//31)).astype("uint8"))
        path = ROOT/"design/visual-language/screens"/(code+".svg")
        ref = Image.open(io.BytesIO(resvg_py.svg_to_bytes(svg_path=str(path), width=240,height=240))).convert("RGBA")
        x,y = (i%4)*256+8,(i//4)*548
        canvas.paste(ref,(x,y+20),ref)
        canvas.paste(image,(x,y+294))
        draw.text((x+10,y),code+" / Атлас",font=font)
        draw.text((x+10,y+274),"GoBot / RGB565 прошивки",font=font)
    canvas.save(destination,optimize=True)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source",type=Path)
    parser.add_argument("destination",type=Path)
    args=parser.parse_args()
    compare(args.source,args.destination)
