@echo off
rem Double-click me (Windows) to set up Tinfoil Kit, and again whenever you want the newest models, books and maps.
rem The first time, it asks whether the kit goes on an external drive or on this PC, says how much fits there, and
rem copies it there. Then it's kit update, sync and test (the first time, the essentials come first), as
rem SETUP.command does on a Mac or Linux.
rem A home server, a PC that stays on: SETUP-Windows.bat --home-server, in a terminal. At the end it shares the kit
rem on the home network behind an access code, and starts it whenever you sign in to this PC. It goes in the
rem environment, KIT_HOME_SERVER, since this script starts itself again after moving or updating the kit.
rem The kit's tools run on Python. SETUP gets python.org's own build from nuget.org (about 15 MB, once), checks it
rem against the checksum below, and keeps it in %LOCALAPPDATA%\TinfoilKit, outside the kit folder, so the kit can
rem move. UNINSTALL-Windows.bat removes it. KIT_PYTHON_URL: get the same file from there instead (tests).
rem cmd reads this file a line at a time while it runs, and kit update can replace it, so each line that hands
rem over to a new copy of SETUP also ends this one.
setlocal EnableExtensions EnableDelayedExpansion
for %%a in (%*) do if /i "%%~a"=="--home-server" set "KIT_HOME_SERVER=1"
cd /d "%~dp0"
set "KIT=%CD%"
set "NAME=TinfoilKit"
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
rem UPDATE: set up before, so this run is an update
set "UPDATE="
if exist ".kit\state.json" findstr /c:"\"last_sync\"" ".kit\state.json" >nul 2>&1 && set "UPDATE=1"
rem Steps are counted across the times this script starts itself again (after moving or updating the kit).
if not "%~1"=="--placed" if not "%~1"=="--updated" (set "KIT_STEP=0" & set "KIT_STEPS=3")

if not exist "%KIT%\tools\kit.py" (
  echo(
  echo This is only part of Tinfoil Kit. If you opened the ZIP file, extract it first: right-click it, choose
  echo Extract All, then double-click SETUP-Windows.bat in the folder that makes.
  call :finish 1
)
if "%~1"=="--updated" goto download
if "%~1"=="--placed" goto placed

echo(
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
  call :step "the kit is !WHERE!, in !KIT!"
) else (
  set "KIT_STEPS=4"
  call :pick_region first
  call :place
)
goto checks

rem The first run's copy of this script chose this place and copied the kit here.
:placed
if not "%~2"=="" call :remove_download "%~2"
if defined KIT_ESSENTIALS call :kit essentials !KIT_ESSENTIALS! >nul
rem A kit that was there already gets the answer to "where do you live?" too
if defined KIT_REGION call :set_region >nul 2>&1
:checks
call :writable || call :finish 1
echo(
"%PY%" "%KIT%\tools\kit.py" --root "%KIT%" update & if errorlevel 3 call "%KIT%\SETUP-Windows.bat" --updated & exit

:download
call :python || call :finish 1
rem After kit update, so a kit from before this question gets it
if not defined KIT_REGION_ASKED call :pick_region
rem An update can bring models too big for this computer
if not defined KIT_FIT_ASKED call :kit fit --ask
set "ONLY=all"
findstr /r /c:"\"essentials_only\": *true" kit.json >nul 2>&1 && set "ONLY=essentials"
if defined UPDATE if "!ONLY!"=="essentials" call :offer_rest
if defined UPDATE (
  call :step "download. Here's what will change:"
  call :kit plan || call :finish 1
) else (
  call :step "the essentials. Here's what comes first:"
  call :kit plan --essentials || call :finish 1
)
echo(
echo Each item comes from its publisher under its own license, listed in THIRD-PARTY.md. Downloading means you accept them.
echo Big downloads take hours. Keep this PC plugged in with the lid open: it won't go to sleep while this runs.
echo You can stop any time (press Ctrl+C, or close this window) and double-click SETUP later to carry on.
call :ask "Start downloading?" || call :finish 0
call :stop_kit
rem The first time, the essentials come first and get checked, so the kit works hours before the rest is in.
if defined UPDATE goto get_rest
if "!ONLY!"=="essentials" goto get_rest
call :get --essentials
if not "!TESTED!"=="0" goto results
echo(
echo The essentials work: from now on, if the internet goes down, the kit is ready.
call :space "!KIT!"
call :step "everything else (about !NEED_GB!). It takes hours, and the kit works the whole time."
:get_rest
call :get
if not defined UPDATE if "!ONLY!"=="essentials" if "!TESTED!"=="0" call :step "everything else: not now. You chose just the essentials. Once there's room, SETUP offers the rest."

:results
if "%TESTED%"=="0" if "%RC%"=="0" goto all_set
if "%TESTED%"=="0" (
  echo(
  echo Everything in the kit works, but some downloads didn't finish:
  call :problems
  echo(
  if defined KIT_HOME_SERVER (
    call :home_server
    echo Run SETUP again later to get the rest.
  ) else (
    echo You can use the kit now: double-click Open Tinfoil Kit for Windows.bat. Double-click SETUP again later to get the rest.
  )
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
rem (a home server starts by itself: home_server says so)
if not defined KIT_HOME_SERVER if "!WHERE!"=="on this PC" (
  echo In an outage: in File Explorer, open that folder and double-click Open Tinfoil Kit for Windows.bat. No internet needed.
) else (
  echo In an outage: plug in the drive, open its !KIT:~3! folder and double-click Open Tinfoil Kit for Windows.bat. No internet needed.
)
echo(
echo Also in that folder:
echo   GUIDE.md               a short guide. Print it and keep it handy.
echo   SETUP-Windows.bat      double-click it again whenever you want the newest AI models, books and maps (needs internet).
echo   UNINSTALL-Windows.bat  removes the kit and everything it downloaded.
start "" explorer.exe "%KIT%"
if defined KIT_HOME_SERVER (call :home_server & call :finish 0)
call :ask "Open the kit now?" && (del "%OUT%" 2>nul & call "%KIT%\Open Tinfoil Kit for Windows.bat" & exit 0)
call :finish 0

rem Phones and laptops on the home network open the kit with its access code, and it starts as you sign in.
:home_server
echo(
echo Home server: sharing the kit on your home network, and starting it whenever you sign in to this PC.
call :kit share on >nul
call :kit autostart on
echo(
call :kit share
goto :eof

rem kit sync with these options, then start everything offline and check that it answers. Sets RC and TESTED.
:get
call :kit sync --yes %*
set "RC=%errorlevel%"
if "%RC%"=="130" (
  echo(
  echo Stopped. Everything downloaded so far is kept. Double-click SETUP again to carry on where it left off.
  call :finish 130
)
if defined UPDATE (
  call :step "start everything offline and check that it answers."
) else (
  echo(
  echo Now a check that it all starts offline and answers.
)
call :kit test
set "TESTED=%errorlevel%"
if "%TESTED%"=="130" (
  echo Stopped.
  call :finish 130
)
goto :eof

rem An update of a kit with just the essentials: offer the rest once it fits.
:offer_rest
call :space "!KIT!"
if not "!FULL!"=="fits" goto :eof
echo(
echo This kit has just the essentials, and now there's room for the rest (about !NEED_GB! more).
call :ask_no "Get the rest too?" || goto :eof
call :kit essentials off >nul
set "ONLY=all"
goto :eof

rem Where the person lives sets the maps (street detail, directions, address search, home) and Wikipedia's language.
rem kit region does the work; this asks. The first run asks before the kit moves (its size depends on the answer),
rem and hands the answer on in KIT_REGION and KIT_WIKIPEDIA to the copy of this script where the kit lands, in case
rem a kit was there already. Updates ask after kit update, so a kit from before this question gets it too.
:pick_region
call :kit region >nul 2>&1 || goto :eof
set "KIT_REGION_ASKED=1"
if not "%~1"=="first" goto region_now
call :step "where do you live?"
echo The maps show your area in street detail, with directions and address search, and Wikipedia comes in your language.
<nul set /p "=Right now: "
call :kit region
echo(
set "Q=Type your US state or your country (like Texas, Ontario or Germany), or press Enter to keep that: "
goto region_ask
:region_now
echo(
call :kit region
set "Q=To change that, type where you live (a US state or a country), or press Enter to keep it: "
:region_ask
set "PLACE="
set /p "PLACE=!Q!"
if defined PLACE set "PLACE=!PLACE:"=!"
if not defined PLACE goto :eof
"%PY%" "%KIT%\tools\kit.py" --root "%KIT%" region --find "!PLACE!" > "%OUT%" 2>nul
set "N=0"
for /f "usebackq tokens=1 delims=	" %%a in ("%OUT%") do (
  set /a "N+=1"
  set "RID!N!=%%a"
)
echo(
if !N!==0 goto region_none
if !N! gtr 20 goto region_many
set "RID=!RID1!"
if !N!==1 goto region_languages
echo Which one?
call :list
set /a "NONE=N+1"
echo   !NONE!  None of these
call :choose "Type a number, then press Enter:" !NONE!
if !PICK!==!NONE! goto region_other
set "RID=!RID%PICK%!"
echo(
goto region_languages
:region_other
echo(
set "Q=Type where you live: "
goto region_ask
:region_none
set "Q=No place called "!PLACE!" here. Type a US state or a country, in English (or press Enter to keep the maps as they are): "
goto region_ask
:region_many
set "Q=!N! places match "!PLACE!". Type your state, province or a nearby big town instead: "
goto region_ask
:region_languages
"%PY%" "%KIT%\tools\kit.py" --root "%KIT%" region --languages "!RID!" > "%OUT%" 2>nul
set "N=0"
for /f "usebackq tokens=1 delims=	" %%a in ("%OUT%") do (
  set /a "N+=1"
  set "WIKI!N!=%%a"
)
set "WIKI=!WIKI1!"
if !N! leq 1 goto region_set
echo Which language should Wikipedia be in?
call :list " GB"
call :choose "Type a number, then press Enter:" !N!
set "WIKI=!WIKI%PICK%!"
echo(
:region_set
set "KIT_REGION=!RID!"
set "KIT_WIKIPEDIA=!WIKI!"
call :set_region || (set "KIT_REGION=" & set "KIT_WIKIPEDIA=")
goto :eof

rem kit region with the answer: the place in KIT_REGION, and Wikipedia's languages in KIT_WIKIPEDIA if any
:set_region
if defined KIT_WIKIPEDIA (call :kit region "!KIT_REGION!" --wikipedia "!KIT_WIKIPEDIA!") else call :kit region "!KIT_REGION!"
exit /b %errorlevel%

rem The lines kit region wrote, numbered, as "  1  NAME (GROUP)" with this label's argument after GROUP. Python
rem prints them, since cmd would garble letters with accents.
:list
"%PY%" -c "import sys; [print('  {}  {} ({}{})'.format(i, *l.rstrip('\r\n').split('\t')[1:3], sys.argv[2])) for i, l in enumerate(open(sys.argv[1], encoding='utf-8'), 1)]" "%OUT%" "%~1"
goto :eof

rem ---------------------------------------------------------------------------- first run: where the kit goes

:place
call :step "where should the kit go?"
rem Which AI model this computer runs, and whether to get the ones too big for it
call :kit fit --ask
set "KIT_FIT_ASKED=1"
call :space "%USERPROFILE%\%NAME%"
echo(
echo All of the kit is about !NEED_GB!. Just the essentials (the AI, the medical, preparedness and repair
echo books, and the map) are about !NEED_ESS_GB!.
echo(
echo   1  An external drive
echo      Keep it somewhere safe and plug it in when you need it: into any Windows PC, Mac or Linux PC.
echo   2  This PC
echo      Nothing to plug in. Its disk has !FREE_GB! free of !TOTAL_GB!: !NOTE!.
call :choose "Type 1 or 2, then press Enter:" 2
if "!PICK!"=="1" goto which_drive
:this_pc
call :space "%USERPROFILE%\%NAME%"
call :how_much "this PC" || goto which_drive
set "DEST=%USERPROFILE%\%NAME%"
goto put_kit

:which_drive
set "N=0"
"%PY%" "%KIT%\tools\kit.py" --root "%KIT%" drives > "%OUT%" 2>nul
for /f "usebackq tokens=1-5 delims=	" %%a in ("%OUT%") do (
  set /a "N+=1"
  set "D!N!=%%a" & set "F!N!=%%b" & set "W!N!=%%d" & set "L!N!=%%e"
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
for /l %%i in (1,1,!N!) do call :drive_line %%i
set /a "LOOK=N+1, HERE=N+2"
echo   !LOOK!  Look again (just plugged one in?)
echo   !HERE!  Put the kit on this PC instead
call :choose "Type a number, then press Enter:" !HERE!
if !PICK!==!HERE! goto this_pc
if !PICK!==!LOOK! goto which_drive
set "VOL=!D%PICK%!" & set "FMT=!F%PICK%!" & set "WHY=!W%PICK%!" & set "VNAME=!L%PICK%!"
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
if not "!VOL:~-1!"=="\" set "VOL=!VOL!\"
call :space "!VOL!%NAME%"
call :how_much "!VNAME!" || goto which_drive
set "DEST=!VOL!%NAME%"

:put_kit
rem The copy there records how much of the kit it gets in its kit.json
set "KIT_ESSENTIALS=off"
if "!ONLY!"=="essentials" set "KIT_ESSENTIALS=on"
rem kit place says what it did, or why it can't, and prints the kit's new folder
"%PY%" "%KIT%\tools\kit.py" --root "%KIT%" place "%DEST%" > "%OUT%" || call :finish 1
set "NEW="
for /f "usebackq delims=" %%l in ("%OUT%") do set "NEW=%%l"
if not defined NEW call :finish 1
if /i "!NEW!"=="!KIT!" (
  call :kit essentials !KIT_ESSENTIALS! >nul
  goto :eof
)
cd /d "!NEW!" & call "!NEW!\SETUP-Windows.bat" --placed "!KIT!" & exit

rem One line of the list of drives: its name, format, free space and what fits there, or why it won't work.
:drive_line
if not "!W%~1!"=="-" (
  echo   %~1  !L%~1! ^(won't work: !F%~1!^)
  goto :eof
)
set "P=!D%~1!"
if not "!P:~-1!"=="\" set "P=!P!\"
call :space "!P!%NAME%"
echo   %~1  !L%~1! (!F%~1!, !FREE_GB! free of !TOTAL_GB!): !NOTE!
goto :eof

rem After :space, how much of the kit goes to the place it looked at (its argument names it). Sets ONLY to all or
rem essentials, or returns 1 to choose somewhere else.
:how_much
set "AT=%~1"
set "KEEPS="
if "!AT!"=="this PC" set "KEEPS=, so this PC keeps running well"
if "!FULL!"=="fits" (
  set "ONLY=all"
  exit /b 0
)
echo(
if "!FULL!"=="tight" goto how_much_tight
if "!ESS!"=="fits" goto how_much_essentials
if "!ESS!"=="tight" goto how_much_essentials_tight
echo There isn't room on !AT!, even for the essentials: they need about !NEED_ESS_GB! plus some to spare, and !FREE_GB! is free.
echo Make room there, or choose somewhere else.
exit /b 1
:how_much_tight
echo All of it fits on !AT!, but leaves only !LEFT_GB! free. Better to leave at least !LEAVE_GB!!KEEPS!.
echo   1  Just the essentials (about !NEED_ESS_GB!)
echo   2  All of it anyway (about !NEED_GB!)
echo   3  Somewhere else
call :choose "Type 1, 2 or 3, then press Enter:" 3
if "!PICK!"=="1" set "ONLY=essentials" & exit /b 0
if "!PICK!"=="2" set "ONLY=all" & exit /b 0
exit /b 1
:how_much_essentials
echo All of it won't fit on !AT!: it needs about !NEED_GB! plus some to spare, and !FREE_GB! is free.
echo   1  Just the essentials (about !NEED_ESS_GB!). SETUP offers the rest later, once it fits.
echo   2  Somewhere else
call :choose "Type 1 or 2, then press Enter:" 2
if "!PICK!"=="1" set "ONLY=essentials" & exit /b 0
exit /b 1
:how_much_essentials_tight
echo Only the essentials fit on !AT!, and they leave only !LEFT_ESS_GB! free. Better to leave at least !LEAVE_GB!!KEEPS!.
echo   1  Just the essentials anyway (about !NEED_ESS_GB!)
echo   2  Somewhere else
call :choose "Type 1 or 2, then press Enter:" 2
if "!PICK!"=="1" set "ONLY=essentials" & exit /b 0
exit /b 1

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

rem How the kit fits at a place (kit space): FULL and ESS say whether all of it and just the essentials fit with
rem room to spare (fits), only by leaving less than that (tight), or not at all (no). Then FREE and TOTAL GB on its
rem disk, NEED and NEED_ESS GB for all of it and the essentials, and LEAVE GB worth leaving free. Each also as text
rem (FREE_GB and so on), with LEFT_GB and LEFT_ESS_GB free after them, and NOTE on what fits.
:space
set "FULL=fits" & set "ESS=fits" & set "FREE=0" & set "TOTAL=0" & set "NEED=0" & set "NEED_ESS=0" & set "LEAVE=0"
"%PY%" "%KIT%\tools\kit.py" --root "%KIT%" space "%~1" > "%OUT%" 2>nul
for /f "usebackq tokens=1-7 delims=	" %%a in ("%OUT%") do (
  set "FULL=%%a" & set "ESS=%%b" & set "FREE=%%c" & set "TOTAL=%%d" & set "NEED=%%e" & set "NEED_ESS=%%f" & set "LEAVE=%%g"
)
set /a "LEFT=FREE-NEED, LEFT_ESS=FREE-NEED_ESS"
for %%v in (FREE TOTAL NEED NEED_ESS LEAVE LEFT LEFT_ESS) do call :gb %%v
set "NOTE=not enough room, even for the essentials"
if not "!ESS!"=="no" set "NOTE=room for the essentials, not all of it"
if "!FULL!"=="tight" set "NOTE=room for all of it, but that leaves only !LEFT_GB! free"
if "!FULL!"=="fits" set "NOTE=room for all of it"
goto :eof

rem The GB in the variable it's given, as text in that name with _GB after it: 300 GB, or 1.5 TB
:gb
set /a "G=%~1"
set "%~1_GB=!G! GB"
if !G! geq 1000 (
  set /a "R=(G+50)/100, T=R/10, D=R%%10"
  set "%~1_GB=!T!.!D! TB"
)
goto :eof

:step
set /a "KIT_STEP+=1"
set "MSG=%~1"
echo(
echo Step !KIT_STEP! of !KIT_STEPS!: !MSG!
goto :eof

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

rem The kit's programs hold their files open, and Windows won't replace an open file: stop them before updating. They
rem run from its bin folder, and sharing runs its tools\share.py; the Open Tinfoil Kit window that started them goes too.
:stop_kit
set "TK_BIN=%KIT%\bin\"
set "TK_GATE=%KIT%\tools\share.py"
set "TK_START=%KIT%\Open Tinfoil Kit for Windows.bat"
powershell -NoProfile -Command "$k = [StringComparison]::OrdinalIgnoreCase; $p = @(Get-Process | Where-Object { $_.Path -and $_.Path.StartsWith($env:TK_BIN, $k) }) + @(Get-CimInstance Win32_Process | Where-Object { $c = $_.CommandLine; $c -and (($_.Name -like 'python*' -and $c.IndexOf($env:TK_GATE, $k) -ge 0) -or ($_.Name -eq 'cmd.exe' -and $c.IndexOf($env:TK_START, $k) -ge 0)) } | ForEach-Object { Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue }); if ($p.Count) { 'The kit is running. Stopping it, so its files can be updated...'; $p | Stop-Process -Force; Start-Sleep 2 }" <nul 2>nul
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

:ask_no
set "A="
set /p "A=%~1 [y/N] "
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
