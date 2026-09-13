@echo off
chcp 65001 >nul
title Диагностика драфт-хелпера
cd /d "%~dp0"

set PY=
where py >nul 2>nul && set PY=py -3
if not defined PY (
    where python >nul 2>nul && set PY=python
)
if not defined PY (
    echo Python не найден. Установите Python 3 с python.org,
    echo отметив галочку "Add Python to PATH".
    pause
    exit /b 1
)

%PY% app\tools\diagnose.py
echo.
echo Скопируйте весь текст выше и пришлите его.
pause
