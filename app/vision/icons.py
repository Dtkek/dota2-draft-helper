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


def ensure_icons(source, progress=None, workers=4):
    """Скачивает портреты всех героев.

    Возвращает (скачано, не удалось, всего, причина_последней_ошибки).
    Причина обязательна: без неё «0 из 127» ничего не объясняет.

    Качаем в несколько потоков: 127 файлов по одному — это минута даже
    на быстром канале, а при подвисании каждого запроса — десятки минут.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    stats = source.hero_stats()
    todo = []
    for h in stats:
        dest = portrait_path(h["id"])
        if os.path.exists(dest) and os.path.getsize(dest) > 0:
            continue
        img = h.get("img")
        if img:
            todo.append((CDN + img.split("?")[0], dest))

    downloaded = failed = 0
    last_error = None
    done = len(stats) - len(todo)
    if progress:
        progress(done, len(stats))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(net.download, url, dest): url for url, dest in todo}
        for fut in as_completed(futures):
            ok, err = fut.result()
            if ok:
                downloaded += 1
            else:
                failed += 1
                last_error = f"{futures[fut].rsplit('/', 1)[-1]} — {err}"
            done += 1
            if progress:
                progress(done, len(stats))
    return downloaded, failed, len(stats), last_error


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
