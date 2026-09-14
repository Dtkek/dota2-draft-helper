# -*- coding: utf-8 -*-
"""Собственное окно приложения вместо вкладки браузера.

Интерфейс тот же HTML, что и в браузере, - его показывает pywebview:
на Windows через встроенный WebView2 (есть в любой Windows 10/11),
на macOS через WebKit. Сервер при этом никуда не девается, просто
пользователь его не видит: запустил exe - открылось окно.

Зачем это, кроме удобства: окно можно держать поверх Dota в оконном
режиме без alt-tab - переключатель «Поверх окон» в шапке страницы.
Это ближе всего к оверлею и при этом ничего не делает с процессом игры.

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


class Api:
    """Методы, доступные странице как window.pywebview.api.*

    Атрибут окна - с подчёркиванием: pywebview отдаёт странице все публичные
    атрибуты и пытался сериализовать само окно вместе с его native-объектом.
    """

    def __init__(self):
        self._window = None

    def set_on_top(self, flag):
        """Держать окно поверх остальных (для драфта поверх игры)."""
        if self._window is not None:
            self._window.on_top = bool(flag)
        return bool(flag)

    def get_on_top(self):
        return bool(self._window.on_top) if self._window is not None else False


def _ascii_runtime_workaround(log=None):
    """Windows: кириллица в пути к приложению ломает pythonnet.

    clr_loader передаёт путь к Python.Runtime.dll в .NET как ANSI-строку
    (char*), «Рабочий стол» превращается в мусор, и .NET отвечает «Failed
    to resolve Python.Runtime.Loader.Initialize». Это единственное место,
    где путь идёт через ANSI: остальные DLL грузятся уже через pythonnet
    с нормальными строками. Поэтому копируем папку runtime во временную
    папку с ASCII-путём и подменяем pythonnet.__file__ - load() строит
    путь к DLL от него. Возвращает путь копии или None, если не нужно
    или некуда.
    """
    if sys.platform != "win32":
        return None
    try:
        import pythonnet
    except ImportError:
        return None
    src = os.path.join(os.path.dirname(os.path.abspath(pythonnet.__file__)), "runtime")
    if src.isascii() or not os.path.isdir(src):
        return None

    # первая папка с ASCII-путём, куда можно писать; у пользователя с
    # кириллическим именем TEMP тоже кириллический - идём дальше по списку
    candidates = [os.environ.get("TEMP"), os.environ.get("LOCALAPPDATA"),
                  os.environ.get("ProgramData"), "C:\\Temp"]
    for base in candidates:
        if not base or not base.isascii():
            continue
        dst = os.path.join(base, "dota2-draft-helper", "pythonnet")
        try:
            shutil.copytree(src, os.path.join(dst, "runtime"), dirs_exist_ok=True)
        except OSError:
            continue
        pythonnet.__file__ = os.path.join(dst, "__init__.py")
        if log:
            log(f"  кириллица в пути: pythonnet берёт DLL из копии {dst}")
        return dst
    if log:
        log("  кириллица в пути и нет папки с ASCII-путём для копии DLL - "
            "окно, скорее всего, не откроется")
    return None


def run(url, title="Драфт-хелпер Dota 2", on_top=False, on_closed=None, log=None):
    """Открывает окно и блокирует до его закрытия. Только из главного потока:
    на macOS WebKit иначе не работает."""
    _ascii_runtime_workaround(log)
    api = Api()
    win = webview.create_window(
        title, url, js_api=api,
        width=1320, height=900, min_size=(760, 520), on_top=on_top,
        text_select=True,
    )
    api._window = win
    if on_closed is not None:
        win.events.closed += on_closed
    webview.start()
