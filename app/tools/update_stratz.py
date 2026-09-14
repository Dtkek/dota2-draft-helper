# -*- coding: utf-8 -*-
"""Собирает снимок STRATZ в репозиторий: матчапы по рангам, пары «вместе»,
позиции героев.

Запуск:  STRATZ_TOKEN=... python3 app/tools/update_stratz.py [--weeks 3]

Токен - на https://stratz.com/api (вход через Steam, один токен на аккаунт).
Можно положить его в файл stratz_token.txt в корне проекта вместо переменной.

Зачем снимок, а не живые запросы: пользователю не нужен свой токен,
лимиты API не расходуются на каждого, а токен, привязанный к IP, не ломается
на VPN. Данные STRATZ и так недельные - снимок раз в неделю ничего не теряет.
В репозитории снимок обновляет GitHub Actions
(.github/workflows/update-snapshots.yml) с токеном из секретов.
"""
import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
sys.path.insert(0, APP)

from sources import stratz  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Снимок данных STRATZ")
    ap.add_argument("--weeks", type=int, default=stratz.WEEKS,
                    help=f"сколько последних недель суммировать (по умолчанию {stratz.WEEKS})")
    ap.add_argument("--out", default=stratz.SNAPSHOT)
    args = ap.parse_args()

    token = stratz.token_from_env()
    if not token:
        print("нет токена: задайте STRATZ_TOKEN или положите stratz_token.txt "
              "в корень проекта", file=sys.stderr)
        return 2

    started = time.time()
    client = stratz.StratzClient(token)
    try:
        payload = stratz.build_snapshot(client, weeks=args.weeks, log=print)
    finally:
        client.close()
    stratz.write_snapshot(payload, args.out)

    heroes = len(payload["matchups"].get("all") or {})
    pairs = sum(len(slot["vs"]) for b in payload["matchups"].values() for slot in b.values())
    print(f"\nгероев: {heroes}, пар в матчапах по всем рангам: {pairs}")
    print(f"размер файла: {os.path.getsize(args.out) / 1024:.0f} КБ, "
          f"запросов: {client.requests}, переподключений: {client.reconnected}, "
          f"{time.time() - started:.0f} с")
    print("записано:", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
