# -*- coding: utf-8 -*-
"""HTTP-запросы с кэшем на диск.

У системного python на macOS часто не настроены корневые сертификаты, поэтому
запрос сначала пробуется через urllib, а при ошибке SSL — через curl.
Кэш нужен, чтобы не упираться в лимит OpenDota (60 запросов в минуту).
"""
import gzip
import hashlib
import json
import os
import ssl
import subprocess
import threading
import time
import urllib.error
import urllib.request

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")
UA = "dota2-draft-helper/1.0 (personal use)"

_ssl_context = None
_use_curl = False


def _context():
    """SSL-контекст с сертификатами certifi, если он установлен."""
    global _ssl_context
    if _ssl_context is None:
        try:
            import certifi
            _ssl_context = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            _ssl_context = ssl.create_default_context()
    return _ssl_context


def _cache_path(url):
    key = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
    return os.path.join(CACHE_DIR, key + ".json")


def _read_cache(url, ttl):
    path = _cache_path(url)
    if not os.path.exists(path):
        return None
    if ttl is not None and time.time() - os.path.getmtime(path) > ttl:
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _write_cache(url, data):
    os.makedirs(CACHE_DIR, exist_ok=True)
    tmp = _cache_path(url) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, _cache_path(url))


def _fetch_urllib(url, timeout):
    # Сжатие обязательно: heroStats весит 161 КБ, а со сжатием 33 КБ.
    # На нестабильных каналах большой ответ просто не доходит — соединение
    # рвётся на середине, и приложение выглядит зависшим.
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept-Encoding": "gzip",
    })
    with urllib.request.urlopen(req, timeout=timeout, context=_context()) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))


def _fetch_curl(url, timeout):
    out = subprocess.run(
        ["curl", "-sS", "-L", "--compressed", "--max-time", str(timeout),
         "-H", f"User-Agent: {UA}", url],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        raise RuntimeError(f"curl вернул код {out.returncode}: {out.stderr.strip()[:200]}")
    return json.loads(out.stdout)


def get_json(url, ttl=3600, timeout=45, stale_ok=True):
    """Забирает JSON по url. ttl — сколько секунд кэш считается свежим.

    Если сеть недоступна, а в кэше есть просроченная копия, возвращается она
    (stale_ok): для драфт-хелпера вчерашние винрейты лучше, чем ошибка.
    """
    global _use_curl
    cached = _read_cache(url, ttl)
    if cached is not None:
        return cached

    error = None
    order = (_fetch_curl, _fetch_urllib) if _use_curl else (_fetch_urllib, _fetch_curl)
    for fetch in order:
        try:
            data = fetch(url, timeout)
            _use_curl = fetch is _fetch_curl
            _write_cache(url, data)
            return data
        except Exception as e:  # noqa: BLE001 — нужен любой сбой, чтобы попробовать запасной путь
            error = e

    if stale_ok:
        stale = _read_cache(url, ttl=None)
        if stale is not None:
            return stale
    raise RuntimeError(f"не удалось получить {url}: {error}")


def cached(url, ttl=3600):
    """Отдаёт данные из кэша, если они свежие. В сеть не ходит.

    Нужно, чтобы решать, идти ли в сеть вообще: на медленном канале
    поход за данными стоит десятки секунд, и лучше сперва посмотреть,
    нет ли готового ответа под рукой.
    """
    return _read_cache(url, ttl)


_refreshing = set()
_refresh_lock = threading.Lock()


def refresh_in_background(url, ttl=3600):
    """Обновляет кэш по-тихому, не задерживая ответ пользователю.

    На один url — не больше одного потока. Без этой защиты каждый запрос
    страницы плодил десяток одновременных скачиваний одного и того же:
    hero_stats() зовут отовсюду, и пока кэш пуст, все они просили обновление.
    На медленном канале такой шторм душил сам себя.
    """
    with _refresh_lock:
        if url in _refreshing:
            return None
        _refreshing.add(url)

    def worker():
        try:
            get_json(url, ttl=0)
        except Exception:  # noqa: BLE001 — фоновое обновление не критично
            pass
        finally:
            with _refresh_lock:
                _refreshing.discard(url)

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    return t


def _download_urllib(url, tmp, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout, context=_context()) as r:
        data = r.read()
    if not data:
        raise RuntimeError("пустой ответ")
    with open(tmp, "wb") as f:
        f.write(data)


def _download_curl(url, tmp, timeout):
    out = subprocess.run(
        ["curl", "-sS", "-L", "--max-time", str(timeout),
         "-H", f"User-Agent: {UA}", "-o", tmp, url],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        raise RuntimeError(f"curl: {out.stderr.strip()[:160] or 'код ' + str(out.returncode)}")
    if not os.path.exists(tmp):
        raise RuntimeError("curl не создал файл")


def download(url, dest, timeout=20):
    """Скачивает файл (картинку) в dest.

    Возвращает (True, None) при успехе или (False, причина). Причина нужна
    обязательно: молчаливый False оставлял пользователя с «0 из 127» и без
    единой подсказки, что произошло.

    Способ скачивания липкий, как в get_json: если urllib однажды не смог,
    дальше сразу идём через curl. Иначе на канале, где urllib подвисает,
    127 портретов ждали бы по таймауту каждый.
    """
    global _use_curl
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return True, None
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".part"

    errors = []
    order = (_download_curl, _download_urllib) if _use_curl else (_download_urllib, _download_curl)
    for fetch in order:
        try:
            fetch(url, tmp, timeout)
            if os.path.getsize(tmp) == 0:
                raise RuntimeError("скачан пустой файл")
            _use_curl = fetch is _download_curl
            os.replace(tmp, dest)
            return True, None
        except Exception as e:  # noqa: BLE001 — пробуем второй способ
            errors.append(f"{fetch.__name__.replace('_download_', '')}: "
                          f"{type(e).__name__}: {str(e)[:120]}")
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
    return False, "; ".join(errors)


def clear_cache():
    """Удаляет кэш целиком — на случай, когда нужны свежие данные немедленно."""
    if not os.path.isdir(CACHE_DIR):
        return 0
    removed = 0
    for name in os.listdir(CACHE_DIR):
        if name.endswith(".json"):
            os.remove(os.path.join(CACHE_DIR, name))
            removed += 1
    return removed
