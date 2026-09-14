# -*- coding: utf-8 -*-
"""Распознавание героев на кадре экрана.

Подход двухфазный, потому что честный полный поиск слишком медленный,
чтобы гонять его каждую секунду:

1. Калибровка (`scan`). Один раз ищем портреты по всему кадру в нескольких
   масштабах: 126 эталонов × несколько масштабов — это секунды работы.
   В результате узнаём масштаб портретов на экране и их прямоугольники.

2. Слежение (`classify_boxes`). Дальше вырезаем уже известные прямоугольники
   и сравниваем каждый со всеми эталонами разом — одно матричное умножение,
   миллисекунды. Пересчёт калибровки нужен, только если картинка уехала.

Сравнение идёт по нормализованной корреляции на градациях серого: портреты
берутся с того же CDN, что использует клиент игры, поэтому отличаются
в основном масштабом и лёгким сжатием.
"""
import os

import cv2
import numpy as np

from vision import icons

# размер, к которому приводится вырезанный фрагмент при классификации
CELL_W, CELL_H = 64, 36

# ширины эталона (в пикселях рабочего кадра), которые перебираем при калибровке
SCAN_WIDTHS = (40, 48, 56, 64, 72, 82, 94, 108, 124, 142, 162)

# рабочая ширина кадра: больше не нужно, а скорость важнее
WORK_WIDTH = 1280

# грубый проход для поиска масштаба идёт на сильно уменьшенном кадре:
# перебор масштабов стоит дорого, а для выбора масштаба такой детализации хватает
COARSE_WIDTH = 440

# по скольким лучшим совпадениям судим о качестве масштаба
QUALITY_TOP = 5

# Портрет драфта занимает заметную долю ширины экрана. Совпадения мельче
# этого порога — почти всегда мусор: на произвольном рабочем столе мелкий
# шаблон «находится» где угодно. Проверено на практике: без порога на экране
# без запущенной игры стабильно всплывали три-четыре несуществующих героя.
MIN_REL_WIDTH = 0.030

# Чем меньше найдено героев, тем выше требование к уверенности: в настоящем
# драфте портреты идут рядом и распознаются уверенно (0.82–0.99), а на
# постороннем экране вылезают одиночки и пары на 0.66–0.72.
LONE_HIT_SCORE = 0.85
PAIR_HIT_SCORE = 0.78

# Портрет героя — цветная картинка, а интерфейсы и текст почти серые.
# Проверка насыщенности отсекает совпадения на постороннем содержимом,
# которые по форме похожи, а по цвету — нет.
MIN_SATURATION = 32


def _to_gray(img):
    if img.ndim == 3:
        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return img


def read_image(path):
    """Читает картинку так, чтобы путь с кириллицей не был проблемой.

    cv2.imread на Windows молча возвращает None, если в пути есть
    не-ASCII символы — например, «Рабочий стол» или папка с русским
    названием. Ошибки нет, файлов «нет», распознавать нечем. Чтение
    через numpy + imdecode от пути не зависит.
    """
    try:
        data = np.fromfile(path, dtype=np.uint8)
    except OSError:
        return None
    if data.size == 0:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def _normalize(vec):
    vec = vec.astype(np.float32).ravel()
    vec -= vec.mean()
    norm = np.linalg.norm(vec)
    return vec / norm if norm > 1e-6 else vec


def _cell_vector(img):
    """Цветная подпись изображения: уменьшенная картинка как единый вектор."""
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    cell = cv2.resize(img, (CELL_W, CELL_H), interpolation=cv2.INTER_AREA)
    return _normalize(cell)


def saturation(img):
    """Средняя насыщенность: у портрета героя высокая, у серого интерфейса низкая."""
    if img is None or img.size == 0:
        return 0.0
    if img.ndim == 2:
        return 0.0
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    return float(hsv[:, :, 1].mean())


class Recognizer:
    """Держит эталоны героев и ищет их на кадрах."""

    def __init__(self, hero_names=None):
        # Одно ядро под распознавание. По умолчанию OpenCV забирает все ядра
        # на matchTemplate - и игра в этот момент проседает по FPS. Нам
        # спешить некуда: драфт длится минуту, полный поиск на одном ядре
        # занимает несколько секунд, и это нормально.
        try:
            cv2.setNumThreads(1)
        except Exception:  # noqa: BLE001 — не во всех сборках доступно
            pass
        self.hero_names = hero_names or {}
        self.ids = []
        self.templates = {}       # hero_id -> серое изображение эталона
        self.matrix = None        # (N, CELL_W*CELL_H) нормализованные эталоны
        self._load()

    # --- загрузка эталонов ------------------------------------------------
    def _load(self):
        rows = []
        for hero_id in icons.available_ids():
            path = icons.portrait_path(hero_id)
            img = read_image(path)
            if img is None:
                continue
            # для поиска по кадру нужен серый шаблон (так быстрее),
            # а для классификации — цветной: цвет отличает героя от интерфейса
            self.templates[hero_id] = _to_gray(img)
            rows.append(_cell_vector(img))
            self.ids.append(hero_id)
        self.matrix = np.vstack(rows) if rows else None

    @property
    def ready(self):
        return self.matrix is not None and len(self.ids) > 0

    def name(self, hero_id):
        return self.hero_names.get(hero_id, str(hero_id))

    # --- быстрый путь: классификация известных прямоугольников -------------
    def classify_crop(self, crop):
        """Определяет героя на вырезанном фрагменте: (hero_id, уверенность)."""
        if not self.ready or crop is None or crop.size == 0:
            return None, 0.0
        vec = _cell_vector(crop)
        scores = self.matrix @ vec
        best = int(np.argmax(scores))
        return self.ids[best], float(scores[best])

    def classify_boxes(self, frame, boxes, threshold=0.55):
        """Классифицирует список прямоугольников (x, y, w, h) на кадре."""
        out = []
        h, w = frame.shape[:2]
        for (x, y, bw, bh) in boxes:
            x0, y0 = max(0, int(x)), max(0, int(y))
            x1, y1 = min(w, int(x + bw)), min(h, int(y + bh))
            if x1 <= x0 or y1 <= y0:
                continue
            hero_id, score = self.classify_crop(frame[y0:y1, x0:x1])
            if hero_id is not None and score >= threshold:
                out.append({"hero_id": hero_id, "name": self.name(hero_id),
                            "score": round(score, 3), "box": [x0, y0, x1 - x0, y1 - y0]})
        return out

    # --- медленный путь: поиск по всему кадру ------------------------------
    def _match_all(self, work, tw):
        """Лучшее совпадение каждого эталона при ширине tw: {hero_id: (score, loc)}."""
        th = max(4, int(round(tw * 9 / 16)))
        wh, ww = work.shape[:2]
        if th >= wh or tw >= ww:
            return None, th
        out = {}
        for hero_id, tmpl in self.templates.items():
            small = cv2.resize(tmpl, (tw, th), interpolation=cv2.INTER_AREA)
            res = cv2.matchTemplate(work, small, cv2.TM_CCOEFF_NORMED)
            _, mx, _, loc = cv2.minMaxLoc(res)
            out[hero_id] = (float(mx), loc)
        return out, th

    @staticmethod
    def _quality(matches):
        """Насколько правдоподобен масштаб: среднее по нескольким лучшим.

        Судить по сумме всех совпадений выше порога нельзя: мелкий шаблон
        всегда «находится» во множестве мест и выигрывает по количеству,
        хотя ни одно совпадение не настоящее.
        """
        if not matches:
            return 0.0
        top = sorted((s for s, _ in matches.values()), reverse=True)[:QUALITY_TOP]
        return sum(top) / len(top)

    def scan(self, frame, threshold=0.70, widths=SCAN_WIDTHS, max_results=12,
             verify_threshold=0.62, hint_width=None):
        """Ищет портреты героев по всему кадру в нескольких масштабах.

        Порядок работы:
        1. грубый проход на уменьшенном кадре — определяем масштаб портретов;
        2. точный проход на рабочем кадре только в найденном масштабе;
        3. подавление пересечений;
        4. проверка каждой детекции быстрым классификатором — он почти не
           ошибается, поэтому отсекает ложные срабатывания поиска.

        hint_width — ширина портрета (в пикселях исходного кадра) с прошлого
        удачного поиска. Масштаб интерфейса игры за время драфта не меняется,
        поэтому повторный поиск перебирает три масштаба вокруг известного
        вместо одиннадцати — это в несколько раз дешевле по процессору.

        Возвращает (детекции, ширина портрета в координатах исходного кадра).
        """
        if not self.ready:
            return [], None

        gray_full = _to_gray(frame)
        fh, fw = gray_full.shape[:2]

        if hint_width:
            k_hint = min(1.0, WORK_WIDTH / fw)
            base = hint_width * k_hint
            widths = tuple(sorted({max(8, int(round(base * f))) for f in (0.94, 1.0, 1.06)}))

        def resized(target_w):
            k = min(1.0, target_w / fw)
            if k >= 1.0:
                return gray_full, 1.0
            return cv2.resize(gray_full, (int(fw * k), int(fh * k)),
                              interpolation=cv2.INTER_AREA), k

        work, k_work = resized(WORK_WIDTH)
        coarse, k_coarse = resized(COARSE_WIDTH)
        ratio = k_coarse / k_work if k_work else 1.0

        def coarse_quality(tw_fine):
            """Качество масштаба, посчитанное на уменьшенном кадре."""
            tw_c = max(8, int(round(tw_fine * ratio)))
            matches, _ = self._match_all(coarse, tw_c)
            return self._quality(matches) if matches else -1.0

        # --- 1. подбор масштаба: сетка, затем уточнение вокруг лучшего ---
        # Весь перебор идёт на уменьшенном кадре: это единственный способ
        # уложиться в секунды, полный кадр стоит примерно в восемь раз дороже.
        min_width = MIN_REL_WIDTH * work.shape[1]
        best_q, best_w = -1.0, None
        for tw in widths:
            if tw < min_width:
                continue
            q = coarse_quality(tw)
            if q > best_q:
                best_q, best_w = q, tw
        if best_w is None:
            return [], None

        # шаг сетки около 15%, поэтому истинный размер может отличаться
        # на несколько процентов — без уточнения герой на краю допуска теряется.
        # С подсказкой масштаба сетка и так плотная, уточнять нечего.
        for factor in () if hint_width else (0.93, 0.97, 1.03, 1.07):
            tw = int(round(best_w * factor))
            # порог минимального размера обязателен и здесь: без проверки
            # уточнение уползало ниже него и возвращало ложные срабатывания
            if tw == best_w or tw < min_width:
                continue
            q = coarse_quality(tw)
            if q > best_q:
                best_q, best_w = q, tw

        # --- 2. один точный проход в найденном масштабе ---
        matches, used_height = self._match_all(work, best_w)
        if not matches:
            return [], None
        used_width = best_w

        hits = [{"hero_id": hid, "score": score,
                 "box": [loc[0], loc[1], used_width, used_height]}
                for hid, (score, loc) in matches.items() if score >= threshold]
        if not hits:
            return [], None

        hits = _suppress_overlaps(hits)
        hits.sort(key=lambda h: -h["score"])
        hits = hits[:max_results]

        # --- 3. перевод в координаты исходного кадра ---
        inv = 1.0 / k_work
        for h in hits:
            x, y, w_, h_ = h["box"]
            h["box"] = [int(x * inv), int(y * inv), int(w_ * inv), int(h_ * inv)]

        # --- 4. проверка классификатором ---
        # Главный критерий здесь — совпадение ответов двух независимых методов
        # (поиск по шаблону в масштабе и классификация нормализованной вырезки).
        # Порог по уверенности вторичен: у мелких портретов он занижен,
        # и жёсткий порог выбрасывал правильно распознанных героев.
        verified = []
        for h in hits:
            x, y, w_, h_ = h["box"]
            crop = frame[max(0, y):y + h_, max(0, x):x + w_]
            if saturation(crop) < MIN_SATURATION:
                continue
            hero_id, score = self.classify_crop(crop)
            if hero_id == h["hero_id"] and score >= verify_threshold:
                h["score"] = round(min(h["score"], score), 3)
                h["name"] = self.name(h["hero_id"])
                verified.append(h)

        # --- 5. отбор по геометрии ---
        verified = _keep_dominant_row(verified)
        if verified:
            mean_score = sum(h["score"] for h in verified) / len(verified)
            if len(verified) == 1 and mean_score < LONE_HIT_SCORE:
                verified = []
            elif len(verified) == 2 and mean_score < PAIR_HIT_SCORE:
                verified = []
        return verified, int(used_width * inv)


def self_test(recognizer, count=5, tile_w=110, screen=(1920, 594)):
    """Проверка распознавания на месте: кладём свои же эталоны на тёмный
    кадр и смотрим, находятся ли они. Не зависит ни от игры, ни от захвата.

    Возвращает словарь с итогом: сколько положили, сколько нашли, время.
    Если здесь провал — сломано что-то в самом распознавателе или в его
    окружении (opencv, numpy, эталоны), а не в захвате экрана.
    """
    import random
    import time

    if not recognizer.ready:
        return {"ok": False, "placed": 0, "found": 0,
                "reason": "нет загруженных эталонов"}

    ids = random.sample(recognizer.ids, min(count, len(recognizer.ids)))
    w, h = screen
    frame = np.full((h, w, 3), 24, dtype=np.uint8)
    th = int(round(tile_w * 9 / 16))
    gap = 16
    x = (w - (len(ids) * tile_w + (len(ids) - 1) * gap)) // 2
    y = 40
    for hid in ids:
        tmpl = read_image(icons.portrait_path(hid))
        if tmpl is None:
            continue
        frame[y:y + th, x:x + tile_w] = cv2.resize(tmpl, (tile_w, th),
                                                   interpolation=cv2.INTER_AREA)
        x += tile_w + gap

    started = time.time()
    hits, width = recognizer.scan(frame)
    found = {hh["hero_id"] for hh in hits}
    ok = found == set(ids)
    return {
        "ok": ok,
        "placed": len(ids),
        "found": len(found & set(ids)),
        "extra": len(found - set(ids)),
        "seconds": round(time.time() - started, 1),
        "width": width,
        "missing": [recognizer.name(i) for i in ids if i not in found],
    }


def _iou(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    x0, y0 = max(ax, bx), max(ay, by)
    x1, y1 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    if x1 <= x0 or y1 <= y0:
        return 0.0
    inter = (x1 - x0) * (y1 - y0)
    return inter / float(aw * ah + bw * bh - inter)


def _keep_dominant_row(hits):
    """Оставляет детекции, стоящие в одну строку.

    Портреты драфта выстроены в ряд на одной высоте, а ложные срабатывания
    разбросаны по кадру. Уверенность их не разделяет: настоящий герой на
    мелком портрете может набрать меньше, чем случайное совпадение на фоне.
    Геометрия разделяет надёжно.
    """
    if len(hits) < 3:
        return hits

    groups = []
    for hit in sorted(hits, key=lambda h: h["box"][1]):
        y, h_ = hit["box"][1], hit["box"][3]
        placed = False
        for g in groups:
            if abs(y - g["y"]) <= max(6, h_ * 0.5):
                g["items"].append(hit)
                g["y"] = sum(i["box"][1] for i in g["items"]) / len(g["items"])
                placed = True
                break
        if not placed:
            groups.append({"y": y, "items": [hit]})

    groups.sort(key=lambda g: (len(g["items"]),
                               sum(i["score"] for i in g["items"])), reverse=True)
    # внутри ряда портреты не накладываются вовсе, поэтому здесь можно
    # давить пересечения куда жёстче, чем при общем поиске
    return _suppress_overlaps(groups[0]["items"], iou_threshold=0.08)


def _suppress_overlaps(hits, iou_threshold=0.35):
    """Из пересекающихся детекций оставляет самую уверенную.

    Нужно, потому что похожие портреты дают отклик в одном и том же месте.
    """
    kept = []
    for hit in sorted(hits, key=lambda h: -h["score"]):
        if all(_iou(hit["box"], k["box"]) < iou_threshold for k in kept):
            kept.append(hit)
    return kept
