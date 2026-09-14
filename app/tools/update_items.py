# -*- coding: utf-8 -*-
"""Снимок справочника предметов: названия, картинки, цена, тип.

Запуск:  python3 app/tools/update_items.py

Полный /constants/items весит 336 КБ и на слабом канале не доходит.
Здесь оставлены только нужные поля — 11 КБ в сжатом виде. Справочник
меняется редко, раз в патч, поэтому живёт в репозитории.
"""
import gzip
import json
import os
import subprocess
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
OUT = os.path.join(APP, "data", "items_fallback.json.gz")


def main():
    out = subprocess.run(
        ["curl", "-sS", "-L", "--compressed", "--max-time", "120",
         "https://api.opendota.com/api/constants/items"],
        capture_output=True, text=True, check=True)
    items = json.loads(out.stdout)

    # «часть» - базовый предмет (сам ни из чего не собирается), который
    # входит в состав другого: Ogre Axe, Reaver, Soul Booster. По метке qual
    # это не определить: component стоит и на Blink Dagger, а у Soul Booster
    # стоит epic. Blink - единственная базовая часть, которую носят как есть.
    used_in = set()
    for it in items.values():
        if isinstance(it, dict):
            used_in.update(c for c in (it.get("components") or []) if isinstance(c, str))
    standalone = {"blink", "ghost"}
    # промежуточные сборки, которые сами собираются из частей, но носить
    # их как есть никто не будет - по данным их от Vanguard не отличить
    intermediate = {"soul_booster"}

    slim = {}
    for name, it in items.items():
        if not isinstance(it, dict) or not it.get("dname"):
            continue
        slim[name] = {
            "id": it.get("id"),
            "dname": it.get("dname"),
            "img": (it.get("img") or "").split("?")[0],
            "cost": it.get("cost"),
            "qual": it.get("qual"),
            "part": name in intermediate or (
                not it.get("components") and name in used_in and name not in standalone),
        }
    parts = sorted(n for n, v in slim.items() if v["part"])
    print(f"частей: {len(parts)}: {', '.join(parts)}")

    payload = {
        "_комментарий": "Урезанный справочник предметов OpenDota. "
                        "Пересобрать: python3 app/tools/update_items.py",
        "снято": date.today().isoformat(),
        "items": slim,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with gzip.open(OUT, "wt", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    print(f"предметов: {len(slim)}, файл {os.path.getsize(OUT) / 1024:.0f} КБ")
    print("записано:", OUT)


if __name__ == "__main__":
    sys.exit(main())
