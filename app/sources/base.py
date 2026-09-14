# -*- coding: utf-8 -*-
"""Интерфейс основного источника данных.

Слой сделан сменным, чтобы источник героев, турниров и про-матчей можно было
заменить, не трогая логику подбора и веб-часть. STRATZ в итоге подключён
не как замена, а как надстройка над подбором (sources/stratz.py): у него
матчапы по рангам и синергии, но нет турниров и про-матчей.
"""


class HeroSource:
    """Что обязан уметь источник данных, чтобы приложение с ним работало."""

    #: человекочитаемое имя, показывается в интерфейсе
    name = "abstract"

    #: набор рангов, которые источник умеет различать: [(ключ, подпись), ...]
    brackets = []

    def heroes(self):
        """Список героев: id, name, localized_name, roles, img, primary_attr."""
        raise NotImplementedError

    def hero_stats(self):
        """Статистика героев: пики и победы по рангам, про-пики, про-баны."""
        raise NotImplementedError

    def matchups(self, hero_id):
        """Матчапы героя: [{hero_id, games_played, wins}] — победы этого героя."""
        raise NotImplementedError

    def pro_matches(self):
        """Лента последних профессиональных матчей."""
        raise NotImplementedError

    def match(self, match_id):
        """Подробности матча: пики, баны, игроки."""
        raise NotImplementedError

    @staticmethod
    def picks_wins(hero_stat, bracket):
        """Пики и победы героя в выбранном ранге: (picks, wins)."""
        raise NotImplementedError

    def available_brackets(self):
        """Ранги, по которым у источника реально есть данные."""
        raise NotImplementedError

    def tournament_leagues(self, months=3):
        """Турниры за период: [{leagueid, name, tier, matches}]."""
        raise NotImplementedError

    def tournament_stats(self, months=3, tier="top", leagueid=None):
        """Пики/баны/победы героев в турнирах: ([{hero_id, picks, bans, wins}], всего матчей)."""
        raise NotImplementedError
