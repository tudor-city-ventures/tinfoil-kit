# The drive test's Windows setup: SETUP-Windows.bat from a fresh download, against the mock internet, the way
# a person double-clicking it would answer. First onto this PC (~\TinfoilKit): the try-it kit, with a small real
# map (Andorra's tiles), then SETUP again for the rest (the kit builder's questions, the map's roads and address
# search with the real map programs), an update, and --home-server, which must share it on the home network, behind
# the access code, and set it to start as you sign in. Then onto an exFAT drive, and onto the drive again with the
# one command an AI hands over (--drive, --yes and more) and the same again for the rest, which must ask nothing.
# Each time Open Tinfoil Kit for Windows.bat must serve the library, the AI and any map, and UNINSTALL-Windows.bat
# must remove it all. Last, Open Tinfoil Kit for Windows.bat --share on a kit with no SETUP, on this PC's own Python.
# With -Drive, it plugs in the drive the Mac made (tests\work\drive.vhd) instead, starts the kit on it with a
# double-click and uses the page in Edge.
# CI runs it (.github/workflows/drive.yml). Fixtures: tests/build_fixtures.sh drive, in tests\work\remote.
param([switch]$Drive)
$ErrorActionPreference = "Stop"
$tests = $PSScriptRoot
$root = Split-Path $tests
$work = Join-Path $tests "work"
$logs = Join-Path $work "logs"
New-Item -ItemType Directory -Force $logs | Out-Null
$env:KIT_TEST_WORK = $work
$script:fails = 0
function Fail($msg) { "FAIL: $msg"; $script:fails++ }
function Step($msg) { ""; "=== $msg" }

# The mock internet, and the KIT_* settings that point the kit at it
Get-Content "$tests\env.sh" | ForEach-Object { if ($_ -match '^export (\w+)="(.*)"$') { Set-Item "env:$($Matches[1])" $Matches[2] } }
if (-not $Drive) {
  $mock = Start-Process python -ArgumentList "`"$tests\mock_remote.py`"", 19000 -PassThru -NoNewWindow `
    -RedirectStandardOutput "$logs\mock_remote.log" -RedirectStandardError "$logs\mock_remote.err"
}

# The kit as a browser leaves a Download ZIP that File Explorer unzipped: in Downloads, every file marked as from
# the internet. Its kit.json is the test kit, put in the folder the way one from the website's builder goes in.
function Get-Kit($dir, [switch]$Maps) {
  if (Test-Path $dir) { Remove-Item -Recurse -Force $dir }
  New-Item -ItemType Directory -Force (Split-Path $dir) | Out-Null
  git -C $root archive --format=zip --prefix=tinfoilkit-main/ -o "$work\kit.zip" HEAD
  Expand-Archive "$work\kit.zip" (Split-Path $dir)
  $kitjson = @("$tests\drive.py", "kitjson", "$dir\kit.json") + @(if ($Maps) { "maps" })
  python @kitjson
  Get-ChildItem -Recurse -File $dir | ForEach-Object {
    Set-Content -LiteralPath $_.FullName -Stream Zone.Identifier -Value "[ZoneTransfer]`r`nZoneId=3"
  }
}

# A script in a console window of its own, with the answers typed in as it asks them (tests/drive.py type), and its
# exit code. Not Start-Process -Wait: that also waits for what the script leaves running, like the File Explorer
# window SETUP opens at the end.
function Invoke-Cmd($line, $log, $answers) {
  $answers | Set-Content -Encoding ascii "$work\answers.txt"
  $p = Start-Process (Get-Command python).Source -PassThru `
    -ArgumentList "`"$tests\drive.py`" type `"$logs\$log`" `"@$work\answers.txt`" -- $line"
  $null = $p.Handle    # keeps the exit code readable after it exits
  if (-not $p.WaitForExit(1200000)) { Fail "$line was still running after 20 minutes"; Stop-Process -Id $p.Id -Force }
  "exit $($p.ExitCode)"
}

# SETUP-Windows.bat with these answers, one per line, as if typed. Its own Python, not this one, runs the kit.
function Invoke-Setup($dir, $log, $answers, $flags = "") {
  Invoke-Cmd "`"$dir\SETUP-Windows.bat`" $flags" $log $answers
  Get-Content "$logs\$log" | Select-String "PASS|FAIL|All set|try-it kit|Moved|Copied|Removed|Problems|^  - |^  [0-9]+  [A-Za-z]" |
    Select-Object -Last 30 | ForEach-Object { $_.Line }
  if (-not (Select-String -Quiet -Path "$logs\$log" -Pattern "All set|The try-it kit works")) {
    Fail "SETUP didn't end with All set or a working try-it kit (logs\$log)"
    Get-Content "$logs\$log" -Tail 40
  }
}

# Fails for each of these SETUP didn't say in its log.
function Test-Said($log, $what, [string[]]$said) {
  foreach ($s in $said) {
    if (-not (Select-String -Quiet -SimpleMatch -Path "$logs\$log" -Pattern $s)) { Fail "$what didn't say `"$s`"" }
  }
}

# SETUP's answer when it asks how much of the kit goes to a place, from ./kit space there: none when all of it fits
# with room to spare, all of it anyway when that leaves less free than SETUP likes, else just the essentials.
function Get-RoomAnswer($dir, $place) {
  $room = (python "$dir\tools\kit.py" --root $dir space $place).Split("`t")
  "Room at ${place}: $($room -join ' ')" | Out-Host
  if ($room[0] -eq "tight") { "2" } elseif ($room[0] -ne "fits") { "1" }
}

# The kit's servers, its sharing gate, and the Open Tinfoil Kit windows that started them.
function Stop-Kit($kit, $proc) {
  Get-Process | Where-Object { $_.Path -and $_.Path.StartsWith("$kit\bin\", "OrdinalIgnoreCase") } | Stop-Process -Force
  $mine = "$kit\tools\share.py", "$kit\Open Tinfoil Kit for Windows.bat"
  Get-CimInstance Win32_Process | Where-Object { $c = $_.CommandLine; $c -and ($mine | Where-Object { $c.IndexOf($_, [StringComparison]::OrdinalIgnoreCase) -ge 0 }) } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
  if ($proc) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }
  Start-Sleep 2
}

# The kit shared on the home network: a phone there opens ADDRESS and types the access code.
function Test-Share($kit, $address, $code) {
  "The kit is shared at $address, access code $code"
  python "$tests\drive.py" share $address $code 8888 8080
  if ($LASTEXITCODE -ne 0) {
    Fail "sharing on the home network ($kit)"
    "--- share.log"; Get-Content "$kit\logs\share.log" -Tail 15 -ErrorAction SilentlyContinue
  }
}

# Double-click Open Tinfoil Kit for Windows.bat, check the library, the AI and any map, stop it. -Share: with --share, which needs Python
# and gets this PC's own when SETUP's isn't there.
function Test-Kit($kit, $name, [switch]$Share) {
  if ($Share) {
    Step "Open Tinfoil Kit for Windows.bat --share in $kit"
    $p = Start-Process "$kit\Open Tinfoil Kit for Windows.bat" -ArgumentList "--share" -WorkingDirectory $kit -PassThru
  } else {
    Step "double-click Open Tinfoil Kit for Windows.bat in $kit"
    $p = Start-Process "$kit\Open Tinfoil Kit for Windows.bat" -WorkingDirectory $kit -PassThru
  }
  python "$tests\drive.py" check 8888 8080
  if ($LASTEXITCODE -ne 0) {
    Fail "the kit $name after a double-click"
    netstat -ano | Select-String "LISTENING" | Select-String ":8[0-9]{3} "
    foreach ($f in "kiwix-serve.log", "llama-server.log", "tiles.log", "geocoder.log", "routing.log") {
      if (Test-Path "$kit\logs\$f") { "--- $f"; Get-Content "$kit\logs\$f" -Tail 15 }
    }
  }
  if ($Share) {
    for ($i = 0; $i -lt 60 -and -not (Test-Path "$kit\.kit\share.json"); $i++) { Start-Sleep 1 }    # the gate makes the code
    $ip = python -c "import sys; sys.path.insert(0, sys.argv[1]); import share; print(share.lan_ips()[0])" "$kit\tools"
    Test-Share $kit "http://${ip}:8000" (Get-Content "$kit\.kit\share.json" -ErrorAction SilentlyContinue | ConvertFrom-Json).code
  }
  Stop-Kit $kit $p
  Copy-Item -Recurse "$kit\logs" "$logs\$($name -replace '\W', '-')-logs" -ErrorAction SilentlyContinue
}

function Invoke-Uninstall($kit, $log) {
  Invoke-Cmd "`"$kit\UNINSTALL-Windows.bat`" --yes" $log @("")
  Get-Content "$logs\$log" | Select-Object -Last 4
  if (Test-Path $kit) { Fail "$kit is still there after UNINSTALL" }
  if (Test-Path "$env:LOCALAPPDATA\TinfoilKit") { Fail "UNINSTALL left the Python SETUP got" }
}

if ($Drive) {
  Step "plug in the drive the Mac made"
  New-Item -ItemType Directory -Force "$work\shots" | Out-Null
  $disk = Mount-DiskImage -ImagePath "$work\drive.vhd" -PassThru | Get-Disk
  $part = Get-Partition -DiskNumber $disk.Number |
    Where-Object { (Get-Volume -Partition $_ -ErrorAction SilentlyContinue).FileSystem -eq "exFAT" } | Select-Object -First 1
  if (-not $part) { Get-Partition -DiskNumber $disk.Number | Format-List; throw "no exFAT partition on the drive" }
  if (-not $part.DriveLetter) {
    $part | Add-PartitionAccessPath -AssignDriveLetter
    $part = Get-Partition -DiskNumber $disk.Number -PartitionNumber $part.PartitionNumber
  }
  $kit = "$($part.DriveLetter):\TinfoilKit"
  "The drive is $($part.DriveLetter):"
  Get-ChildItem -Force "$kit\library", "$kit\models" -Recurse | ForEach-Object { "$($_.Mode)  $($_.FullName)" }
  Step "double-click Open Tinfoil Kit for Windows.bat on the drive: it starts the kit and opens the page"
  $p = Start-Process "$kit\Open Tinfoil Kit for Windows.bat" -WorkingDirectory $kit -PassThru
  python "$tests\drive.py" check 8888 8080
  if ($LASTEXITCODE -ne 0) { Fail "the kit on the drive after a double-click" }
  Start-Sleep 5
  try {
    Add-Type -AssemblyName System.Windows.Forms, System.Drawing
    $b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
    $bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
    [System.Drawing.Graphics]::FromImage($bmp).CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size)
    $bmp.Save("$work\shots\windows-desktop.png")
  } catch { "(no desktop screenshot here: $_)" }
  Step "the page in Edge"
  $env:KIT_BROWSER = "msedge"; $env:KIT_LIBRARY_PORT = "8888"; $env:KIT_AI_PORT = "8080"
  $env:KIT_TEST_SHOTS = "$work\shots\windows"
  python "$tests\ui_test.py"
  if ($LASTEXITCODE -ne 0) { Fail "the page in Edge" }
  Stop-Kit $kit $p
  ""
  if ($script:fails) { "$($script:fails) FAILED"; exit 1 }
  "ALL PASSED"
  exit 0
}

Step "SETUP-Windows.bat in the unzipped download: this PC; it copies the kit to ~\TinfoilKit and gets the try-it kit"
$dl = "$HOME\Downloads\tinfoilkit-main"
$kit = "$HOME\TinfoilKit"
if (Test-Path $kit) { Remove-Item -Recurse -Force $kit }
Get-Kit $dl -Maps
# Answers: keep where it's for, this PC, how much if room is short (SETUP asks then), download, don't open it, close.
$answers = @("", "2") + @(Get-RoomAnswer $dl $kit) + @("y", "n", "")
Invoke-Setup $dl "setup-windows-pc.log" $answers
Test-Said "setup-windows-pc.log" "SETUP" @("Step 1 of 3: where do you live", "Step 3 of 3: a small kit to try first",
  "The try-it kit works. It's on this PC", "The rest of the kit is about", "double-click SETUP-Windows.bat again: it asks what you want")
if (-not (Test-Path "$kit\models\Two")) { Fail "the try-it kit didn't get its sample AI" }
if (Test-Path "$kit\maps\routing") { Fail "the try-it kit got the map's roads, which come with the rest" }
if (Test-Path $dl) { Fail "the download is still in $dl after the move" }
foreach ($f in "Open Tinfoil Kit for Windows.bat", "SETUP-Windows.bat", "UNINSTALL-Windows.bat") {
  if (Get-Item -LiteralPath "$kit\$f" -Stream Zone.Identifier -ErrorAction SilentlyContinue) { Fail "$f is still marked as from the internet" }
}
Step "SETUP-Windows.bat again in ~\TinfoilKit, for the rest: what goes in it (Recommended), the map's roads and address search"
# Answers: keep where it's for, Recommended, how much if room is short, download, don't open it, close.
$answers = @("", "") + @(Get-RoomAnswer $kit $kit) + @("y", "n", "")
Invoke-Setup $kit "setup-windows-rest.log" $answers
Test-Said "setup-windows-rest.log" "SETUP" "What goes in the kit?", "Step 2 of 3: the rest of the kit", "All set"
foreach ($f in "maps\routing\graph-cache\properties", "maps\geocoder\photon_data") {
  if (-not (Test-Path "$kit\$f")) { Fail "SETUP didn't make $f (logs\setup-windows-rest.log)" }
}
if (Test-Path "$kit\models\Two") { Fail "the try-it kit's sample AI is still there after the rest" }
Test-Kit $kit "this PC"
Step "SETUP-Windows.bat again in ~\TinfoilKit: an update"
# Answers: keep where it's for, download, don't open it, close.
Invoke-Setup $kit "setup-windows-update.log" @("", "y", "n", "")
Test-Said "setup-windows-update.log" "the update" "TINFOIL KIT UPDATE", "To change that", "Step 3 of 3: start everything offline"
Step "SETUP-Windows.bat --home-server: shared on the home network, and started now and whenever you sign in"
$startup = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\Tinfoil Kit.cmd"
# Answers: keep where it's for, download, close.
Invoke-Setup $kit "setup-windows-home-server.log" @("", "y", "") "--home-server"
$said = Get-Content "$logs\setup-windows-home-server.log" -Raw
$said -split "`n" | Select-String "Home server|home network|Access code|sign in" | ForEach-Object { $_.Line }
$address = if ($said -match "open (http://[0-9.]+:[0-9]+) on a phone") { $Matches[1] }
$code = if ($said -match "Access code: ([0-9 ]+)") { $Matches[1] -replace " ", "" }
if (-not ($address -and $code)) { Fail "SETUP --home-server didn't show the address and the access code" }
if (-not ((Get-Content $startup -Raw -ErrorAction SilentlyContinue) -like "*`"$kit\Open Tinfoil Kit for Windows.bat`" --no-browser*")) {
  Fail "SETUP --home-server didn't set the kit to start as you sign in ($startup)"
}
Test-Share $kit $address $code    # the kit Windows started from the Startup folder, minimized
$out = & "$kit\kit.cmd" autostart
"kit.cmd autostart: $out"
if ($LASTEXITCODE -ne 0 -or -not ("$out" -match "starts when you sign in")) { Fail "kit.cmd autostart doesn't say the kit starts as you sign in" }
Stop-Kit $kit $null
Step "./kit fit: Windows says how much memory this PC has"
$fit = python "$kit\tools\kit.py" --root $kit fit
$fit
if (-not ($fit -match "has \d+ GB of memory")) { Fail "./kit fit can't tell this PC's memory" }
Step "UNINSTALL-Windows.bat --yes: the kit, its downloads and the Python SETUP got are gone"
Invoke-Uninstall $kit "uninstall-windows-pc.log"
if (Test-Path $startup) { Fail "UNINSTALL left the kit starting as you sign in ($startup)" }

Step "a 2 GB disk, formatted exFAT the way File Explorer does"
$vhd = "$work\drive-windows.vhd"
Remove-Item -Force $vhd -ErrorAction SilentlyContinue
fsutil file createnew $vhd 2147483648 | Out-Null
python "$tests\drive.py" vhd $vhd
$disk = Mount-DiskImage -ImagePath $vhd -PassThru | Get-Disk
$part = $disk | Initialize-Disk -PartitionStyle GPT -PassThru | New-Partition -UseMaximumSize -AssignDriveLetter
$part | Format-Volume -FileSystem exFAT -NewFileSystemLabel TINFOIL -Confirm:$false | Out-Null
$letter = (Get-Partition -DiskNumber $disk.Number -PartitionNumber $part.PartitionNumber).DriveLetter
$kit = "${letter}:\TinfoilKit"
"The drive is ${letter}:"
Set-Content "${letter}:\keep-me.txt" "mine"

Step "SETUP-Windows.bat in a new download: the drive; it copies the kit there and gets the try-it kit"
Get-Kit $dl
$lines = @(python "$dl\tools\kit.py" --root $dl drives)
$lines | ForEach-Object { "  $_" }
$n = 1 + [array]::FindIndex([string[]]$lines, [Predicate[string]] { param($l) $l.StartsWith("${letter}:\") })
if ($n -lt 1) { Fail "SETUP doesn't list the drive ${letter}:"; $n = 1 }
# Answers: keep where it's for, an external drive, this one, how much if room is short, download, don't open it, close.
$answers = @("", "1", "$n") + @(Get-RoomAnswer $dl $kit) + @("y", "n", "")
Invoke-Setup $dl "setup-windows-drive.log" $answers
if (-not (Test-Path "$kit\models\Two")) { Fail "the try-it kit isn't on the drive, at $kit" }
if (Test-Path $dl) { Fail "the download is still in $dl after the move" }
Test-Kit $kit "the drive"
Step "UNINSTALL-Windows.bat --yes on the drive: the kit goes, and nothing else on the drive"
Invoke-Uninstall $kit "uninstall-windows-drive.log"
if (-not (Test-Path "${letter}:\keep-me.txt")) { Fail "UNINSTALL deleted something else on the drive" }

Step "SETUP-Windows.bat --help, and an option it doesn't have"
Get-Kit $dl
$help = & "$dl\SETUP-Windows.bat" --help
if ($LASTEXITCODE -ne 0 -or -not ($help -match "^--drive PATH")) { Fail "SETUP-Windows.bat --help didn't list its options (exit $LASTEXITCODE)"; $help }
& "$dl\SETUP-Windows.bat" --nope > $null
if ($LASTEXITCODE -ne 2) { Fail "SETUP-Windows.bat --nope should stop with exit 2, not $LASTEXITCODE" }
Step "SETUP-Windows.bat --drive ${letter}: --models Tiny --share --yes: the one command an AI hands over; no questions, the try-it kit, and it opens"
$out = Invoke-Setup $dl "setup-windows-yes.log" @("") "--drive ${letter}: --models Tiny --share --yes"
$out
if (-not ($out -contains "exit 0")) { Fail "SETUP --yes didn't end with exit 0" }
Test-Said "setup-windows-yes.log" "SETUP --yes" @("What goes in it:", "The try-it kit works",
  "When you're ready for it: `"$kit\SETUP-Windows.bat`" --yes", "Sharing: phones and laptops", "Access code")
$asked = "\[Y/n\]|\[y/N\]|Type (1|a number)|Press Enter"
if (Select-String -Quiet -Path "$logs\setup-windows-yes.log" -Pattern $asked) { Fail "SETUP --yes asked something" }
if (-not (Test-Path "$kit\models\Two")) { Fail "the try-it kit isn't on the drive, at $kit" }
if (Test-Path $dl) { Fail "the download is still in $dl after the move" }
python "$tests\drive.py" check 8888 8080
if ($LASTEXITCODE -ne 0) { Fail "the kit SETUP --yes opened" }
Step "`"$kit\SETUP-Windows.bat`" --yes, as the try-it kit said, with the kit still open: it stops it, then gets the rest"
$out = Invoke-Setup $kit "setup-windows-yes-rest.log" @("") "--yes"
$out
if (-not ($out -contains "exit 0")) { Fail "SETUP --yes for the rest didn't end with exit 0" }
Test-Said "setup-windows-yes-rest.log" "SETUP --yes for the rest" "Step 2 of 3: the rest of the kit", "The kit is running. Stopping it", "All set"
if (Select-String -Quiet -Path "$logs\setup-windows-yes-rest.log" -Pattern $asked) { Fail "SETUP --yes for the rest asked something" }
if (Test-Path "$kit\models\Two") { Fail "the try-it kit's sample AI is still there after the rest" }
Test-Kit $kit "the drive, set up with --yes"
Invoke-Uninstall $kit "uninstall-windows-yes.log"
Dismount-DiskImage -ImagePath $vhd | Out-Null

# A cmd window, unlike the cmd /c that PowerShell or an AI's shell starts, would close at SETUP's exit: there
# SETUP runs itself in a cmd of its own. Here cmd reads what's typed from a file, as a window reads the keyboard.
# With --all, the rest comes right after the try-it kit, in the same run.
Step "SETUP-Windows.bat --this-computer --models Tiny --all --yes typed in a cmd window: the window stays, and says how SETUP ended"
Get-Kit $dl
$kit = "$env:USERPROFILE\TinfoilKit"
@("`"$dl\SETUP-Windows.bat`" --this-computer --models Tiny --all --yes", "echo SETUP ended with %errorlevel%", "exit") |
  Set-Content -Encoding ascii "$work\cmd-window.txt"
$p = Start-Process cmd.exe -ArgumentList "/d /q" -PassThru -NoNewWindow -RedirectStandardInput "$work\cmd-window.txt" `
  -RedirectStandardOutput "$logs\setup-windows-cmd.log" -RedirectStandardError "$logs\setup-windows-cmd.err"
$null = $p.Handle
if (-not $p.WaitForExit(1200000)) { Fail "SETUP in a cmd window was still running after 20 minutes"; Stop-Process -Id $p.Id -Force }
Get-Content "$logs\setup-windows-cmd.log" | Select-String "Step [0-9]|try-it kit|All set|SETUP ended" | ForEach-Object { $_.Line }
if (-not (Select-String -Quiet -Path "$logs\setup-windows-cmd.log" -Pattern "SETUP ended with 0")) {
  Fail "SETUP --yes in a cmd window closed it, or didn't end with 0"
  Get-Content "$logs\setup-windows-cmd.log" -Tail 25; Get-Content "$logs\setup-windows-cmd.err" -ErrorAction SilentlyContinue
}
Test-Said "setup-windows-cmd.log" "SETUP --all --yes" "Step 3 of 4: a small kit to try first", "Step 4 of 4: the rest of the kit", "All set"
if (Test-Path "$kit\models\Two") { Fail "the try-it kit's sample AI is still there after --all, at $kit" }
if (-not (Test-Path "$kit\models\Tiny")) { Fail "the kit isn't set up on this PC, at $kit" }
if (Test-Path $dl) { Fail "the download is still in $dl after the move" }
Invoke-Uninstall $kit "uninstall-windows-cmd.log"

# A kit on a drive opened on a PC that never ran SETUP: sharing it needs Python, and this PC's own does.
Step "a kit ./kit sync got, with no SETUP: Open Tinfoil Kit for Windows.bat --share on this PC's own Python"
Get-Kit $dl
Get-ChildItem -Recurse -File $dl | Unblock-File    # no SETUP here to do it, and Open Tinfoil Kit starts with a double-click
python "$dl\tools\kit.py" --root $dl sync --yes *> "$logs\sync-windows-own-python.log"
"exit $LASTEXITCODE"
if ($LASTEXITCODE -ne 0) { Fail "./kit sync (logs\sync-windows-own-python.log)"; Get-Content "$logs\sync-windows-own-python.log" -Tail 20 }
Test-Kit $dl "this PC's own Python" -Share
Remove-Item -Recurse -Force $dl -ErrorAction SilentlyContinue

Stop-Process -Id $mock.Id -Force -ErrorAction SilentlyContinue
""
if ($script:fails) { "$($script:fails) FAILED"; exit 1 }
"ALL PASSED"
