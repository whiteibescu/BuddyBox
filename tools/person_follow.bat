@echo off
setlocal
cd /d "%~dp0..\python\examples"
set PY=C:\Users\User\AppData\Local\Programs\Python\Python312\python.exe
if not exist "%PY%" set PY=python
rem Qt(PySide6) UI가 설치돼 있으면 그쪽을, 아니면 tkinter UI
set APP=person_follow_qt.py
"%PY%" -c "import PySide6" >nul 2>&1 || set APP=person_follow.py
set VRX=--camera "UVC Camera" --preset vrx1080
set WEBCAM=--camera "HD Webcam" --preset webcam720

:menu
echo.
echo  ==== BuddyBox Person Follow (Meteor75 Pro 2 / Walksnail VRX Pro) ====
echo   [1] VRX Pro 1080p30 + sim        (no hardware output, screen only)
echo   [2] VRX Pro 1080p30 + Pro Micro  (REAL trainer output!)
echo   [3] VRX Pro 1080p30 + SITL       (WSL Betaflight, needs run_all.sh)
echo   [4] Webcam 720p     + sim
echo   [5] Video file      + sim        (pick file in the UI)
echo   [6] List UVC devices
echo   [Q] Quit
echo.
choice /c 123456Q /n /m "Select: "
set N=%errorlevel%
if %N%==7 exit /b 0
if %N%==1 goto vrx_sim
if %N%==2 goto vrx_real
if %N%==3 goto vrx_sitl
if %N%==4 goto webcam
if %N%==5 goto file
if %N%==6 goto list
goto menu

:vrx_sim
"%PY%" %APP% %VRX% --port sim %*
goto done

:vrx_real
"%PY%" %APP% %VRX% --port auto %*
goto done

:vrx_sitl
set SITL_IP=
for /f "usebackq tokens=1" %%i in (`wsl hostname -I`) do if not defined SITL_IP set SITL_IP=%%i
if not defined SITL_IP (
  echo [ERROR] could not get WSL IP - is WSL running?
  goto done
)
echo WSL IP = %SITL_IP%
"%PY%" %APP% %VRX% --port sitl --sitl-host %SITL_IP% %*
goto done

:webcam
"%PY%" %APP% %WEBCAM% --port sim %*
goto done

:file
"%PY%" %APP% --camera "" --preset raw --port sim --no-autoconnect %*
goto done

:list
"%PY%" %APP% --list
echo.
pause
goto menu

:done
if errorlevel 1 (
  echo.
  echo [ERROR] exit code %errorlevel% - check camera USB / COM port / model path.
  pause
)
goto menu
