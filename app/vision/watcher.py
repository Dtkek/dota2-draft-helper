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
    def __init__(self, hero_names=None, source=None, interval=2.0, monitor=1,
                 region=None):
        self.hero_names = hero_names or {}
        self.source = source
        self.recognizer = recognize.Recognizer(self.hero_names)
        self.interval = interval
        self.monitor = monitor
        # по умолчанию верхняя половина экрана: там идёт драфт
        self.region = region or (0.0, 0.0, 1.0, 0.55)

        self._thread = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        # последний захваченный кадр в JPEG — чтобы в интерфейсе было видно,
        # что именно попало в объектив: игра, браузер или чёрный экран
        self._last_jpeg = None
        self._state = {
            "running": False,
            "heroes": [],
            "boxes": [],
            "template_width": None,
            "last_scan": None,
            "last_error": None,
            "scans": 0,
            "mode": "ожидание",
            "frame_brightness": None,
            "frame_hint": None,
        }

    # --- состояние --------------------------------------------------------
    def state(self):
        with self._lock:
            return dict(self._state)

    def last_frame_jpeg(self):
        with self._lock:
            return self._last_jpeg

    def _grab(self):
        """Захват кадра + сохранение превью и оценка, что в нём вообще есть."""
        import cv2
        frame = capture.grab(self.monitor, self.region)
        h, w = frame.shape[:2]
        k = min(1.0, 640 / w)
        small = cv2.resize(frame, (int(w * k), int(h * k)),
                           interpolation=cv2.INTER_AREA) if k < 1 else frame
        ok, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 70])

        brightness = float(frame.mean())
        hint = None
        if brightness < 6:
            hint = ("кадр почти чёрный. Обычно это Dota в режиме «Полноэкранный»: "
                    "захват экрана его не видит. Переключите игру в "
                    "«Оконный без рамки» (настройки → видео)")
        with self._lock:
            if ok:
                self._last_jpeg = buf.tobytes()
            self._state["frame_brightness"] = round(brightness, 1)
            self._state["frame_hint"] = hint
        return frame

    def _set(self, **kw):
        with self._lock:
            self._state.update(kw)

    # --- эталоны ----------------------------------------------------------
    def reload_templates(self):
        """Перечитывает портреты с диска.

        Нужно после докачки: распознаватель загружает эталоны при создании,
        и без перечитывания слежение не заработало бы до перезапуска сервера.
        """
        self.recognizer = recognize.Recognizer(self.hero_names)
        return self.recognizer.ready

    def _download_templates(self):
        """Качает недостающие портреты, показывая прогресс в состоянии."""
        from vision import icons
        if self.source is None:
            self._set(last_error="нет источника данных для скачивания портретов")
            return False

        def progress(done, total):
            self._set(mode=f"скачиваю портреты героев: {done} из {total}")

        self._set(mode="скачиваю портреты героев…", last_error=None)
        try:
            got, failed, total, reason = icons.ensure_icons(self.source, progress)
        except Exception as e:  # noqa: BLE001
            self._set(last_error=f"не удалось скачать портреты: {e}")
            return False

        ready = self.reload_templates()
        if failed:
            # причина обязательна: раньше здесь молча получалось «0 из 127»
            self._set(last_error=(
                f"портреты: скачано {got}, не удалось {failed} из {total}. "
                f"Последняя ошибка: {reason}"))
        if not ready:
            self._set(mode="остановлено: нет эталонов героев")
        return ready

    # --- управление -------------------------------------------------------
    def start(self):
        if self._thread and self._thread.is_alive():
            return False
        if not capture.available():
            self._set(last_error="не установлены пакеты для захвата экрана")
            return False

        # эталонов может не быть: в репозиторий они не входят. Не ругаемся,
        # а качаем сами — пользователю незачем знать про это устройство.
        if not self.recognizer.ready:
            self.reload_templates()

        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._set(running=True, last_error=None)
        return True

    def _run(self):
        if not self.recognizer.ready and not self._download_templates():
            self._set(running=False, mode="остановлено")
            return
        self._loop()

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
        if not self.recognizer.ready:
            self.reload_templates()
        if not self.recognizer.ready and not self._download_templates():
            return self.state()
        frame = self._grab()
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
                frame = self._grab()
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
