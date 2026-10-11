@echo off
setlocal
cd /d "%~dp0"
set "ROOT=%~dp0.."

if not exist "%ROOT%\python\models\rfdetr_nano_coco.onnx" (
    echo [ERROR] python\models\rfdetr_nano_coco.onnx not found.
    echo         Place the RF-DETR ONNX model in python\models\ first.
    exit /b 1
)

if not exist ".venv-build" (
    py -3 -m venv .venv-build || python -m venv .venv-build || exit /b 1
)
call ".venv-build\Scripts\activate.bat"
python -m pip install --upgrade pip || exit /b 1
pip install -r buildvenv-requirements.txt || exit /b 1

rem Preserve user data (recordings, saved config) across the rebuild:
rem pyinstaller --noconfirm wipes dist\BuddyBox entirely.
if exist "dist\BuddyBox\recordings" move "dist\BuddyBox\recordings" "dist\_keep_recordings" >nul || exit /b 1
if exist "dist\BuddyBox\person_follow.json" copy /y "dist\BuddyBox\person_follow.json" "dist\_keep_config.json" >nul
if exist "dist\BuddyBox\person_follow_aruco.json" copy /y "dist\BuddyBox\person_follow_aruco.json" "dist\_keep_config_aruco.json" >nul

pyinstaller --noconfirm buddybox.spec || exit /b 1

if exist "dist\_keep_recordings" move "dist\_keep_recordings" "dist\BuddyBox\recordings" >nul
if exist "dist\_keep_config.json" (
    move /y "dist\_keep_config.json" "dist\BuddyBox\person_follow.json" >nul
) else (
    copy /y "%ROOT%\python\examples\person_follow.json" "dist\BuddyBox\" >nul 2>&1
)
if exist "dist\_keep_config_aruco.json" (
    move /y "dist\_keep_config_aruco.json" "dist\BuddyBox\person_follow_aruco.json" >nul
) else (
    copy /y "%ROOT%\python\examples\person_follow_aruco.json" "dist\BuddyBox\" >nul 2>&1
)

powershell -NoProfile -Command "Compress-Archive -Force -Path (Get-ChildItem 'dist/BuddyBox' -Exclude 'recordings').FullName -DestinationPath 'dist/BuddyBox.zip'" || exit /b 1

echo.
echo [OK] dist\BuddyBox\BuddyBox.exe / dist\BuddyBox.zip
