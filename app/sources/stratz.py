# -*- coding: utf-8 -*-
"""STRATZ - второй источник матчапов, поверх OpenDota.

Что даёт, чего нет у OpenDota: матчапы с разбивкой по рангу, пары «вместе»
(синергия с союзниками) и базовые винрейты героев по позиции. Матчапов
по позиции у STRATZ тоже нет. Всё остальное - турниры, про-матчи, сборки,
аккаунт - остаётся на OpenDota, поэтому это не замена источника, а надстройка
над подбором.

Откуда данные
-------------
Из снимка app/data/stratz_fallback.json.gz. Собирает его
app/tools/update_stratz.py; в репозитории он обновляется по расписанию
(GitHub Actions с токеном в секретах), так что пользователю ключ STRATZ
не нужен. Если токен всё же задан - переменная STRATZ_TOKEN или файл
stratz_token.txt рядом с папкой app - приложение обновляет снимок само,
в фоне, когда он старше недели.

Что важно знать про API
-----------------------
- GraphQL, один адрес. Нужны заголовки Authorization: Bearer <токен>
  и User-Agent: STRATZ_API - без второго отвечает 403.
- Токен привязывается к IP первого запроса. С VPN, который меняет адрес
  на каждом соединении, каждый новый запрос отвергается («You cannot use
  different IP Addresses»). Поэтому одно постоянное соединение на всё,
  а при отказе - переподключение, пока не попадём на привязанный адрес.
- week - Unix-время начала недели, недели идут от четверга (как эпоха).
  Без week отдаётся текущая, неполная. Объёмы за неделю огромные: у
  популярного героя сотни тысяч игр в одном ранге, медиана по паре -
  тысячи. Снимок суммирует последние WEEKS недель.
- Лимиты токена по умолчанию: 20 запросов в секунду, 250 в минуту,
  2000 в час, 10000 в сутки. Снимок целиком - около 120 запросов.
- Условия токена по умолчанию: без специальных требований, просьба
  показывать «Powered by STRATZ». Интерфейс показывает.
"""
import gzip
import http.client
import json
import os
import ssl
import sys
import threading
import time
from datetime import date

import net

HOST = "api.stratz.com"
PATH = "/graphql"

import paths

SNAPSHOT_NAME = "stratz_fallback.json.gz"
# читаем обновлённую копию, если она есть, иначе снимок из сборки;
# пишем всегда в папку данных пользователя (в exe рядом с кодом писать нельзя)
SNAPSHOT = os.path.join(paths.BUNDLED_DATA, SNAPSHOT_NAME)
SNAPSHOT_UPDATED = os.path.join(paths.UPDATED_DATA, SNAPSHOT_NAME)
TOKEN_FILE = paths.TOKEN_FILE

# сколько последних недель суммировать в снимке (включая текущую неполную)
WEEKS = 3
WEEK = 7 * 24 * 3600

# снимок старше этого - обновить в фоне, если есть токен
STALE_AFTER = 7 * 24 * 3600

# ключ ранга в интерфейсе -> значение enum RankBracketBasicEnum;
# "all" - без фильтра по рангу
BRACKETS = [
    ("all", "Все ранги", None),
    ("DIVINE_IMMORTAL", "Divine – Immortal", "DIVINE_IMMORTAL"),
    ("LEGEND_ANCIENT", "Legend – Ancient", "LEGEND_ANCIENT"),
    ("CRUSADER_ARCHON", "Crusader – Archon", "CRUSADER_ARCHON"),
    ("HERALD_GUARDIAN", "Herald – Guardian", "HERALD_GUARDIAN"),
]

# герой «играет» на позиции, если на неё приходится хотя бы такая доля
# его игр в ранге: Anti-Mage в миду - 5% игр, это не позиция, а эксперимент
POSITION_SHARE = 0.10

# героев за один запрос matchUp: ответ по герою около 30 КБ
BATCH = 20

# пауза между запросами: лимит 20 в секунду, с большим запасом
PAUSE = 0.5


def token_from_env():
    """Токен из переменной окружения или файла рядом с приложением."""
    tok = (os.environ.get("STRATZ_TOKEN") or "").strip()
    if tok:
        return tok
    try:
        with open(TOKEN_FILE, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def week_start(ts=None):
    """Начало недели STRATZ для момента ts: недели считаются от эпохи."""
    ts = int(ts if ts is not None else time.time())
    return ts - ts % WEEK


class StratzClient:
    """GraphQL-клиент с постоянным соединением.

    Одно соединение на все запросы и повтор подключения при отказе по IP -
    см. модуль. reconnects - сколько раз пробовать поймать нужный адрес:
    у VPN с пулом в 15 адресов это в среднем 15 попыток.
    """

    def __init__(self, token, reconnects=60, timeout=60):
        if not token:
            raise ValueError("нет токена STRATZ")
        self.headers = {
            "Content-Type": "application/json",
            "User-Agent": "STRATZ_API",
            "Authorization": f"Bearer {token}",
            "Connection": "keep-alive",
        }
        self.reconnects = reconnects
        self.timeout = timeout
        self._conn = None
        self.requests = 0
        self.reconnected = 0

    def _connect(self):
        self.close()
        self._conn = http.client.HTTPSConnection(
            HOST, context=net._context(), timeout=self.timeout)

    def close(self):
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:  # noqa: BLE001
                pass
            self._conn = None

    def _once(self, body):
        if self._conn is None:
            self._connect()
        self._conn.request("POST", PATH, body=body, headers=self.headers)
        resp = self._conn.getresponse()
        raw = resp.read().decode("utf-8", "replace")
        self.requests += 1
        return resp.status, raw

    def query(self, gql, variables=None):
        """Выполняет запрос, возвращает поле data. Ошибки GraphQL - исключение."""
        body = json.dumps({"query": gql, "variables": variables or {}})
        last = None
        for attempt in range(self.reconnects + 1):
            try:
                status, raw = self._once(body)
            except (http.client.HTTPException, OSError) as e:
                # соединение протухло (keep-alive закрыт сервером) - открыть заново
                last = f"{type(e).__name__}: {e}"
                self._connect()
                continue
            if status == 200:
                data = json.loads(raw)
                if data.get("errors"):
                    raise RuntimeError("STRATZ: " + "; ".join(
                        str(e.get("message")) for e in data["errors"])[:300])
                return data.get("data") or {}
            last = f"HTTP {status}: {raw[:200]}"
            if status == 403 and "IP" in raw:
                # попали не на тот адрес VPN - следующее соединение уйдёт с другого
                self.reconnected += 1
                self._connect()
                time.sleep(0.4)
                continue
            if status == 429:
                time.sleep(5)
                continue
            raise RuntimeError(f"STRATZ: {last}")
        raise RuntimeError(f"STRATZ: не удалось выполнить запрос за "
                           f"{self.reconnects} переподключений, последняя ошибка: {last}")


# --- сборка снимка ---------------------------------------------------------

def _bracket_arg(enum):
    return f"bracketBasicIds: [{enum}], " if enum else ""


def build_snapshot(client, weeks=WEEKS, log=None):
    """Собирает снимок: матчапы, пары «вместе» и позиции по всем рангам.

    Возвращает словарь для записи в SNAPSHOT. Формат строк матчапов -
    [id второго героя, игр, побед первого], позиций - [игр, побед] по
    ключам "1".."5". Всё просуммировано по последним weeks неделям.
    """
    say = log or (lambda *_: None)
    hero_ids = sorted(h["id"] for h in client.query(
        "{ constants { heroes { id } } }")["constants"]["heroes"])
    now_week = week_start()
    week_list = [now_week - i * WEEK for i in range(weeks)]
    say(f"героев: {len(hero_ids)}, недели: "
        + ", ".join(date.fromtimestamp(w).isoformat() for w in week_list))

    matchups = {}   # bracket -> hero -> {"vs": {id: [g, w]}, "with": {...}}
    positions = {}  # bracket -> hero -> {"1": [g, w], ...}

    for key, _label, enum in BRACKETS:
        by_hero = matchups.setdefault(key, {})
        pos = positions.setdefault(key, {})
        for week in week_list:
            for i in range(0, len(hero_ids), BATCH):
                batch = hero_ids[i:i + BATCH]
                data = client.query(f"""{{ heroStats {{
                    matchUp(heroIds: [{", ".join(map(str, batch))}], week: {week},
                            {_bracket_arg(enum)}take: 200) {{
                        heroId
                        vs {{ heroId2 matchCount winCount }}
                        with {{ heroId2 matchCount winCount }}
                    }} }} }}""")
                for h in data["heroStats"]["matchUp"] or []:
                    slot = by_hero.setdefault(str(h["heroId"]), {"vs": {}, "with": {}})
                    for side in ("vs", "with"):
                        for r in h.get(side) or []:
                            acc = slot[side].setdefault(r["heroId2"], [0, 0])
                            acc[0] += int(r.get("matchCount") or 0)
                            acc[1] += int(r.get("winCount") or 0)
                time.sleep(PAUSE)

            data = client.query(f"""{{ heroStats {{
                stats(week: {week}, {_bracket_arg(enum)}groupByPosition: true) {{
                    heroId position matchCount winCount
                }} }} }}""")
            for r in data["heroStats"]["stats"] or []:
                p = (r.get("position") or "")
                if not p.startswith("POSITION_"):
                    continue
                acc = pos.setdefault(str(r["heroId"]), {}).setdefault(p[-1], [0, 0])
                acc[0] += int(r.get("matchCount") or 0)
                acc[1] += int(r.get("winCount") or 0)
            time.sleep(PAUSE)
        games = sum(v[0] for h in by_hero.values() for v in h["vs"].values())
        say(f"  {key}: героев {len(by_hero)}, игр в матчапах {games:,}, "
            f"запросов всего {client.requests}, переподключений {client.reconnected}")

    # компактный формат для файла: списки вместо словарей
    packed = {
        b: {hid: {side: [[oid, g, w] for oid, (g, w) in sorted(tbl.items())]
                  for side, tbl in slot.items()}
            for hid, slot in heroes.items()}
        for b, heroes in matchups.items()
    }
    return {
        "_комментарий": "Снимок STRATZ: матчапы и пары «вместе» по рангам, "
                        "позиции героев. Строка матчапа: [id второго героя, игр, "
                        "побед первого]. Позиции: {\"1\"..\"5\": [игр, побед]}. "
                        "Пересобрать: python3 app/tools/update_stratz.py",
        "снято": date.today().isoformat(),
        "недели": [date.fromtimestamp(w).isoformat() for w in week_list],
        "brackets": [[k, label] for k, label, _ in BRACKETS],
        "matchups": packed,
        "positions": positions,
    }


def write_snapshot(payload, path=SNAPSHOT):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    os.replace(tmp, path)


# --- чтение снимка и интерфейс для подбора ------------------------------------

class _Bound:
    """Матчапы и синергии одного ранга в формате, который ждёт scoring.py."""

    def __init__(self, table):
        self._table = table

    def _rows(self, hero_id, side):
        slot = self._table.get(str(int(hero_id))) or {}
        return [{"hero_id": oid, "games_played": g, "wins": w}
                for oid, g, w in (slot.get(side) or [])]

    def matchups(self, hero_id):
        """Игры и победы hero_id против каждого героя - как у OpenDota."""
        return self._rows(hero_id, "vs")

    def synergies(self, hero_id):
        """Игры и победы hero_id в одной команде с каждым героем."""
        return self._rows(hero_id, "with")


class StratzMatchups:
    """Снимок STRATZ для подбора: ранги, матчапы, синергии, позиции."""

    name = "STRATZ"

    def __init__(self, path=SNAPSHOT, updated_path=SNAPSHOT_UPDATED):
        # path - снимок из сборки (только чтение), updated_path - куда
        # пишет фоновое обновление; читается тот из двух, что свежее
        self.bundled_path = path
        self.updated_path = updated_path
        self._payload = None
        self._loaded_from = None

    @property
    def path(self):
        """Тот из снимков, что свежее: обновлённый или из сборки."""
        candidates = []
        for p in (self.updated_path, self.bundled_path):
            try:
                candidates.append((os.path.getmtime(p), p))
            except OSError:
                pass
        return max(candidates)[1] if candidates else self.bundled_path

    _refresh_lock = threading.Lock()
    _refreshing = False
    refresh_error = None

    def _load(self):
        path = self.path
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            self._payload = None
            return None
        if self._payload is not None and self._loaded_from == (path, mtime):
            return self._payload
        try:
            with gzip.open(path, "rt", encoding="utf-8") as f:
                self._payload = json.load(f)
            self._loaded_from = (path, mtime)
        except (OSError, ValueError):
            self._payload = None
        return self._payload

    @property
    def available(self):
        return self._load() is not None

    @property
    def date(self):
        p = self._load()
        return p.get("снято") if p else None

    @property
    def weeks(self):
        p = self._load()
        return p.get("недели") if p else []

    def brackets(self):
        """Ранги, по которым в снимке есть данные: [{key, label}]."""
        p = self._load()
        if not p:
            return []
        return [{"key": k, "label": label}
                for k, label in p.get("brackets") or []
                if p.get("matchups", {}).get(k)]

    def bound(self, bracket):
        """Матчапы и синергии выбранного ранга; нет ранга - None."""
        p = self._load()
        if not p:
            return None
        table = p.get("matchups", {}).get(bracket)
        return _Bound(table) if table else None

    def base_stats(self, bracket, position=None):
        """{hero_id: (игр, побед)} в ранге; с позицией - только на ней."""
        p = self._load()
        if not p:
            return {}
        out = {}
        for hid, pos in (p.get("positions", {}).get(bracket) or {}).items():
            if position:
                g, w = pos.get(str(position), (0, 0))
            else:
                g = sum(v[0] for v in pos.values())
                w = sum(v[1] for v in pos.values())
            out[int(hid)] = (g, w)
        return out

    def position_ids(self, bracket, position):
        """Герои, которые реально играют на позиции в этом ранге.

        Не ручной справочник, а данные: доля игр героя на позиции не ниже
        POSITION_SHARE. None - позиция не задана, фильтра нет.
        """
        if not position:
            return None
        p = self._load()
        if not p:
            return set()
        out = set()
        for hid, pos in (p.get("positions", {}).get(bracket) or {}).items():
            total = sum(v[0] for v in pos.values())
            g = pos.get(str(position), (0, 0))[0]
            if total and g / total >= POSITION_SHARE:
                out.add(int(hid))
        return out

    # --- фоновое обновление ---------------------------------------------

    def maybe_refresh(self):
        """Пересобрать снимок в фоне, если есть токен и снимок устарел.

        Один поток на всё приложение; результат виден на следующем запросе:
        _load() перечитывает файл по времени изменения.
        """
        token = token_from_env()
        if not token:
            return False
        try:
            fresh = time.time() - os.path.getmtime(self.path) < STALE_AFTER
        except OSError:
            fresh = False
        if fresh:
            return False
        with self._refresh_lock:
            if self._refreshing:
                return False
            self._refreshing = True

        def worker():
            client = StratzClient(token)
            try:
                sys.stderr.write("  STRATZ: снимок устарел, обновляю в фоне\n")
                # пишем в папку данных пользователя: в exe рядом с кодом нельзя
                write_snapshot(build_snapshot(client), self.updated_path)
                self.refresh_error = None
                sys.stderr.write("  STRATZ: снимок обновлён\n")
            except Exception as e:  # noqa: BLE001 - фон не должен ронять сервер
                self.refresh_error = str(e)[:200]
                sys.stderr.write(f"  STRATZ: не удалось обновить снимок: {e}\n")
            finally:
                client.close()
                with self._refresh_lock:
                    self._refreshing = False

        threading.Thread(target=worker, daemon=True).start()
        return True

    def status(self):
        """Для интерфейса: есть ли снимок, когда снят, обновляется ли."""
        return {
            "available": self.available,
            "date": self.date,
            "weeks": self.weeks,
            "brackets": self.brackets(),
            "refreshing": self._refreshing,
            "refresh_error": self.refresh_error,
            "has_token": bool(token_from_env()),
        }
