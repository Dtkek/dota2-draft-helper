# -*- coding: utf-8 -*-
"""Собирает снимок матчапов всех героев в репозиторий.

Запуск:  python3 app/tools/update_matchups.py

Зачем
-----
Подбор героев делает по запросу к OpenDota на каждого героя противника.
На быстром канале это незаметно, но у OpenDota бывает жёсткое ограничение
скорости на отдельных направлениях: замеры с машины пользователя показали
около 2 КБ/с, то есть 20-40 секунд на запрос. Три врага в драфте
превращались в минуты ожидания, и приложение выглядело зависшим.

Снимок решает это полностью: матчапы всех героев лежат рядом с кодом,
подбор работает мгновенно и вообще без сети. Обновлять раз в патч.
"""
import gzip
import json
import os
import sys
import time
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
sys.path.insert(0, APP)

import net  # noqa: E402
from sources import get_source  # noqa: E402

OUT = os.path.join(APP, "data", "matchups_fallback.json.gz")
API = "https://api.opendota.com/api"

# у OpenDota без ключа лимит 60 запросов в минуту — идём с запасом
PAUSE = 1.2


def main():
    src = get_source()
    heroes = src.hero_stats()
    print(f"героев: {len(heroes)}, пойдёт примерно "
          f"{len(heroes) * PAUSE / 60:.0f} мин")

    data = {}
    failed = []
    for i, h in enumerate(heroes, 1):
        hid = h["id"]
        try:
            rows = net.get_json(f"{API}/heroes/{hid}/matchups", ttl=0)
            # оставляем только нужные поля: файл и так пойдёт в репозиторий
            data[str(hid)] = [
                [r["hero_id"], r["games_played"], r["wins"]]
                for r in rows if r.get("games_played")
            ]
        except Exception as e:  # noqa: BLE001
            failed.append((hid, h.get("localized_name"), str(e)[:80]))
        if i % 20 == 0 or i == len(heroes):
            print(f"  {i}/{len(heroes)}", flush=True)
        time.sleep(PAUSE)

    if failed:
        print(f"\nне удалось получить: {len(failed)}")
        for hid, name, err in failed[:10]:
            print(f"  {hid} {name}: {err}")

    payload = {
        "_комментарий": "Снимок матчапов героев: сколько игр и побед у героя "
                        "против каждого другого. Формат строки: "
                        "[id соперника, игр, побед]. "
                        "Пересобрать: python3 app/tools/update_matchups.py",
        "снято": date.today().isoformat(),
        "matchups": data,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with gzip.open(OUT, "wt", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)

    pairs = sum(len(v) for v in data.values())
    print(f"\nгероев в снимке: {len(data)}, пар героев: {pairs}")
    print(f"размер файла: {os.path.getsize(OUT) / 1024:.0f} КБ")
    print("записано:", OUT)


if __name__ == "__main__":
    main()
