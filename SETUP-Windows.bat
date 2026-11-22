@echo off
rem Double-click me (Windows) to set up Tinfoil Kit, and again whenever you want the newest models, books and maps.
rem The first time, it asks whether the kit goes on an external drive or on this PC, and copies it there.
rem Then it's kit update, sync and test, as SETUP.command does on a Mac or Linux.
rem The kit's tools run on Python. SETUP gets python.org's own build from nuget.org (about 15 MB, once), checks it
rem against the checksum below, and keeps it in %LOCALAPPDATA%\TinfoilKit, outside the kit folder, so the kit can
rem move. UNINSTALL-Windows.bat removes it. KIT_PYTHON_URL: get the same file from there instead (tests).
rem cmd reads this file a line at a time while it runs, and kit update can replace it, so each line that hands
rem over to a new copy of SETUP also ends this one.
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
set "KIT=%CD%"
set "NAME=TinfoilKit"
set "ROOM=50"
set "PYV=3.14.10"
set "PYSHA=f54ba67c9951c3d773ea47d2bb095150c037c399f0423a968bcda22809241784"
set "PYURL=https://api.nuget.org/v3-flatcontainer/python/%PYV%/python.%PYV%.nupkg"
if defined KIT_PYTHON_URL set "PYURL=%KIT_PYTHON_URL%"
set "PYHOME=%LOCALAPPDATA%\TinfoilKit\python-%PYV%"
set "PY=%PYHOME%\tools\python.exe"
set "PYTHONUTF8=1"
set "SYS=%SystemRoot%\System32"
set "OUT=%TEMP%\tinfoilkit-setup-%RANDOM%.txt"
set "TRIES=0"
title Tinfoil Kit setup

if not exist "%KIT%\tools\kit.py" (
  echo(
  echo This is only part of Tinfoil Kit. If you opened the ZIP file, extract it first: right-click it, choose
  echo Extract All, then double-click SETUP-Windows.bat in the folder that makes.
  call :finish 1
)
if "%~1"=="--updated" goto download
if "%~1"=="--placed" goto placed

echo(
set "UPDATE="
if exist ".kit\state.json" findstr /c:"\"last_sync\"" ".kit\state.json" >nul 2>&1 && set "UPDATE=1"
if defined UPDATE (
  echo TINFOIL KIT UPDATE
  echo This gets the newest AI models, books and maps, including any added to the kit since you last ran it.
  echo It downloads only what changed. If it's cut off, the kit keeps working with what it has.
) else (
  echo TINFOIL KIT SETUP
  echo This gets an offline AI, library and maps ready for when the internet is down, then checks that they work.
  echo The first time takes a few hours. Later runs only download what changed.
)
call :python || call :finish 1
if exist ".kit\" (
  call :where_kit
  echo(
  echo Step 1 of 3: the kit is !WHERE!, in !KIT!
) else (
  call :place
)
goto checks

:placed
if not "%~2"=="" call :remove_download "%~2"
:checks
call :writable || call :finish 1
echo(
"%PY%" "%KIT%\tools\kit.py" --root "%KIT%" update & if errorlevel 3 call "%KIT%\SETUP-Windows.bat" --updated & exit

:download
call :python || call :finish 1
echo(
echo Step 2 of 3: download. Here's what will change:
call :kit plan || call :finish 1
echo(
echo Each item comes from its publisher under its own license, listed in THIRD-PARTY.md. Downloading means you accept them.
echo Big downloads take hours. Keep this PC plugged in with the lid open: it won't go to sleep while this runs.
echo You can stop any time (press Ctrl+C, or close this window) and double-click SETUP later to carry on.
call :ask "Start downloading?" || call :finish 0
call :stop_kit
call :kit sync --yes
set "RC=%errorlevel%"
if "%RC%"=="130" (
  echo(
  echo Stopped. Everything downloaded so far is kept. Double-click SETUP again to carry on where it left off.
  call :finish 130
)
echo(
echo Step 3 of 3: start everything offline and check that it answers.
call :kit test
set "TESTED=%errorlevel%"
if "%TESTED%"=="130" (
  echo Stopped.
  call :finish 130
)
if "%TESTED%"=="0" if "%RC%"=="0" goto all_set
if "%TESTED%"=="0" (
  echo(
  echo Everything in the kit works, but some downloads didn't finish:
  call :problems
  echo(
  echo You can use the kit now: double-click START-HERE-Windows.bat. Double-click SETUP again later to get the rest.
  call :finish 1
)
echo(
echo Some checks failed. The messages above say which; logs are in the logs folder.
if not "%RC%"=="0" call :problems
echo Running SETUP again often fixes a download that was cut off.
call :finish 1

:all_set
call :where_kit
echo(
echo All set. Tinfoil Kit is !WHERE!, in !KIT!
if "!WHERE!"=="on this PC" (
  echo In an outage: in File Explorer, open that folder and double-click START-HERE-Windows.bat. No internet needed.
) else (
  echo In an outage: plug in the drive, open its !KIT:~3! folder and double-click START-HERE-Windows.bat. No internet needed.
)
echo(
echo Also in that folder:
echo   GUIDE.md               a short guide. Print it and keep it handy.
echo   SETUP-Windows.bat      double-click it again whenever you want the newest AI models, books and maps (needs internet).
echo   UNINSTALL-Windows.bat  removes the kit and everything it downloaded.
start "" explorer.exe "%KIT%"
call :ask "Open the kit now?" && (del "%OUT%" 2>nul & call "%KIT%\START-HERE-Windows.bat" & exit 0)
call :finish 0

rem ---------------------------------------------------------------------------- first run: where the kit goes

:place
set "NEED=" & set "HOMEFREE="
"%PY%" "%KIT%\tools\kit.py" --root "%KIT%" estimate > "%OUT%" 2>nul && set /p NEED=<"%OUT%"
call :number "!NEED!" || set "NEED=300"
"%PY%" -c "import shutil, sys; print(shutil.disk_usage(sys.argv[1]).free // 10**9)" "%USERPROFILE%" > "%OUT%" 2>nul && set /p HOMEFREE=<"%OUT%"
call :number "!HOMEFREE!" || set "HOMEFREE=0"
set /a "ENOUGH=NEED+ROOM"
echo(
echo Step 1 of 3: where should the kit go?
echo Your kit needs about !NEED! GB.
echo(
echo   1  An external drive
echo      Keep it somewhere safe and plug it in when you need it: into any Windows PC, Mac or Linux PC.
echo   2  This PC
if !HOMEFREE! geq !ENOUGH! (
  echo      Nothing to plug in. Its disk has !HOMEFREE! GB free.
) else (
  echo      Nothing to plug in, but its disk has only !HOMEFREE! GB free, too little for all of it.
)
call :choose "Type 1 or 2, then press Enter:" 2
if "!PICK!"=="2" goto this_pc

:which_drive
set "N=0"
"%PY%" "%KIT%\tools\kit.py" --root "%KIT%" drives > "%OUT%" 2>nul
for /f "usebackq tokens=1-5 delims=	" %%a in ("%OUT%") do (
  set /a "N+=1"
  set "D!N!=%%a" & set "F!N!=%%b" & set "G!N!=%%c" & set "W!N!=%%d" & set "L!N!=%%e"
)
echo(
echo Which drive?
if !N!==0 (
  echo No external drive is plugged in.
  echo   1  Look again ^(plug the drive in first, and give it a few seconds^)
  echo   2  Put the kit on this PC instead
  call :choose "Type 1 or 2, then press Enter:" 2
  if "!PICK!"=="2" goto this_pc
  goto which_drive
)
for /l %%i in (1,1,!N!) do (
  if "!W%%i!"=="-" (
    echo   %%i  !L%%i! ^(!F%%i!, !G%%i! GB free^)
  ) else (
    echo   %%i  !L%%i! ^(won't work: !F%%i!^)
  )
)
set /a "LOOK=N+1, HERE=N+2"
echo   !LOOK!  Look again (just plugged one in?)
echo   !HERE!  Put the kit on this PC instead
call :choose "Type a number, then press Enter:" !HERE!
if !PICK!==!HERE! goto this_pc
if !PICK!==!LOOK! goto which_drive
set "VOL=!D%PICK%!" & set "FMT=!F%PICK%!" & set "VFREE=!G%PICK%!" & set "WHY=!W%PICK%!" & set "VNAME=!L%PICK%!"
if not "!WHY!"=="-" (
  echo(
  echo !VNAME! won't work: !WHY!.
  echo To use it, erase it as exFAT. Erasing deletes everything on it, so copy off anything you want to keep first.
  echo In File Explorer: right-click the drive under This PC, choose Format, pick exFAT as the file system, and click Start.
  echo(
  set /p "_=When the drive is ready, press Enter to look again. "
  goto which_drive
)
if /i "!FMT!"=="NTFS" (
  echo(
  echo !VNAME! is formatted as NTFS. The kit works on it on Windows and Linux, but a Mac can't save to it.
  echo For a drive that works with any computer, erase it as exFAT first ^(File Explorer: right-click it, Format^).
  call :ask "Use !VNAME! as it is?" || goto which_drive
)
if !VFREE! lss !NEED! (
  echo(
  echo !VNAME! has !VFREE! GB free, and the kit needs about !NEED! GB.
  echo The most important things download first, and what doesn't fit is skipped. A bigger drive holds it all.
  call :ask "Use !VNAME! anyway?" || goto which_drive
)
if not "!VOL:~-1!"=="\" set "VOL=!VOL!\"
set "DEST=!VOL!%NAME%"
goto put_kit

:this_pc
if !HOMEFREE! lss !ENOUGH! (
  echo(
  echo !HOMEFREE! GB is free on this PC. The kit needs about !NEED! GB, and leaves %ROOM% GB free so this PC keeps working.
  echo The most important things download first, and what doesn't fit is skipped.
  call :ask "Put the kit on this PC anyway?" || goto which_drive
)
set "DEST=%USERPROFILE%\%NAME%"

:put_kit
rem kit place says what it did, or why it can't, and prints the kit's new folder
"%PY%" "%KIT%\tools\kit.py" --root "%KIT%" place "%DEST%" > "%OUT%" || call :finish 1
set "NEW="
for /f "usebackq delims=" %%l in ("%OUT%") do set "NEW=%%l"
if not defined NEW call :finish 1
if /i "!NEW!"=="!KIT!" goto :eof
cd /d "!NEW!" & call "!NEW!\SETUP-Windows.bat" --placed "!KIT!" & exit

rem Remove the download the kit was copied from: only a fresh one, never a git checkout, a drive or the user folder.
:remove_download
set "OLD=%~1"
if exist "%OLD%\.git\" goto :eof
if not exist "%OLD%\tools\kit.py" goto :eof
if not exist "%OLD%\SETUP-Windows.bat" goto :eof
if "%OLD:~3%"=="" goto :eof
if /i "%OLD%"=="%USERPROFILE%" goto :eof
if /i "%OLD%"=="%KIT%" goto :eof
rd /s /q "%OLD%" 2>nul
if exist "%OLD%\" (
  echo The download it came from is still in !OLD!. You can delete it.
) else (
  echo Removed the download it came from.
)
goto :eof

rem ---------------------------------------------------------------------------- helpers

:kit
"%PY%" "%KIT%\tools\kit.py" --root "%KIT%" %*
exit /b %errorlevel%

rem Python for the kit's tools: python.org's build, checked against PYSHA. Needs Windows 10 1803+ (curl, tar).
:python
if exist "%PY%" goto :eof
if not exist "%SYS%\curl.exe" goto old_windows
if not exist "%SYS%\tar.exe" goto old_windows
echo(
echo First, the kit needs Python, which its tools run on. Getting python.org's own build (about 15 MB, once)...
if not exist "%LOCALAPPDATA%\TinfoilKit\" mkdir "%LOCALAPPDATA%\TinfoilKit"
set "PKG=%PYHOME%.nupkg"
"%SYS%\curl.exe" -fL --retry 3 --progress-bar -o "%PKG%" "%PYURL%" || (
  del "%PKG%" 2>nul
  echo Couldn't download Python. Is this PC online? Then double-click SETUP again.
  exit /b 1
)
set "GOT="
for /f "skip=1 delims=" %%h in ('certutil -hashfile "%PKG%" SHA256') do if not defined GOT set "GOT=%%h"
set "GOT=!GOT: =!"
if /i not "!GOT!"=="%PYSHA%" (
  del "%PKG%" 2>nul
  echo Python's download didn't match its checksum, so it was deleted. Double-click SETUP again.
  exit /b 1
)
rd /s /q "%PYHOME%.partial" 2>nul
mkdir "%PYHOME%.partial"
"%SYS%\tar.exe" -xf "%PKG%" -C "%PYHOME%.partial" || (
  echo Couldn't unpack Python. Double-click SETUP again.
  exit /b 1
)
rd /s /q "%PYHOME%" 2>nul
move "%PYHOME%.partial" "%PYHOME%" >nul || exit /b 1
del "%PKG%" 2>nul
"%PY%" -c "import sys" || (
  echo Python won't start on this PC.
  exit /b 1
)
goto :eof
:old_windows
echo(
echo Tinfoil Kit needs Windows 10 (version 1803 or newer) or Windows 11.
exit /b 1

rem "on this PC" or "on the drive NAME", in WHERE
:where_kit
set "WHERE=on this PC"
if /i "%KIT:~0,2%"=="%USERPROFILE:~0,2%" goto :eof
set "WHERE=on the drive %KIT:~0,2%"
"%PY%" "%KIT%\tools\kit.py" --root "%KIT%" drives > "%OUT%" 2>nul
for /f "usebackq tokens=1,5 delims=	" %%a in ("%OUT%") do (
  set "P=%%a"
  if /i "!P:~0,2!"=="%KIT:~0,2%" set "WHERE=on the drive %%b"
)
goto :eof

:writable
(type nul > "%KIT%\.kit-write-test") 2>nul || (
  echo(
  echo Can't save anything in !KIT!. If it's on a drive, the drive may be locked or read-only.
  echo Check the drive, or move this folder somewhere else, and run SETUP again.
  exit /b 1
)
del "%KIT%\.kit-write-test" 2>nul
goto :eof

rem The kit's programs hold their files open, and Windows won't replace an open file: stop them before updating.
:stop_kit
set "TK_BIN=%KIT%\bin\"
powershell -NoProfile -Command "$p = @(Get-Process | Where-Object { $_.Path -and $_.Path.StartsWith($env:TK_BIN, [StringComparison]::OrdinalIgnoreCase) }); if ($p.Count) { 'The kit is running. Stopping it, so its files can be updated...'; $p | Stop-Process -Force; Start-Sleep 2 }" <nul 2>nul
goto :eof

rem The list of what failed, from the newest sync log: the sync's own copy has scrolled far up by now.
:problems
"%PY%" -c "import glob; f = sorted(glob.glob('logs/sync-*.log'))[-1:]; t = open(f[0], encoding='utf-8', errors='replace').read().split('===== sync started')[-1] if f else ''; p = t.split('Problems', 1)[1].split('Re-run', 1)[0] if 'Problems' in t else ''; print(chr(10).join(l for l in p.splitlines() if l.startswith('  - ')))"
goto :eof

:ask
set "A="
set /p "A=%~1 [Y/n] "
if not defined A exit /b 0
if /i "!A!"=="y" exit /b 0
if /i "!A!"=="yes" exit /b 0
exit /b 1

rem A number from 1 to %2, in PICK. Stops if the window has nothing more to read, rather than asking forever.
:choose
set /a "TRIES+=1"
if !TRIES! gtr 30 (
  echo(
  echo No answer, so SETUP stopped.
  call :finish 1
)
set "PICK="
set /p "PICK=%~1 "
call :number "!PICK!" && if !PICK! geq 1 if !PICK! leq %2 (
  set "TRIES=0"
  goto :eof
)
echo Type a number from 1 to %2, then press Enter.
goto choose

:number
set "NUM=%~1"
if not defined NUM exit /b 1
for /f "delims=0123456789" %%x in ("!NUM!") do exit /b 1
exit /b 0

:finish
del "%OUT%" 2>nul
echo(
set /p "_=Press Enter to close this window. "
exit %~1
