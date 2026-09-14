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
try:
    import webview
    AVAILABLE = True
except ImportError:  # pragma: no cover - без пакета просто браузер
    webview = None
    AVAILABLE = False


def requirements_hint():
    return "нет пакета pywebview: pip install pywebview"


class Api:
    """Методы, доступные странице как window.pywebview.api.*"""

    def __init__(self):
        self.window = None

    def set_on_top(self, flag):
        """Держать окно поверх остальных (для драфта поверх игры)."""
        if self.window is not None:
            self.window.on_top = bool(flag)
        return bool(flag)

    def get_on_top(self):
        return bool(self.window.on_top) if self.window is not None else False


def run(url, title="Драфт-хелпер Dota 2", on_top=False, on_closed=None):
    """Открывает окно и блокирует до его закрытия. Только из главного потока:
    на macOS WebKit иначе не работает."""
    api = Api()
    win = webview.create_window(
        title, url, js_api=api,
        width=1320, height=900, min_size=(760, 520), on_top=on_top,
        text_select=True,
    )
    api.window = win
    if on_closed is not None:
        win.events.closed += on_closed
    webview.start()
