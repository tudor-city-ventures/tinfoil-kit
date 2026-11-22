@echo off
rem Double-click me (Windows) to set up Tinfoil Kit, and again whenever you want the newest models, books and maps.
rem The first time, it asks where you live and whether the kit goes on an external drive or on this PC, says how
rem much fits there, and copies it there. Then it's kit update, sync and test, as SETUP.command does on a Mac or
rem Linux: first a small kit to try (kit starter), then the rest when SETUP runs again.
rem The answers can come with it instead, the same ones SETUP.command takes, so one command sets the kit up: an AI
rem helping someone asks them the questions, then gives them that command. It asks only what these leave out:
rem   --region PLACE      where you live: a US state, a country or a part of one, as kit region takes it
rem   --wikipedia CODES   Wikipedia's languages, like de or de,en
rem   --this-computer     the kit goes on this PC, in your user folder
rem   --drive PATH        the kit goes on the drive at PATH (like E:), in a TinfoilKit folder at its top
rem   --essentials        just the essentials (the first time, right after the kit to try)
rem   --all               all of it, even when that leaves less free space than SETUP likes (the first time, right after the kit to try)
rem   --no-ai             no AI models
rem   --models IDS        just these AI models (kit pick)
rem   --skip IDS          leave these out: AI models, books, maps, extras (kit pick)
rem   --add IDS           add these, like the books that are off unless asked for (kit pick)
rem   --share             share the kit on the home network, behind an access code, whenever it's open
rem   --home-server       share it, and start it whenever you sign in: for a PC that stays on
rem   --yes               ask nothing: what isn't given keeps its default, and SETUP stops and says why instead of asking
rem The kit's tools run on Python. SETUP gets python.org's own build from nuget.org (about 15 MB, once), checks it
rem against the checksum below, and keeps it in %LOCALAPPDATA%\TinfoilKit, outside the kit folder, so the kit can
rem move. UNINSTALL-Windows.bat removes it. KIT_PYTHON_URL: get the same file from there instead (tests).
rem cmd reads this file a line at a time while it runs, and kit update can replace it, so each line that hands
rem over to a new copy of SETUP also ends this one.
setlocal EnableExtensions EnableDelayedExpansion
set "ME=%~f0"
call :options %*
if "!OPTS!"=="help" exit /b 0
if "!OPTS!"=="bad" exit /b 2
rem With --yes it ends with exit, as a double-click does. Typed in a cmd window, not a cmd /c that PowerShell or a
rem script starts, that would close the window, so there it runs in a cmd of its own, from a copy of these two
rem lines in TEMP: cmd would read the rest of this file after it, and moving the kit deletes the download it's in.
if not defined KIT_YES goto begin
set "CMDLN=!CMDCMDLINE!"
if /i not "!CMDLN:/c =!"=="!CMDLN!" goto begin
> "%TEMP%\TinfoilKit-SETUP.cmd" (
  echo @cmd /d /c call %%*
  echo @exit /b %%errorlevel%%
) || goto begin
"%TEMP%\TinfoilKit-SETUP.cmd" "%ME%" %*
:begin
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
  if not defined UPDATE (
    set "KIT_STEPS=2"
    call :goes_on && set "KIT_STEPS=3"
  )
  call :where_kit
  call :step "the kit is !WHERE!, in !KIT!"
  if defined KIT_PLACE call :stays
) else (
  set "KIT_STEPS=3"
  call :goes_on && set "KIT_STEPS=4"
  call :pick_region first
  call :place
)
goto checks

rem The first run's copy of this script chose this place and copied the kit here.
:placed
if not "%~2"=="" call :remove_download "%~2"
if defined KIT_ESSENTIALS call :kit essentials !KIT_ESSENTIALS! >nul
:checks
call :writable || call :finish 1
echo(
set "UPDATE_ARGS="
if defined KIT_YES set "UPDATE_ARGS=--yes"
"%PY%" "%KIT%\tools\kit.py" --root "%KIT%" update !UPDATE_ARGS! & if errorlevel 3 call "%KIT%\SETUP-Windows.bat" --updated & exit

:download
call :python || call :finish 1
rem The answers that came with SETUP, after kit update so that new items can be left out too. The first run said
rem them before moving the kit, and says them again quietly in case a kit was already where it landed.
if defined KIT_GIVEN (
  call :given_region >nul 2>&1
  call :given_parts >nul 2>&1
) else (
  call :given_region || call :finish 1
  call :given_parts || call :finish 1
)
rem After kit update, so a kit from before this question gets it
if not defined KIT_REGION_ASKED call :pick_region
set "ONLY=all"
findstr /r /c:"\"essentials_only\": *true" kit.json >nul 2>&1 && set "ONLY=essentials"
rem The first time, SETUP gets the try-it kit (kit starter): a few GB, checked, then the kit opens to be tried. The
rem rest comes when SETUP runs again (that's saying it's ready), or right after the try-it kit with --all,
rem --essentials or --home-server. After that, SETUP updates what's there. TRY: the first run, or one on a try-it
rem kit. REST: with TRY, the rest comes in this run. LATER: the rest, on a run after the try-it kit's: it asks what
rem goes in.
set "TRY=" & set "REST=" & set "LATER="
if not defined UPDATE set "TRY=1"
findstr /r /c:"\"starter_only\": *true" kit.json >nul 2>&1 && set "TRY=1"
if defined UPDATE set "REST=1"
call :goes_on && set "REST=1"
if defined TRY if defined UPDATE set "LATER=1"
rem An update can bring models too big for this computer
if not defined KIT_FIT_ASKED if not defined LATER call :fit_ai
if not defined UPDATE (
  call :kit starter on >nul
  if "!KIT_HOW_MUCH!"=="all" set "ONLY=all"
  if "!KIT_HOW_MUCH!"=="essentials" set "ONLY=essentials"
)
if defined UPDATE if not defined TRY call :how_much_now
if not defined TRY goto update_all
if defined UPDATE goto the_rest

"%PY%" "%KIT%\tools\kit.py" --root "%KIT%" estimate > "%OUT%" 2>nul
set "SMALL=0"
for /f "usebackq delims=" %%g in ("%OUT%") do set "SMALL=%%g"
call :gb SMALL
call :step "a small kit to try first (about !SMALL_GB!). Here's what it gets:"
call :kit plan || call :finish 1
set "TAKES=It takes minutes on a fast connection."
if defined REST set "TAKES=The kit to try takes minutes on a fast connection, the rest hours."
call :before_download "!TAKES!" || call :finish 0
call :get
if not "!TESTED!/!RC!"=="0/0" goto results
if not defined REST goto try_it
echo(
echo The try-it kit works: from now on, if the internet goes down, the kit is ready.

rem The rest, now that the try-it kit works. The first time, what goes in was settled before the kit moved.
:the_rest
call :step "the rest of the kit"
if not defined LATER goto rest_plan
set "PICK_ASK=--ask"
call :chosen && set "PICK_ASK="
if defined KIT_YES set "PICK_ASK="
call :kit pick !PICK_ASK! || call :finish 1
call :fit_ai
call :space "!KIT!"
call :where_kit
set "AT=this PC"
if not "!WHERE!"=="on this PC" set "AT=!WHERE:~13!"
call :how_much "!AT!" "Not now" && goto rest_plan
echo(
echo The try-it kit keeps working. Run SETUP again when you're ready for the rest.
call :finish 1
:rest_plan
call :kit starter off >nul
set "ESSENTIALS=off"
if "!ONLY!"=="essentials" set "ESSENTIALS=on"
call :kit essentials !ESSENTIALS! >nul
echo(
echo Here's what it gets:
call :kit plan || (call :kit starter on >nul & call :finish 1)
if defined LATER call :before_download "The kit keeps working while it downloads." || (call :kit starter on >nul & call :finish 0)
call :get
goto results

:update_all
call :step "download. Here's what will change:"
call :kit plan || call :finish 1
call :before_download "Big downloads take hours." || call :finish 0
call :get

:results
if "%TESTED%"=="0" if "%RC%"=="0" goto all_set
if "%TESTED%"=="0" (
  echo(
  echo Everything in the kit works, but some downloads didn't finish:
  call :problems
  echo(
  if defined KIT_SHARE if not defined KIT_HOME_SERVER call :share_home
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
if defined KIT_SHARE call :share_home
rem (nobody may be there to use it)
if defined KIT_YES call :finish 0
call :ask "Open the kit now?" && (del "%OUT%" 2>nul & call "%KIT%\Open Tinfoil Kit for Windows.bat" & exit 0)
call :finish 0

rem The try-it kit works: how big the rest is, how long it takes at the speed just measured, and how to get it. Then
rem the kit opens, to be tried.
:try_it
call :where_kit
echo(
echo The try-it kit works. It's !WHERE!, in !KIT!
echo Turn off Wi-Fi and try it: ask the AI something, look something up, find your street on the map.
set "REMAIN=0" & set "TOOK="
"%PY%" "%KIT%\tools\kit.py" --root "%KIT%" estimate --rest > "%OUT%" 2>nul
for /f "usebackq tokens=1,2 delims=	" %%a in ("%OUT%") do (set "REMAIN=%%a" & set "TOOK=%%b")
call :gb REMAIN
set "SAY=The rest of the kit"
if "!ONLY!"=="essentials" set "SAY=The rest of the essentials"
set "SAY=!SAY! is about !REMAIN_GB! more"
if defined TOOK set "SAY=!SAY!: !TOOK!"
echo(
echo !SAY!. You can use the kit while it downloads.
set "THEN=it asks what you want in the kit, then gets that"
call :chosen && set "THEN=it gets it"
if defined KIT_YES (
  echo When you're ready for it: "!KIT!\SETUP-Windows.bat" --yes
) else (
  echo When you're ready, double-click SETUP-Windows.bat again: !THEN!.
)
if defined KIT_SHARE call :share_home
if not defined KIT_YES goto try_it_ask
rem (in a window of its own, so a command an AI runs doesn't wait for it)
start "Tinfoil Kit" "%KIT%\Open Tinfoil Kit for Windows.bat"
call :finish 0
:try_it_ask
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

rem --share: phones and laptops on the home network can use the kit, with its access code, whenever it's open.
:share_home
echo(
echo Sharing: phones and laptops on your home network can use the kit whenever it's open, with its access code.
call :kit share on >nul
echo(
call :kit share
goto :eof

rem Before a download: whose files they are, and how to keep it going. Its argument says how long it takes. Returns 1
rem if the person would rather not start.
:before_download
set "TAKES=%~1"
echo(
echo Each item comes from its publisher under its own license, listed in THIRD-PARTY.md. Downloading means you accept them.
echo !TAKES! Keep this PC plugged in with the lid open: it won't go to sleep while this runs.
echo You can stop any time (press Ctrl+C, or close this window) and double-click SETUP later to carry on.
call :ask "Start downloading?" || exit /b 1
call :stop_kit
exit /b 0

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

rem An update: --essentials or --all switches how much of the kit it gets, and a kit with just the essentials is
rem offered the rest once it fits.
:how_much_now
if "!KIT_HOW_MUCH!/!ONLY!"=="essentials/all" (
  call :kit essentials on
  set "ONLY=essentials"
)
if "!KIT_HOW_MUCH!/!ONLY!"=="all/essentials" (
  call :kit essentials off
  set "ONLY=all"
)
if defined KIT_HOW_MUCH goto :eof
if not "!ONLY!"=="essentials" goto :eof
call :space "!KIT!"
if not "!FULL!"=="fits" goto :eof
echo(
echo This kit has just the essentials, and now there's room for the rest (about !NEED_GB! more).
if defined KIT_YES (
  echo SETUP-Windows.bat --all gets it.
  goto :eof
)
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
if "%~1"=="first" call :step "where do you live?"
rem (it came with SETUP)
if defined KIT_REGION goto region_given
if defined KIT_YES (
  if defined KIT_WIKIPEDIA goto region_given
  if "%~1"=="first" call :kit region
  goto :eof
)
if not "%~1"=="first" goto region_now
echo The maps show your area in street detail, with directions and address search, and Wikipedia comes in your language.
<nul set /p "=Right now: "
call :kit region
echo(
set "Q=Type your US state or your country (like Texas, Ontario or Germany), or press Enter to keep that: "
goto region_ask
:region_given
call :given_region || call :finish 1
goto :eof
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
set "WIKI=!KIT_WIKIPEDIA!"
if defined WIKI goto region_set
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
call :given_region || (set "KIT_REGION=" & set "KIT_WIKIPEDIA=")
goto :eof

rem The answers that came with SETUP's options (or the first run's, for a kit that was already where it put this
rem one): where you live, in KIT_REGION and KIT_WIKIPEDIA, and what goes in the kit. Saying them again changes nothing.
:given_region
set "REGION_ARGS="
if defined KIT_REGION set "REGION_ARGS="!KIT_REGION!""
if defined KIT_WIKIPEDIA set "REGION_ARGS=!REGION_ARGS! --wikipedia "!KIT_WIKIPEDIA!""
if not defined REGION_ARGS exit /b 0
call :kit region !REGION_ARGS!
exit /b !errorlevel!

rem (say: and say so first)
:given_parts
set "PICKS="
if defined KIT_NO_AI set "PICKS=--no-ai"
if defined KIT_MODELS set "PICKS=!PICKS! --models "!KIT_MODELS!""
if defined KIT_SKIP set "PICKS=!PICKS! --skip "!KIT_SKIP!""
if defined KIT_ADD set "PICKS=!PICKS! --add "!KIT_ADD!""
if not defined PICKS exit /b 0
if "%~1"=="say" echo What goes in it:
call :kit pick !PICKS!
exit /b !errorlevel!

rem Whether someone has said what goes in the kit, now or before (kit pick sets "picked").
:chosen
if defined KIT_NO_AI exit /b 0
if defined KIT_MODELS exit /b 0
if defined KIT_SKIP exit /b 0
if defined KIT_ADD exit /b 0
findstr /r /c:"\"picked\": *true" kit.json >nul 2>&1 && exit /b 0
exit /b 1

rem Whether the first run goes on to the rest of the kit right after the kit to try, instead of stopping there.
:goes_on
if "!KIT_HOW_MUCH!"=="all" exit /b 0
if "!KIT_HOW_MUCH!"=="essentials" exit /b 0
if defined KIT_HOME_SERVER exit /b 0
exit /b 1

rem Which AI model this computer runs, and whether to get the ones too big for it (on an update, also the ones
rem skipped before on a computer with less memory). Models chosen with --models or --no-ai stay as chosen.
:fit_ai
set "KIT_FIT_ASKED=1"
set "FIT=--ask"
rem (what --ask does when nobody answers)
if defined KIT_YES set "FIT=--restore --skip"
if defined KIT_MODELS set "FIT="
if defined KIT_NO_AI set "FIT="
call :kit fit !FIT!
goto :eof

rem The lines kit region wrote, numbered, as "  1  NAME (GROUP)" with this label's argument after GROUP. Python
rem prints them, since cmd would garble letters with accents.
:list
"%PY%" -c "import sys; [print('  {}  {} ({}{})'.format(i, *l.rstrip('\r\n').split('\t')[1:3], sys.argv[2])) for i, l in enumerate(open(sys.argv[1], encoding='utf-8'), 1)]" "%OUT%" "%~1"
goto :eof

rem ---------------------------------------------------------------------------- first run: where the kit goes

:place
call :step "where should the kit go?"
call :given_parts say || call :finish 1
call :fit_ai
set "KIT_GIVEN=1"
if defined KIT_PLACE goto place_options
if not defined KIT_YES goto place_ask
:place_options
call :place_given && goto :eof
if defined KIT_YES (
  echo Run the command again once that's sorted. Without --yes, SETUP asks instead.
  call :finish 1
)
:place_ask
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

rem Where --this-computer or --drive puts the kit (with --yes and neither, this PC), in DEST, and the folder it goes
rem in, in VOL: --drive E: or E:\ is E:\TinfoilKit, and a PATH that ends in TinfoilKit is the kit's folder itself.
:given_dest
set "DEST=%USERPROFILE%\%NAME%"
set "VOL=%USERPROFILE%"
if not "!KIT_PLACE!"=="drive" goto :eof
set "VOL=!KIT_DRIVE:/=\!"
if "!VOL:~-1!"=="\" set "VOL=!VOL:~0,-1!"
if "!VOL:~1!"=="" set "VOL=!VOL!:"
set "DEST=!VOL!\%NAME%"
if /i "!VOL:~-11!"=="\%NAME%" (set "DEST=!VOL!" & set "VOL=!VOL:~0,-11!")
goto :eof

rem Putting the kit where the options say. Returns 1, having said why, if it can't go there.
:place_given
call :given_dest
set "LABEL=this PC"
if not "!KIT_PLACE!"=="drive" goto place_given_room
set "LABEL=!VOL!"
if not exist "!VOL!\" (
  echo(
  echo There's no drive at !KIT_DRIVE!. Is it plugged in? Give it a few seconds after plugging it in.
  exit /b 1
)
set "WHY=-" & set "FMT="
"%PY%" "%KIT%\tools\kit.py" --root "%KIT%" drives > "%OUT%" 2>nul
for /f "usebackq tokens=1-5 delims=	" %%a in ("%OUT%") do (
  set "P=%%a"
  if "!P:~-1!"=="\" set "P=!P:~0,-1!"
  if /i "!P!"=="!VOL!" set "FMT=%%b" & set "WHY=%%d" & set "LABEL=%%e"
)
if not "!WHY!"=="-" (
  echo(
  echo !LABEL! won't work: !WHY!.
  echo To use it, erase it as exFAT. Erasing deletes everything on it, so copy off anything you want to keep first.
  echo In File Explorer: right-click the drive under This PC, choose Format, pick exFAT as the file system, and click Start.
  exit /b 1
)
if /i "!FMT!"=="NTFS" (
  echo(
  echo !LABEL! is formatted as NTFS. The kit works on it on Windows and Linux, but a Mac can't save to it.
)
:place_given_room
call :space "!DEST!"
call :how_much "!LABEL!" || exit /b 1
call :put_kit
exit /b 0

rem A kit that's set up stays where it is: --this-computer and --drive are for a new one.
:stays
call :given_dest
if /i not "!DEST!"=="!KIT!" echo It stays there: --this-computer and --drive choose where a new kit goes.
goto :eof

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

rem After :space, how much of the kit goes to the place it looked at (its first argument names it). Sets ONLY to all
rem or essentials, or returns 1 for the way out: choosing somewhere else, or the second argument if there is one
rem ("Not now", once the kit is in place).
:how_much
set "AT=%~1"
set "OTHER=%~2"
if not defined OTHER set "OTHER=Somewhere else"
set "KEEPS="
if "!AT!"=="this PC" set "KEEPS=, so this PC keeps running well"
set "TIGHT=All of it fits on !AT!, but leaves only !LEFT_GB! free. Better to leave at least !LEAVE_GB!!KEEPS!."
set "TIGHT_ESS=Only the essentials fit on !AT!, and they leave only !LEFT_ESS_GB! free. Better to leave at least !LEAVE_GB!!KEEPS!."
set "NOT_ALL=All of it won't fit on !AT!: it needs about !NEED_GB! plus some to spare, and !FREE_GB! is free."
set "NO_ROOM=There isn't room on !AT!, even for the essentials: they need about !NEED_ESS_GB! plus some to spare, and !FREE_GB! is free."
rem --essentials or --all, and what fits
set "PREF=!KIT_HOW_MUCH!"
if "!PREF!/!FULL!"=="/fits" set "ONLY=all" & exit /b 0
if "!PREF!/!FULL!"=="all/fits" set "ONLY=all" & exit /b 0
if "!PREF!/!ESS!"=="essentials/fits" set "ONLY=essentials" & exit /b 0
echo(
if "!PREF!/!FULL!"=="all/tight" (echo !TIGHT!) & set "ONLY=all" & exit /b 0
if "!PREF!/!ESS!"=="essentials/tight" (echo !TIGHT_ESS!) & set "ONLY=essentials" & exit /b 0
if defined KIT_YES goto how_much_given
if "!FULL!"=="tight" goto how_much_tight
if "!ESS!"=="fits" goto how_much_essentials
if "!ESS!"=="tight" goto how_much_essentials_tight
echo !NO_ROOM!
if "%~2"=="" echo Make room there, or choose somewhere else.
exit /b 1
:how_much_tight
echo !TIGHT!
echo   1  Just the essentials (about !NEED_ESS_GB!)
echo   2  All of it anyway (about !NEED_GB!)
echo   3  !OTHER!
call :choose "Type 1, 2 or 3, then press Enter:" 3
if "!PICK!"=="1" set "ONLY=essentials" & exit /b 0
if "!PICK!"=="2" set "ONLY=all" & exit /b 0
exit /b 1
:how_much_essentials
echo !NOT_ALL!
echo   1  Just the essentials (about !NEED_ESS_GB!). SETUP offers the rest later, once it fits.
echo   2  !OTHER!
call :choose "Type 1 or 2, then press Enter:" 2
if "!PICK!"=="1" set "ONLY=essentials" & exit /b 0
exit /b 1
:how_much_essentials_tight
echo !TIGHT_ESS!
echo   1  Just the essentials anyway (about !NEED_ESS_GB!)
echo   2  !OTHER!
call :choose "Type 1 or 2, then press Enter:" 2
if "!PICK!"=="1" set "ONLY=essentials" & exit /b 0
exit /b 1
rem Nobody to ask: just the essentials where all of it doesn't fit with room to spare, unless --all said otherwise
:how_much_given
if "!ESS!"=="no" (echo !NO_ROOM!) & exit /b 1
set "SAID=!NOT_ALL!"
if "!ESS!"=="tight" set "SAID=!TIGHT_ESS!"
if "!FULL!"=="tight" set "SAID=!TIGHT!"
echo !SAID!
if "!PREF!"=="all" exit /b 1
echo So it gets just the essentials (about !NEED_ESS_GB!). SETUP offers the rest later, once it fits.
set "ONLY=essentials"
exit /b 0

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

rem With --yes the questions take their defaults, and one that has none stops SETUP rather than wait for an answer.
:ask
if defined KIT_YES exit /b 0
set "A="
set /p "A=%~1 [Y/n] "
if not defined A exit /b 0
if /i "!A!"=="y" exit /b 0
if /i "!A!"=="yes" exit /b 0
exit /b 1

:ask_no
if defined KIT_YES exit /b 1
set "A="
set /p "A=%~1 [y/N] "
if /i "!A!"=="y" exit /b 0
if /i "!A!"=="yes" exit /b 0
exit /b 1

rem A number from 1 to %2, in PICK. Stops if the window has nothing more to read, rather than asking forever.
:choose
if defined KIT_YES (
  echo(
  echo SETUP needs an answer here, so it stopped. Run it without --yes to be asked.
  call :finish 1
)
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
if defined KIT_YES exit %~1
echo(
set /p "_=Press Enter to close this window. "
exit %~1

rem The options, into the environment, since this script starts itself again after moving or updating the kit.
rem cmd splits words at commas and spaces, so a value is every word up to the next option: --skip a,b and --region
rem New York both work. OPTS is help once it has listed them, and bad when it can't take them (SETUP exits 2).
:options
set "OPTS="
:options_next
if "%~1"=="" exit /b 0
set "OPT=%~1"
shift
rem (this script starting itself again)
if "!OPT!"=="--placed" exit /b 0
if "!OPT!"=="--updated" exit /b 0
if /i "!OPT!"=="--yes" (set "KIT_YES=1" & goto options_next)
if /i "!OPT!"=="--this-computer" (set "KIT_PLACE=computer" & goto options_next)
if /i "!OPT!"=="--essentials" (set "KIT_HOW_MUCH=essentials" & goto options_next)
if /i "!OPT!"=="--all" (set "KIT_HOW_MUCH=all" & goto options_next)
if /i "!OPT!"=="--no-ai" (set "KIT_NO_AI=1" & goto options_next)
if /i "!OPT!"=="--share" (set "KIT_SHARE=1" & goto options_next)
if /i "!OPT!"=="--home-server" (set "KIT_HOME_SERVER=1" & goto options_next)
if /i "!OPT!"=="-h" goto options_help
if /i "!OPT!"=="--help" goto options_help
set "SEP=,"
if /i "!OPT!"=="--region" set "SEP= "
if /i "!OPT!"=="--drive" set "SEP= "
for %%o in (--region --wikipedia --drive --models --skip --add) do if /i "!OPT!"=="%%o" goto options_value
>&2 echo SETUP: there's no !OPT!. It takes:
call :options_list >&2
set "OPTS=bad"
exit /b 2
:options_value
set "VAL="
:options_word
set "W=%~1"
if not defined W goto options_valued
if "!W:~0,2!"=="--" goto options_valued
if defined VAL (set "VAL=!VAL!!SEP!!W!") else set "VAL=!W!"
shift
goto options_word
:options_valued
if not defined VAL (
  >&2 echo SETUP: !OPT! needs a value after it. SETUP-Windows.bat --help lists them all.
  set "OPTS=bad"
  exit /b 2
)
if /i "!OPT!"=="--region" set "KIT_REGION=!VAL!" & set "KIT_REGION_ASKED=1"
if /i "!OPT!"=="--wikipedia" set "KIT_WIKIPEDIA=!VAL!"
if /i "!OPT!"=="--drive" set "KIT_PLACE=drive" & set "KIT_DRIVE=!VAL!"
if /i "!OPT!"=="--models" set "KIT_MODELS=!VAL!"
if /i "!OPT!"=="--skip" set "KIT_SKIP=!VAL!"
if /i "!OPT!"=="--add" set "KIT_ADD=!VAL!"
goto options_next
:options_help
call :options_list
set "OPTS=help"
exit /b 0

rem The options listed at the top of this file
:options_list
for /f "delims=" %%l in ('findstr /b /c:"rem   -" "%ME%"') do (
  set "L=%%l"
  echo(!L:~6!
)
goto :eof
