# -*- coding: utf-8 -*-
"""Иконка приложения: app/icon.ico (Windows, exe и окно) и app/web/icon.png.

Запуск:  python3 app/tools/make_icon.py      (нужен Pillow: pip install pillow)

Идея - «линия преимущества»: тёмная плитка, разделённая по диагонали на
поле Radiant (зелёный) и поле Dire (красный), а по диагонали - жирный
оранжевый штрих, акцентный цвет интерфейса. Три цвета - ровно те, что
в app/web/styles.css, поэтому иконка и окно выглядят одним целым.
Рисуется в 8-кратном размере и уменьшается: так края ровные на любом
размере, включая 16 px в панели задач.
"""
import os
import sys

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
ICO = os.path.join(APP, "icon.ico")
PNG = os.path.join(APP, "web", "icon.png")

# токены из styles.css
BG = "#161b22"
LINE = "#2a323d"
ACCENT = "#e87a21"
RADIANT = "#3fb950"
DIRE = "#e2544a"

SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]
SUPER = 8  # коэффициент суперсэмплинга


def render(size):
    s = size * SUPER
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # плитка со скруглением ~22% - как у иконок Windows 11, но не «блин»
    r = int(s * 0.22)
    d.rounded_rectangle((0, 0, s - 1, s - 1), radius=r, fill=BG, outline=LINE,
                        width=max(1, s // 48))

    # внутреннее поле с отступом, на нём два треугольника по диагонали
    pad = int(s * 0.16)
    x0, y0, x1, y1 = pad, pad, s - pad, s - pad
    inner = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    di = ImageDraw.Draw(inner)
    di.polygon([(x0, y0), (x1, y0), (x0, y1)], fill=RADIANT)   # верх-лево: Radiant
    di.polygon([(x1, y0), (x1, y1), (x0, y1)], fill=DIRE)      # низ-право: Dire
    # диагональ - линия преимущества
    w = int(s * 0.11)
    di.line([(x0, y1), (x1, y0)], fill=ACCENT, width=w)
    # маска: поле тоже со скруглением, чуть меньше плитки
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle((x0, y0, x1, y1), radius=int(r * 0.55), fill=255)
    img.paste(inner, (0, 0), mask)

    return img.resize((size, size), Image.LANCZOS)


def main():
    frames = {size: render(size) for size in SIZES}
    frames[256].save(PNG)
    # ICO: Pillow берёт первое изображение и сам масштабирует под sizes,
    # но отрисованные отдельно кадры чётче - подставляем их через append_images
    ordered = [frames[s] for s in sorted(SIZES, reverse=True)]
    ordered[0].save(ICO, format="ICO", sizes=[(s, s) for s in sorted(SIZES, reverse=True)],
                    append_images=ordered[1:])
    print("записано:", ICO, f"({os.path.getsize(ICO) // 1024} КБ),", PNG)
    return 0


if __name__ == "__main__":
    sys.exit(main())
