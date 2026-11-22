@echo off
rem Tinfoil Kit's command line on Windows, as ./kit is on a Mac or Linux:  kit.cmd sync, kit.cmd share on and the rest
rem (.\kit.cmd in PowerShell). It runs the kit's own program, tools\tinfoilkit-windows-x64.exe, which every download
rem carries. GitHub's Download ZIP has none until tools/tinfoilkit/build.sh builds it (it needs Go).
setlocal EnableExtensions
rem The kit's folder: the one above this app folder, or this one in a git checkout (even one called app).
for %%d in ("%~dp0.") do (
  set "KIT=%%~fd"
  if /i "%%~nxd"=="app" if not exist "%%~fd\.git" for %%p in ("%%~fd\..") do set "KIT=%%~fp"
)
set "TK=%~dp0tools\tinfoilkit-windows-x64.exe"
if not exist "%TK%" (
  echo This copy of the kit doesn't have its program for Windows ^(tools\tinfoilkit-windows-x64.exe^). Download the kit
  echo from https://tinfoilkit.com, or build the program with tools/tinfoilkit/build.sh ^(it needs Go: https://go.dev/dl^).
  exit /b 1
)
"%TK%" version >nul 2>&1 || (
  echo The kit's program ^(tools\tinfoilkit-windows-x64.exe^) doesn't run on this PC. Download the kit again from
  echo https://tinfoilkit.com.
  exit /b 1
)
rem One line, so cmd reads nothing more from this file once kit update has replaced it.
"%TK%" --root "%KIT%\." %* & exit /b
