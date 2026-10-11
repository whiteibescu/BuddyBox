@echo off
setlocal
cd /d "%~dp0..\python"
set PY=python
set CAM=--camera "UVC Camera" --preset vrx1080
set GLYPHS=tools\osd_glyphs.json

:menu
echo.
echo  ==== BuddyBox MTF-02P OSD readout (Walksnail video -> sensor values) ====
echo   [1] Grid check only        (camera, no FC)        osd_calibrate --show
echo   [2] Calibrate on bench     (camera + FC USB MSP)  osd_calibrate --msp COMx
echo   [3] Live values in flight  (camera)               osd_sensor --show
echo   [4] Live values + CSV      (camera)               osd_sensor --csv flight_YYYYMMDD.csv
echo   [5] Extract from video     (raw.mp4 -> CSV)       osd_sensor --video
echo   [6] Print Betaflight CLI lines (osd_*_pos)
echo   [0] Quit
echo.
set /p CH=Select:
if "%CH%"=="1" %PY% tools\osd_calibrate.py %CAM% --show & goto menu
if "%CH%"=="2" (
    set /p COM=FC USB port (e.g. COM7):
    %PY% tools\osd_calibrate.py %CAM% --msp %COM% --out %GLYPHS% --show
    goto menu
)
if "%CH%"=="3" %PY% tools\osd_sensor.py %CAM% --glyphs %GLYPHS% --show & goto menu
if "%CH%"=="4" (
    for /f "tokens=1-3 delims=/.- " %%a in ("%date%") do set D=%%a%%b%%c
    %PY% tools\osd_sensor.py %CAM% --glyphs %GLYPHS% --csv recordings\osd_flight_%D%.csv --show
    goto menu
)
if "%CH%"=="5" (
    set /p VID=Video path (raw.mp4):
    %PY% tools\osd_sensor.py --video "%VID%" --glyphs %GLYPHS% --csv "%VID%.osd.csv"
    goto menu
)
if "%CH%"=="6" %PY% tools\osd_calibrate.py --pos & goto menu
if "%CH%"=="0" exit /b 0
goto menu
