# -*- coding: utf-8 -*-
"""Сохраняет снимок heroStats в репозиторий как запасной источник.

Нужен для холодного старта: если сеть недоступна или ответ не доходит,
приложение поднимется на этом снимке и покажет предупреждение, что данные
не свежие, вместо пустого интерфейса.
"""
import gzip
import json
import os
import subprocess
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "data", "herostats_fallback.json.gz")

raw = subprocess.run(
    ["curl", "-sS", "-L", "--compressed", "--max-time", "60",
     "https://api.opendota.com/api/heroStats"],
    capture_output=True, text=True, check=True).stdout
data = json.loads(raw)

payload = {
    "_комментарий": "Снимок heroStats на случай, когда сеть недоступна. "
                    "Пересоздать: python3 app/tools/update_fallback.py",
    "снято": date.today().isoformat(),
    "heroes": data,
}

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with gzip.open(OUT, "wt", encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False)

print(f"героев в снимке: {len(data)}")
print(f"размер файла: {os.path.getsize(OUT) / 1024:.0f} КБ")
print("записано:", OUT)
