@echo off
rem Double-click me (Windows) to start Tinfoil Kit: the library, the AI and the map, then the kit's page in a
rem browser. No internet needed. Close this window to stop everything. tools\launch.sh does the same on a Mac or Linux.
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
set "KIT=%CD%"
title Tinfoil Kit
if not exist "%KIT%\logs\" mkdir "%KIT%\logs"
if not exist "%KIT%\.kit\" mkdir "%KIT%\.kit"
call :setting LIB_PORT library_port 8888
call :setting AI_PORT ai_port 8080
call :setting CTX context_size 16384
call :setting MODEL default_model
call :setting TILES_PORT tiles_port 8090
call :setting GEO_PORT geocoder_port 2322
call :setting ROUTE_PORT routing_port 8989
call :setting GEO_HEAP geocoder_heap 3g
call :setting ROUTE_HEAP routing_heap 2g
call :find KIWIX kiwix-tools kiwix-serve.exe
call :find LLAMA llama.cpp llama-server.exe
call :find PMTILES pmtiles pmtiles.exe
call :find JAVA java java.exe
set "CURL=%SystemRoot%\System32\curl.exe"
if not exist "%CURL%" set "CURL="

rem A Mac leaves "._name" files beside books and models on exFAT drives. The servers could take them for books or models.
del /q /a "%KIT%\library\._*" 2>nul
for /d %%d in ("%KIT%\models\*") do del /q /a "%%d\._*" 2>nul
set "ZIMS=" & set "BOOKS=0"
for %%f in ("%KIT%\library\*.zim") do (
  set "ZIMS=!ZIMS! "%%~ff""
  set /a "BOOKS+=1"
)
call :pick_model
if defined MODEL if not exist "%KIT%\models\%MODEL%\*.gguf" set "MODEL="
if not defined MODEL for /d %%d in ("%KIT%\models\*") do if not defined MODEL if exist "%%d\*.gguf" set "MODEL=%%~nxd"

echo(
echo   TINFOIL KIT
echo   ===========
if not defined KIWIX echo   - Library server not found ^(bin\kiwix-tools-windows-x64^). Run SETUP-Windows.bat while online.
if not defined LLAMA echo   - AI server not found ^(bin\llama.cpp-windows-x64^). Run SETUP-Windows.bat while online.
if !BOOKS!==0 echo   - No library files in library. Run SETUP-Windows.bat while online.
if not defined MODEL echo   No AI models in models, so the AI stays off. If kit.json lists some, run SETUP-Windows.bat while online.
if defined TOO_BIG echo   This computer has !GB! GB of memory, too little for !TOO_BIG!. Starting with !MODEL!.

rem --- library
call :ours "http://127.0.0.1:%LIB_PORT%/" "Tinfoil Kit" && (
  echo   Library already running on port %LIB_PORT%.
) || if defined KIWIX if !BOOKS! gtr 0 call :start_library
rem --- AI
call :ours "http://127.0.0.1:%AI_PORT%/v1/models" "\"data\"" && (
  echo   AI already running on port %AI_PORT%.
) || if defined LLAMA if defined MODEL call :start_ai
rem --- maps: tiles, address search, directions
set "MAPS="
if exist "%KIT%\maps\" call :start_maps

rem Wait for the library and the AI to answer.
set "LIB_OK=0" & set "AI_OK=0" & set "AI_ON="
if defined LLAMA if defined MODEL set "AI_ON=1"
if not defined CURL (
  ping -n 11 127.0.0.1 >nul
  set "LIB_OK=1"
  if defined AI_ON set "AI_OK=1"
)
if defined CURL for /l %%i in (1,1,60) do if !LIB_OK!==0 call :ours "http://127.0.0.1:%LIB_PORT%/" "Tinfoil Kit" && (set "LIB_OK=1") || ping -n 2 127.0.0.1 >nul
if defined CURL if defined AI_ON for /l %%i in (1,1,30) do if !AI_OK!==0 call :ours "http://127.0.0.1:%AI_PORT%/v1/models" "\"data\"" && (set "AI_OK=1") || ping -n 2 127.0.0.1 >nul

set "URL=http://127.0.0.1:%LIB_PORT%/?model=%MODEL%&ai=%AI_PORT%"
echo(
if !LIB_OK!==1 (echo   Library:  ready) else (echo   Library:  NOT running ^(see logs\kiwix-serve.log^))
if !AI_OK!==1 (
  echo   AI:       ready ^(the first answer takes longer while the model loads^)
) else if not defined MODEL (
  echo   AI:       off ^(no models^). The library still works.
) else (
  echo   AI:       NOT running ^(see logs\llama-server.log^). The library still works.
)
echo(
echo   Open:     !URL!
echo   AI chat:  http://127.0.0.1:!AI_PORT!/
if defined MAPS echo   Maps:     on the Map tab of the page above
echo(
echo   Keep this window open. Close it to stop everything.
if !LIB_OK!==1 start "" "!URL!"
rem Out of the kit folder, so nothing here holds it open (UNINSTALL-Windows.bat can delete it).
cd /d "%TEMP%"
:wait
pause >nul
ping -n 2 127.0.0.1 >nul
goto wait

rem ---------------------------------------------------------------------------- servers
rem start /b: the servers share this window, so closing it stops them all.

:start_library
call :free_port LIB_PORT library
set "PORTAL=%KIT%\.kit\portal.html"
rem The page ./kit sync builds has the map inside; the bare template has none.
if not exist "%PORTAL%" set "PORTAL=%KIT%\tools\portal.html"
set "SKIP="
"%KIWIX%" --help 2>&1 | findstr /c:"skipInvalid" >nul && set "SKIP=--skipInvalid"
start "" /b "%KIWIX%" --port %LIB_PORT% --address 127.0.0.1 --customIndex "%PORTAL%" --threads 4 %SKIP% %ZIMS% > "%KIT%\logs\kiwix-serve.log" 2>&1
echo   Starting library (%BOOKS% books)...
goto :eof

:start_ai
call :free_port AI_PORT AI
(
  echo version = 1
  echo(
  echo [!MODEL!]
  echo load-on-startup = true
) > "%KIT%\.kit\presets.ini"
rem AI chat is llama-server's own page, so it gets the Ask tab's safety rules as its default system message.
rem An environment variable, not a flag: a llama-server too old to know it ignores it instead of refusing to start.
if exist "%KIT%\tools\ai-chat.json" set "LLAMA_ARG_UI_CONFIG_FILE=%KIT%\tools\ai-chat.json"
rem Browsers accept exactly one allowed origin: the kit's page.
start "" /b "%LLAMA%" --models-dir "%KIT%\models" --models-preset "%KIT%\.kit\presets.ini" --models-max 1 -c %CTX% --host 127.0.0.1 --port %AI_PORT% --cors-origins http://127.0.0.1:%LIB_PORT% > "%KIT%\logs\llama-server.log" 2>&1
echo   Starting AI (loading !MODEL!)...
goto :eof

:start_maps
set "CORS=http://127.0.0.1:%LIB_PORT%"
set "PHOTON_JAR=" & set "GH_JAR="
for %%f in ("%KIT%\bin\photon\photon-*.jar") do set "PHOTON_JAR=%%~ff"
for %%f in ("%KIT%\bin\graphhopper\graphhopper-web-*.jar") do set "GH_JAR=%%~ff"
if defined PMTILES if exist "%KIT%\maps\tiles\basemap.pmtiles" call :up "http://127.0.0.1:%TILES_PORT%/basemap.json" || (
  start "" /b "%PMTILES%" serve "%KIT%\maps\tiles" --port %TILES_PORT% --interface 127.0.0.1 --cors "%CORS%" --public-url "http://127.0.0.1:%TILES_PORT%" > "%KIT%\logs\tiles.log" 2>&1
  set "MAPS=!MAPS! map"
)
if defined JAVA if defined PHOTON_JAR if exist "%KIT%\maps\geocoder\photon_data\" call :up "http://127.0.0.1:%GEO_PORT%/status" || (
  start "" /b "%JAVA%" -Xmx%GEO_HEAP% -jar "%PHOTON_JAR%" serve -data-dir "%KIT%\maps\geocoder" -listen-ip 127.0.0.1 -listen-port %GEO_PORT% -cors-origin "%CORS%" > "%KIT%\logs\geocoder.log" 2>&1
  set "MAPS=!MAPS! address-search"
)
if defined JAVA if defined GH_JAR if exist "%KIT%\maps\routing\graph-cache\properties" call :up "http://127.0.0.1:%ROUTE_PORT%/health" || (
  start "" /b /d "%KIT%\maps\routing" "%JAVA%" -Xmx%ROUTE_HEAP% "-Ddw.server.application_connectors[0].bind_host=127.0.0.1" "-Ddw.server.application_connectors[0].port=%ROUTE_PORT%" -jar "%GH_JAR%" server gh-serve.yml > "%KIT%\logs\routing.log" 2>&1
  set "MAPS=!MAPS! directions"
)
if defined MAPS echo   Starting maps:!MAPS! (address search and directions take up to a minute)...
goto :eof

rem ---------------------------------------------------------------------------- helpers

rem A simple "key": value from kit.json, without needing Python.
:setting
set "%~1=%~3"
for /f "usebackq tokens=1,* delims=:" %%a in (`findstr /c:"\"%~2\"" "%KIT%\kit.json" 2^>nul`) do (
  set "V=%%b"
  set "V=!V:"=!"
  set "V=!V:,=!"
  set "V=!V: =!"
  if defined V set "%~1=!V!"
)
goto :eof

rem A program's .exe for Windows: the current version first, then any older one kept as a fallback.
:find
set "%~1="
set "B=%KIT%\bin\%~2-windows-x64"
if not exist "%B%\" goto :eof
set "CUR="
if exist "%B%\CURRENT" for /f "usebackq delims=" %%v in ("%B%\CURRENT") do set "CUR=%%v"
if defined CUR if exist "%B%\!CUR!\" for /f "delims=" %%f in ('dir /s /b "%B%\!CUR!\%~3" 2^>nul') do if not defined %~1 set "%~1=%%f"
if not defined %~1 for /f "delims=" %%f in ('dir /s /b "%B%\%~3" 2^>nul') do if not defined %~1 set "%~1=%%f"
goto :eof

rem A model has to fit in memory with room for everything else. On a PC with less memory than the first model
rem needs, or without that model, start with the biggest one that fits (./kit fit picks the same way); the Ask page
rem still lists them all.
:pick_model
set "TOO_BIG=" & set "GB=0"
set "MEM_MB=%KIT_MEMORY_MB%"
if not defined MEM_MB for /f %%m in ('powershell -NoProfile -Command "[int64]((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1MB)" ^<nul 2^>nul') do set "MEM_MB=%%m"
if not defined MEM_MB set "MEM_MB=0"
set /a "ROOM=MEM_MB*6/10, GB=MEM_MB/1024"
set "HAVE="
if defined MODEL if exist "%KIT%\models\%MODEL%\*.gguf" set "HAVE=1"
if defined HAVE (
  if !ROOM!==0 goto :eof
  call :model_mb "%KIT%\models\%MODEL%" WANT
  if !WANT! leq !ROOM! goto :eof
)
set "FIT=" & set "FIT_MB=0" & set "SMALL=" & set "SMALL_MB=0"
for /d %%d in ("%KIT%\models\*") do (
  call :model_mb "%%~fd" MB
  if !MB! gtr 0 (
    set "OK="
    if !ROOM!==0 (set "OK=1") else if !MB! leq !ROOM! set "OK=1"
    if defined OK if !MB! gtr !FIT_MB! (set "FIT=%%~nxd" & set "FIT_MB=!MB!")
    if !SMALL_MB!==0 (set "SMALL=%%~nxd" & set "SMALL_MB=!MB!") else if !MB! lss !SMALL_MB! (set "SMALL=%%~nxd" & set "SMALL_MB=!MB!")
  )
)
if not defined FIT set "FIT=!SMALL!"
if not defined FIT goto :eof
if "!FIT!"=="!MODEL!" goto :eof
if defined HAVE set "TOO_BIG=!MODEL!"
set "MODEL=!FIT!"
goto :eof

rem The size of a model's files in MB (1,048,576 bytes, as memory is counted), in %2. cmd counts only to about
rem 2 billion, so each file's size drops its last 6 digits first.
:model_mb
set "%~2=0"
for %%f in ("%~1\*.gguf") do (
  set "S=%%~zf"
  set "S=!S:~0,-6!"
  if not defined S set "S=0"
  set /a "%~2+=S*15625/16384"
)
goto :eof

rem Does this address answer with this text? (is the kit's own server already running there?)
:ours
if not defined CURL exit /b 1
"%CURL%" -s --max-time 2 "%~1" 2>nul | findstr /c:"%~2" >nul
goto :eof

:up
if not defined CURL exit /b 1
"%CURL%" -s -f -o nul --max-time 2 "%~1" 2>nul
goto :eof

rem Another program can hold a port (many developer tools take 8080): use the next free one. netstat says what's
rem listening at once, where connecting to a free port takes Windows about 2 seconds to give up.
:free_port
set /a "P=!%~1!, LAST=!%~1!+9"
:free_port_next
rem A listening port's line has no remote address: 0.0.0.0:0 or [::]:0 (the state's name depends on the language).
netstat -an | findstr /r /c:"TCP  *[^ ]*:%P%  *0\.0\.0\.0:0 " /c:"TCP  *[^ ]*:%P%  *\[::\]:0 " >nul || goto free_port_done
if !P! geq !LAST! goto free_port_done
set /a "P+=1"
goto free_port_next
:free_port_done
if !P!==!%~1! goto :eof
echo   Another program is using port !%~1!, so the %~2 uses !P!.
set "%~1=!P!"
goto :eof
