@echo off
rem Tinfoil Kit's command line on Windows, as ./kit is on a Mac or Linux:  kit.cmd sync, kit.cmd share on and the rest
rem (.\kit.cmd in PowerShell). The kit's own program (tools\tinfoilkit-windows-x64.exe, which releases carry) runs
rem them when it's here and runs; without it, tools\kit.py does, on the Python SETUP-Windows.bat got, or else this
rem PC's own. KIT_NO_GO=1 keeps to Python.
setlocal EnableExtensions
rem The kit's folder: the one above this app folder, or this one in a git checkout (even one called app).
for %%d in ("%~dp0.") do (
  set "KIT=%%~fd"
  if /i "%%~nxd"=="app" if not exist "%%~fd\.git" for %%p in ("%%~fd\..") do set "KIT=%%~fp"
)
set "TK=%~dp0tools\tinfoilkit-windows-x64.exe"
set "GO="
if not defined KIT_NO_GO if exist "%TK%" "%TK%" version >nul 2>&1 && set "GO=1"
rem One line, so cmd reads nothing more from this file once kit update has replaced it.
if defined GO "%TK%" --root "%KIT%\." %* & exit /b
set "PY="
for /d %%d in ("%LOCALAPPDATA%\TinfoilKit\python-*") do if /i not "%%~xd"==".partial" if exist "%%d\tools\python.exe" set "PY=%%d\tools\python.exe"
rem A Python of this PC's own, 3.9 or newer. Windows' stand-in python.exe only offers to install one from the Store.
if not defined PY for /f "delims=" %%p in ('python -c "import sys; print(sys.executable * (sys.version_info >= (3, 9)))" 2^>nul') do if exist "%%p" set "PY=%%p"
if not defined PY (
  echo The kit needs Python. Double-click SETUP-Windows.bat while online: it gets it.
  exit /b 1
)
set "PYTHONUTF8=1"
rem One line, as above.
"%PY%" "%~dp0tools\kit.py" --root "%KIT%\." %* & exit /b
