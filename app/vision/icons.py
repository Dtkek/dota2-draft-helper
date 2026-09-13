# -*- coding: utf-8 -*-
"""Эталонные изображения героев для распознавания экрана.

Портреты берутся с того же CDN, которым пользуется сам клиент Dota 2,
поэтому на экране драфта они совпадают с эталонами почти пиксель в пиксель —
отличается только масштаб.
"""
import os

import net

CDN = "https://cdn.cloudflare.steamstatic.com"
ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "assets", "heroes")


def portrait_path(hero_id):
    return os.path.join(ASSETS, f"{hero_id}.png")


def ensure_icons(source, progress=None):
    """Скачивает портреты всех героев. Возвращает (скачано, пропущено, всего).

    Вызывается один раз: дальше файлы лежат локально и сеть не нужна.
    """
    stats = source.hero_stats()
    downloaded = failed = 0
    for i, h in enumerate(stats):
        dest = portrait_path(h["id"])
        if os.path.exists(dest) and os.path.getsize(dest) > 0:
            continue
        img = h.get("img")
        if not img:
            failed += 1
            continue
        url = CDN + img.split("?")[0]
        if net.download(url, dest):
            downloaded += 1
        else:
            failed += 1
        if progress:
            progress(i + 1, len(stats))
    return downloaded, failed, len(stats)


def available_ids():
    """id героев, для которых портрет уже лежит на диске."""
    if not os.path.isdir(ASSETS):
        return []
    out = []
    for name in os.listdir(ASSETS):
        stem, ext = os.path.splitext(name)
        if ext.lower() == ".png" and stem.isdigit():
            out.append(int(stem))
    return sorted(out)
