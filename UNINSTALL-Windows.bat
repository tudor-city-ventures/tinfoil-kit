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
rem The kit's folder: the one above the app folder this was in (in a git checkout, even one called app, this
rem folder itself).
set "APP=%~f2"
set "KIT=%~f2"
for %%d in ("%~f2") do if /i "%%~nxd"=="app" if not exist "%~f2\.git" for %%p in ("%~f2\..") do set "KIT=%%~fp"
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
if not exist "%APP%\kit" set "OK="
if not exist "%APP%\tools\kit.py" set "OK="
if /i "%KIT%"=="%USERPROFILE%" set "OK="
if not defined OK (
  echo This folder ^(!KIT!^) doesn't look like a Tinfoil Kit, so nothing was deleted.
  goto finish1
)
rem It goes whole when it holds just the kit (a git checkout, a kit from before the app folder, and one named TinfoilKit
rem do too). An app folder put somewhere on its own, like the Desktop, has other things beside it, which aren't the kit's.
set "OTHER="
for %%d in ("%KIT%") do set "KIT_NAME=%%~nxd"
if /i not "%KIT%"=="%APP%" if /i not "!KIT_NAME!"=="TinfoilKit" for /f "eol=: delims=" %%f in ('dir /b /a "%KIT%" 2^>nul') do (
  set "ENTRY=%%f"
  if /i not "!ENTRY!"=="app" if /i not "!ENTRY!"=="downloads" if /i not "!ENTRY!"=="data" if /i not "!ENTRY!"==".DS_Store" if /i not "!ENTRY!"=="desktop.ini" if /i not "!ENTRY!"=="Thumbs.db" if /i not "!ENTRY!"==".kit-write-test" if not "!ENTRY:~0,2!"=="._" set "OTHER=1"
)
if defined OTHER (
  echo This app folder isn't in a folder of its own: !KIT! has other things in it, so nothing was deleted.
  echo Delete the app folder yourself, and the downloads and data folders beside it if they're the kit's.
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
echo with the AI models, books, maps and programs it downloaded, and your settings (!SIZE! in all).
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
rem Stop the kit if it's running, so nothing holds its files open: its programs run from its downloads\bin folder
rem (bin, before the three folders) and its tools folder (the kit's own program), sharing runs its tools\share.py,
rem and the Open Tinfoil Kit window that started them goes too.
set "TK_BIN=%KIT%\downloads\bin\"
if not exist "%KIT%\downloads\" set "TK_BIN=%KIT%\bin\"
set "TK_TOOLS=%APP%\tools\"
set "TK_GATE=%APP%\tools\share.py"
set "TK_START=%APP%\Open Tinfoil Kit for Windows.bat"
powershell -NoProfile -Command "$k = [StringComparison]::OrdinalIgnoreCase; $p = @(Get-Process | Where-Object { $_.Path -and ($_.Path.StartsWith($env:TK_BIN, $k) -or $_.Path.StartsWith($env:TK_TOOLS, $k)) }) + @(Get-CimInstance Win32_Process | Where-Object { $c = $_.CommandLine; $c -and (($_.Name -like 'python*' -and $c.IndexOf($env:TK_GATE, $k) -ge 0) -or ($_.Name -eq 'cmd.exe' -and $c.IndexOf($env:TK_START, $k) -ge 0)) } | ForEach-Object { Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue }); if ($p.Count) { 'Stopping the kit, which is running...'; $p | Stop-Process -Force; Start-Sleep 2 }" <nul 2>nul
rem And Windows no longer starts it as you sign in (kit.cmd autostart on), if this is the kit it starts.
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Tinfoil Kit.cmd"
if exist "%STARTUP%" findstr /i /c:"%APP%\Open Tinfoil Kit for Windows.bat" "%STARTUP%" >nul && del "%STARTUP%"
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
