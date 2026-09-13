@echo off
chcp 65001 >nul
title Drafт-хелпер Dota 2
cd /d "%~dp0"

rem Ищем Python: сначала лаунчер py, потом python из PATH
set PY=
where py >nul 2>nul && set PY=py -3
if not defined PY (
    where python >nul 2>nul && set PY=python
)
if not defined PY (
    echo Python не найден. Установите Python 3 с python.org
    echo и при установке отметьте галочку "Add Python to PATH".
    pause
    exit /b 1
)

rem Чтение экрана требует дополнительных пакетов. Ставим один раз.
%PY% -c "import cv2, numpy, mss" >nul 2>nul
if errorlevel 1 (
    echo Устанавливаю пакеты для чтения экрана, это займёт пару минут...
    %PY% -m pip install --user -r app\requirements-vision.txt
)

echo Запускаю драфт-хелпер. Закрыть — Ctrl+C или крестик этого окна.
%PY% app\server.py
pause
