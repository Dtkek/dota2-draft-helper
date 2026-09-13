# -*- coding: utf-8 -*-
"""Источник данных OpenDota — публичный API, ключ не нужен.

Ограничения, которые важно понимать при чтении рекомендаций:
матчапы «герой против героя» OpenDota отдаёт по профессиональным матчам,
и выборка там небольшая — медиана около 30 игр на пару героев. Поэтому
в scoring.py применяется сглаживание, а в интерфейсе показывается объём выборки.
"""
import gzip
import json
import os

import net
from net import get_json
from sources.base import HeroSource

API = "https://api.opendota.com/api"

FALLBACK = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "herostats_fallback.json.gz")

MATCHUPS_FALLBACK = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "matchups_fallback.json.gz")

ITEMS_FALLBACK = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "items_fallback.json.gz")

_fallback_cache = None
fallback_date = None
_matchups_cache = None
matchups_date = None
_items_cache = None


def _load_items():
    global _items_cache
    if _items_cache is not None:
        return _items_cache
    try:
        with gzip.open(ITEMS_FALLBACK, "rt", encoding="utf-8") as f:
            _items_cache = json.load(f).get("items") or {}
    except (OSError, ValueError):
        _items_cache = {}
    return _items_cache


def _load_matchups():
    """Снимок матчапов, приложенный к репозиторию: {id героя: [[id, игр, побед]]}."""
    global _matchups_cache, matchups_date
    if _matchups_cache is not None:
        return _matchups_cache
    try:
        with gzip.open(MATCHUPS_FALLBACK, "rt", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, ValueError):
        _matchups_cache = {}
        return _matchups_cache
    _matchups_cache = payload.get("matchups") or {}
    matchups_date = payload.get("снято")
    return _matchups_cache


def _load_fallback():
    """Читает снимок справочника, приложенный к репозиторию."""
    global _fallback_cache, fallback_date
    if _fallback_cache is not None:
        return _fallback_cache
    try:
        with gzip.open(FALLBACK, "rt", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, ValueError):
        return None
    _fallback_cache = payload.get("heroes")
    fallback_date = payload.get("снято")
    return _fallback_cache

# час для меты, сутки для справочника героев: герои меняются куда реже статистики
TTL_HEROES = 24 * 3600
TTL_STATS = 3600
TTL_MATCHUPS = 6 * 3600
TTL_PRO_LIST = 600
TTL_MATCH = 7 * 24 * 3600
TTL_TOURNAMENT = 6 * 3600


def _explorer(sql, ttl):
    """Запрос к базе OpenDota через /explorer с кэшем, как у остальных данных."""
    import urllib.parse
    url = f"{API}/explorer?sql={urllib.parse.quote(' '.join(sql.split()))}"
    return get_json(url, ttl=ttl, timeout=120)


class OpenDotaSource(HeroSource):
    name = "OpenDota"

    # у OpenDota поля вида 1_pick..8_pick — это ранги от Herald до Immortal.
    # Список кандидатов; пустые отсеивает available_brackets().
    brackets = [
        ("all", "Все ранги"),
        ("8", "Immortal"),
        ("7", "Divine"),
        ("6", "Ancient"),
        ("5", "Legend"),
        ("4", "Archon"),
        ("3", "Crusader"),
        ("2", "Guardian"),
        ("1", "Herald"),
        ("turbo", "Turbo"),
    ]

    #: True, если справочник пришёл из локального снимка, а не из сети
    using_fallback = False

    def heroes(self):
        return get_json(f"{API}/heroes", ttl=TTL_HEROES)

    def hero_stats(self):
        """Справочник героев: свежий кэш → снимок с фоновым обновлением → сеть.

        Тот же порядок, что у матчапов, и по той же причине: на медленном
        канале поход в сеть за справочником занимал до полутора минут, и всё
        это время сервер даже не стартовал — окно выглядело зависшим.
        Со снимком запуск мгновенный, а свежие данные подтягиваются фоном
        и подхватятся на следующем запросе.
        """
        url = f"{API}/heroStats"

        fresh = net.cached(url, TTL_STATS)
        if fresh is not None:
            OpenDotaSource.using_fallback = False
            return fresh

        snapshot = _load_fallback()
        if snapshot is not None:
            OpenDotaSource.using_fallback = True
            net.refresh_in_background(url, TTL_STATS)
            return snapshot

        data = get_json(url, ttl=TTL_STATS)
        OpenDotaSource.using_fallback = False
        return data

    def matchups(self, hero_id):
        """Матчапы героя. Снимок в приоритете, сеть — фоном.

        На медленном канале запрос к OpenDota стоит десятки секунд, а на
        драфт из пяти врагов их нужно пять. Поэтому порядок такой:
        свежий кэш → снимок из репозитория (мгновенно, обновление уходит
        в фон) → и только если снимка нет, ждём сеть.
        """
        hero_id = int(hero_id)
        url = f"{API}/heroes/{hero_id}/matchups"

        fresh = net.cached(url, TTL_MATCHUPS)
        if fresh is not None:
            return fresh

        snapshot = _load_matchups().get(str(hero_id))
        if snapshot:
            net.refresh_in_background(url, TTL_MATCHUPS)
            return [{"hero_id": a, "games_played": b, "wins": c}
                    for a, b, c in snapshot]

        return get_json(url, ttl=TTL_MATCHUPS)

    def pro_matches(self):
        return get_json(f"{API}/proMatches", ttl=TTL_PRO_LIST)

    # --- турнирная статистика ------------------------------------------
    # Поля pro_pick/pro_win в heroStats почти пустые, поэтому турнирная
    # статистика считается напрямую по базе матчей через /explorer:
    # picks_bans — драфт, matches — исход, leagues — уровень турнира.

    TIERS = {
        "top": ("premium", "professional"),
        "premium": ("premium",),
        "all": ("premium", "professional", "excluded", "amateur"),
    }

    def tournament_leagues(self, months=3):
        """Турниры за период: id, название, уровень, число матчей."""
        sql = f"""
        select l.leagueid, l.name, l.tier, count(*) as matches
        from matches m join leagues l on l.leagueid = m.leagueid
        where m.start_time > extract(epoch from now() - interval '{int(months)} months')
        group by l.leagueid, l.name, l.tier
        order by matches desc
        limit 60
        """
        return _explorer(sql, ttl=TTL_TOURNAMENT).get("rows") or []

    def tournament_stats(self, months=3, tier="top", leagueid=None):
        """Пики, баны и победы каждого героя в турнирных матчах.

        Возвращает (строки, всего_матчей). Победа засчитывается по стороне:
        team 0 в picks_bans — Radiant, 1 — Dire.
        """
        tiers = self.TIERS.get(tier, self.TIERS["top"])
        tier_sql = ", ".join(f"'{t}'" for t in tiers)
        league_sql = f"and m.leagueid = {int(leagueid)}" if leagueid else ""
        sql = f"""
        with pro as (
          select m.match_id, m.radiant_win
          from matches m join leagues l on l.leagueid = m.leagueid
          where m.start_time > extract(epoch from now() - interval '{int(months)} months')
            and l.tier in ({tier_sql}) {league_sql}
        )
        select * from (
          select pb.hero_id,
            sum(case when pb.is_pick then 1 else 0 end) as picks,
            sum(case when not pb.is_pick then 1 else 0 end) as bans,
            sum(case when pb.is_pick and ((pb.team = 0 and pro.radiant_win)
                  or (pb.team = 1 and not pro.radiant_win)) then 1 else 0 end) as wins,
            (select count(*) from pro) as total_matches
          from picks_bans pb join pro on pro.match_id = pb.match_id
          group by pb.hero_id
        ) t
        order by picks + bans desc
        """
        rows = _explorer(sql, ttl=TTL_TOURNAMENT).get("rows") or []
        total = rows[0]["total_matches"] if rows else 0
        return rows, total

    def match(self, match_id):
        """Матч целиком с /matches/{id} — 45 КБ на проводе и больше.

        На каналах, где соединение обрывается на 20-30 КБ, это никогда
        не доходит. Основной путь теперь match_slim(); этот — запасной.
        """
        return get_json(f"{API}/matches/{int(match_id)}", ttl=TTL_MATCH)

    def match_slim(self, match_id):
        """Только нужные поля матча через базу OpenDota, тремя запросами.

        Каждый кусок — единицы килобайт, чтобы проходить через самый
        капризный канал: шапка с драфтом, игроки со статистикой, закупы.
        Закупы идут отдельно и последними: они самые тяжёлые, и без них
        матч всё равно показать можно. Возвращает структуру, совместимую
        с ответом /matches/{id} в той части, которую использует приложение.
        """
        mid = int(match_id)
        hdr = _explorer(f"""
            select m.match_id, m.radiant_win, m.duration, m.radiant_score,
                   m.dire_score, m.picks_bans, l.name as league,
                   rt.name as radiant_name, dt.name as dire_name
            from matches m
            left join leagues l on l.leagueid = m.leagueid
            left join teams rt on rt.team_id = m.radiant_team_id
            left join teams dt on dt.team_id = m.dire_team_id
            where m.match_id = {mid}
        """, ttl=TTL_MATCH).get("rows") or []
        if not hdr:
            raise RuntimeError(f"матч {mid} не найден в базе OpenDota")
        h = hdr[0]

        players = _explorer(f"""
            select pm.player_slot, pm.hero_id, pm.kills, pm.deaths, pm.assists,
                   pm.gold_per_min, pm.xp_per_min,
                   pm.item_0, pm.item_1, pm.item_2, pm.item_3, pm.item_4,
                   pm.item_5, pm.item_neutral, np.name as player
            from player_matches pm
            left join notable_players np on np.account_id = pm.account_id
            where pm.match_id = {mid}
            order by pm.player_slot
        """, ttl=TTL_MATCH).get("rows") or []

        logs = {}
        try:
            for r in _explorer(f"""
                select pm.player_slot, pm.purchase_log
                from player_matches pm where pm.match_id = {mid}
            """, ttl=TTL_MATCH).get("rows") or []:
                logs[r["player_slot"]] = r.get("purchase_log") or []
        except Exception:  # noqa: BLE001 — без закупов матч всё равно показываем
            pass

        for p in players:
            p["isRadiant"] = p["player_slot"] < 128
            p["name"] = p.get("player")
            p["purchase_log"] = logs.get(p["player_slot"], [])

        return {
            "match_id": h["match_id"],
            "radiant_win": h["radiant_win"],
            "duration": h["duration"],
            "radiant_score": h["radiant_score"],
            "dire_score": h["dire_score"],
            "picks_bans": h.get("picks_bans") or [],
            "league": {"name": h.get("league")},
            "radiant_team": {"name": h.get("radiant_name")},
            "dire_team": {"name": h.get("dire_name")},
            "players": players,
        }

    # --- сборка героя по про-матчам ------------------------------------
    def hero_builds(self, hero_id, months=3, tier="top"):
        """Агрегированные закупы героя в турнирных матчах.

        Закупы каждой игры тянуть нельзя: 50 игр - 75 КБ, на слабом канале
        не дойдёт. Агрегируем в базе: для каждого предмета - в скольких
        играх куплен, сколько раз до рога, медианная секунда покупки.
        Ответ - единицы килобайт. Возвращает (покупки, итоговые предметы).
        """
        hid = int(hero_id)
        tiers = self.TIERS.get(tier, self.TIERS["top"])
        tier_sql = ", ".join(f"'{t}'" for t in tiers)
        period = f"m.start_time > extract(epoch from now() - interval '{int(months)} months')"

        purchases = _explorer(f"""
            with g as (
              select pm.match_id, pm.purchase_log,
                     ((pm.player_slot < 128) = m.radiant_win) as won
              from player_matches pm
              join matches m on m.match_id = pm.match_id
              join leagues l on l.leagueid = m.leagueid
              where pm.hero_id = {hid} and {period}
                and l.tier in ({tier_sql}) and pm.purchase_log is not null
            ),
            p as (
              select g.match_id, (e->>'key') as key, (e->>'time')::int as t
              from g, unnest(g.purchase_log) e
            )
            select key,
              count(distinct match_id) as games,
              count(distinct case when t <= 0 then match_id end) as start_games,
              sum(case when t <= 0 then 1 else 0 end)::float
                / nullif(count(distinct case when t <= 0 then match_id end), 0)
                as start_per_game,
              percentile_cont(0.5) within group (order by t) filter (where t > 0)
                as median_time,
              (select count(*) from g) as total_games,
              (select count(*) from g where won) as wins
            from p group by key order by games desc
        """, ttl=TTL_TOURNAMENT).get("rows") or []

        final = _explorer(f"""
            with g as (
              select pm.item_0, pm.item_1, pm.item_2, pm.item_3, pm.item_4, pm.item_5
              from player_matches pm
              join matches m on m.match_id = pm.match_id
              join leagues l on l.leagueid = m.leagueid
              where pm.hero_id = {hid} and {period} and l.tier in ({tier_sql})
            )
            select item_id, count(*) as games, (select count(*) from g) as total
            from (select unnest(array[item_0, item_1, item_2, item_3, item_4, item_5])
                  as item_id from g) t
            where item_id > 0 group by item_id order by games desc limit 20
        """, ttl=TTL_TOURNAMENT).get("rows") or []
        return purchases, final

    # --- аккаунт игрока ---------------------------------------------------
    # Данные публичные при включённой в Steam настройке «Открытая история
    # матчей»; без неё OpenDota о игроке ничего не знает.

    def player_profile(self, account_id):
        return get_json(f"{API}/players/{int(account_id)}", ttl=24 * 3600)

    def player_heroes(self, account_id):
        """Игры и победы на каждом герое, с ним и против него."""
        return get_json(f"{API}/players/{int(account_id)}/heroes", ttl=3600)

    def player_wl(self, account_id):
        return get_json(f"{API}/players/{int(account_id)}/wl", ttl=3600)

    # --- предметы ---------------------------------------------------------
    def items(self):
        """Справочник предметов: {внутреннее_имя: {id, dname, img, cost, qual}}.

        Снимок в приоритете: полный /constants/items весит 336 КБ и меняется
        раз в патч, гонять его по сети незачем.
        """
        snapshot = _load_items()
        if snapshot:
            return snapshot
        return get_json(f"{API}/constants/items", ttl=TTL_HEROES)

    # --- вспомогательное ---------------------------------------------------

    @staticmethod
    def picks_wins(hero_stat, bracket):
        """Пики и победы героя в выбранном ранге: (picks, wins).

        Подмены нет: если в ранге данных нет, возвращается (0, 0), и герой
        останется без базового винрейта. Молчаливый откат на общую публику
        показывал бы чужие числа под видом выбранного ранга.
        """
        if bracket == "all":
            return hero_stat.get("pub_pick") or 0, hero_stat.get("pub_win") or 0
        if bracket == "turbo":
            return hero_stat.get("turbo_picks") or 0, hero_stat.get("turbo_wins") or 0
        return hero_stat.get(f"{bracket}_pick") or 0, hero_stat.get(f"{bracket}_win") or 0

    def available_brackets(self):
        """Только те ранги, по которым у OpenDota реально есть данные.

        Поля 1_pick..8_pick заполняются не всегда: на момент написания
        Immortal (8) пустой, а pro_pick по всем героям даёт около тысячи игр —
        слишком мало, чтобы показывать это как отдельный режим.
        """
        stats = self.hero_stats()
        out = []
        for key, label in self.brackets:
            total = sum(self.picks_wins(h, key)[0] for h in stats)
            if total > 0:
                out.append({"key": key, "label": label, "games": total})
        return out
