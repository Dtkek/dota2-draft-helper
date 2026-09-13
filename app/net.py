# -*- coding: utf-8 -*-
"""HTTP-запросы с кэшем на диск.

У системного python на macOS часто не настроены корневые сертификаты, поэтому
запрос сначала пробуется через urllib, а при ошибке SSL — через curl.
Кэш нужен, чтобы не упираться в лимит OpenDota (60 запросов в минуту).
"""
import hashlib
import json
import os
import ssl
import subprocess
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
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout, context=_context()) as r:
        return json.loads(r.read().decode("utf-8"))


def _fetch_curl(url, timeout):
    out = subprocess.run(
        ["curl", "-sS", "-L", "--max-time", str(timeout), "-H", f"User-Agent: {UA}", url],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        raise RuntimeError(f"curl вернул код {out.returncode}: {out.stderr.strip()[:200]}")
    return json.loads(out.stdout)


def get_json(url, ttl=3600, timeout=20, stale_ok=True):
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


def download(url, dest, timeout=60):
    """Скачивает файл (картинку) в dest. Возвращает True, если файл на месте."""
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return True
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".part"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout, context=_context()) as r:
            data = r.read()
        if not data:
            raise RuntimeError("пустой ответ")
        with open(tmp, "wb") as f:
            f.write(data)
    except Exception:  # noqa: BLE001 — на Windows сертификаты бывают не настроены
        out = subprocess.run(
            ["curl", "-sS", "-L", "--max-time", str(timeout),
             "-H", f"User-Agent: {UA}", "-o", tmp, url],
            capture_output=True, text=True,
        )
        if out.returncode != 0 or not os.path.exists(tmp):
            return False
    if os.path.getsize(tmp) == 0:
        os.remove(tmp)
        return False
    os.replace(tmp, dest)
    return True


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
