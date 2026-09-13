@echo off
chcp 65001 >nul
title Драфт-хелпер Dota 2
cd /d "%~dp0"

rem Проверяем, что рядом лежит сам проект. Частая ошибка: скачали один
rem батник (через мессенджер или по ссылке на файл), а папку app - нет.
rem Без этой проверки Python падает с невразумительным "No such file".
if not exist "app\server.py" (
    echo.
    echo ================================================================
    echo  Рядом с этим файлом нет папки "app" - значит, запущена копия
    echo  батника в стороне от проекта.
    echo.
    echo  Текущая папка:
    echo    %CD%
    echo.
    call :findproject
    echo.
    echo  Если проект ещё не скачан:
    echo   1. Открыть https://github.com/Dtkek/dota2-draft-helper
    echo   2. Зелёная кнопка "Code" - "Download ZIP"
    echo   3. РАСПАКОВАТЬ архив (запускать прямо из архива нельзя)
    echo   4. Запустить start.bat из распакованной папки
    echo ================================================================
    echo.
    pause
    exit /b 1
)
goto :checked

rem Ищем распакованный проект в обычных местах: людям проще, когда им
rem показывают готовый путь, а не просят искать самим.
:findproject
set FOUND=
for %%R in ("%USERPROFILE%\Downloads" "%USERPROFILE%\Desktop" "%USERPROFILE%\Documents" "%USERPROFILE%\Downloads\Telegram Desktop") do (
    if exist "%%~R\app\server.py" call :report "%%~R"
    for /d %%D in ("%%~R\*") do (
        if exist "%%~D\app\server.py" call :report "%%~D"
    )
)
if not defined FOUND echo  Найти проект в обычных папках не удалось.
exit /b 0

:report
if not defined FOUND echo  Похоже, проект лежит здесь - запускайте start.bat оттуда:
set FOUND=1
echo    %~1
exit /b 0

:checked

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
