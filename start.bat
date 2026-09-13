@echo off
chcp 65001 >nul
title Драфт-хелпер Dota 2
cd /d "%~dp0"

rem Ищем Python: сначала лаунчер py, потом python из PATH
set PY=
where py >nul 2>nul && set PY=py -3
if not defined PY (
    where python >nul 2>nul && set PY=python
)
if not defined PY (
    echo.
    echo Python не найден.
    echo Установите Python 3 с https://www.python.org/downloads/
    echo и при установке ОБЯЗАТЕЛЬНО отметьте галочку "Add Python to PATH".
    echo.
    pause
    exit /b 1
)

echo Python найден:
%PY% --version

rem --- пакеты для чтения экрана -------------------------------------------
rem Основное приложение работает и без них, но тогда вкладка "Чтение экрана"
rem будет отключена. Ставим и обязательно проверяем результат: молча
rem продолжать после неудачной установки нельзя, иначе ошибка вылезет позже
rem и будет непонятно, откуда она.
%PY% -c "import cv2, numpy, mss" >nul 2>nul
if not errorlevel 1 goto packages_ok

echo.
echo Устанавливаю пакеты для чтения экрана. Это займёт пару минут...
%PY% -m pip install --upgrade pip
%PY% -m pip install -r app\requirements-vision.txt
if errorlevel 1 (
    echo Первая попытка не удалась, пробую установить в папку пользователя...
    %PY% -m pip install --user -r app\requirements-vision.txt
)

%PY% -c "import cv2, numpy, mss" >nul 2>nul
if not errorlevel 1 goto packages_ok

echo.
echo ================================================================
echo  ВНИМАНИЕ: пакеты для чтения экрана установить не удалось.
echo  Приложение запустится, но вкладка "Чтение экрана" работать не будет:
echo  героев придётся выбирать мышкой. Всё остальное работает.
echo.
echo  Попробуйте выполнить вручную в этом окне:
echo    %PY% -m pip install numpy opencv-python mss
echo  Если ругается на права - запустите этот файл от имени администратора.
echo ================================================================
echo.
pause
goto run

:packages_ok
echo Пакеты для чтения экрана на месте.

:run
echo.
echo Запускаю драфт-хелпер. Браузер откроется сам.
echo Чтобы закрыть - нажмите Ctrl+C или закройте это окно.
echo.
%PY% app\server.py
pause
