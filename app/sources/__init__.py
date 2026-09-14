# -*- coding: utf-8 -*-
"""Источники данных.

Основной источник (герои, турниры, про-матчи, сборки, аккаунт) - OpenDota,
выбирается здесь одной строкой. STRATZ - не замена, а надстройка для подбора:
матчапы по рангу, синергии, позиции. Живёт отдельным объектом, см. stratz.py.
"""
from sources.opendota import OpenDotaSource
from sources.stratz import StratzMatchups

ACTIVE = OpenDotaSource()
STRATZ = StratzMatchups()


def get_source():
    return ACTIVE


def get_stratz():
    return STRATZ
