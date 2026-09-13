@echo off
chcp 65001 >nul
title Диагностика драфт-хелпера
cd /d "%~dp0"

rem То же, что в start.bat: без папки app рядом запускать нечего
if not exist "app\tools\diagnose.py" (
    echo.
    echo ================================================================
    echo  Рядом с этим файлом нет папки "app" - значит, скачан только
    echo  сам батник, а не проект целиком.
    echo.
    echo  Текущая папка:
    echo    %CD%
    echo.
    echo  Что делать:
    echo   1. Открыть https://github.com/Dtkek/dota2-draft-helper
    echo   2. Зелёная кнопка "Code" - "Download ZIP"
    echo   3. РАСПАКОВАТЬ архив в обычную папку, например C:\dota-helper
    echo   4. Запустить diagnose.bat уже из распакованной папки
    echo ================================================================
    echo.
    pause
    exit /b 1
)

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
