# The drive test's Windows setup: SETUP-Windows.bat from a fresh download, against the mock internet, the way
# a person double-clicking it would answer. First onto this PC (~\TinfoilKit), then onto an exFAT drive. Each
# time START-HERE-Windows.bat must serve the library and the AI, and UNINSTALL-Windows.bat must remove it all.
# CI runs it (.github/workflows/drive.yml). Fixtures: tests/build_fixtures.sh drive, in tests\work\remote.
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
$mock = Start-Process python -ArgumentList "`"$tests\mock_remote.py`"", 19000 -PassThru -NoNewWindow `
  -RedirectStandardOutput "$logs\mock_remote.log" -RedirectStandardError "$logs\mock_remote.err"

# The kit as a browser leaves a Download ZIP that File Explorer unzipped: in Downloads, every file marked as from
# the internet. Its kit.json is the test kit, put in the folder the way one from the website's builder goes in.
function Get-Kit($dir) {
  if (Test-Path $dir) { Remove-Item -Recurse -Force $dir }
  New-Item -ItemType Directory -Force (Split-Path $dir) | Out-Null
  git -C $root archive --format=zip --prefix=tinfoilkit-main/ -o "$work\kit.zip" HEAD
  Expand-Archive "$work\kit.zip" (Split-Path $dir)
  python "$tests\drive.py" kitjson "$dir\kit.json"
  Get-ChildItem -Recurse -File $dir | ForEach-Object {
    Set-Content -LiteralPath $_.FullName -Stream Zone.Identifier -Value "[ZoneTransfer]`r`nZoneId=3"
  }
}

# cmd.exe running a script, and its exit code. Not Start-Process -Wait: that also waits for what the script
# leaves running, like the File Explorer window SETUP opens at the end.
function Invoke-Cmd($line, $log, $answers) {
  $answers | Set-Content -Encoding ascii "$work\answers.txt"
  $p = Start-Process cmd.exe -ArgumentList "/c `"$line`"" -PassThru -NoNewWindow -RedirectStandardInput "$work\answers.txt" `
    -RedirectStandardOutput "$logs\$log" -RedirectStandardError "$logs\$log.err"
  $null = $p.Handle    # keeps the exit code readable after it exits
  if (-not $p.WaitForExit(1200000)) { Fail "$line was still running after 20 minutes"; Stop-Process -Id $p.Id -Force }
  "exit $($p.ExitCode)"
}

# SETUP-Windows.bat with these answers, one per line, as if typed. Its own Python, not this one, runs the kit.
function Invoke-Setup($dir, $log, $answers) {
  Invoke-Cmd "`"$dir\SETUP-Windows.bat`"" $log $answers
  Get-Content "$logs\$log", "$logs\$log.err" | Select-String "PASS|FAIL|All set|Moved|Copied|Removed|Problems|^  - |^  [0-9]+  [A-Za-z]" |
    Select-Object -Last 30 | ForEach-Object { $_.Line }
  if (-not (Select-String -Quiet -Path "$logs\$log" -Pattern "All set")) {
    Fail "SETUP didn't end with All set (logs\$log)"
    Get-Content "$logs\$log", "$logs\$log.err" -Tail 40
  }
}

function Stop-Kit($kit, $proc) {
  Get-Process | Where-Object { $_.Path -and $_.Path.StartsWith("$kit\bin\", "OrdinalIgnoreCase") } | Stop-Process -Force
  if ($proc) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }
  Start-Sleep 2
}

# Double-click START-HERE-Windows.bat, check the library and the AI, stop it.
function Test-Kit($kit, $name) {
  Step "double-click START-HERE-Windows.bat in $kit"
  $p = Start-Process "$kit\START-HERE-Windows.bat" -WorkingDirectory $kit -PassThru
  python "$tests\drive.py" check 8888 8080
  if ($LASTEXITCODE -ne 0) {
    Fail "the kit $name after a double-click"
    netstat -ano | Select-String "LISTENING" | Select-String ":8[0-9]{3} "
    foreach ($f in "kiwix-serve.log", "llama-server.log") { "--- $f"; Get-Content "$kit\logs\$f" -Tail 15 -ErrorAction SilentlyContinue }
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

Step "SETUP-Windows.bat in the unzipped download: this PC; it copies the kit to ~\TinfoilKit and sets it up"
$dl = "$HOME\Downloads\tinfoilkit-main"
$kit = "$HOME\TinfoilKit"
if (Test-Path $kit) { Remove-Item -Recurse -Force $kit }
Get-Kit $dl
$need = [int](python "$dl\tools\kit.py" --root $dl estimate)
$free = [math]::Floor((Get-PSDrive ($HOME.Substring(0, 1))).Free / 1e9)
"The kit needs about $need GB; this PC has $free GB free"
# Answers: this PC, yes even if the disk is short of room (SETUP asks then), download, don't open it, close.
$answers = @("2") + @(if ($free -lt $need + 50) { "y" }) + @("y", "n", "")
Invoke-Setup $dl "setup-windows-pc.log" $answers
if (-not (Test-Path "$kit\models")) { Fail "the kit isn't set up in $kit" }
if (Test-Path $dl) { Fail "the download is still in $dl after the move" }
foreach ($f in "START-HERE-Windows.bat", "SETUP-Windows.bat", "UNINSTALL-Windows.bat") {
  if (Get-Item -LiteralPath "$kit\$f" -Stream Zone.Identifier -ErrorAction SilentlyContinue) { Fail "$f is still marked as from the internet" }
}
Test-Kit $kit "this PC"
Step "UNINSTALL-Windows.bat --yes: the kit, its downloads and the Python SETUP got are gone"
Invoke-Uninstall $kit "uninstall-windows-pc.log"

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

Step "SETUP-Windows.bat in a new download: the drive; it copies the kit there and sets it up"
Get-Kit $dl
$lines = @(python "$dl\tools\kit.py" --root $dl drives)
$lines | ForEach-Object { "  $_" }
$n = 1 + [array]::FindIndex([string[]]$lines, [Predicate[string]] { param($l) $l.StartsWith("${letter}:\") })
if ($n -lt 1) { Fail "SETUP doesn't list the drive ${letter}:"; $n = 1 }
$vfree = [int]($lines[$n - 1].Split("`t")[2])
# Answers: an external drive, this one, yes if it's short of room, download, don't open it, close.
$answers = @("1", "$n") + @(if ($vfree -lt $need) { "y" }) + @("y", "n", "")
Invoke-Setup $dl "setup-windows-drive.log" $answers
if (-not (Test-Path "$kit\models")) { Fail "the kit isn't set up on the drive, at $kit" }
if (Test-Path $dl) { Fail "the download is still in $dl after the move" }
Test-Kit $kit "the drive"
Step "UNINSTALL-Windows.bat --yes on the drive: the kit goes, and nothing else on the drive"
Invoke-Uninstall $kit "uninstall-windows-drive.log"
if (-not (Test-Path "${letter}:\keep-me.txt")) { Fail "UNINSTALL deleted something else on the drive" }
Dismount-DiskImage -ImagePath $vhd | Out-Null

Stop-Process -Id $mock.Id -Force -ErrorAction SilentlyContinue
""
if ($script:fails) { "$($script:fails) FAILED"; exit 1 }
"ALL PASSED"
