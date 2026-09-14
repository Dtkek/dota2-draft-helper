# -*- coding: utf-8 -*-
"""Снимок справочников способностей: id → имя, способности и таланты героев,
названия и картинки. Нужен для показа прокачки и талантов.

Запуск:  python3 app/tools/update_abilities.py

Полный /constants/abilities весит 259 КБ; здесь остаются только способности
и таланты героев, с названием и картинкой - десятки килобайт в сжатом виде.

Числа талантов. OpenDota хранит название уникального таланта шаблоном без
числа: «+{s:bonus_heal_per_second} Living Armor Heal Per Second». Само число
лежит в игровых файлах героя (scripts/npc/heroes/npc_dota_hero_*.txt), в блоке
значения способности, под ключом с именем таланта:

    "heal_per_second" { "value" "4 7 10 13"  "special_bonus_unique_treant_8" "+3" }

Файлы берутся из открытого зеркала игровых ресурсов dotabuff/d2vpkr на GitHub.
Если зеркало недоступно, шаблон остаётся как есть - сервер покажет название
без числа и пометит его.
"""
import gzip
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
OUT = os.path.join(APP, "data", "abilities_fallback.json.gz")
API = "https://api.opendota.com/api/constants/"
VPK = "https://raw.githubusercontent.com/dotabuff/d2vpkr/master/dota/scripts/npc/"


def curl(url):
    out = subprocess.run(["curl", "-sS", "-L", "--compressed", "--max-time", "120", url],
                         capture_output=True, text=True, check=True)
    return out.stdout


def fetch(name):
    return json.loads(curl(API + name))


# --- KeyValues Valve --------------------------------------------------------

_TOKEN = re.compile(r'"((?:[^"\\]|\\.)*)"|(\{)|(\})|(//[^\n]*)|(\[[^\]]*\])|([^\s"{}]+)')


def parse_kv(text):
    """Разбор формата KeyValues: вложенные блоки {ключ: строка | блок}.
    Комментарии // и условия [$WIN32] пропускаются. Повторный ключ
    перезаписывает предыдущий - для наших нужд этого достаточно."""
    root = {}
    stack = [root]
    key = None
    for m in _TOKEN.finditer(text):
        s, open_, close, comment, cond, bare = m.groups()
        if comment is not None or cond is not None:
            continue
        if open_:
            block = {}
            stack[-1][key] = block
            stack.append(block)
            key = None
        elif close:
            stack.pop()
            key = None
        else:
            tok = s if s is not None else bare
            if key is None:
                key = tok
            else:
                stack[-1][key] = tok
                key = None
    return root


def find_talent_values(node, talent, path=()):
    """Все места в дереве, где ключ равен имени таланта: [(путь, значение)].
    Путь нужен, чтобы из нескольких совпадений выбрать то, что называет
    шаблон: {s:bonus_heal_per_second} → ключ heal_per_second."""
    found = []
    if not isinstance(node, dict):
        return found
    for k, v in node.items():
        if k == talent and not isinstance(v, dict):
            found.append((path, v))
        elif isinstance(v, dict):
            found.extend(find_talent_values(v, talent, path + (k,)))
    return found


def own_value(tree, talent):
    """Значение из блока самого таланта: AbilityValues.value или старый
    формат AbilitySpecial.NN.value."""
    block = None
    for top in tree.values():
        if isinstance(top, dict) and isinstance(top.get(talent), dict):
            block = top[talent]
            break
    if not block:
        return None
    av = block.get("AbilityValues")
    if isinstance(av, dict):
        v = av.get("value")
        if isinstance(v, dict):
            v = v.get("value")
        if v is not None:
            return v
    sp = block.get("AbilitySpecial")
    if isinstance(sp, dict):
        for entry in sp.values():
            if isinstance(entry, dict) and "value" in entry:
                return entry["value"]
    return None


_TPL = re.compile(r"\{s:([^}]+)\}")


def resolve_dname(dname, talent, hero_tree, generic_tree):
    """Подставить числа в шаблон таланта. Возвращает (название, все ли
    подстановки удались)."""
    ok = True

    def sub(m):
        nonlocal ok
        var = m.group(1)
        val = None
        if var == "value":
            val = own_value(hero_tree, talent) or own_value(generic_tree, talent)
        else:
            want = var[len("bonus_"):] if var.startswith("bonus_") else var
            hits = find_talent_values(hero_tree, talent) or find_talent_values(generic_tree, talent)
            exact = [v for p, v in hits if p and p[-1].lower() == want.lower()]
            if exact:
                val = exact[0]
            elif hits:
                val = hits[0][1]
            else:
                val = own_value(hero_tree, talent) or own_value(generic_tree, talent)
        if val is None:
            ok = False
            return m.group(0)
        val = str(val).strip()
        # знак стоит и в шаблоне («+{s:...}»), и в значении («+3», а у
        # замедлений даже «+-10»): в шаблоне знак смысловой, в значении - нет
        before = dname[:m.start()]
        if before.endswith(("+", "-")):
            val = val.lstrip("+-")
        # процент тоже бывает с обеих сторон: «{s:...}%» и «-25%»
        if val.endswith("%") and dname[m.end():m.end() + 1] == "%":
            val = val[:-1]
        return val

    return _TPL.sub(sub, dname), ok


def load_hero_tree(hero):
    try:
        return parse_kv(curl(VPK + f"heroes/{hero}.txt"))
    except (subprocess.CalledProcessError, ValueError):
        return {}


def main():
    ids = fetch("ability_ids")          # {"5435": "treant_natures_grasp", ...}
    heroes = fetch("hero_abilities")    # {"npc_dota_hero_treant": {abilities, talents}}
    abilities = fetch("abilities")      # {"treant_living_armor": {dname, img, ...}}

    used = set()
    slim_heroes = {}
    for hero, h in heroes.items():
        # у некоторых героев элемент списка - сам список (варианты способности)
        abil = []
        for a in h.get("abilities") or []:
            for x in (a if isinstance(a, list) else [a]):
                if isinstance(x, str) and x and x != "generic_hidden":
                    abil.append(x)
        talents = [{"name": t["name"], "level": t.get("level")}
                   for t in (h.get("talents") or []) if t.get("name")]
        slim_heroes[hero] = {"abilities": abil, "talents": talents}
        used.update(abil)
        used.update(t["name"] for t in talents)

    slim_abilities = {}
    for name in used:
        a = abilities.get(name) or {}
        slim_abilities[name] = {
            "dname": a.get("dname") or name,
            "img": (a.get("img") or "").split("?")[0] or None,
        }

    # числа талантов из игровых файлов
    try:
        generic_tree = parse_kv(curl(VPK + "npc_abilities.txt"))
    except (subprocess.CalledProcessError, ValueError):
        generic_tree = {}
    names = sorted(slim_heroes)
    with ThreadPoolExecutor(max_workers=8) as pool:
        trees = dict(zip(names, pool.map(load_hero_tree, names)))

    resolved = unresolved = 0
    missing = []
    for hero, h in slim_heroes.items():
        tree = trees.get(hero) or {}
        for t in h["talents"]:
            entry = slim_abilities[t["name"]]
            if "{s:" not in entry["dname"]:
                continue
            new, ok = resolve_dname(entry["dname"], t["name"], tree, generic_tree)
            if ok:
                entry["dname"] = new
                resolved += 1
            else:
                unresolved += 1
                missing.append(f"{hero}: {t['name']} = {entry['dname']}")

    payload = {
        "_комментарий": "Урезанные справочники способностей OpenDota; числа талантов "
                        "из игровых файлов (dotabuff/d2vpkr). "
                        "Пересобрать: python3 app/tools/update_abilities.py",
        "снято": date.today().isoformat(),
        "ids": {str(k): v for k, v in ids.items() if v in used},
        "heroes": slim_heroes,
        "abilities": slim_abilities,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with gzip.open(OUT, "wt", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    print(f"героев: {len(slim_heroes)}, способностей и талантов: {len(slim_abilities)}, "
          f"id: {len(payload['ids'])}, файл {os.path.getsize(OUT) / 1024:.0f} КБ")
    print(f"талантов с числом из игровых файлов: {resolved}, без числа: {unresolved}")
    for line in missing[:20]:
        print("  нет числа:", line)
    t = slim_heroes.get("npc_dota_hero_treant", {})
    print("таланты Treant:", [slim_abilities[x["name"]]["dname"] for x in t.get("talents", [])])
    print("записано:", OUT)


if __name__ == "__main__":
    sys.exit(main())
