# -*- coding: utf-8 -*-
"""Диагностика: что именно не работает.

Запуск:  python3 app/tools/diagnose.py     (на Windows: py -3 app\\tools\\diagnose.py)

Проверяет по отдельности каждое звено, от которого зависит приложение,
и печатает, где именно затык. Каждая проверка со своим коротким таймаутом,
чтобы скрипт не повисал сам.
"""
import json
import os
import socket
import ssl
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
sys.path.insert(0, APP)

TIMEOUT = 15
OK, FAIL, WARN = "  ОК   ", " СБОЙ ", "ВНИМАН"
problems = []


def say(mark, text, detail=""):
    print(f"[{mark}] {text}" + (f"\n         {detail}" if detail else ""), flush=True)


def check(name, fn):
    start = time.time()
    try:
        detail = fn()
        say(OK, f"{name}  ({time.time() - start:.1f} с)", detail or "")
        return True
    except Exception as e:  # noqa: BLE001 — печатаем любую поломку
        say(FAIL, f"{name}  ({time.time() - start:.1f} с)",
            f"{type(e).__name__}: {e}")
        problems.append(name)
        return False


print("=" * 62)
print("ДИАГНОСТИКА ДРАФТ-ХЕЛПЕРА")
print("=" * 62)

# --- 1. окружение ---------------------------------------------------------
print("\n1. Окружение")
say(OK, f"Python {sys.version.split()[0]}  ({sys.executable})")
if sys.version_info < (3, 8):
    say(WARN, "Нужен Python 3.8 или новее")
    problems.append("версия Python")

for mod, why in (("numpy", "чтение экрана"), ("cv2", "чтение экрана"),
                 ("mss", "захват экрана")):
    try:
        __import__(mod)
        say(OK, f"пакет {mod} — есть")
    except ImportError:
        say(WARN, f"пакет {mod} — нет ({why} работать не будет)")

def has_curl():
    try:
        subprocess.run(["curl", "--version"], capture_output=True, timeout=10)
        return True
    except Exception:  # noqa: BLE001
        return False


CURL = has_curl()
say(OK if CURL else WARN,
    "curl — есть" if CURL else "curl — нет (запасной путь скачивания недоступен)")

# --- 2. сеть --------------------------------------------------------------
print("\n2. Доступ к сети")


def dns(host):
    def fn():
        ip = socket.gethostbyname(host)
        return f"{host} -> {ip}"
    return fn


def tcp(host, port=443):
    def fn():
        s = socket.create_connection((host, port), timeout=TIMEOUT)
        s.close()
        return f"порт {port} открыт"
    return fn


def https_urllib(url):
    def fn():
        req = urllib.request.Request(url, headers={"User-Agent": "draft-helper-diag"})
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as r:
            data = r.read(2000)
        return f"HTTP {r.status}, получено {len(data)} байт"
    return fn


def https_curl(url):
    def fn():
        if not CURL:
            raise RuntimeError("curl не установлен")
        out = subprocess.run(
            ["curl", "-sS", "-o", os.devnull, "-w", "%{http_code}",
             "--max-time", str(TIMEOUT), url],
            capture_output=True, text=True, timeout=TIMEOUT + 10)
        if out.returncode != 0:
            raise RuntimeError(out.stderr.strip()[:200] or f"код {out.returncode}")
        return f"HTTP {out.stdout.strip()}"
    return fn


check("DNS api.opendota.com", dns("api.opendota.com"))
check("TCP api.opendota.com:443", tcp("api.opendota.com"))
urllib_ok = check("HTTPS через urllib (основной путь)",
                  https_urllib("https://api.opendota.com/api/heroes"))
curl_ok = check("HTTPS через curl (запасной путь)",
                https_curl("https://api.opendota.com/api/heroes"))
check("CDN портретов героев",
      https_curl("https://cdn.cloudflare.steamstatic.com/apps/dota2/images/"
                 "dota_react/heroes/antimage.png") if CURL
      else https_urllib("https://cdn.cloudflare.steamstatic.com/apps/dota2/"
                        "images/dota_react/heroes/antimage.png"))

# --- 3. сам источник данных ----------------------------------------------
print("\n3. Источник данных приложения")


def source_heroes():
    from sources import get_source
    heroes = get_source().hero_stats()
    return f"героев получено: {len(heroes)}"


check("net.get_json через слой приложения", source_heroes)

# --- 4. локальные файлы ---------------------------------------------------
print("\n4. Файлы приложения")


def positions_file():
    p = os.path.join(APP, "data", "positions.json")
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    return f"позиций для героев: {len(data.get('positions', {}))}"


def cache_dir():
    p = os.path.join(APP, ".cache")
    n = len([x for x in os.listdir(p)]) if os.path.isdir(p) else 0
    return f"файлов в кэше: {n}"


def icons_dir():
    from vision import icons
    return f"портретов на диске: {len(icons.available_ids())}"


check("справочник позиций", positions_file)
check("папка кэша", cache_dir)
check("портреты героев", icons_dir)

# --- 5. порт --------------------------------------------------------------
print("\n5. Локальный порт 8777")


def port_free():
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 8777))
        return "свободен"
    except OSError as e:
        raise RuntimeError(f"занят ({e}) — возможно, сервер уже запущен")
    finally:
        s.close()


check("порт 8777", port_free)

# --- итог -----------------------------------------------------------------
print("\n" + "=" * 62)
if not problems:
    print("Всё в порядке. Если приложение всё равно висит — пришлите этот вывод.")
else:
    print("Проблемы:", ", ".join(problems))
    if "HTTPS через urllib (основной путь)" in problems and curl_ok:
        print("\nurllib не работает, а curl работает — приложение переключится")
        print("на curl само, это не смертельно.")
    if not urllib_ok and not curl_ok:
        print("\nГЛАВНОЕ: доступа к api.opendota.com нет ни одним способом.")
        print("Приложение без него работать не может: оттуда берутся все данные.")
        print("Проверьте VPN, брандмауэр и блокировки провайдера.")
print("=" * 62)
