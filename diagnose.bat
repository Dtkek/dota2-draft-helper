@echo off
chcp 65001 >nul
title Диагностика драфт-хелпера
cd /d "%~dp0"

rem Написано на goto, без блоков в круглых скобках: см. пояснение в start.bat

if exist "app\tools\diagnose.py" goto have_project

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
echo  Если проект ещё не скачан - возьмите ZIP:
echo   https://github.com/Dtkek/dota2-draft-helper
echo  и распакуйте, запускать прямо из архива нельзя.
echo ================================================================
echo.
pause
exit /b 1

:have_project
set PY=
where py >nul 2>nul && set PY=py -3
if defined PY goto have_python
where python >nul 2>nul && set PY=python
if defined PY goto have_python

echo Python не найден. Установите Python 3 с python.org,
echo отметив галочку "Add Python to PATH".
pause
exit /b 1

:have_python
%PY% app\tools\diagnose.py
echo.
echo Скопируйте весь текст выше и пришлите его.
pause
exit /b 0

:findproject
set FOUND=
for %%R in ("%USERPROFILE%\Downloads" "%USERPROFILE%\Desktop" "%USERPROFILE%\Documents" "%USERPROFILE%\Downloads\Telegram Desktop") do call :scan "%%~R"
if not defined FOUND echo  Найти проект в обычных папках не удалось.
exit /b 0

:scan
if exist "%~1\app\tools\diagnose.py" call :report "%~1"
for /d %%D in ("%~1\*") do call :scan_one "%%~D"
exit /b 0

:scan_one
if exist "%~1\app\tools\diagnose.py" call :report "%~1"
exit /b 0

:report
if not defined FOUND echo  Проект найден здесь:
set FOUND=1
echo    %~1
exit /b 0
