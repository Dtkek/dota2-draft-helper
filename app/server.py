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
    return out

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
CDN = "https://cdn.cloudflare.steamstatic.com"

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


def pro_match_detail(source, match_id):
    """Драфт матча + кто выигрывал по матчапам ещё до начала игры."""
    m = source.match(match_id)
    stats_by_id = {h["id"]: h for h in source.hero_stats()}

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
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "DraftHelper/1.0"

    def log_message(self, fmt, *args):  # тише в консоли
        if "/api/" in (args[0] if args else ""):
            sys.stderr.write("  %s\n" % (fmt % args))

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
        self.send_response(200)
        self.send_header("Content-Type", MIME.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # --- маршруты ------------------------------------------------------
    def do_GET(self):
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
                return self._json({
                    "heroes": hero_list(src),
                    "brackets": src.available_brackets(),
                    "positions": [{"key": k, "label": v}
                                  for k, v in POSITION_LABELS],
                    "source": src.name,
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
            if url.path == "/api/pro/match":
                mid = (q.get("id") or [None])[0]
                if not mid:
                    return self._json({"error": "не передан id матча"}, 400)
                return self._json(pro_match_detail(src, int(mid)))
            if url.path == "/api/cache/clear":
                return self._json({"removed": net.clear_cache()})

            if url.path == "/api/vision/status":
                return self._json(vision_status())
            if url.path == "/api/vision/state":
                if not vision.AVAILABLE:
                    return self._json({"error": vision.requirements_hint()}, 400)
                return self._json(get_watcher().state())

            return self._json({"error": "неизвестный маршрут"}, 404)
        except Exception as e:  # noqa: BLE001 — сервер не должен падать от сбоя API
            traceback.print_exc()
            return self._json({"error": str(e)}, 500)

    def do_POST(self):
        url = urlparse(self.path)
        src = get_source()
        try:
            length = int(self.headers.get("Content-Length") or 0)
            data = json.loads(self.rfile.read(length) or b"{}")

            if url.path == "/api/recommend":
                enemy = data.get("enemy") or []
                if not enemy:
                    return self._json({"error": "не выбран ни один герой противника"}, 400)
                bracket, note = resolve_bracket(src, data.get("bracket") or "all")
                rows, k_shrink = scoring.recommend(
                    src,
                    enemy_ids=enemy,
                    ally_ids=data.get("ally") or [],
                    banned_ids=data.get("banned") or [],
                    bracket=bracket,
                    role=data.get("role") or None,
                    limit=int(data.get("limit") or 15),
                    allowed_ids=ids_for_position(data.get("position")),
                )
                return self._json({
                    "rows": rows,
                    "source": src.name,
                    "bracket_used": bracket,
                    "note": note,
                    "k_shrink": k_shrink,
                })

            if url.path.startswith("/api/vision/"):
                if not vision.AVAILABLE:
                    return self._json({"error": vision.requirements_hint()}, 400)
                action = url.path.rsplit("/", 1)[-1]

                if action == "icons":
                    from vision import icons
                    got, failed, total = icons.ensure_icons(src)
                    # без перечитывания распознаватель остался бы пустым
                    # до перезапуска сервера
                    ready = get_watcher().reload_templates()
                    return self._json({"downloaded": got, "failed": failed,
                                       "total": total, "ready": ready,
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
    say(f"Источник данных: {src.name}. Проверяю доступ к api.opendota.com…")
    try:
        heroes = src.hero_stats()
        say(f"  ок, героев получено: {len(heroes)}")
    except Exception as e:  # noqa: BLE001 — сервер поднимаем в любом случае
        say(f"  НЕ УДАЛОСЬ: {e}")
        say("  Без доступа к api.opendota.com подбор работать не будет.")
        say("  Проверьте интернет, VPN и брандмауэр, затем перезапустите.")

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
