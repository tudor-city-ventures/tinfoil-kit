#!/bin/bash
# The drive test: the kit on a real exFAT disk, set up on a Mac, then plugged into Windows and Linux.
# CI runs it nightly and on demand (.github/workflows/drive.yml). Fixtures: tests/build_fixtures.sh drive.
#   tests/drive_test.sh mac     erase a disk image as exFAT the way Disk Utility does, build the Mac app, unzip
#                               the kit as a download leaves it (with the kit's own program, tools/tinfoilkit-*,
#                               which the launchers hand over to), run its SETUP against the mock internet and
#                               pick the drive (the try-it kit), run SETUP again from the drive for the rest (it
#                               builds a small real map there: Andorra's), delete the kit's app folder and run a new
#                               download's SETUP, which puts its own there, double-click Open Tinfoil Kit, check
#                               the library, the AI and the map, check the page in WebKit, open it again with a
#                               second address on the loopback (kiwix-serve then won't use 127.0.0.1), open the
#                               kit with the app, eject. Leaves tests/work/drive.vhd. Then set the kit up on
#                               this Mac (~/TinfoilKit) from the app, as a home server (SETUP --home-server), check
#                               that the Mac started it and that it's shared behind the access code, and remove
#                               it with UNINSTALL.
#   tests/drive_test.sh linux   mount that drive the way a Linux desktop does, start the kit on this
#                               machine (the newest Ubuntu in CI), then in Ubuntu 24.04 and 22.04, Debian 12
#                               and Fedora. Then make it a home server (./kit share on, ./kit autostart on) and
#                               check it the same way, and remove it from the drive with UNINSTALL.
# Windows: tests/drive_windows.ps1. SETUP and UNINSTALL run in terminal windows of their own with their answers typed
# in, and the launchers' output shows in windows too, so that tests/drive.py record can film it all.
set -u
TESTS="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$TESTS")"
export KIT_TEST_WORK="${KIT_TEST_WORK:-$TESTS/work}"
W="$KIT_TEST_WORK" L="$KIT_TEST_WORK/logs" SHOTS="$KIT_TEST_WORK/shots"
mkdir -p "$L" "$SHOTS"
FAILS=0
fail() { echo "FAIL: $*"; FAILS=$((FAILS + 1)); }
step() { echo; echo "=== $*"; }
# The end of the kit's own logs, after a check failed: the job's log is all a cloud session can read.
kit_logs() { # KIT LOG...
  local k="$1" f; shift
  for f in "$@"; do [ -f "$k/data/logs/$f" ] && { echo "--- $f"; tail -15 "$k/data/logs/$f"; }; done
}
# A kit folder holds its app, downloads and data folders, the launchers and Read me first.txt beside them, and
# nothing else of its own.
TOP=(app data downloads "Open Tinfoil Kit.command" "Open Tinfoil Kit for Windows.bat" "Read me first.txt")
just_the_kit() { # KIT
  local f more=""
  for f in "${TOP[@]}"; do [ -e "$1/$f" ] || fail "$1 has no $f"; done
  for f in "$1"/* "$1"/.[!.]*; do
    case "${f##*/}" in
      app | data | downloads | "Open Tinfoil Kit.command" | "Open Tinfoil Kit for Windows.bat" | "Read me first.txt") ;;
      ._* | .DS_Store | '*' | '.[!.]*') ;;
      *) more="$more, ${f##*/}" ;;
    esac
  done
  [ -z "$more" ] || fail "$1 holds more than ${TOP[*]}: ${more#, }"
}
# The kit's servers, gone before the next kit starts: a map server still answering would stand in for the next one's.
SERVERS='llama-server|kiwix-serve|pmtiles serve|graphhopper-web|photon-'
stop_kit() {
  pkill -f 'tools/tinfoilkit-'; sleep 1; pkill -f "$SERVERS"
  for _ in 1 2 3 4 5 6 7 8 9 10; do pgrep -f "$SERVERS" > /dev/null || break; sleep 1; done
} 2>/dev/null

# The kit as Safari leaves a download: a TinfoilKit folder with the app folder in it, every file marked as from the
# internet. Its standard list (app/kit.json) is the test kit's; with maps, a map too. Like a release's download, it
# has the kit's own program for each computer in its tools (drive.yml builds them; else kit/tools/tinfoilkit/build.sh).
download_kit() { # KIT [maps]
  rm -rf "$1" && mkdir -p "$1/app"
  git -C "$ROOT/kit" archive HEAD | tar -xf - -C "$1/app"
  cp "$W"/programs/tinfoilkit-* "$1/app/tools/"
  python3 "$TESTS/drive.py" kitjson "$1/app/kit.json" ${2:-}
  xattr -r -w com.apple.quarantine "0083;$(printf %x "$(date +%s)");Safari;" "$1"
}
# Where SETUP lists a drive: its line in ./kit drives (folder, format, GB free, problem, name).
drive_number() { # KIT NAME
  "$1/app/kit" drives | awk -F'\t' -v n="$2" '$5 == n {print NR; exit}'
}
# COMMAND in a terminal window of its own, with the mock internet and ANSWERS typed in as it asks (printf %b, a
# line each), the way a person double-clicking it would: Terminal on a Mac, xterm where there's a screen, else no
# window. Its output goes to logs/LOG; returns its exit code.
terminal() { # FOLDER LOG ANSWERS COMMAND...
  local dir="$1" log="$L/$2" answers="$3" run="$W/${2%.log}.command" i
  shift 3
  rm -f "$log.exit"
  { echo '#!/bin/bash'
    echo 'printf "\033[3;0;0t\033[8;34;100t\033[2J\033[H"'    # Terminal: top left, 100 columns by 34 rows, cleared
    printf 'cd %q && . %q\n' "$dir" "$TESTS/env.sh"
    for i in $(compgen -e | grep '^KIT_'); do printf 'export %s=%q\n' "$i" "${!i}"; done    # KIT_YES=1 setup ...
    printf '%q ' "$(command -v python3)" "$TESTS/drive.py" type "$log" "$answers" -- "$@"; echo
    printf 'echo $? > %q\n' "$log.exit"
  } > "$run"
  chmod +x "$run"
  if [ "$(uname -s)" = Darwin ]; then open "$run"
  elif [ -n "${DISPLAY:-}" ] && command -v xterm > /dev/null; then xterm $XTERM -T "${2%.log}" -e bash "$run" > /dev/null 2>&1 &
  else bash "$run" > /dev/null 2>&1 & fi
  for ((i = 0; i < 1800; i++)); do [ -f "$log.exit" ] && break; sleep 1; done
  [ -f "$log.exit" ] || { echo "(still running after 30 minutes)"; return 124; }
  sleep 2    # the end, on screen a moment
  return "$(cat "$log.exit")"
}
XTERM="-geometry 100x34+0+0 -fa Monospace -fs 11 -bg #1d1f21 -fg #e0e0e0"
# COMMAND's output in a window, where there's a screen: what's on screen when a person runs it.
window() { # TITLE COMMAND...
  [ -n "${DISPLAY:-}" ] && command -v xterm > /dev/null || return 0
  local title="$1"; shift
  xterm $XTERM -T "$title" -e "$@" > /dev/null 2>&1 &
}
# The kit's SETUP, in its app folder, with the mock internet, a stock Mac's PATH and bash, and these answers.
setup() { # KIT LOG ANSWERS [SETUP'S OPTIONS]
  local dir="$1/app" log="$2" answers="$3"; shift 3
  terminal "$dir" "$log" "$answers" env PATH=/usr/bin:/bin:/usr/sbin:/sbin /bin/bash SETUP.command "$@"
  echo "exit $?"
  grep -E "PASS|FAIL|All set|Moved|Problems|^  - |^  [0-9]  |home network|Access code|starts" "$L/$log" | tail -24
  grep -qE "All set|The try-it kit works" "$L/$log" || fail "SETUP didn't end with All set or a working try-it kit (logs/$log)"
}
# A home server's kit, checked the way a phone on the home network finds it: at the address and with the access
# code that ./kit share shows. The servers behind the gate mustn't answer at that address themselves.
share_check() { # KIT
  local out addr code
  out="$("$1/app/kit" share 2>&1)"
  echo "$out"
  addr="$(echo "$out" | sed -n 's/.*open \(http:[^ ]*\) on a phone.*/\1/p' | head -1)"
  code="$(echo "$out" | sed -n 's/.*Access code: //p' | tr -d ' ' | head -1)"
  [ -n "$addr" ] && [ -n "$code" ] || { fail "./kit share showed no address or access code"; return; }
  python3 "$TESTS/drive.py" share "$addr" "$code" 8888 8080 || fail "the kit shared on the home network"
}

# Fails unless the kit's own program is what runs the kit: the launchers hand over to it.
program_runs() { # PROGRAM WHAT [CONTAINER]
  if [ -n "${3:-}" ]; then docker top "$3" | grep -q "tools/$1 --root .* open"; else pgrep -f "tools/$1 --root .* open" > /dev/null; fi &&
    echo "The kit's own program ($1) runs $2" || fail "$2: the launcher didn't hand over to the kit's own program ($1)"
}

# The Mac app, run the way a test can answer its questions (KIT_APP_ANSWERS): from this shell, which macOS lets use
# the drive, rather than through open. Waits for it to quit, up to SECONDS (it stays open while the kit runs).
run_app() { # LOG SECONDS [VAR=VALUE...]
  local log="$L/$1" secs="$2" i=0; shift 2
  env "$@" "$app/Contents/MacOS/Tinfoil Kit" > "$log" 2>&1 &
  APP_PID=$!
  while [ $i -lt "$secs" ]; do kill -0 "$APP_PID" 2> /dev/null || return 0; sleep 1; i=$((i + 1)); done
  return 1
}

mac() {
  local img="$W/drive.img" vol=/Volumes/TINFOIL disk kit src mock f much same
  local support="$HOME/Library/Application Support/TinfoilKit"    # where the Mac app keeps where the kit is
  local app="$HOME/Applications/Tinfoil Kit.app"
  step "a 4 GB disk, erased as exFAT the way Disk Utility does"
  hdiutil detach "$vol" > /dev/null 2>&1
  rm -f "$img" "$W/drive.vhd" && mkfile -n 4g "$img"    # a map's tiles count as about 1 GB until they're built
  disk=$(hdiutil attach -imagekey diskimage-class=CRawDiskImage -nomount "$img" | awk 'NR == 1 {print $1}')
  diskutil eraseDisk ExFAT TINFOIL GPT "$disk" || { fail "erase $disk"; return; }

  step "the kit's own program, signed again the way Apple's signing does it: tinfoilkit compare finds only the"
  echo "signature changed (build.sh verify says so of the Mac app's copy)"
  [ -f "$W/programs/tinfoilkit-macos-arm64" ] || "$ROOT/kit/tools/tinfoilkit/build.sh" "$W/programs" || fail "the kit's own program didn't build"
  f="$W/programs/tinfoilkit-macos-arm64"
  chmod +x "$W"/programs/tinfoilkit-*    # an Actions artifact keeps no file modes
  cp "$f" "$W/program-signed" && codesign --force --options runtime --sign - "$W/program-signed"
  cmp -s "$f" "$W/program-signed" && fail "codesign left the program as it was, so this didn't test compare"
  same="$("$f" compare "$f" "$W/program-signed")"
  echo "$same"
  [ "$same" = "the same apart from the code signature" ] || fail "tinfoilkit compare: $same"
  printf 'x' | dd of="$W/program-signed" bs=1 seek=4096 conv=notrunc 2> /dev/null    # one byte of its code changed
  same="$("$f" compare "$f" "$W/program-signed")"
  [ "$same" = "different" ] || fail "tinfoilkit compare called a changed program \"$same\""

  step "the Mac app, built from this commit and signed ad hoc, in Applications as it puts itself"
  rm -rf "$app" "$W/app" "$W/app-kit" && mkdir -p "$W/app-kit/TinfoilKit"
  git -C "$ROOT/kit" archive HEAD | tar -xf - -C "$W/app-kit/TinfoilKit"
  cp "$W"/programs/tinfoilkit-* "$W/app-kit/TinfoilKit/tools/"
  tar -czf "$W/app-kit.tar.gz" -C "$W/app-kit" TinfoilKit    # a release's archive, which mac/build.sh takes
  if "$ROOT/mac/build.sh" "$W/app-kit.tar.gz" "$W/app" > "$L/mac_app_build.log" 2>&1; then
    tail -1 "$L/mac_app_build.log"
    mkdir -p "${app%/*}" && ditto "$W/app/Tinfoil Kit.app" "$app"
  else
    tail -20 "$L/mac_app_build.log"; fail "the Mac app didn't build (logs/mac_app_build.log)"
  fi

  python3 "$TESTS/mock_remote.py" 19000 > "$L/mock_remote.log" 2>&1 &
  mock=$!
  step "SETUP.command in the unzipped download: pick the drive; it moves the kit there and gets the try-it kit"
  src="$W/Downloads/TinfoilKit" kit="$vol/TinfoilKit"
  rm -rf "$support"
  download_kit "$src" maps
  n="$(drive_number "$src" TINFOIL)"
  echo "SETUP lists TINFOIL as drive ${n:-(not at all)}"
  "$src/app/kit" space "$kit"
  # Answers: keep where it's for, an external drive, TINFOIL, all of it even if that leaves less free than SETUP
  # likes (it asks then), start downloading, don't open the kit, close.
  much=""; [ "$("$src/app/kit" space "$kit" | cut -f1)" = tight ] && much="2\n"
  setup "$src" setup.log "\n1\n${n:-1}\n${much}y\nn\n\n"
  grep -q "The try-it kit works" "$L/setup.log" || kit_logs "$kit" test-tiles.log test-llama.log
  [ -d "$kit/downloads/models/Two" ] || fail "the try-it kit didn't get its sample AI"
  [ -d "$kit/downloads/maps/routing" ] && fail "the try-it kit got the map's roads, which come with the rest"
  just_the_kit "$kit"

  step "SETUP again, from the drive, to get the rest: the kit builder's questions (Return takes Recommended),"
  echo "then the map's roads and address search, and the try-it kit's sample AI goes"
  # Answers: keep where it's for, Recommended, all of it even if that leaves less free than SETUP likes (it asks
  # then), start downloading, don't open the kit, close.
  much=""; [ "$("$kit/app/kit" space "$kit" | cut -f1)" = tight ] && much="2\n"
  setup "$kit" setup-rest.log "\n\n${much}y\nn\n\n"
  grep -q "All set" "$L/setup-rest.log" || kit_logs "$kit" test-tiles.log test-geocoder.log test-routing.log
  grep -q "What goes in the kit?" "$L/setup-rest.log" || fail "SETUP didn't ask what goes in the kit"
  [ -f "$kit/downloads/maps/routing/graph-cache/properties" ] || fail "SETUP didn't build the map's roads on the drive"
  grep -q "merging the road data of 2 places" "$L/setup-rest.log" || fail "SETUP didn't merge the two places' roads"
  [ -d "$kit/downloads/models/Two" ] && fail "the try-it kit's sample AI is still there after the rest"
  [ -d "$kit/downloads/models" ] || fail "the kit isn't set up on the drive, at $kit"
  [ -d "$src" ] && fail "the download is still in $src after the move"

  step "a new version, by hand: delete the kit's app folder, download the kit again and run that SETUP. It finds the"
  echo "kit on the drive, puts its own app folder there and updates the kit: nothing downloads again"
  rm -rf "$kit/app"
  download_kit "$src" maps
  # Answers: update the kit on the drive, keep where it's for, start downloading, don't open the kit, close.
  setup "$src" setup-new-app.log "\n\ny\nn\n\n"
  grep -q "this version's is in it now" "$L/setup-new-app.log" || fail "SETUP from a new download didn't put its app folder in the kit"
  grep -q "TINFOIL KIT UPDATE" "$L/setup-new-app.log" || fail "SETUP from a new download didn't update the kit on the drive"
  grep -E "^ +downloading " "$L/setup-new-app.log" && fail "SETUP downloaded something again after the app folder was replaced"
  [ -f "$kit/app/SETUP.command" ] || fail "the kit on the drive has no app folder after SETUP from a new download"
  just_the_kit "$kit"
  echo "$(find "$kit" -name '._*' | wc -l | tr -d ' ') ._ files on the drive"
  for f in "app/Open Tinfoil Kit.command" app/SETUP.command app/UNINSTALL.command app/kit app/tools/tinfoilkit-macos-arm64 \
    "Open Tinfoil Kit.command"; do
    xattr -p com.apple.quarantine "$kit/$f" > /dev/null 2>&1 && fail "$f is marked as from the internet"
  done
  [ -f "$vol/.metadata_never_index" ] || fail "no .metadata_never_index, so Spotlight would index the drive"
  if [ -d "$app" ]; then
    grep -q "open Tinfoil Kit, in Applications" "$L/setup-rest.log" || fail "SETUP didn't say to open the app in an outage"
  fi
  [ "$(cat "$support/last-kit" 2> /dev/null)" = "$kit" ] || fail "SETUP didn't note where the kit is, for the app"

  step "double-click Open Tinfoil Kit.command beside the kit's three folders: Terminal runs it, it starts the one in"
  echo "app, and that opens the page in Safari"
  open "$kit/Open Tinfoil Kit.command"
  python3 "$TESTS/drive.py" check 8888 8080 || { fail "the kit after a double-click"; kit_logs "$kit" tiles.log geocoder.log routing.log; }
  program_runs tinfoilkit-macos-arm64 "the kit on the drive"
  sleep 5
  screencapture -x "$SHOTS/mac-desktop.png" 2> /dev/null || echo "(no desktop screenshot here)"

  step "the page in WebKit, Safari's engine"
  KIT_BROWSER=webkit KIT_LIBRARY_PORT=8888 KIT_AI_PORT=8080 KIT_DATA_PORT=8095 KIT_TEST_SHOTS="$SHOTS/mac" \
    python3 "$TESTS/ui_test.py" > "$L/mac_ui.log" 2>&1 || fail "the page in WebKit (logs/mac_ui.log)"
  grep -E "^(FAIL|\(video only)" "$L/mac_ui.log"; tail -1 "$L/mac_ui.log"

  step "a second address on this Mac's loopback: kiwix-serve keeps only the last one, so it says 127.0.0.1 \"is not"
  echo "available on this system\". Double-click Open Tinfoil Kit.command: the library listens on ::1, and the"
  echo "kit's own program forwards 127.0.0.1 to it"
  stop_kit
  sudo ifconfig lo0 alias 127.0.0.2 up
  open "$kit/Open Tinfoil Kit.command"
  python3 "$TESTS/drive.py" check 8888 8080 || { fail "the kit with its library on ::1"; kit_logs "$kit" kiwix-serve.log; }
  grep -q "not available on this system: 127.0.0.1" "$kit/data/logs/kiwix-serve.log" ||
    fail "kiwix-serve took 127.0.0.1 anyway, so this didn't test the way around it"
  stop_kit
  sudo ifconfig lo0 -alias 127.0.0.2

  step "the app: it finds the kit on the drive and starts it, and quitting it stops the kit"
  stop_kit
  if [ -d "$app" ]; then
    rm -f "$support/last-kit"
    run_app mac_app.log 0 KIT_APP_ANSWERS=0
    python3 "$TESTS/drive.py" check 8888 8080 || fail "the kit the app started (logs/mac_app.log)"
    program_runs tinfoilkit-macos-arm64 "the kit the app started"
    sleep 3
    screencapture -x "$SHOTS/mac-app.png" 2> /dev/null
    kill -TERM "$APP_PID"
    for f in $(seq 20); do kill -0 "$APP_PID" 2> /dev/null || break; sleep 1; done
    kill -0 "$APP_PID" 2> /dev/null && { fail "the app didn't quit"; kill -9 "$APP_PID"; }
    grep -E "^(ASK|RAN):|Library:|AI:|Open:" "$L/mac_app.log"
    grep -q "^ASK:" "$L/mac_app.log" && fail "the app asked something, with one kit plugged in and ready"
    for f in 1 2 3 4 5; do curl -s -o /dev/null -m 2 http://127.0.0.1:8888/ || break; sleep 1; done
    curl -s -o /dev/null -m 2 http://127.0.0.1:8888/ && fail "quitting the app left the kit running"
    [ "$(cat "$support/last-kit" 2> /dev/null)" = "$kit" ] || fail "the app didn't note the kit it opened"
  fi

  step "using it from Finder leaves ._ files beside books and models; then eject"
  for f in "$kit"/downloads/library/*.zim "$kit"/downloads/models/*/*.gguf; do xattr -w org.tinfoilkit.opened 1 "$f"; done
  stop_kit
  cp -R "$kit/data/logs" "$L/mac-drive-logs" 2> /dev/null
  hdiutil detach "$disk" || hdiutil detach -force "$disk" || fail "eject"
  python3 "$TESTS/drive.py" vhd "$img" && mv "$img" "$W/drive.vhd"    # a VHD, so Windows can mount it

  step "the app, with that drive unplugged: it asks for it. Set Up a New Kit copies the kit out of the app and"
  echo "opens its SETUP in Terminal: here, SETUP --home-server with answers. This Mac; it moves the kit to"
  # shellcheck disable=SC2088  # the words a person reads, not a path
  echo "~/TinfoilKit, sets it up, shares it on the home network and has the Mac start it"
  kit="$HOME/TinfoilKit" agent="$HOME/Library/LaunchAgents/com.tinfoilkit.kit.plist"
  rm -rf "$kit"
  if [ -d "$app" ]; then
    src="$support/Setup/TinfoilKit"
    xattr -r -w com.apple.quarantine "0083;$(printf %x "$(date +%s)");Safari;" "$app/Contents/Resources/kit"    # as downloaded
    run_app mac_app_setup.log 30 KIT_APP_ANSWERS=2,1 KIT_APP_OPEN=echo || { fail "the app didn't quit after starting setup"; kill -9 "$APP_PID"; }
    grep -E "^(ASK|RAN):" "$L/mac_app_setup.log"
    grep -q "^ASK: Plug in the drive TINFOIL" "$L/mac_app_setup.log" || fail "the app didn't ask for the drive it opened last"
    grep -q "^$src/app/SETUP.command" "$L/mac_app_setup.log" || fail "the app didn't open its copy's SETUP (logs/mac_app_setup.log)"
    for f in SETUP.command "Open Tinfoil Kit.command"; do
      xattr -p com.apple.quarantine "$src/app/$f" > /dev/null 2>&1 && fail "the app's copy of $f is still marked as from the internet"
    done
    python3 "$TESTS/drive.py" kitjson "$src/app/kit.json"
  else
    download_kit "$src"
  fi
  # Answers: keep where it's for, this Mac, all of it even if that leaves less free than SETUP likes (it asks then),
  # download, close.
  much=""; [ "$("$src/app/kit" space "$kit" | cut -f1)" = tight ] && much="2\n"
  setup "$src" setup-mac.log "\n2\n${much}y\n\n" --home-server
  [ -d "$kit/downloads/models" ] || fail "the kit isn't set up in $kit"
  [ -d "$src" ] && fail "the copy SETUP started from is still in $src after the move"
  just_the_kit "$kit"
  tmutil isexcluded "$kit/downloads" | grep -q Excluded || fail "Time Machine would back up $kit/downloads"
  tmutil isexcluded "$kit/data" | grep -q Excluded && fail "Time Machine would skip your settings, in $kit/data"
  [ -f "$agent" ] || fail "no LaunchAgent, so the kit won't start with the Mac"

  step "the Mac started the kit by itself, shared on its network behind the access code"
  python3 "$TESTS/drive.py" check 8888 8080 || fail "the kit the Mac started"
  program_runs tinfoilkit-macos-arm64 "the kit the Mac started"
  share_check "$kit"
  cp -R "$kit/data/logs" "$L/mac-home-logs" 2> /dev/null

  step "UNINSTALL.command: type delete, and the kit, its downloads and its LaunchAgent are gone"
  terminal "$HOME" uninstall-mac.log 'delete\n\n' /bin/bash "$kit/app/UNINSTALL.command"
  tail -4 "$L/uninstall-mac.log"
  [ -e "$kit" ] && fail "$kit is still there after UNINSTALL"
  [ -e "$agent" ] && fail "UNINSTALL left the LaunchAgent, which would start a kit that's gone"
  [ -e "$support" ] && fail "UNINSTALL left the Mac app's note of where the kit is, in $support"
  [ -d "$app" ] && ! grep -q "drag it from Applications" "$L/uninstall-mac.log" && fail "UNINSTALL didn't say how to remove the app"
  sleep 2
  curl -s -o /dev/null -m 3 http://127.0.0.1:8888/ && fail "the kit is still running after UNINSTALL"
  stop_kit
  rm -rf "$app"
  kill "$mock"
}

linux() {
  local vhd="$W/drive.vhd" mnt="/media/$USER/TINFOIL" loop part kit img
  step "plug in the drive the Mac made, and mount it the way a Linux desktop (udisks2) does"
  loop=$(sudo losetup --find --show --partscan --sizelimit $(( $(stat -c %s "$vhd") - 512 )) "$vhd") || { fail "losetup"; return; }
  sleep 2
  part=$(sudo blkid -c /dev/null -o device -t TYPE=exfat | grep "^${loop}p" | head -1)
  [ -n "$part" ] || { fail "no exFAT partition on $loop"; sudo blkid; return; }
  sudo modprobe exfat 2> /dev/null
  sudo mkdir -p "$mnt"
  if ! sudo mount -t exfat -o "uid=$(id -u),gid=$(id -g),iocharset=utf8,errors=remount-ro" "$part" "$mnt"; then
    echo "(this kernel has no exFAT driver: using exfat-fuse)"
    { sudo apt-get install -y -qq exfat-fuse > /dev/null &&
      sudo mount.exfat-fuse -o "uid=$(id -u),gid=$(id -g),allow_other" "$part" "$mnt"; } || { fail "mount $part"; return; }
  fi
  kit="$mnt/TinfoilKit"
  echo "$(find "$kit/downloads/library" "$kit/downloads/models" -name '._*' | wc -l | tr -d ' ') ._ files beside books and models"
  just_the_kit "$kit"

  run_linux "this machine ($(. /etc/os-release && echo "$PRETTY_NAME"))" ""
  for img in ubuntu:24.04 ubuntu:22.04 debian:12 fedora:latest; do run_linux "$img" "$img"; done

  step "a home server, set up over SSH: ./kit share on, then ./kit autostart on (a systemd user service)"
  terminal "$kit/app" home-server.log "" bash -c './kit share on && ./kit autostart on' || fail "./kit share on, ./kit autostart on"
  tr -d '\r' < "$L/home-server.log"
  loginctl show-user "$USER" --property=Linger | grep -q yes || fail "the kit won't start at boot: lingering is off"
  python3 "$TESTS/drive.py" check 8888 8080 || fail "the kit systemd started"
  program_runs tinfoilkit-linux-x64 "the kit systemd started"
  share_check "$kit"
  cp -R "$kit/data/logs" "$L/linux-drive-logs" 2> /dev/null

  step "UNINSTALL.command --yes: the kit and its systemd service go, and nothing else on the drive"
  echo mine > "$mnt/keep-me.txt"
  terminal "$mnt" uninstall-linux.log "" bash "$kit/app/UNINSTALL.command" --yes
  tail -4 "$L/uninstall-linux.log"
  [ -e "$kit" ] && fail "the kit is still on the drive after UNINSTALL"
  [ -e "${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/tinfoil-kit.service" ] && fail "UNINSTALL left the systemd service"
  sleep 2
  curl -s -o /dev/null -m 3 http://127.0.0.1:8000/ && fail "the kit is still running after UNINSTALL"
  [ -f "$mnt/keep-me.txt" ] || fail "UNINSTALL deleted something else on the drive"
  [ -e "$mnt/.metadata_never_index" ] && fail "UNINSTALL left Spotlight switched off for the drive"
  sudo umount "$mnt" && sudo losetup -d "$loop"
}

run_linux() { # NAME IMAGE: start the kit from the drive, in a container when IMAGE is set, and check it
  local name="$1" img="$2" log prep ok=1
  log="$L/linux-$(printf '%s' "${img:-host}" | tr -c 'a-zA-Z0-9.' '-').log"
  step "$name: bash \"Open Tinfoil Kit.command\", beside the kit's three folders"
  if [ -z "$img" ]; then
    (cd "$kit" && exec bash "Open Tinfoil Kit.command" --no-browser > "$log" 2>&1) &
    window "bash \"Open Tinfoil Kit.command\"" tail -n +1 --pid=$! -f "$log"
  else
    # Libraries a desktop install has and these bare images don't, plus the package GUIDE.md tells Fedora users
    # to add (Fedora 45 moved to OpenSSL 4; llama.cpp's Linux build needs 3). Not curl: Ubuntu's desktop lacks it.
    case "$img" in
      fedora*) prep="dnf install -y -q libgomp vulkan-loader openssl3-libs procps-ng findutils gawk > /dev/null" ;;
      *) prep="apt-get update -qq && apt-get install -y -qq libgomp1 libvulkan1 procps > /dev/null" ;;
    esac
    docker run -d --name kit --network host -v "$mnt:/media/user/TINFOIL" -w /media/user/TINFOIL/TinfoilKit \
      "$img" bash -c "$prep && exec bash \"Open Tinfoil Kit.command\" --no-browser" > /dev/null
    window "$name: bash \"Open Tinfoil Kit.command\"" docker logs -f kit
  fi
  python3 "$TESTS/drive.py" check 8888 8080 || { fail "$name"; ok=0; }
  program_runs tinfoilkit-linux-x64 "$name" ${img:+kit}
  if [ -z "$img" ] && [ "$ok" = 1 ]; then
    step "the page in Chrome"
    if python3 -c "import playwright" 2> /dev/null; then
      KIT_BROWSER="$(command -v google-chrome > /dev/null && echo chrome || echo chromium)" KIT_LIBRARY_PORT=8888 \
        KIT_AI_PORT=8080 KIT_DATA_PORT=8095 KIT_TEST_SHOTS="$SHOTS/linux" python3 "$TESTS/ui_test.py" > "$L/linux_ui.log" 2>&1 ||
        fail "the page in Chrome (logs/linux_ui.log)"
      grep -E "^(FAIL|\(video only)" "$L/linux_ui.log"; tail -1 "$L/linux_ui.log"
    else
      echo "(no Playwright here, so the page isn't checked)"
    fi
  fi
  if [ -n "$img" ]; then docker logs kit > "$log" 2>&1; docker rm -f kit > /dev/null; else stop_kit; fi
  if [ "$ok" = 1 ]; then grep -E "Library:|AI:|!" "$log"; else tail -25 "$log"; kit_logs "$kit" tiles.log geocoder.log routing.log; fi
}

case "${1:-}" in
  mac) mac ;;
  linux) linux ;;
  *) sed -n '2,10p' "$0"; exit 2 ;;
esac
echo
[ "$FAILS" -eq 0 ] || { echo "DRIVE TEST: $FAILS FAILED (logs in $L)"; exit 1; }
echo "DRIVE TEST PASSED"
