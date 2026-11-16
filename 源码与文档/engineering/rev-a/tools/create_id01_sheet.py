"""Assemble unchanged native CAD view renders into a review contact sheet."""
from pathlib import Path
import os
from PIL import Image, ImageDraw, ImageFont

R = Path(__file__).resolve().parents[1]
D = Path(os.environ.get('ID01_OUTPUT_DIR', str(R / 'mechanical/id01-reference')))
out = Image.new('RGB', (1536, 1300), '#f0efeb')
draw = ImageDraw.Draw(out)
font_path = '/System/Library/Fonts/STHeiti Medium.ttc'
large = ImageFont.truetype(font_path, 24)
small = ImageFont.truetype(font_path, 16)
draw.text((30, 22), 'ID-01 · 原型还原 / FreeCAD 原生模型 REV 04', font=large, fill='#29302c')
draw.text((30, 61), '视觉比例优先 · 实际尺寸另列 · 外观模型，内部结构待重新适配', font=small, fill='#626a61')
views = [('front', '正视 FRONT'), ('rear', '后视 REAR'), ('left', '左视 LEFT'),
         ('right', '右视 RIGHT'), ('top', '俯视 TOP'), ('bottom', '仰视 BOTTOM')]
for i, (view, title) in enumerate(views):
    x, y = (i % 3) * 512, 110 + (i // 3) * 570
    im = Image.open(D / (view + '.png')).convert('RGB').crop((150, 55, 750, 755))
    im.thumbnail((470, 510))
    out.paste(im, (x + (512 - im.width) // 2, y + 35))
    draw.text((x + 26, y), title, font=small, fill='#404b41')
    draw.line((x, y + 560, x + 512, y + 560), fill='#d0d3ca')
out.save(D / 'ID01-六视图.png')
print(D / 'ID01-六视图.png')
