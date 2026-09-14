# -*- coding: utf-8 -*-
"""Собственное окно приложения вместо вкладки браузера.

Интерфейс тот же HTML, что и в браузере, - его показывает pywebview:
на Windows через встроенный WebView2 (есть в любой Windows 10/11),
на macOS через WebKit. Сервер при этом никуда не девается, просто
пользователь его не видит: запустил exe - открылось окно.

Зачем это, кроме удобства: окно можно держать поверх Dota в оконном
режиме без alt-tab - ключ запуска --on-top. Это ближе всего к оверлею
и при этом ничего не делает с процессом игры.

Без pywebview приложение работает как раньше - через браузер.
"""
import os
import shutil
import sys

try:
    import webview
    AVAILABLE = True
except ImportError:  # pragma: no cover - без пакета просто браузер
    webview = None
    AVAILABLE = False


def requirements_hint():
    return "нет пакета pywebview: pip install pywebview"


def _unblock_tree(root):
    """Снимает метку «скачано из интернета» со всех файлов под root.

    Метка - альтернативный поток Zone.Identifier; Windows ставит его на
    каждый файл, распакованный из скачанного архива. Возвращает пару
    (снято, осталось): «осталось» - файлы, где снять не удалось, обычно
    потому что папка только для чтения.
    """
    done = left = 0
    for base, _dirs, files in os.walk(root):
        for name in files:
            try:
                os.remove(os.path.join(base, name) + ":Zone.Identifier")
                done += 1
            except FileNotFoundError:
                pass
            except OSError:
                left += 1
    return done, left


def _dotnet_runtime_workaround(log=None):
    """Windows: две причины, по которым .NET не отдаёт Python.Runtime.dll.

    Обе выглядят одинаково - «Failed to resolve
    Python.Runtime.Loader.Initialize», HRESULT 0x80131515:

    1. Метка «скачано из интернета». Сборка приезжает к пользователю
       архивом из релиза, Windows метит архив, а проводник переносит
       метку на каждый распакованный файл. .NET Framework отказывается
       грузить помеченную сборку. Это то, на чём приложение и стояло:
       окно не открывалось, хотя и WebView2, и .NET 4.8 были на месте.
    2. Не-ASCII в пути: clr_loader передаёт путь к DLL в нативный
       загрузчик как ANSI-строку (char*), и «Рабочий стол» превращается
       в мусор.

    Метку снимаем со всей папки приложения, а не только с pythonnet:
    через .NET грузится ещё и WebView2. Если снять не удалось (папка
    только для чтения) или в пути есть не-ASCII - копируем runtime в
    папку с ASCII-путём и снимаем метку уже там. Возвращает путь копии
    или None, если копия не понадобилась или её некуда положить.
    """
    if sys.platform != "win32":
        return None
    try:
        import pythonnet
    except ImportError:
        return None
    src = os.path.join(os.path.dirname(os.path.abspath(pythonnet.__file__)), "runtime")
    if not os.path.isdir(src):
        return None

    # в собранном exe всё лежит в _internal (sys._MEIPASS); при запуске
    # из исходников метки взяться неоткуда, чистим только сам runtime
    done, left = _unblock_tree(getattr(sys, "_MEIPASS", None) or src)
    if done and log:
        log(f"  снята метка «скачано из интернета» с {done} файлов: "
            "иначе .NET не принимает Python.Runtime.dll")
    if src.isascii() and not left:
        return None

    # первая папка с ASCII-путём, куда можно писать; у пользователя с
    # кириллическим именем TEMP тоже кириллический - идём дальше по списку
    candidates = [os.environ.get("TEMP"), os.environ.get("LOCALAPPDATA"),
                  os.environ.get("ProgramData"), "C:\\Temp"]
    for base in candidates:
        if not base or not base.isascii():
            continue
        dst = os.path.join(base, "pickline", "pythonnet")
        try:
            shutil.copytree(src, os.path.join(dst, "runtime"), dirs_exist_ok=True)
        except OSError:
            continue
        # copytree на Windows копирует файл вместе с его потоками, так что
        # метка переезжает в копию - снимаем и здесь. Раньше это и делало
        # копирование бесполезным: путь становился ASCII, а метка ехала с ним
        _unblock_tree(dst)
        pythonnet.__file__ = os.path.join(dst, "__init__.py")
        if log:
            log(f"  pythonnet берёт DLL из копии {dst}")
        return dst
    if log:
        log("  нет папки с ASCII-путём для копии DLL - окно, скорее всего, "
            "не откроется")
    return None


def run(url, title="Pickline", on_top=False, on_closed=None, log=None):
    """Открывает окно и блокирует до его закрытия. Только из главного потока:
    на macOS WebKit иначе не работает."""
    _dotnet_runtime_workaround(log)
    # «Поверх окон» только ключом запуска --on-top: переключение из страницы
    # на ходу (window.on_top из js_api) на Windows вешало приложение -
    # вызов уходит в поток окна, который в этот момент ждёт ответа страницы
    win = webview.create_window(
        title, url,
        width=1320, height=900, min_size=(760, 520), on_top=on_top,
        text_select=True,
    )
    if on_closed is not None:
        win.events.closed += on_closed
    webview.start()
