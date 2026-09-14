@echo off
chcp 65001 >nul
title Pickline
cd /d "%~dp0"

rem Весь файл написан на goto, без блоков в круглых скобках. В cmd любая
rem закрывающая скобка внутри блока if ( ... ) обрывает блок, даже если она
rem в тексте echo. Из-за этого прошлая версия всегда доходила до pause
rem и exit, и сервер не запускался вовсе.

if exist "app\server.py" goto have_project

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
echo   1. Открыть https://github.com/Dtkek/pickline
echo   2. Зелёная кнопка "Code" - "Download ZIP"
echo   3. Распаковать архив. Запускать прямо из архива нельзя.
echo   4. Запустить start.bat из распакованной папки
echo ================================================================
echo.
pause
exit /b 1

:have_project

rem --- Python -------------------------------------------------------------
set PY=
where py >nul 2>nul && set PY=py -3
if defined PY goto have_python
where python >nul 2>nul && set PY=python
if defined PY goto have_python

echo.
echo Python не найден.
echo Установите Python 3 с https://www.python.org/downloads/
echo и при установке ОБЯЗАТЕЛЬНО отметьте галочку "Add Python to PATH".
echo.
pause
exit /b 1

:have_python
echo Python найден:
%PY% --version

rem --- пакеты для чтения экрана -------------------------------------------
rem Основное приложение работает и без них, но тогда вкладка "Чтение экрана"
rem будет отключена. Ставим и обязательно проверяем результат.
%PY% -c "import cv2, numpy, mss" >nul 2>nul
if not errorlevel 1 goto packages_ok

echo.
echo Устанавливаю пакеты для чтения экрана. Это займёт пару минут...
%PY% -m pip install --upgrade pip
%PY% -m pip install -r app\requirements-vision.txt
if not errorlevel 1 goto packages_check
echo Первая попытка не удалась, пробую установить в папку пользователя...
%PY% -m pip install --user -r app\requirements-vision.txt

:packages_check
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

rem --- собственное окно (pywebview) ----------------------------------------
rem Без него приложение откроется во вкладке браузера - это не ошибка,
rem поэтому здесь без предупреждений и пауз.
%PY% -c "import webview" >nul 2>nul
if not errorlevel 1 goto window_ok
echo Устанавливаю pywebview для собственного окна...
%PY% -m pip install -r app\requirements-window.txt >nul 2>nul || %PY% -m pip install --user -r app\requirements-window.txt >nul 2>nul
%PY% -c "import webview" >nul 2>nul
if errorlevel 1 echo pywebview не установился - открою в браузере.
:window_ok

:run
echo.
echo Запускаю Pickline. Браузер откроется сам.
echo Чтобы закрыть - нажмите Ctrl+C или закройте это окно.
echo.
%PY% app\server.py
pause
exit /b 0

rem --- поиск распакованного проекта ---------------------------------------
rem Людям проще, когда им показывают готовый путь, а не просят искать самим.
:findproject
set FOUND=
for %%R in ("%USERPROFILE%\Downloads" "%USERPROFILE%\Desktop" "%USERPROFILE%\Documents" "%USERPROFILE%\Downloads\Telegram Desktop") do call :scan "%%~R"
if not defined FOUND echo  Найти проект в обычных папках не удалось.
exit /b 0

:scan
if exist "%~1\app\server.py" call :report "%~1"
for /d %%D in ("%~1\*") do call :scan_one "%%~D"
exit /b 0

:scan_one
if exist "%~1\app\server.py" call :report "%~1"
exit /b 0

:report
if not defined FOUND echo  Похоже, проект лежит здесь - запускайте start.bat оттуда:
set FOUND=1
echo    %~1
exit /b 0
