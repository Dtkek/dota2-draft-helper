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


def https_urllib(url, gzip_on=True):
    """Скачивает ответ ЦЕЛИКОМ.

    Читать кусочек нельзя: именно так первая версия этой проверки и
    ошиблась. Она брала 2000 байт, соединение успевало их отдать, проверка
    проходила — а приложение потом висело на полном ответе в 161 КБ,
    который на том же канале обрывался на середине.
    """
    def fn():
        headers = {"User-Agent": "draft-helper-diag"}
        if gzip_on:
            headers["Accept-Encoding"] = "gzip"
        req = urllib.request.Request(url, headers=headers)
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as r:
            data = r.read()
            enc = r.headers.get("Content-Encoding") or "нет"
        kb = len(data) / 1024
        return f"HTTP {r.status}, скачано {kb:.0f} КБ, сжатие: {enc}"
    return fn


def https_curl(url, compressed=True):
    def fn():
        if not CURL:
            raise RuntimeError("curl не установлен")
        cmd = ["curl", "-sS"]
        if compressed:
            cmd.append("--compressed")
        # -o и его значение обязаны идти подряд: вставка флага между ними
        # отправляла тело ответа в stdout и ломала разбор результата
        cmd += ["-o", os.devnull, "-w", "%{http_code} %{size_download}",
                "--max-time", str(TIMEOUT), url]
        out = subprocess.run(cmd, capture_output=True, text=True,
                             timeout=TIMEOUT + 10)
        if out.returncode != 0:
            raise RuntimeError(out.stderr.strip()[:200] or f"код {out.returncode}")
        code, size = (out.stdout.strip().split() + ["?"])[:2]
        return f"HTTP {code}, скачано {int(size) / 1024:.0f} КБ"
    return fn


HEAVY = "https://api.opendota.com/api/heroStats"  # 161 КБ, 33 КБ со сжатием

check("DNS api.opendota.com", dns("api.opendota.com"))
check("TCP api.opendota.com:443", tcp("api.opendota.com"))

# Именно этот запрос делает приложение при запуске, и именно он самый
# тяжёлый. Проверяем оба пути и со сжатием, и без: если без сжатия рвётся,
# а со сжатием проходит — значит канал не тянет большие ответы.
gzip_urllib = check("Справочник героев через urllib, со сжатием (33 КБ)",
                    https_urllib(HEAVY, gzip_on=True))
plain_urllib = check("Справочник героев через urllib, без сжатия (161 КБ)",
                     https_urllib(HEAVY, gzip_on=False))
gzip_curl = check("Справочник героев через curl, со сжатием",
                  https_curl(HEAVY, compressed=True))
plain_curl = check("Справочник героев через curl, без сжатия",
                   https_curl(HEAVY, compressed=False))
urllib_ok, curl_ok = gzip_urllib, gzip_curl

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

# --- 6. собственное окно --------------------------------------------------
# Всё, без чего окно не открывается и приложение уходит в браузер. Окно -
# удобство, а не функция, поэтому здесь только предупреждения.
print("\n6. Собственное окно")

try:
    import webview  # noqa: F401
    say(OK, "пакет pywebview — есть")
except ImportError:
    say(WARN, "пакет pywebview — нет (приложение откроется в браузере)")

if sys.platform == "win32":
    import winreg

    def reg_value(path, name):
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as k:
            return winreg.QueryValueEx(k, name)[0]

    def dotnet():
        rel = reg_value(r"SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full",
                        "Release")
        if rel < 461808:  # 4.7.2
            raise RuntimeError(f"Release {rel} — нужен .NET Framework 4.7.2 или новее")
        return f"Release {rel}"

    def webview2():
        return "версия " + reg_value(
            r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients"
            r"\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}", "pv")

    def marked_files():
        """Метка «скачано из интернета»: из-за неё .NET не грузит сборки.

        Приложение снимает её само при запуске, но если папка только для
        чтения — снять не выйдет, и окно не откроется.
        """
        root = getattr(sys, "_MEIPASS", None) or APP
        n = 0
        for base, _dirs, files in os.walk(root):
            for name in files:
                try:
                    with open(os.path.join(base, name) + ":Zone.Identifier", "rb"):
                        n += 1
                except OSError:
                    pass
        if n:
            raise RuntimeError(
                f"помечено файлов: {n} — .NET откажется грузить "
                "Python.Runtime.dll. Снять вручную: в папке приложения "
                "Get-ChildItem -Recurse | Unblock-File")
        return "меток нет"

    check(".NET Framework", dotnet)
    check("WebView2 Runtime", webview2)
    check("метка «скачано из интернета»", marked_files)
    ascii_path = sys.executable.isascii()
    say(OK if ascii_path else WARN,
        "путь к приложению без кириллицы" if ascii_path
        else f"в пути есть кириллица: {sys.executable}")

# --- итог -----------------------------------------------------------------
print("\n" + "=" * 62)
if not problems:
    print("Всё в порядке. Если приложение всё равно висит — пришлите этот вывод.")
else:
    print("Проблемы:", ", ".join(problems))
    if "HTTPS через urllib (основной путь)" in problems and curl_ok:
        print("\nurllib не работает, а curl работает — приложение переключится")
        print("на curl само, это не смертельно.")
    any_gzip = gzip_urllib or gzip_curl
    any_plain = plain_urllib or plain_curl
    if any_gzip and not any_plain:
        print("\nГЛАВНОЕ: сжатые ответы доходят, несжатые — нет.")
        print("Канал не вытягивает большие ответы: 161 КБ рвётся, 33 КБ проходят.")
        print("Приложение запрашивает сжатие, так что работать должно.")
    elif any_gzip or any_plain:
        print("\nДоступ к api.opendota.com есть хотя бы одним способом —")
        print("приложение выберет рабочий путь само.")
    if not any_gzip and not any_plain:
        print("\nГЛАВНОЕ: доступа к api.opendota.com нет ни одним способом.")
        print("Приложение поднимется на локальном снимке справочника,")
        print("но подбор по матчапам работать не будет: для него нужна сеть.")
        print("Проверьте VPN, брандмауэр и блокировки провайдера.")
print("=" * 62)
