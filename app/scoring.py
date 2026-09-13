# -*- coding: utf-8 -*-
"""Подбор героев против вражеского драфта.

Как считается оценка
--------------------
Итоговый балл героя H против вражеского драфта E складывается из двух частей:

    score(H) = W_MATCHUP * Σ_{e∈E} adv(H, e) + W_BASE * (winrate(H) − средний winrate)

1. adv(H, e) — насколько H лучше играет против e, чем e играет в среднем.
   Считается из матчапов: если e против H побеждает реже, чем вообще,
   значит H его контрит.

2. Вторая часть — базовая сила героя в выбранном ранге. Без неё подбор начнёт
   советовать слабых героев только потому, что у них удачный матчап.

Откуда берутся матчапы
----------------------
OpenDota отдаёт матчапы по публичным матчам: около 9000 игр на героя,
распределённых по 126 соперникам, отсюда медиана всего ~30 игр на пару.
Базовый винрейт соперника считается по этой же таблице (сумма побед делить на
сумму игр). Смешивать датасеты нельзя: поля pro_win/pro_pick сейчас почти
пустые — у отдельных героев там 3 игры из 3, что дало бы «базу» в 100%
и сделало бы все оценки бессмысленными.

Сглаживание
-----------
При n=30 разброс винрейта — примерно ±9 процентных пунктов, то есть сырое число
почти ничего не значит. Поэтому каждое преимущество умножается на n / (n + K):
при маленькой выборке оценка прижимается к нулю, при большой — работает почти
целиком. K задаётся в K_SHRINK.

Чего здесь нет
--------------
Синергии между союзниками: OpenDota не отдаёт винрейт пар героев в одной
команде. Своих героев мы учитываем только как «этих уже нельзя брать».
"""

# вес матчапов и вес базовой силы героя в итоговом балле
W_MATCHUP = 1.0
W_BASE = 0.6

# границы — только страховка от вырожденных данных, не рабочая настройка
K_MIN, K_MAX = 20, 2000

# ранг с числом пиков меньше этого считаем непоказательным
MIN_PICKS = 200


def _safe_ratio(wins, games):
    return (wins / games) if games else None


def build_base_winrates(source, bracket):
    """Базовый винрейт каждого героя в выбранном ранге + средний по всем."""
    stats = source.hero_stats()
    base = {}
    for h in stats:
        picks, wins = source.picks_wins(h, bracket)
        base[h["id"]] = _safe_ratio(wins, picks) if picks >= MIN_PICKS else None
    known = [v for v in base.values() if v is not None]
    mean = sum(known) / len(known) if known else 0.5
    return base, mean, {h["id"]: h for h in stats}


def raw_matchup_table(source, enemy_id):
    """Несглаженные преимущества против enemy_id: {hero_id: (raw_adv, n, p)}.

    Базовый винрейт соперника берётся из его же таблицы матчапов, а не из
    heroStats: только так числитель и знаменатель считаются по одной выборке.
    """
    rows = source.matchups(enemy_id)
    total_games = sum((r.get("games_played") or 0) for r in rows)
    total_wins = sum((r.get("wins") or 0) for r in rows)
    baseline = _safe_ratio(total_wins, total_games)
    if baseline is None:
        return {}

    table = {}
    for row in rows:
        n = row.get("games_played") or 0
        if n <= 0:
            continue
        # wins в ответе — победы enemy_id против этого героя
        p = (row.get("wins") or 0) / n
        table[row["hero_id"]] = (baseline - p, n, p)
    return table


def estimate_k(tables):
    """Оценивает силу сглаживания K по самим данным (эмпирический байес).

    Разброс наблюдаемых преимуществ складывается из настоящего эффекта контрпика
    и шума малой выборки:

        Var(наблюдаемое) ≈ Var(истинное) + среднее(p(1-p)/n)

    Отсюда Var(истинное) = Var(наблюдаемое) − шум, а оптимальный коэффициент
    сжатия для пары — n / (n + K), где K = p(1-p) / Var(истинное).

    Смысл простой: чем сильнее наблюдаемый разброс объясняется шумом, тем больше
    K и тем жёстче оценки прижимаются к нулю. Считается по тем же таблицам,
    которые уже загружены для текущего запроса, — лишних обращений к API нет.

    Более известную оценку DerSimonian–Laird здесь применять нельзя: объёмы
    выборок различаются в сотни раз, её знаменатель вырождается, и она выдаёт
    заведомо абсурдный разброс. Простая оценка при этом несмещённая.
    """
    advs, noises = [], []
    for table in tables.values():
        for raw_adv, n, p in table.values():
            advs.append(raw_adv)
            noises.append(p * (1 - p) / n)
    if len(advs) < 30:
        return K_MAX

    mean_adv = sum(advs) / len(advs)
    var_observed = sum((a - mean_adv) ** 2 for a in advs) / len(advs)
    mean_noise = sum(noises) / len(noises)
    var_true = var_observed - mean_noise
    if var_true <= 0:
        # весь разброс объясняется шумом — значит, настоящего сигнала не видно
        return K_MAX
    k = 0.25 / var_true
    return max(K_MIN, min(K_MAX, k))


def shrink(tables, k):
    """Применяет сглаживание: {enemy_id: {hero_id: (adv, n)}}."""
    out = {}
    for enemy_id, table in tables.items():
        out[enemy_id] = {
            hero_id: (raw_adv * n / (n + k), n)
            for hero_id, (raw_adv, n, _p) in table.items()
        }
    return out


def matchup_tables(source, enemy_ids):
    """Сглаженные таблицы матчапов + использованное значение K."""
    raw = {e: raw_matchup_table(source, e) for e in enemy_ids}
    k = estimate_k(raw)
    return shrink(raw, k), k


def recommend(source, enemy_ids, ally_ids=(), banned_ids=(), bracket="all",
              role=None, limit=15, allowed_ids=None):
    """Топ героев против вражеского драфта.

    enemy_ids — герои противника, ally_ids — уже взятые свои,
    banned_ids — забаненные. Возвращает список словарей, отсортированный по баллу.
    """
    enemy_ids = [int(x) for x in enemy_ids]
    excluded = set(int(x) for x in list(ally_ids) + list(banned_ids)) | set(enemy_ids)

    base, mean_base, stats_by_id = build_base_winrates(source, bracket)
    tables, k_used = matchup_tables(source, enemy_ids)

    results = []
    for hero_id, stat in stats_by_id.items():
        if hero_id in excluded:
            continue
        # allowed_ids — фильтр по позиции: он приходит снаружи, потому что
        # позиции берутся из отдельного справочника, а не из данных источника
        if allowed_ids is not None and hero_id not in allowed_ids:
            continue
        if role and role not in (stat.get("roles") or []):
            continue

        per_enemy = []
        matchup_sum = 0.0
        games_total = 0
        for e in enemy_ids:
            adv, n = tables[e].get(hero_id, (0.0, 0))
            matchup_sum += adv
            games_total += n
            per_enemy.append({"enemy_id": e, "adv_pp": round(adv * 100, 2), "games": n})

        # среднее, а не сумма: складывать пять матчапов значит утверждать, что
        # они независимы и складываются один к одному — это неверно и завышает
        # оценку в разы. На порядок героев среднее не влияет, зато число
        # остаётся интерпретируемым: «столько винрейта против типичного из них».
        matchup_avg = matchup_sum / len(enemy_ids)

        hero_base = base.get(hero_id)
        base_delta = (hero_base - mean_base) if hero_base is not None else 0.0
        score = W_MATCHUP * matchup_avg + W_BASE * base_delta

        results.append({
            "hero_id": hero_id,
            "name": stat.get("localized_name"),
            "img": stat.get("img"),
            "roles": stat.get("roles") or [],
            "primary_attr": stat.get("primary_attr"),
            # вклады уже с весами, чтобы matchup_pp + base_pp == score_pp
            "score_pp": round(score * 100, 2),
            "matchup_pp": round(W_MATCHUP * matchup_avg * 100, 2),
            "base_pp": round(W_BASE * base_delta * 100, 2),
            "base_winrate": round(hero_base * 100, 2) if hero_base is not None else None,
            "games_total": games_total,
            "per_enemy": per_enemy,
        })

    results.sort(key=lambda r: r["score_pp"], reverse=True)
    return results[:limit], round(k_used)


def draft_edge(source, radiant_ids, dire_ids, bracket="all"):
    """Кто выигрывал по матчапам на стадии драфта. Для разбора про-матчей.

    Возвращает суммарное преимущество Radiant в процентных пунктах и разбивку
    по героям: у кого из Radiant драфт сложился удачно, у кого нет.
    """
    _, _, stats_by_id = build_base_winrates(source, bracket)
    tables, k_used = matchup_tables(source, dire_ids)

    per_hero = []
    total = 0.0
    for h in radiant_ids:
        # как и в recommend: среднее по соперникам, а не сумма
        adv = (sum(tables[e].get(h, (0.0, 0))[0] for e in dire_ids)
               / max(len(dire_ids), 1))
        games = sum(tables[e].get(h, (0.0, 0))[1] for e in dire_ids)
        total += adv
        stat = stats_by_id.get(h, {})
        per_hero.append({
            "hero_id": h,
            "name": stat.get("localized_name"),
            "img": stat.get("img"),
            "adv_pp": round(adv * 100, 2),
            "games": games,
        })
    per_hero.sort(key=lambda r: r["adv_pp"], reverse=True)
    # среднее по героям Radiant: «типичный герой Radiant имел столько-то
    # преимущества против типичного героя Dire»
    total /= max(len(radiant_ids), 1)
    return {
        "radiant_edge_pp": round(total * 100, 2),
        "radiant_heroes": per_hero,
        "k_shrink": round(k_used),
    }
