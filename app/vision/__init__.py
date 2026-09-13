# -*- coding: utf-8 -*-
"""Модуль распознавания экрана.

Зависимости (opencv, numpy, mss, Pillow) опциональные: если их нет,
приложение работает как обычно, просто без чтения экрана.
"""

MISSING = []

try:
    import cv2  # noqa: F401
except ImportError:
    MISSING.append("opencv-python")

try:
    import numpy  # noqa: F401
except ImportError:
    MISSING.append("numpy")

try:
    import mss  # noqa: F401
except ImportError:
    MISSING.append("mss")

AVAILABLE = not MISSING


def requirements_hint():
    if AVAILABLE:
        return None
    return ("не установлены пакеты: " + ", ".join(MISSING) +
            ". Установите: pip install -r requirements-vision.txt")
