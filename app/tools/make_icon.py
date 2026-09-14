# -*- coding: utf-8 -*-
"""Иконка приложения: app/icon.ico (Windows, exe и окно) и app/web/icon.png.

Запуск:  python3 app/tools/make_icon.py      (нужен Pillow: pip install pillow)

Идея - буквально «pick line», линия пиков: ломаная линия драфта идёт
снизу вверх, на ней узлы-пики - зелёные свои, красные вражеские, - а
последний, большой оранжевый со свечением, - ваш пик, момент решения.
Линия растёт слева направо: преимущество набирается пик за пиком.
Цвета - из app/web/styles.css, чтобы иконка и окно были одним целым.

Рисуется в 8-кратном размере и уменьшается: края ровные на любом размере.
На 16-24 px мелкие узлы убираются - остаются линия и оранжевая точка,
этого достаточно, чтобы узнать иконку в панели задач.
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
MUTED = (0x8b, 0x98, 0xa8)
TEXT = (0xe6, 0xed, 0xf3)
ACCENT = (0xe8, 0x7a, 0x21)
ACCENT_LIGHT = (0xff, 0xb0, 0x5a)
RADIANT = (0x3f, 0xb9, 0x50)
DIRE = (0xe2, 0x54, 0x4a)

SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]
SUPER = 8

# узлы линии в долях размера: (x, y, цвет). Последний - ваш пик.
NODES = [
    (0.20, 0.76, RADIANT),
    (0.36, 0.62, DIRE),
    (0.50, 0.66, RADIANT),
    (0.63, 0.46, DIRE),
    (0.79, 0.27, ACCENT),
]


def _lerp(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def _radial_glow(size, center, radius, color, alpha):
    """Мягкое круглое свечение цвета color с центром center."""
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse(
        (center[0] - radius, center[1] - radius, center[0] + radius, center[1] + radius),
        fill=color + (alpha,))
    return glow.filter(ImageFilter.GaussianBlur(radius * 0.6))


def render(size):
    s = size * SUPER
    tiny = size <= 24

    # --- плитка: тёмная, чуть светлее сверху, тонкая рамка, лёгкий блик
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    r = int(s * 0.22)
    tile = Image.new("RGBA", (s, s))
    px = tile.load()
    for y in range(s):
        c = _lerp(_lerp(BG, LINE, 0.3), BG_DARK, y / (s - 1))
        for x in range(s):
            px[x, y] = c + (255,)
    tile_mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(tile_mask).rounded_rectangle((0, 0, s - 1, s - 1), radius=r, fill=255)
    img.paste(tile, (0, 0), tile_mask)

    pts = [(int(x * s), int(y * s)) for x, y, _ in NODES]
    last = pts[-1]

    # --- свечение вокруг последнего узла - под линией, чтобы не перекрывать её
    img.alpha_composite(_radial_glow(s, last, int(s * 0.26), ACCENT, 120))

    # --- линия: тёмная подложка для контраста и сама линия
    d = ImageDraw.Draw(img)
    w = int(s * (0.075 if not tiny else 0.10))
    d.line(pts, fill=BG_DARK, width=w + max(2, s // 40), joint="curve")
    d.line(pts, fill=MUTED if not tiny else TEXT, width=w, joint="curve")

    # --- узлы: свои и вражеские пики; на мелких размерах только последний
    if not tiny:
        rr = int(s * 0.055)
        ring = max(2, s // 48)
        for (x, y), (_, _, color) in zip(pts[:-1], NODES[:-1]):
            d.ellipse((x - rr - ring, y - rr - ring, x + rr + ring, y + rr + ring), fill=BG_DARK)
            d.ellipse((x - rr, y - rr, x + rr, y + rr), fill=color)

    # --- ваш пик: большой оранжевый узел со светлой сердцевиной
    R = int(s * (0.12 if not tiny else 0.15))
    ring = max(2, s // 40)
    x, y = last
    d.ellipse((x - R - ring, y - R - ring, x + R + ring, y + R + ring), fill=BG_DARK)
    d.ellipse((x - R, y - R, x + R, y + R), fill=ACCENT)
    core = int(R * 0.45)
    d.ellipse((x - core, y - core - R // 5, x + core, y + core - R // 5), fill=ACCENT_LIGHT)

    # рамка поверх всего
    d.rounded_rectangle((0, 0, s - 1, s - 1), radius=r, outline=LINE, width=max(1, s // 48))

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
