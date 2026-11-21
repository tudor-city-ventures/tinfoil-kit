@echo off
rem Tinfoil Kit for a Windows PC: the fallback if the Mac is gone. Double-click to start.
rem Needs the drive formatted exFAT (so Windows can read it). Best effort: the Mac launcher is the tested one.
setlocal EnableDelayedExpansion
cd /d "%~dp0"
set LIB_PORT=8888
set AI_PORT=8080
set CTX=8192
set KIWIX=
set LLAMA=
set KCUR=
set LCUR=
if exist "bin\kiwix-tools-windows-x64\CURRENT" for /f "usebackq delims=" %%v in ("bin\kiwix-tools-windows-x64\CURRENT") do set KCUR=%%v
if exist "bin\llama.cpp-windows-x64\CURRENT" for /f "usebackq delims=" %%v in ("bin\llama.cpp-windows-x64\CURRENT") do set LCUR=%%v
for /f "delims=" %%f in ('dir /s /b "bin\kiwix-tools-windows-x64\!KCUR!\kiwix-serve.exe" 2^>nul') do set KIWIX=%%f
for /f "delims=" %%f in ('dir /s /b "bin\llama.cpp-windows-x64\!LCUR!\llama-server.exe" 2^>nul') do set LLAMA=%%f
set ZIMS=
for %%f in (library\*.zim) do set ZIMS=!ZIMS! "%%~ff"

echo.
echo   TINFOIL KIT (Windows)
echo   =====================
if not defined KIWIX echo   ! Library server missing: bin\kiwix-tools-windows-x64
if not defined LLAMA echo   ! AI server missing: bin\llama.cpp-windows-x64
if defined KIWIX start "Tinfoil Kit - Library (close to stop)" /min "!KIWIX!" --port %LIB_PORT% --address 127.0.0.1 --customIndex "%~dp0tools\portal.html" !ZIMS!
if defined LLAMA start "Tinfoil Kit - AI (close to stop)" /min "!LLAMA!" --models-dir "%~dp0models" --models-max 1 -c %CTX% --host 127.0.0.1 --port %AI_PORT% --cors-origins http://127.0.0.1:%LIB_PORT%
echo   Starting... the browser opens in a few seconds.
timeout /t 10 /nobreak >nul
start "" "http://127.0.0.1:%LIB_PORT%/?ai=%AI_PORT%"
echo.
echo   Open http://127.0.0.1:%LIB_PORT%/ in a browser.
echo   To stop: close the two minimized "Tinfoil Kit" windows.
echo   On a PC without a good graphics card, pick the small model (Gemma-4-E4B).
pause
