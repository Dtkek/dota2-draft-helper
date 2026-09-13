@echo off
chcp 65001 >nul
title Диагностика драфт-хелпера
cd /d "%~dp0"

rem То же, что в start.bat: без папки app рядом запускать нечего
if not exist "app\tools\diagnose.py" (
    echo.
    echo ================================================================
    echo  Рядом с этим файлом нет папки "app" - значит, запущена копия
    echo  батника в стороне от проекта.
    echo.
    echo  Текущая папка:
    echo    %CD%
    echo.
    set FOUND=
    for %%R in ("%USERPROFILE%\Downloads" "%USERPROFILE%\Desktop" "%USERPROFILE%\Documents" "%USERPROFILE%\Downloads\Telegram Desktop") do (
        for /d %%D in ("%%~R\*") do (
            if exist "%%~D\app\tools\diagnose.py" echo  Проект найден здесь: %%~D
        )
    )
    echo.
    echo  Если проект ещё не скачан - возьмите ZIP:
    echo   https://github.com/Dtkek/dota2-draft-helper
    echo  и распакуйте, запускать прямо из архива нельзя.
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
