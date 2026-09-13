# -*- coding: utf-8 -*-
"""Обновляет справочник позиций героев по данным OpenDota.

Запуск:  python3 app/tools/update_positions.py

Откуда берутся позиции
----------------------
Готового поля «позиция» у OpenDota нет. Зато есть /explorer — произвольный
SQL по их базе матчей, где у каждого игрока проставлен lane_role:
1 — лёгкая линия, 2 — центр, 3 — сложная, 4 — лес.

Линия — ещё не позиция: на лёгкой линии стоят и керри, и хардсаппорт,
на сложной — оффлейнер и роумер, да и в центре нередко оказывается
саппорт на ротации. Разделяем по фарму: внутри своей пятёрки игроки
ранжируются по золоту в минуту, первые три считаются корами, остальные —
саппортами независимо от того, на какой линии их застал разбор матча.
Без этого правила Earthshaker получал 48% «мида», хотя это саппорт,
которого разбор матча застал в центре.

На проверочных героях результат сходится: Anti-Mage — 92% позиция 1,
Crystal Maiden — 93% позиция 5, Storm Spirit — 97% центр.

Важно: база /explorer — это профессиональные матчи. В обычных играх
расстановка бывает другой.
"""
import json
import os
import subprocess
import sys
import urllib.parse
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
sys.path.insert(0, APP)

OUT = os.path.join(APP, "data", "positions.json")
API = "https://api.opendota.com/api/explorer"

# позицию оставляем в справочнике, если герой играет её хотя бы в такой доле игр
MIN_SHARE = 10
# и не больше стольких позиций на героя, чтобы фильтр оставался осмысленным
MAX_POSITIONS = 3
# сколько месяцев матчей берём
MONTHS = 12

SQL = """
with ranked as (
  select
    pm.hero_id,
    pm.lane_role,
    pm.is_roaming,
    row_number() over (
      partition by pm.match_id, (pm.player_slot < 128)
      order by pm.gold_per_min desc
    ) as farm_rank
  from player_matches pm
  join matches m on m.match_id = pm.match_id
  where pm.lane_role is not null
    and pm.gold_per_min is not null
    and m.start_time > extract(epoch from now() - interval '%d months')
)
select
  hero_id,
  case
    when is_roaming then 4
    when lane_role = 4 then 4
    when farm_rank > 3 and lane_role = 1 then 5
    when farm_rank > 3 then 4
    when lane_role = 1 then 1
    when lane_role = 2 then 2
    when lane_role = 3 then 3
  end as position,
  count(*) as games
from ranked
group by hero_id, position
order by hero_id, games desc
""" % MONTHS


def query(sql, timeout=300):
    url = API + "?sql=" + urllib.parse.quote(sql)
    out = subprocess.run(["curl", "-sS", "--max-time", str(timeout), url],
                         capture_output=True, text=True)
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError:
        raise SystemExit("OpenDota вернул не JSON: " + out.stdout[:300])


def main():
    print("запрашиваю позиции у OpenDota, это займёт до минуты…")
    res = query(SQL)
    rows = res.get("rows") if isinstance(res, dict) else None
    if not rows:
        raise SystemExit("пустой ответ: " + str(res)[:300])
    print(f"строк получено: {len(rows)}")

    by_hero = {}
    for r in rows:
        if r.get("position") is None:
            continue
        by_hero.setdefault(int(r["hero_id"]), []).append(
            (int(r["position"]), int(r["games"])))

    positions, shares = {}, {}
    total_games = 0
    for hero_id, data in sorted(by_hero.items()):
        total = sum(g for _, g in data)
        total_games += total
        if not total:
            continue
        ranked = sorted(((p, round(g * 100 / total)) for p, g in data),
                        key=lambda t: -t[1])
        kept = [p for p, share in ranked if share >= MIN_SHARE][:MAX_POSITIONS]
        if not kept:  # герой почти не играется — берём самую частую позицию
            kept = [ranked[0][0]]
        positions[str(hero_id)] = kept
        shares[str(hero_id)] = {str(p): s for p, s in ranked if s > 0}

    payload = {
        "_комментарий": [
            "Позиции героев. Файл собран автоматически из базы матчей OpenDota,",
            "не заполнен вручную. Пересобрать: python3 app/tools/update_positions.py",
            "Источник — профессиональные матчи, в обычных играх расстановка",
            "может отличаться. Позиции меняются от патча к патчу, файл можно",
            "править руками: ключ — id героя, значение — список позиций.",
            "1 — керри, 2 — мид, 3 — хард, 4 — роумер, 5 — хардсаппорт.",
            "В shares видно, в какой доле игр герой встречался на каждой позиции.",
        ],
        "источник": f"OpenDota /explorer, профессиональные матчи за {MONTHS} мес.",
        "обновлено": date.today().isoformat(),
        "порог_доли_процентов": MIN_SHARE,
        "всего_записей_игроков": total_games,
        "positions": positions,
        "shares": shares,
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)

    print(f"героев с позициями: {len(positions)}")
    print(f"записей игроков в выборке: {total_games}")
    print("записано:", OUT)

    try:
        from sources import get_source
        names = {h["id"]: h["localized_name"] for h in get_source().hero_stats()}
    except Exception:  # noqa: BLE001 — контроль необязателен
        return
    print("\nконтроль на героях с очевидной позицией:")
    for hid in (1, 5, 11, 26, 29, 44, 86, 96, 17):
        sh = shares.get(str(hid), {})
        top = ", ".join(f"поз.{p}: {s}%" for p, s in
                        sorted(sh.items(), key=lambda t: -t[1])[:3])
        print(f"  {names.get(hid, hid):<20} {top}")


if __name__ == "__main__":
    main()
