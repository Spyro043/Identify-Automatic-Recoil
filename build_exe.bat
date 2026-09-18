@echo off
setlocal
cd /d "%~dp0"
python -m pip install -r requirements.txt
python -m pip install pyinstaller
python -m PyInstaller --noconfirm --clean --windowed --name OfficeLogoDrag --hidden-import kmNet --hidden-import dxcam --hidden-import comtypes --hidden-import serial --hidden-import webview --add-binary "kmNet.cp312-win_amd64.pyd;." main.py
if not exist "dist\OfficeLogoDrag\CONFIG" mkdir "dist\OfficeLogoDrag\CONFIG"
xcopy /E /I /Y "CONFIG" "dist\OfficeLogoDrag\CONFIG"
if not exist "dist\OfficeLogoDrag\WEBUI" mkdir "dist\OfficeLogoDrag\WEBUI"
xcopy /E /I /Y "WEBUI" "dist\OfficeLogoDrag\WEBUI"
python -m PyInstaller --noconfirm --clean --console --name ReverseTrajectory reverse_trajectory.py
echo.
echo Build complete: dist\OfficeLogoDrag\OfficeLogoDrag.exe
echo Reverse tool: dist\ReverseTrajectory\ReverseTrajectory.exe
pause
