# -*- coding: utf-8 -*-
"""Локальный веб-сервер драфт-хелпера.

Запуск:  python3 app/server.py
Затем открыть http://127.0.0.1:8777 (браузер откроется сам).

Никаких зависимостей: только стандартная библиотека.
"""
import argparse
import json
import os
import sys
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gsi  # noqa: E402
import net  # noqa: E402
import scoring  # noqa: E402
import vision  # noqa: E402
from sources import get_source  # noqa: E402

_watcher = None
_watcher_lock = threading.Lock()


def get_watcher():
    """Создаёт наблюдателя за экраном при первом обращении.

    Зависимости зрения опциональные, поэтому импорт отложенный: без них
    приложение работает как обычно, просто без чтения экрана.
    """
    global _watcher
    with _watcher_lock:
        if _watcher is None:
            from vision.watcher import ScreenWatcher
            src = get_source()
            names = {h["id"]: h.get("localized_name") for h in src.hero_stats()}
            # источник нужен наблюдателю, чтобы самому докачать портреты
            _watcher = ScreenWatcher(names, source=src)
        return _watcher


def vision_status():
    """Состояние чтения экрана.

    Функция обязана отвечать и тогда, когда пакеты зрения не установлены:
    её задача в этом случае — сказать, чего не хватает. Поэтому всё, что
    тянет opencv, numpy или mss, импортируется только после проверки.
    """
    from vision import icons  # зависит лишь от стандартной библиотеки
    src = get_source()
    have = len(icons.available_ids())
    total = len(src.hero_stats())
    out = {
        "available": vision.AVAILABLE,
        "hint": vision.requirements_hint(),
        "icons": {"have": have, "total": total, "ready": have >= total * 0.95},
        "monitors": [],
        "state": None,
    }
    if vision.AVAILABLE:
        from vision import capture
        out["monitors"] = capture.monitors()
    if vision.AVAILABLE and have:
        w = get_watcher()
        out["state"] = w.state()
        out["config"] = {"monitor": w.monitor, "interval": w.interval,
                         "region": list(w.region)}
        # файлов на диске и эталонов в распознавателе может быть разное
        # число: на Windows cv2.imread молчит на путях с кириллицей
        out["templates_loaded"] = len(w.recognizer.ids)
        out["assets_dir"] = icons.ASSETS
    return out


def vision_self_test():
    """Самопроверка распознавания на собственных эталонах."""
    from vision import recognize
    w = get_watcher()
    if not w.recognizer.ready:
        w.reload_templates()
    return recognize.self_test(w.recognizer)

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
CDN = "https://cdn.cloudflare.steamstatic.com"

# Версия показывается в консоли и в шапке страницы: когда что-то идёт не так,
# первым делом нужно понять, какой код на самом деле запущен.
VERSION = "2026-09-13.23"

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
}


def hero_list(source):
    """Справочник героев для интерфейса: имя, картинка, роли, позиции."""
    positions = hero_positions()
    out = []
    for h in source.hero_stats():
        out.append({
            "id": h["id"],
            "name": h.get("localized_name"),
            "img": CDN + h["img"] if h.get("img") else None,
            "roles": h.get("roles") or [],
            "positions": positions.get(h["id"], []),
            "attr": h.get("primary_attr"),
        })
    out.sort(key=lambda x: (x["name"] or "").lower())
    return out


POSITIONS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "data", "positions.json")

POSITION_LABELS = [
    ("1", "Керри (1)"),
    ("2", "Мид (2)"),
    ("3", "Хард (3)"),
    ("4", "Роумер (4)"),
    ("5", "Хардсаппорт (5)"),
]

_positions_cache = None


def hero_positions():
    """Справочник позиций: {hero_id: [позиции]}.

    Это не данные источника, а файл, составленный вручную: OpenDota позиций
    не отдаёт. Файл перечитывается при изменении, чтобы правки подхватывались
    без перезапуска сервера.
    """
    global _positions_cache
    try:
        mtime = os.path.getmtime(POSITIONS_FILE)
    except OSError:
        return {}
    if _positions_cache and _positions_cache[0] == mtime:
        return _positions_cache[1]
    try:
        with open(POSITIONS_FILE, encoding="utf-8") as f:
            raw = json.load(f).get("positions", {})
        table = {int(k): list(v) for k, v in raw.items()}
    except (OSError, ValueError):
        return {}
    _positions_cache = (mtime, table)
    return table


def ids_for_position(position):
    """id героев, играющих на этой позиции. None — фильтр не задан."""
    if not position:
        return None
    try:
        want = int(position)
    except (TypeError, ValueError):
        return None
    return {hid for hid, pos in hero_positions().items() if want in pos}


def resolve_bracket(source, requested):
    """Проверяет, что по запрошенному рангу есть данные.

    Если нет — честно откатывается на «Все ранги» и возвращает пояснение,
    чтобы интерфейс показал чужие числа не молча.
    """
    available = {b["key"] for b in source.available_brackets()}
    if requested in available:
        return requested, None
    return "all", (f"по рангу «{requested}» у источника нет данных, "
                   f"показаны все ранги")


def meta_table(source, bracket, role=None, allowed_ids=None):
    """Таблица меты: винрейт, доля пиков, про-пики и про-баны."""
    stats = source.hero_stats()
    total_picks = 0
    rows = []
    for h in stats:
        picks, wins = source.picks_wins(h, bracket)
        if allowed_ids is not None and h["id"] not in allowed_ids:
            continue
        if role and role not in (h.get("roles") or []):
            continue
        total_picks += picks
        rows.append({
            "id": h["id"],
            "name": h.get("localized_name"),
            "img": CDN + h["img"] if h.get("img") else None,
            "roles": h.get("roles") or [],
            "picks": picks,
            "winrate": round(wins / picks * 100, 2) if picks else None,
            "pro_pick": h.get("pro_pick") or 0,
            "pro_ban": h.get("pro_ban") or 0,
            "pro_winrate": (round((h.get("pro_win") or 0) / h["pro_pick"] * 100, 2)
                            if h.get("pro_pick") else None),
        })
    for r in rows:
        r["pick_share"] = round(r["picks"] / total_picks * 100, 2) if total_picks else 0
    rows.sort(key=lambda r: (r["winrate"] is None, -(r["winrate"] or 0)))
    return rows


def tournament_table(source, months=3, tier="top", leagueid=None):
    """Турнирная статистика по героям с долями от числа матчей."""
    rows, total = source.tournament_stats(months, tier, leagueid)
    stats_by_id = {h["id"]: h for h in source.hero_stats()}
    out = []
    for r in rows:
        s = stats_by_id.get(r["hero_id"], {})
        picks, bans, wins = int(r["picks"]), int(r["bans"]), int(r["wins"])
        out.append({
            "id": r["hero_id"],
            "name": s.get("localized_name"),
            "img": CDN + s["img"] if s.get("img") else None,
            "picks": picks,
            "bans": bans,
            "wins": wins,
            "winrate": round(wins / picks * 100, 1) if picks else None,
            "pick_rate": round(picks / total * 100, 1) if total else 0,
            "ban_rate": round(bans / total * 100, 1) if total else 0,
            "contest_rate": round((picks + bans) / total * 100, 1) if total else 0,
        })
    return out, total


def pro_matches(source, limit=40):
    out = []
    for m in source.pro_matches()[:limit]:
        out.append({
            "match_id": m.get("match_id"),
            "league": m.get("league_name"),
            "radiant": m.get("radiant_name") or m.get("radiant_team_name") or "Radiant",
            "dire": m.get("dire_name") or m.get("dire_team_name") or "Dire",
            "radiant_win": m.get("radiant_win"),
            "duration": m.get("duration"),
            "start_time": m.get("start_time"),
            "score": [m.get("radiant_score"), m.get("dire_score")],
        })
    return out


# расходники в ленте сборки только шумят; стартовый закуп показываем целиком
CONSUMABLE_QUALS = {"consumable", "consumable;laning"}


def item_builds(player, items_by_name, items_by_id):
    """Предметы игрока: стартовый закуп, сборка по времени, итоговый инвентарь.

    purchase_log — покупки с временем в секундах от рога; отрицательное время
    значит «до начала игры», это и есть стартовый закуп. В сборке расходники
    и компоненты не показываем: интересны собранные предметы и порядок.
    """
    def info(name):
        it = items_by_name.get(name)
        if not it:
            return {"key": name, "dname": name, "img": None, "cost": 0}
        return {"key": name, "dname": it.get("dname") or name,
                "img": CDN + it["img"] if it.get("img") else None,
                "cost": it.get("cost") or 0}

    log = sorted((e for e in (player.get("purchase_log") or []) if e.get("key")),
                 key=lambda e: e.get("time", 0))
    start = [info(e["key"]) for e in log if (e.get("time") or 0) <= 0]

    build = []
    for e in log:
        t = e.get("time") or 0
        if t <= 0:
            continue
        it = items_by_name.get(e["key"]) or {}
        if it.get("qual") in CONSUMABLE_QUALS or it.get("qual") == "component":
            continue
        if (it.get("cost") or 0) < 500:
            continue
        entry = info(e["key"])
        entry["minute"] = int(t // 60)
        build.append(entry)

    final = []
    for slot in ("item_0", "item_1", "item_2", "item_3", "item_4", "item_5"):
        iid = player.get(slot)
        if iid:
            name = items_by_id.get(int(iid))
            if name:
                final.append(info(name))
    neutral = None
    if player.get("item_neutral"):
        name = items_by_id.get(int(player["item_neutral"]))
        if name:
            neutral = info(name)
    return {"start": start, "build": build, "final": final, "neutral": neutral,
            "has_log": bool(log)}


def hero_build(source, hero_id, months=3):
    """Рекомендуемая сборка героя по турнирным матчам.

    Стартовый закуп - предметы, купленные до рога хотя бы в 40% игр,
    с числом штук. Порядок сборки - предметы дороже 500 золота, купленные
    хотя бы в четверти игр, по медианной минуте покупки. Ситуативные -
    дорогие предметы из 10-25% игр. Итог - что чаще всего в инвентаре.
    """
    purchases, final = source.hero_builds(hero_id, months)
    items = source.items() or {}
    by_id = {it["id"]: name for name, it in items.items() if it.get("id")}

    def info(name):
        it = items.get(name) or {}
        return {"key": name, "dname": it.get("dname") or name,
                "img": CDN + it["img"] if it.get("img") else None,
                "cost": it.get("cost") or 0, "qual": it.get("qual")}

    if not purchases:
        return {"hero_id": hero_id, "games": 0}
    total = int(purchases[0]["total_games"]) or 1
    wins = int(purchases[0]["wins"] or 0)

    start = []
    for r in purchases:
        sg = int(r["start_games"] or 0)
        if sg / total >= 0.4:
            e = info(r["key"])
            e["share"] = round(sg / total * 100)
            e["count"] = round(float(r["start_per_game"] or 1))
            start.append(e)
    start.sort(key=lambda e: -e["share"])

    order, situational = [], []
    for r in purchases:
        if not r["median_time"]:
            continue
        e = info(r["key"])
        if e["qual"] in CONSUMABLE_QUALS or e["qual"] == "component" or e["cost"] < 500:
            continue
        share = int(r["games"]) / total
        e["share"] = round(share * 100)
        e["minute"] = int(float(r["median_time"]) // 60)
        if share >= 0.25:
            order.append(e)
        elif share >= 0.10 and e["cost"] >= 1500:
            situational.append(e)
    order.sort(key=lambda e: e["minute"])
    situational.sort(key=lambda e: -e["share"])

    final_items = []
    for r in final:
        name = by_id.get(int(r["item_id"]))
        if not name:
            continue
        e = info(name)
        e["share"] = round(int(r["games"]) / int(r["total"]) * 100)
        final_items.append(e)

    return {
        "hero_id": hero_id,
        "games": total,
        "wins": wins,
        "winrate": round(wins / total * 100, 1),
        "months": months,
        "start": start,
        "order": order,
        "situational": situational[:8],
        "final": final_items[:10],
    }


def pro_match_detail(source, match_id):
    """Драфт матча + кто выигрывал по матчапам ещё до начала игры."""
    # лёгкий путь через базу; полный JSON матча - только если база не отдала
    slim_error = None
    try:
        m = source.match_slim(match_id)
    except Exception as e:  # noqa: BLE001
        slim_error = str(e)[:160]
        m = source.match(match_id)
    stats_by_id = {h["id"]: h for h in source.hero_stats()}

    items_by_name = source.items() or {}
    items_by_id = {it["id"]: name for name, it in items_by_name.items() if it.get("id")}

    def hero_info(hid):
        s = stats_by_id.get(hid, {})
        return {"id": hid, "name": s.get("localized_name"),
                "img": CDN + s["img"] if s.get("img") else None}

    radiant, dire = [], []
    for p in m.get("players") or []:
        entry = hero_info(p.get("hero_id"))
        entry.update({
            "player": p.get("name") or p.get("personaname"),
            "kda": [p.get("kills"), p.get("deaths"), p.get("assists")],
            "gpm": p.get("gold_per_min"),
            "xpm": p.get("xp_per_min"),
            "net_worth": p.get("net_worth"),
            "items": item_builds(p, items_by_name, items_by_id),
        })
        (radiant if p.get("isRadiant") else dire).append(entry)

    draft_order = []
    for pb in m.get("picks_bans") or []:
        draft_order.append({
            "is_pick": pb.get("is_pick"),
            "team": "radiant" if pb.get("team") == 0 else "dire",
            "order": pb.get("order"),
            **hero_info(pb.get("hero_id")),
        })
    draft_order.sort(key=lambda x: x["order"] if x["order"] is not None else 0)

    edge = {}
    if radiant and dire:
        edge = scoring.draft_edge(source, [h["id"] for h in radiant],
                                  [h["id"] for h in dire])

    return {
        "match_id": m.get("match_id"),
        "league": (m.get("league") or {}).get("name"),
        "radiant_name": (m.get("radiant_team") or {}).get("name") or "Radiant",
        "dire_name": (m.get("dire_team") or {}).get("name") or "Dire",
        "radiant_win": m.get("radiant_win"),
        "duration": m.get("duration"),
        "score": [m.get("radiant_score"), m.get("dire_score")],
        "radiant": radiant,
        "dire": dire,
        "draft_order": draft_order,
        "edge": edge,
        "has_draft": bool(draft_order),
        "slim_error": slim_error,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "DraftHelper/1.0"

    def log_message(self, fmt, *args):
        # Стандартный лог отключён: вместо него печатаем каждый запрос к API
        # с временем ответа, см. _timed. По такому логу видно, что именно
        # тормозит, без отдельной диагностики.
        pass

    def _timed(self, method, fn):
        import time
        path = self.path.split("?")[0]
        if not path.startswith("/api/"):
            return fn()
        started = time.time()
        sys.stderr.write(f"  {method} {path} …\n")
        sys.stderr.flush()
        try:
            return fn()
        finally:
            ms = (time.time() - started) * 1000
            sys.stderr.write(f"  {method} {path} — {ms:.0f} мс\n")
            sys.stderr.flush()

    # --- ответы --------------------------------------------------------
    def _json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path):
        if not os.path.isfile(path):
            self._json({"error": "не найдено"}, 404)
            return
        ext = os.path.splitext(path)[1]
        with open(path, "rb") as f:
            body = f.read()
        if ext == ".html":
            # версия в адресе скрипта и стилей: даже если браузер проигнорирует
            # заголовки кэширования, новый адрес он обязан скачать заново
            body = (body.replace(b'/static/app.js', f'/static/app.js?v={VERSION}'.encode())
                        .replace(b'/static/styles.css', f'/static/styles.css?v={VERSION}'.encode()))
        self.send_response(200)
        self.send_header("Content-Type", MIME.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        # без этого браузер после обновления кода подсовывает старый app.js
        # к новому серверу, и поведение становится необъяснимым
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(body)

    # --- маршруты ------------------------------------------------------
    def do_GET(self):
        return self._timed("GET", self._do_get)

    def do_POST(self):
        return self._timed("POST", self._do_post)

    def _do_get(self):
        url = urlparse(self.path)
        q = parse_qs(url.query)
        src = get_source()
        try:
            if url.path in ("/", "/index.html"):
                return self._file(os.path.join(WEB_DIR, "index.html"))
            if url.path.startswith("/static/"):
                name = os.path.basename(url.path)
                return self._file(os.path.join(WEB_DIR, name))

            if url.path == "/api/heroes":
                heroes = hero_list(src)
                snapshot = getattr(src, "using_fallback", False)
                from sources import opendota as od
                return self._json({
                    "heroes": heroes,
                    "brackets": src.available_brackets(),
                    "positions": [{"key": k, "label": v}
                                  for k, v in POSITION_LABELS],
                    "source": src.name,
                    "version": VERSION,
                    "snapshot": snapshot,
                    "snapshot_note": (
                        f"Справочник героев взят из снимка от {od.fallback_date}; "
                        "свежие данные подтягиваются в фоне и появятся при "
                        "следующем обновлении страницы."
                    ) if snapshot else None,
                })
            if url.path == "/api/meta":
                bracket, note = resolve_bracket(src, q.get("bracket", ["all"])[0])
                return self._json({
                    "rows": meta_table(
                        src, bracket,
                        (q.get("role") or [None])[0] or None,
                        ids_for_position((q.get("position") or [None])[0])),
                    "bracket_used": bracket,
                    "note": note,
                })
            if url.path == "/api/pro/matches":
                return self._json({"matches": pro_matches(src)})
            if url.path == "/api/tournaments":
                months = int((q.get("months") or ["3"])[0])
                tier = (q.get("tier") or ["top"])[0]
                league = (q.get("league") or [None])[0] or None
                rows, total = tournament_table(src, months, tier, league)
                return self._json({"rows": rows, "total_matches": total,
                                   "months": months, "tier": tier,
                                   "league": league})
            if url.path == "/api/gsi/state":
                s = gsi.state()
                # имя героя из игры -> id из справочника
                if s.get("hero_name") and not s.get("hero_id"):
                    for h in src.hero_stats():
                        if h.get("name") == s["hero_name"]:
                            s["hero_id"] = h["id"]
                            break
                if s.get("hero_id"):
                    for h in src.hero_stats():
                        if h["id"] == s["hero_id"]:
                            s["hero_localized"] = h.get("localized_name")
                            break
                s["config_path_hint"] = (
                    "<Steam>\\steamapps\\common\\dota 2 beta\\game\\dota\\cfg\\"
                    "gamestate_integration\\gamestate_integration_drafthelper.cfg")
                return self._json(s)
            if url.path == "/api/gsi/config":
                body = gsi.config_text(self.server.server_address[1]).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Disposition",
                                 'attachment; filename="gamestate_integration_drafthelper.cfg"')
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return None
            if url.path == "/api/build":
                hero = (q.get("hero") or [None])[0]
                if not hero:
                    return self._json({"error": "не передан герой"}, 400)
                months = int((q.get("months") or ["3"])[0])
                return self._json(hero_build(src, int(hero), months))
            if url.path == "/api/tournaments/leagues":
                months = int((q.get("months") or ["3"])[0])
                return self._json({"leagues": src.tournament_leagues(months)})
            if url.path == "/api/pro/match":
                mid = (q.get("id") or [None])[0]
                if not mid:
                    return self._json({"error": "не передан id матча"}, 400)
                return self._json(pro_match_detail(src, int(mid)))
            if url.path == "/api/cache/clear":
                return self._json({"removed": net.clear_cache()})

            if url.path == "/api/vision/status":
                return self._json(vision_status())
            if url.path == "/api/vision/selftest":
                if not vision.AVAILABLE:
                    return self._json({"error": vision.requirements_hint()}, 400)
                return self._json(vision_self_test())
            if url.path == "/api/vision/state":
                if not vision.AVAILABLE:
                    return self._json({"error": vision.requirements_hint()}, 400)
                return self._json(get_watcher().state())
            if url.path == "/api/vision/frame.jpg":
                # последний захваченный кадр: главный инструмент диагностики,
                # когда «не распознаёт» — видно, что реально попало в кадр
                if not vision.AVAILABLE:
                    return self._json({"error": vision.requirements_hint()}, 400)
                data = get_watcher().last_frame_jpeg()
                if not data:
                    return self._json({"error": "кадров ещё не было"}, 404)
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)
                return None

            return self._json({"error": "неизвестный маршрут"}, 404)
        except Exception as e:  # noqa: BLE001 — сервер не должен падать от сбоя API
            traceback.print_exc()
            return self._json({"error": str(e)}, 500)

    def _do_post(self):
        url = urlparse(self.path)
        src = get_source()
        try:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length)

            # сюда стучится сама игра через Game State Integration
            if url.path == "/gsi":
                try:
                    gsi.handle(json.loads(raw or b"{}"))
                except ValueError:
                    pass
                self.send_response(200)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return None

            # изображение приходит сырыми байтами, а не JSON
            if url.path == "/api/vision/recognize":
                if not vision.AVAILABLE:
                    return self._json({"error": vision.requirements_hint()}, 400)
                if not raw:
                    return self._json({"error": "файл пустой"}, 400)
                return self._json(get_watcher().scan_image(raw))

            data = json.loads(raw or b"{}")

            if url.path == "/api/gsi/install":
                path, msg = gsi.install(self.server.server_address[1])
                return self._json({"path": path, "message": msg})

            if url.path == "/api/recommend":
                enemy = data.get("enemy") or []
                if not enemy:
                    return self._json({"error": "не выбран ни один герой противника"}, 400)
                bracket, note = resolve_bracket(src, data.get("bracket") or "all")

                # турнирная составляющая: вес выбирает пользователь,
                # 0 - не учитывать. Если база турниров недоступна, подбор
                # работает без неё и говорит об этом, а не падает.
                tour_weight = float(data.get("tour_weight", scoring.W_TOUR))
                tour, tour_note, tour_matches = None, None, 0
                if tour_weight > 0:
                    try:
                        t_rows, tour_matches = src.tournament_stats(
                            int(data.get("tour_months") or 3), "top")
                        tour = scoring.tournament_strength(t_rows, tour_matches)
                    except Exception as e:  # noqa: BLE001
                        tour_note = f"турнирная статистика недоступна: {str(e)[:120]}"
                        tour_weight = 0.0

                rows, k_shrink = scoring.recommend(
                    src,
                    enemy_ids=enemy,
                    ally_ids=data.get("ally") or [],
                    banned_ids=data.get("banned") or [],
                    bracket=bracket,
                    role=data.get("role") or None,
                    limit=int(data.get("limit") or 15),
                    allowed_ids=ids_for_position(data.get("position")),
                    tour=tour,
                    tour_weight=tour_weight,
                )
                return self._json({
                    "rows": rows,
                    "source": src.name,
                    "bracket_used": bracket,
                    "note": note,
                    "k_shrink": k_shrink,
                    "tour_weight": tour_weight,
                    "tour_matches": tour_matches,
                    "tour_note": tour_note,
                })

            if url.path.startswith("/api/vision/"):
                if not vision.AVAILABLE:
                    return self._json({"error": vision.requirements_hint()}, 400)
                action = url.path.rsplit("/", 1)[-1]

                if action == "icons":
                    from vision import icons
                    got, failed, total, reason = icons.ensure_icons(src)
                    # без перечитывания распознаватель остался бы пустым
                    # до перезапуска сервера
                    ready = get_watcher().reload_templates()
                    return self._json({"downloaded": got, "failed": failed,
                                       "total": total, "ready": ready,
                                       "reason": reason,
                                       "have": len(icons.available_ids())})

                w = get_watcher()
                if action == "config":
                    w.configure(monitor=data.get("monitor"),
                                interval=data.get("interval"),
                                region=data.get("region"))
                    return self._json({"ok": True, "monitor": w.monitor,
                                       "interval": w.interval,
                                       "region": list(w.region)})
                if action == "start":
                    started = w.start()
                    return self._json({"started": started, "state": w.state()})
                if action == "stop":
                    w.stop()
                    return self._json({"state": w.state()})
                if action == "scan":
                    return self._json(w.scan_once())

            return self._json({"error": "неизвестный маршрут"}, 404)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            return self._json({"error": str(e)}, 500)


def main():
    ap = argparse.ArgumentParser(description="Драфт-хелпер для Dota 2")
    ap.add_argument("--port", type=int, default=8777)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    # Прогреваем справочник до старта сервера: так в консоли сразу видно,
    # есть ли доступ к OpenDota. Иначе пользователь видит пустой интерфейс
    # и не понимает, грузится он или сломался.
    # flush обязателен: вывод в stdout буферизуется, и сообщения о ходе
    # запуска пользователь увидел бы только под конец, а нужны они сразу
    def say(msg):
        print(msg, flush=True)

    src = get_source()
    say(f"Драфт-хелпер, версия {VERSION}. Источник данных: {src.name}.")
    try:
        heroes = src.hero_stats()
        if getattr(src, "using_fallback", False):
            from sources import opendota as od
            say(f"  справочник героев: снимок от {od.fallback_date}, "
                f"{len(heroes)} героев. Свежие данные подтягиваю в фоне.")
        else:
            say(f"  справочник героев: {len(heroes)} героев из кэша или сети.")
    except Exception as e:  # noqa: BLE001 — сервер поднимаем в любом случае
        say(f"  справочник героев НЕ ЗАГРУЖЕН: {e}")
        say("  Запустите diagnose.bat, чтобы понять причину.")

    # Самопроверка распознавания при старте: находит ли распознаватель
    # собственные эталоны. Если нет — проблема не в игре и не в захвате.
    if vision.AVAILABLE:
        try:
            from vision import icons
            have = len(icons.available_ids())
            if have:
                res = vision_self_test()
                loaded = len(get_watcher().recognizer.ids)
                if res.get("ok"):
                    say(f"  распознавание: самопроверка ок "
                        f"({res['found']}/{res['placed']} за {res['seconds']} с, "
                        f"эталонов загружено {loaded} из {have} файлов)")
                else:
                    say(f"  распознавание: САМОПРОВЕРКА НЕ ПРОШЛА — "
                        f"найдено {res.get('found', 0)} из {res.get('placed', 0)}, "
                        f"эталонов загружено {loaded} из {have} файлов. "
                        f"{res.get('reason', '')}")
                    say(f"  папка эталонов: {icons.ASSETS}")
            else:
                say("  распознавание: портреты героев ещё не скачаны — "
                    "скачаются при первом запуске слежения")
        except Exception as e:  # noqa: BLE001 — самопроверка не должна ронять старт
            say(f"  распознавание: самопроверка упала: {type(e).__name__}: {e}")
    else:
        say(f"  распознавание отключено: {vision.requirements_hint()}")

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}"
    say(f"\nДрафт-хелпер запущен: {url}")
    say("Ctrl+C — остановить.")
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nОстановлено.")


if __name__ == "__main__":
    main()
