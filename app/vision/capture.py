# -*- coding: utf-8 -*-
"""Захват экрана. Работает на Windows, macOS и Linux через mss.

На Windows дополнительной настройки не требуется. На macOS системе нужно
один раз выдать терминалу право «Запись экрана» в настройках приватности,
иначе кадр вернётся чёрным.
"""
import numpy as np

try:
    import mss
    MSS_OK = True
except ImportError:  # пакет не установлен — модуль зрения просто отключится
    MSS_OK = False


def available():
    return MSS_OK


def monitors():
    """Список мониторов: [{'index', 'left', 'top', 'width', 'height'}]."""
    if not MSS_OK:
        return []
    out = []
    with mss.mss() as sct:
        # элемент 0 — объединённая область всех мониторов, показываем и её
        for i, m in enumerate(sct.monitors):
            out.append({
                "index": i,
                "left": m["left"], "top": m["top"],
                "width": m["width"], "height": m["height"],
                "label": ("все мониторы" if i == 0 else f"монитор {i}")
                         + f" — {m['width']}×{m['height']}",
            })
    return out


def grab(monitor=1, region=None):
    """Кадр экрана как массив BGR.

    monitor — индекс из monitors(); region — (left, top, width, height)
    в долях от 0 до 1 относительно монитора, чтобы не зависеть от разрешения.
    """
    if not MSS_OK:
        raise RuntimeError("не установлен пакет mss — захват экрана недоступен")
    with mss.mss() as sct:
        mons = sct.monitors
        idx = monitor if 0 <= monitor < len(mons) else (1 if len(mons) > 1 else 0)
        box = dict(mons[idx])
        if region:
            fl, ft, fw, fh = region
            box = {
                "left": int(box["left"] + fl * box["width"]),
                "top": int(box["top"] + ft * box["height"]),
                "width": max(1, int(fw * box["width"])),
                "height": max(1, int(fh * box["height"])),
            }
        shot = sct.grab(box)
        frame = np.asarray(shot)  # BGRA
    return frame[:, :, :3].copy()
