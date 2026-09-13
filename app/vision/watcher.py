# -*- coding: utf-8 -*-
"""Фоновое слежение за экраном: раз в несколько секунд обновляет список героев.

Работает в отдельном потоке, состояние читается из веб-интерфейса опросом.
Логика простая: сначала калибровка (полный поиск), дальше — быстрая
классификация найденных прямоугольников. Если уверенных попаданий стало
заметно меньше, калибровка повторяется: значит, картинка на экране уехала.
"""
import threading
import time

from vision import capture, recognize


class ScreenWatcher:
    def __init__(self, hero_names=None, interval=2.0, monitor=1, region=None):
        self.recognizer = recognize.Recognizer(hero_names)
        self.interval = interval
        self.monitor = monitor
        # по умолчанию верхняя половина экрана: там идёт драфт
        self.region = region or (0.0, 0.0, 1.0, 0.55)

        self._thread = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._state = {
            "running": False,
            "heroes": [],
            "boxes": [],
            "template_width": None,
            "last_scan": None,
            "last_error": None,
            "scans": 0,
            "mode": "ожидание",
        }

    # --- состояние --------------------------------------------------------
    def state(self):
        with self._lock:
            return dict(self._state)

    def _set(self, **kw):
        with self._lock:
            self._state.update(kw)

    # --- управление -------------------------------------------------------
    def start(self):
        if self._thread and self._thread.is_alive():
            return False
        if not self.recognizer.ready:
            self._set(last_error="нет эталонов героев — сначала скачайте портреты")
            return False
        if not capture.available():
            self._set(last_error="не установлен пакет mss — захват экрана недоступен")
            return False
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        self._set(running=True, last_error=None)
        return True

    def stop(self):
        self._stop.set()
        self._set(running=False, mode="остановлено")

    def configure(self, monitor=None, interval=None, region=None):
        if monitor is not None:
            self.monitor = int(monitor)
        if interval is not None:
            self.interval = max(0.5, float(interval))
        if region is not None:
            self.region = tuple(region)
        # настройки поменялись — прежние прямоугольники больше не годятся
        self._set(boxes=[], template_width=None)

    def scan_once(self):
        """Разовый полный поиск — для кнопки «сканировать сейчас»."""
        frame = capture.grab(self.monitor, self.region)
        hits, width = self.recognizer.scan(frame)
        self._apply(hits, width, mode="разовый поиск")
        return self.state()

    # --- внутреннее -------------------------------------------------------
    def _apply(self, hits, width, mode):
        seen, heroes = set(), []
        for h in sorted(hits, key=lambda x: x["box"][0]):
            if h["hero_id"] in seen:
                continue
            seen.add(h["hero_id"])
            heroes.append(h)
        self._set(
            heroes=heroes,
            boxes=[h["box"] for h in heroes],
            template_width=width or self._state.get("template_width"),
            last_scan=time.time(),
            mode=mode,
            scans=self._state.get("scans", 0) + 1,
        )

    def _loop(self):
        boxes = []
        misses = 0
        while not self._stop.is_set():
            try:
                frame = capture.grab(self.monitor, self.region)
                if boxes:
                    found = self.recognizer.classify_boxes(frame, boxes)
                    # если уверенно распознали меньше половины — картинка уехала
                    if len(found) < max(1, len(boxes) // 2):
                        misses += 1
                    else:
                        misses = 0
                    self._apply(found, None, mode="слежение")
                    if misses >= 2:
                        boxes = []
                        misses = 0
                else:
                    hits, width = self.recognizer.scan(frame)
                    self._apply(hits, width, mode="калибровка")
                    boxes = [h["box"] for h in hits]
                self._set(last_error=None)
            except Exception as e:  # noqa: BLE001 — поток не должен умирать
                self._set(last_error=str(e))
            self._stop.wait(self.interval)
        self._set(running=False)
