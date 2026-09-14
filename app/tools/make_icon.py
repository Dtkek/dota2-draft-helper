# -*- coding: utf-8 -*-
"""Иконка приложения: app/icon.ico (Windows, exe и окно) и app/web/icon.png.

Запуск:  python3 app/tools/make_icon.py      (нужен Pillow: pip install pillow)

Идея - «pick line» на карте Dota. Тёмное поле - карта: река по диагонали
из левого верхнего угла в правый нижний, база Radiant в левом нижнем углу
(зелёное свечение), база Dire в правом верхнем (красное). Через реку от
своей базы к вражеской идёт линия драфта с узлами-пиками; последний,
оранжевый со свечением, - ваш пик, единственное яркое пятно на карте.
Логотип самой Dota 2 не используется: это товарный знак Valve.

Палитра тёмная, цвета - производные от app/web/styles.css. Рисуется в
8-кратном размере и уменьшается. На 16-24 px остаются река, линия и
оранжевая точка - этого хватает, чтобы узнать иконку в панели задач.
"""
import os
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
ICO = os.path.join(APP, "icon.ico")
PNG = os.path.join(APP, "web", "icon.png")

# тёмная палитра на основе styles.css
BG = (0x0b, 0x0e, 0x13)
BG_TOP = (0x13, 0x18, 0x1f)
LINE = (0x22, 0x29, 0x33)
RIVER = (0x17, 0x2a, 0x33)
RIVER_EDGE = (0x24, 0x40, 0x4a)
LANE = (0x1c, 0x22, 0x2b)
PATH = (0x5a, 0x66, 0x74)
RADIANT = (0x2e, 0x8c, 0x3f)
RADIANT_GLOW = (0x2a, 0x7a, 0x3a)
DIRE = (0xb5, 0x3b, 0x33)
DIRE_GLOW = (0x9a, 0x2f, 0x2a)
ACCENT = (0xe8, 0x7a, 0x21)
ACCENT_LIGHT = (0xff, 0xb0, 0x5a)

SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]
SUPER = 8

# узлы линии пиков в долях размера, от базы Radiant к базе Dire
NODES = [
    (0.22, 0.78, RADIANT),
    (0.36, 0.64, DIRE),
    (0.48, 0.60, RADIANT),
    (0.60, 0.44, DIRE),
    (0.74, 0.30, ACCENT),
]


def _lerp(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def _glow(size, center, radius, color, alpha, blur=0.6):
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(layer).ellipse(
        (center[0] - radius, center[1] - radius, center[0] + radius, center[1] + radius),
        fill=color + (alpha,))
    return layer.filter(ImageFilter.GaussianBlur(radius * blur))


def render(size):
    s = size * SUPER
    tiny = size <= 24
    r = int(s * 0.22)

    # --- поле карты: почти чёрное, чуть светлее сверху
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    tile = Image.new("RGBA", (s, s))
    px = tile.load()
    for y in range(s):
        c = _lerp(BG_TOP, BG, y / (s - 1))
        for x in range(s):
            px[x, y] = c + (255,)
    tile_mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(tile_mask).rounded_rectangle((0, 0, s - 1, s - 1), radius=r, fill=255)
    img.paste(tile, (0, 0), tile_mask)

    # всё содержимое карты рисуем на отдельном слое и режем той же маской
    layer = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)

    # --- базы: свечение в углах, Radiant внизу слева, Dire вверху справа
    layer.alpha_composite(_glow(s, (int(s * 0.10), int(s * 0.90)), int(s * 0.36), RADIANT_GLOW, 150))
    layer.alpha_composite(_glow(s, (int(s * 0.90), int(s * 0.10)), int(s * 0.36), DIRE_GLOW, 150))

    # --- линии: лёгкие дорожки вдоль краёв - верхняя и нижняя линии карты
    if not tiny:
        lw = max(2, s // 40)
        m = int(s * 0.16)
        ld.line([(m, s - m), (m, m), (s - m, m)], fill=LANE, width=lw)          # верхняя линия
        ld.line([(m, s - m), (s - m, s - m), (s - m, m)], fill=LANE, width=lw)  # нижняя линия

    # --- река: диагональная полоса из левого верхнего в правый нижний угол
    rw = int(s * 0.16)
    ld.line([(-s // 8, -s // 8), (s + s // 8, s + s // 8)], fill=RIVER, width=rw)
    ld.line([(-s // 8, -s // 8), (s + s // 8, s + s // 8)], fill=RIVER_EDGE, width=max(1, s // 64))
    # берега - две тонкие линии по краям русла
    if not tiny:
        d2 = rw // 2
        for sign in (-1, 1):
            ld.line([(-s // 8 + sign * d2, -s // 8 - sign * d2), (s + s // 8 + sign * d2, s + s // 8 - sign * d2)],
                    fill=RIVER_EDGE, width=max(1, s // 96))

    # --- древние: маленькие ромбы в углах баз
    if not tiny:
        a = int(s * 0.045)
        for (cx, cy), color in (((int(s * 0.17), int(s * 0.83)), RADIANT), ((int(s * 0.83), int(s * 0.17)), DIRE)):
            ld.polygon([(cx, cy - a), (cx + a, cy), (cx, cy + a), (cx - a, cy)], fill=color)

    # слой обрезаем по плитке через альфу и накладываем поверх, а не paste:
    # paste с маской переносит и прозрачность слоя, пробивая дыры в плитке
    layer.putalpha(ImageChops.multiply(layer.getchannel("A"), tile_mask))
    img.alpha_composite(layer)

    # --- линия пиков и узлы
    pts = [(int(x * s), int(y * s)) for x, y, _ in NODES]
    last = pts[-1]
    img.alpha_composite(_glow(s, last, int(s * 0.24), ACCENT, 130))
    d = ImageDraw.Draw(img)
    w = int(s * (0.07 if not tiny else 0.10))
    d.line(pts, fill=BG, width=w + max(2, s // 40), joint="curve")
    d.line(pts, fill=PATH, width=w, joint="curve")
    if not tiny:
        rr = int(s * 0.05)
        ring = max(2, s // 48)
        for (x, y), (_, _, color) in zip(pts[:-1], NODES[:-1]):
            d.ellipse((x - rr - ring, y - rr - ring, x + rr + ring, y + rr + ring), fill=BG)
            d.ellipse((x - rr, y - rr, x + rr, y + rr), fill=color)

    # ваш пик - единственное яркое пятно
    R = int(s * (0.115 if not tiny else 0.15))
    ring = max(2, s // 40)
    x, y = last
    d.ellipse((x - R - ring, y - R - ring, x + R + ring, y + R + ring), fill=BG)
    d.ellipse((x - R, y - R, x + R, y + R), fill=ACCENT)
    core = int(R * 0.42)
    d.ellipse((x - core, y - core - R // 5, x + core, y + core - R // 5), fill=ACCENT_LIGHT)

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
