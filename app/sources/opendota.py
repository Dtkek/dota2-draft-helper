# -*- coding: utf-8 -*-
"""Источник данных OpenDota — публичный API, ключ не нужен.

Ограничения, которые важно понимать при чтении рекомендаций:
матчапы «герой против героя» OpenDota отдаёт по профессиональным матчам,
и выборка там небольшая — медиана около 30 игр на пару героев. Поэтому
в scoring.py применяется сглаживание, а в интерфейсе показывается объём выборки.
"""
from net import get_json
from sources.base import HeroSource

API = "https://api.opendota.com/api"

# час для меты, сутки для справочника героев: герои меняются куда реже статистики
TTL_HEROES = 24 * 3600
TTL_STATS = 3600
TTL_MATCHUPS = 6 * 3600
TTL_PRO_LIST = 600
TTL_MATCH = 7 * 24 * 3600


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

    def heroes(self):
        return get_json(f"{API}/heroes", ttl=TTL_HEROES)

    def hero_stats(self):
        return get_json(f"{API}/heroStats", ttl=TTL_STATS)

    def matchups(self, hero_id):
        return get_json(f"{API}/heroes/{int(hero_id)}/matchups", ttl=TTL_MATCHUPS)

    def pro_matches(self):
        return get_json(f"{API}/proMatches", ttl=TTL_PRO_LIST)

    def match(self, match_id):
        return get_json(f"{API}/matches/{int(match_id)}", ttl=TTL_MATCH)

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
