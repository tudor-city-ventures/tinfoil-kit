@echo off
rem Double-click me (Windows) to remove Tinfoil Kit, everything it downloaded, and the Python SETUP got for it.
rem It says what it will delete and asks first. --yes skips the question, for scripts and AI agents.
rem cmd reads a script as it runs, and this one deletes itself, so it carries on from a copy in %TEMP%.
setlocal EnableExtensions EnableDelayedExpansion
if "%~1"=="--from-temp" goto start
copy /y "%~f0" "%TEMP%\tinfoilkit-uninstall.bat" >nul || exit /b 1
cd /d "%TEMP%"
"%TEMP%\tinfoilkit-uninstall.bat" --from-temp "%~dp0." %1

:start
set "KIT=%~f2"
set "YES=" & if /i "%~3"=="--yes" set "YES=1"
title Remove Tinfoil Kit
echo(
echo REMOVE TINFOIL KIT
rem This deletes the folder it was in, so make sure that folder is a kit, and not a user folder or a whole drive.
if "%KIT:~3%"=="" (
  echo The kit fills this whole drive ^(!KIT!^), and deleting it would delete everything on the drive.
  echo To start over, format the drive instead ^(File Explorer: right-click it, Format^).
  goto finish1
)
set "OK=1"
if not exist "%KIT%\kit" set "OK="
if not exist "%KIT%\tools\kit.py" set "OK="
if /i "%KIT%"=="%USERPROFILE%" set "OK="
if not defined OK (
  echo This folder ^(!KIT!^) doesn't look like a Tinfoil Kit, so nothing was deleted.
  goto finish1
)

set "TK=%KIT%"
set "DRIVE=" & set "WHERE=from this PC"
if /i not "%KIT:~0,2%"=="%USERPROFILE:~0,2%" (
  set "DRIVE=%KIT:~0,2%"
  set "WHERE=from the drive %KIT:~0,2%"
  for /f "delims=" %%l in ('powershell -NoProfile -Command "(Get-Volume -DriveLetter $env:TK[0]).FileSystemLabel" ^<nul 2^>nul') do set "WHERE=from the drive %%l (%KIT:~0,2%)"
)
echo Adding up what's here...
set "SIZE=under 1 GB"
for /f %%g in ('powershell -NoProfile -Command "[math]::Round((Get-ChildItem -LiteralPath $env:TK -Recurse -Force -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum / 1e9)" ^<nul 2^>nul') do if %%g geq 1 set "SIZE=%%g GB"
echo(
echo This deletes Tinfoil Kit !WHERE!: the folder !KIT!,
echo with the AI models, books, maps and programs it downloaded (!SIZE! in all).
echo It can't be undone. The files don't go to the Recycle Bin.
if defined DRIVE echo Nothing else on the drive is touched.
if defined YES goto delete
echo(
set "ANSWER="
set /p "ANSWER=To delete it, type delete and press Enter. To keep it, just press Enter: "
if /i "!ANSWER!"=="delete" goto delete
echo(
echo Kept. Nothing was deleted.
goto finish0

:delete
rem Stop the kit if it's running, so nothing holds its files open: its programs run from its bin folder, sharing runs
rem its tools\share.py, and the Open Tinfoil Kit window that started them goes too.
set "TK_BIN=%KIT%\bin\"
set "TK_GATE=%KIT%\tools\share.py"
set "TK_START=%KIT%\Open Tinfoil Kit for Windows.bat"
powershell -NoProfile -Command "$k = [StringComparison]::OrdinalIgnoreCase; $p = @(Get-Process | Where-Object { $_.Path -and $_.Path.StartsWith($env:TK_BIN, $k) }) + @(Get-CimInstance Win32_Process | Where-Object { $c = $_.CommandLine; $c -and (($_.Name -like 'python*' -and $c.IndexOf($env:TK_GATE, $k) -ge 0) -or ($_.Name -eq 'cmd.exe' -and $c.IndexOf($env:TK_START, $k) -ge 0)) } | ForEach-Object { Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue }); if ($p.Count) { 'Stopping the kit, which is running...'; $p | Stop-Process -Force; Start-Sleep 2 }" <nul 2>nul
rem And Windows no longer starts it as you sign in (kit.cmd autostart on), if this is the kit it starts.
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Tinfoil Kit.cmd"
if exist "%STARTUP%" findstr /i /c:"%KIT%\Open Tinfoil Kit for Windows.bat" "%STARTUP%" >nul && del "%STARTUP%"
echo Deleting... (a few hundred GB can take a minute)
rd /s /q "%KIT%" 2>nul
if exist "%KIT%\" (
  echo(
  echo Some files couldn't be deleted. What's left is in !KIT!.
  echo Close any window that's using the kit ^(Open Tinfoil Kit or SETUP^) and run this again, or delete the folder in File Explorer.
  goto finish1
)
rd /s /q "%LOCALAPPDATA%\TinfoilKit" 2>nul
rem A Mac told Spotlight to skip the drive the kit is at the top of. Undo that too.
for %%p in ("%KIT%\..") do set "TOP=%%~fp"
if defined DRIVE if "!TOP:~3!"=="" del /a /q "!TOP!.metadata_never_index" 2>nul
echo(
echo Done. Tinfoil Kit is gone, and !SIZE! is free again.
if defined DRIVE echo You can eject the drive now.

:finish0
set "RC=0"
goto finish
:finish1
set "RC=1"
:finish
if not defined YES (
  echo(
  set /p "_=Press Enter to close this window. "
)
exit %RC%
