@echo off
rem Double-click me (Windows) to start Tinfoil Kit: the library, the AI and the map, then the kit's page in a
rem browser. No internet needed. Close this window to stop everything. The kit's own program does it all,
rem tools\tinfoilkit-windows-x64.exe, as Open Tinfoil Kit.command does on a Mac or Linux.
rem   --share       also serve phones and laptops on the home network, behind the access code (this time only;
rem                 kit.cmd share on turns it on for good: data\kit.json's share_on_network)
rem   --model=NAME  the AI to load first (a folder in downloads\models)
rem   --no-browser  don't open the browser (how Windows starts the kit as you sign in, after kit.cmd autostart on)
rem   --no-maps     don't start the map's servers (saves about 5 GB of memory)
setlocal EnableExtensions
rem The kit's folder holds three: app (this and the rest of the code), downloads (what sync gets) and data (the
rem person's own). In a git checkout, even one called app, the code is at the top instead.
for %%d in ("%~dp0.") do (
  set "APP=%%~fd"
  set "KIT=%%~fd"
  if /i "%%~nxd"=="app" if not exist "%%~fd\.git" for %%p in ("%%~fd\..") do set "KIT=%%~fp"
)
set "TK=%APP%\tools\tinfoilkit-windows-x64.exe"
if not exist "%TK%" (
  echo This copy of the kit doesn't have its program for Windows ^(tools\tinfoilkit-windows-x64.exe^). Download the kit
  echo from https://tinfoilkit.com, or build the program with tools/tinfoilkit/build.sh ^(it needs Go: https://go.dev/dl^).
  echo(
  set /p "_=Press Enter to close this window. "
  exit /b 1
)
title Tinfoil Kit
rem Out of the kit folder, so this window doesn't hold it open (UNINSTALL-Windows.bat can delete it).
cd /d "%TEMP%"
"%TK%" --root "%KIT%\." open %*
