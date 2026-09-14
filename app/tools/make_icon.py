# -*- coding: utf-8 -*-
"""Иконка приложения: app/icon.ico (Windows, exe и окно) и app/web/icon.png.

Запуск:  python3 app/tools/make_icon.py      (нужен Pillow: pip install pillow)

Идея - «линия преимущества»: поле Radiant (зелёный) и поле Dire (красный)
по диагонали, между ними оранжевый штрих - акцентный цвет интерфейса.
Сверху - полоса драфта из пяти слотов, как в самой Dota: Radiant слева,
Dire справа, текущий пик подсвечен. Цвета - из app/web/styles.css, чтобы
иконка и окно выглядели одним целым.

Рисуется в 8-кратном размере и уменьшается: так края ровные на любом
размере. Детали (слоты, бевел линии) сделаны так, чтобы на 16 px они
сходили на нет, не ломая основную форму: два поля и диагональ.
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
ICO = os.path.join(APP, "icon.ico")
PNG = os.path.join(APP, "web", "icon.png")

# токены из styles.css
BG = (0x16, 0x1b, 0x22)
BG_DARK = (0x0e, 0x11, 0x16)
LINE = (0x2a, 0x32, 0x3d)
ACCENT = (0xe8, 0x7a, 0x21)
ACCENT_LIGHT = (0xff, 0xa8, 0x4e)
ACCENT_DARK = (0x8a, 0x3e, 0x0a)
RADIANT = (0x3f, 0xb9, 0x50)
RADIANT_LIGHT = (0x6f, 0xd8, 0x7c)
RADIANT_DARK = (0x25, 0x7d, 0x35)
DIRE = (0xe2, 0x54, 0x4a)
DIRE_LIGHT = (0xf5, 0x82, 0x76)
DIRE_DARK = (0x9e, 0x2e, 0x27)

SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]
SUPER = 8


def _lerp(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def _vertical_gradient(size, top, bottom):
    """Вертикальный градиент как картинка RGBA."""
    img = Image.new("RGBA", (size, size))
    px = img.load()
    for y in range(size):
        c = _lerp(top, bottom, y / max(size - 1, 1))
        for x in range(size):
            px[x, y] = c + (255,)
    return img


def render(size):
    s = size * SUPER
    tiny = size <= 24  # на мелких размерах детали только мешают

    # --- плитка: тёмная, чуть светлее к верху, тонкая рамка
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    r = int(s * 0.22)
    tile = _vertical_gradient(s, _lerp(BG, LINE, 0.35), BG_DARK)
    tile_mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(tile_mask).rounded_rectangle((0, 0, s - 1, s - 1), radius=r, fill=255)
    img.paste(tile, (0, 0), tile_mask)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, s - 1, s - 1), radius=r, outline=LINE, width=max(1, s // 48))
    # внутренний блик по верхнему краю плитки
    d.rounded_rectangle((s // 48, s // 48, s - 1 - s // 48, s - 1 - s // 48), radius=int(r * 0.9),
                        outline=_lerp(LINE, (255, 255, 255), 0.12), width=max(1, s // 96))

    # --- внутреннее поле: два треугольника с объёмом
    pad = int(s * 0.15)
    x0, y0, x1, y1 = pad, pad, s - pad, s - pad
    field = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    green = _vertical_gradient(s, RADIANT_LIGHT, RADIANT_DARK)
    red = _vertical_gradient(s, DIRE_LIGHT, DIRE_DARK)
    gmask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(gmask).polygon([(x0, y0), (x1, y0), (x0, y1)], fill=255)   # верх-лево: Radiant
    rmask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(rmask).polygon([(x1, y0), (x1, y1), (x0, y1)], fill=255)   # низ-право: Dire
    field.paste(green, (0, 0), gmask)
    field.paste(red, (0, 0), rmask)

    fd = ImageDraw.Draw(field)
    # тень под линией - глубина; сама линия; светлая сердцевина - свечение
    w = int(s * 0.11)
    off = max(2, s // 64)
    fd.line([(x0 + off, y1 + off), (x1 + off, y0 + off)], fill=ACCENT_DARK, width=w)
    fd.line([(x0, y1), (x1, y0)], fill=ACCENT, width=w)
    if not tiny:
        fd.line([(x0, y1), (x1, y0)], fill=ACCENT_LIGHT, width=max(1, w // 3))

    # полоса драфта: пять слотов по верхнему краю, Radiant слева, Dire справа,
    # средний - текущий пик. На мелких размерах не рисуем: сольётся в шум
    if not tiny:
        n = 5
        gap = int(s * 0.025)
        strip_h = int(s * 0.13)
        inner_w = (x1 - x0) - gap * (n + 1)
        slot_w = inner_w // n
        top = y0 + gap
        for i in range(n):
            left = x0 + gap + i * (slot_w + gap)
            box = (left, top, left + slot_w, top + strip_h)
            if i == n // 2:
                fd.rounded_rectangle(box, radius=gap, fill=ACCENT, outline=ACCENT_LIGHT,
                                     width=max(1, s // 128))
            else:
                fd.rounded_rectangle(box, radius=gap, fill=BG_DARK + (170,),
                                     outline=LINE + (220,), width=max(1, s // 128))

    # маска поля со скруглением и мягкая внутренняя тень по краю
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle((x0, y0, x1, y1), radius=int(r * 0.55), fill=255)
    shadow = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((x0, y0, x1, y1), radius=int(r * 0.55),
                                             outline=(0, 0, 0, 140), width=max(2, s // 40))
    shadow = shadow.filter(ImageFilter.GaussianBlur(max(1, s // 80)))
    field.alpha_composite(shadow)
    img.paste(field, (0, 0), mask)

    return img.resize((size, size), Image.LANCZOS)


def main():
    frames = {size: render(size) for size in SIZES}
    frames[256].save(PNG)
    ordered = [frames[s] for s in sorted(SIZES, reverse=True)]
    ordered[0].save(ICO, format="ICO", sizes=[(s, s) for s in sorted(SIZES, reverse=True)],
                    append_images=ordered[1:])
    print("записано:", ICO, f"({os.path.getsize(ICO) // 1024} КБ),", PNG)
    return 0


if __name__ == "__main__":
    sys.exit(main())
