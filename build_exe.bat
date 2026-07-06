@echo off
setlocal
cd /d "%~dp0"
python -m pip install -r requirements.txt
python -m pip install pyinstaller
python -m PyInstaller --noconfirm --clean --windowed --uac-admin --name OfficeLogoDrag --hidden-import kmNet --hidden-import dxcam --hidden-import comtypes --add-binary "kmNet.cp312-win_amd64.pyd;." main.py
if not exist "dist\OfficeLogoDrag\CONFIG" mkdir "dist\OfficeLogoDrag\CONFIG"
xcopy /E /I /Y "CONFIG" "dist\OfficeLogoDrag\CONFIG"
python -m PyInstaller --noconfirm --clean --console --name ReverseTrajectory reverse_trajectory.py
echo.
echo Build complete: dist\OfficeLogoDrag\OfficeLogoDrag.exe
echo Reverse tool: dist\ReverseTrajectory\ReverseTrajectory.exe
pause
