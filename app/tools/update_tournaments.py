# -*- coding: utf-8 -*-
"""Снимок турнирной статистики героев в репозиторий.

Запуск:  python3 app/tools/update_tournaments.py

Зачем: турнирная составляющая подбора собирается несколькими запросами к
базе OpenDota (/explorer), по секундам каждый, а при сбоях базы - по
минутам. Во время пика ждать это нельзя. Со снимком подбор с первого же
запуска считается мгновенно, а свежие данные подтягиваются в фоне.
В репозитории снимок обновляет CI раз в неделю вместе со снимком STRATZ.

Внутри: пики, баны и победы каждого героя за 1, 3 и 6 месяцев по турнирам
уровня Premium + Professional (tier «top») - ровно то, что использует подбор.
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

from sources import get_source  # noqa: E402

OUT = os.path.join(APP, "data", "tournament_fallback.json.gz")
MONTHS = (1, 3, 6)
TIERS = ("top",)


def main():
    src = get_source()
    stats = {}
    failed = []
    started = time.time()
    for tier in TIERS:
        stats[tier] = {}
        for months in MONTHS:
            try:
                rows, total = src.tournament_stats(months, tier)
                stats[tier][str(months)] = {"rows": rows, "total": total}
                print(f"  {tier} / {months} мес: матчей {total}, героев {len(rows)}", flush=True)
            except Exception as e:  # noqa: BLE001
                failed.append((tier, months, str(e)[:120]))
                print(f"  {tier} / {months} мес: НЕ УДАЛОСЬ - {str(e)[:120]}", flush=True)

    if not any(stats[t] for t in stats):
        print("ни одного периода не собрано, снимок не записан", file=sys.stderr)
        return 1

    payload = {
        "_комментарий": "Снимок турнирной статистики героев: пики, баны, победы "
                        "за период по уровню турниров. Пересобрать: "
                        "python3 app/tools/update_tournaments.py",
        "снято": date.today().isoformat(),
        "stats": stats,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + ".tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    os.replace(tmp, OUT)

    print(f"\nразмер файла: {os.path.getsize(OUT) / 1024:.0f} КБ, {time.time() - started:.0f} с")
    if failed:
        print(f"не собрано: {failed}")
    print("записано:", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
