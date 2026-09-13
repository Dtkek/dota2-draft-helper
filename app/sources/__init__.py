# -*- coding: utf-8 -*-
"""Источники данных. Активный выбирается здесь — одной строкой."""
from sources.opendota import OpenDotaSource

# Когда появится ключ STRATZ, здесь будет StratzSource(token) — остальной код
# трогать не придётся, он работает через интерфейс HeroSource.
ACTIVE = OpenDotaSource()


def get_source():
    return ACTIVE
