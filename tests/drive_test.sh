#!/bin/bash
# The drive test: the kit on a real exFAT disk, set up on a Mac, then plugged into Windows and Linux.
# CI runs it nightly and on demand (.github/workflows/drive.yml). Fixtures: tests/build_fixtures.sh drive.
#   tests/drive_test.sh mac     erase a disk image as exFAT the way Disk Utility does, unzip the kit as
#                               Download ZIP leaves it, run its SETUP against the mock internet and pick the
#                               drive, double-click START-HERE, check the page in WebKit, eject. Leaves
#                               tests/work/drive.vhd. Then set the kit up on this Mac (~/TinfoilKit) as a home
#                               server (SETUP --home-server), check that the Mac started it and that it's shared
#                               behind the access code, and remove it with UNINSTALL.
#   tests/drive_test.sh linux   mount that drive the way a Linux desktop does, start the kit on this
#                               machine (the newest Ubuntu in CI), then in Ubuntu 24.04 and 22.04, Debian 12
#                               and Fedora. Then make it a home server (./kit share on, ./kit autostart on) and
#                               check it the same way, and remove it from the drive with UNINSTALL.
# Windows: the workflow mounts drive.vhd and double-clicks START-HERE-Windows.bat.
set -u
TESTS="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$TESTS")"
export KIT_TEST_WORK="${KIT_TEST_WORK:-$TESTS/work}"
W="$KIT_TEST_WORK" L="$KIT_TEST_WORK/logs" SHOTS="$KIT_TEST_WORK/shots"
mkdir -p "$L" "$SHOTS"
FAILS=0
fail() { echo "FAIL: $*"; FAILS=$((FAILS + 1)); }
step() { echo; echo "=== $*"; }
stop_kit() { pkill -f tools/launch.sh; sleep 1; pkill -f llama-server; pkill -f kiwix-serve; sleep 1; } 2>/dev/null

# The kit as Safari leaves a Download ZIP: unzipped into tinfoilkit-main, every file marked as from the internet.
# Its kit.json is the test kit, put in the folder the way one from the website's builder goes in.
download_kit() { # DIR
  rm -rf "$1" && mkdir -p "$1"
  git -C "$ROOT" archive HEAD | tar -xf - -C "$1"
  python3 "$TESTS/drive.py" kitjson "$1/kit.json"
  xattr -r -w com.apple.quarantine "0083;$(printf %x "$(date +%s)");Safari;" "$1"
}
# Where SETUP lists a drive: its line in ./kit drives (folder, format, GB free, problem, name).
drive_number() { # KIT NAME
  "$1/kit" drives | awk -F'\t' -v n="$2" '$5 == n {print NR; exit}'
}
# SETUP with the mock internet, a stock Mac's PATH and bash, and these answers.
setup() { # FOLDER LOG ANSWERS [SETUP'S OPTIONS]
  local dir="$1" log="$2" answers="$3"; shift 3
  (cd "$dir" && . "$TESTS/env.sh" && printf '%b' "$answers" | PATH=/usr/bin:/bin:/usr/sbin:/sbin /bin/bash SETUP.command "$@") \
    > "$L/$log" 2>&1
  echo "exit $?"
  grep -E "PASS|FAIL|All set|Moved|Problems|^  - |^  [0-9]  |home network|Access code|starts" "$L/$log" | tail -24
  grep -q "All set" "$L/$log" || fail "SETUP didn't end with All set (logs/$log)"
}
# A home server's kit, checked the way a phone on the home network finds it: at the address and with the access
# code that ./kit share shows. The servers behind the gate mustn't answer at that address themselves.
share_check() { # KIT
  local out addr code
  out="$("$1/kit" share 2>&1)"
  echo "$out"
  addr="$(echo "$out" | sed -n 's/.*open \(http:[^ ]*\) on a phone.*/\1/p' | head -1)"
  code="$(echo "$out" | sed -n 's/.*Access code: //p' | tr -d ' ' | head -1)"
  [ -n "$addr" ] && [ -n "$code" ] || { fail "./kit share showed no address or access code"; return; }
  python3 "$TESTS/drive.py" share "$addr" "$code" 8888 8080 || fail "the kit shared on the home network"
}

mac() {
  local img="$W/drive.img" vol=/Volumes/TINFOIL disk kit src mock f much
  local py="$HOME/Library/Application Support/TinfoilKit"    # the Python SETUP gets for a Mac without one
  python3 "$TESTS/mock_remote.py" 19000 > "$L/mock_remote.log" 2>&1 &
  mock=$!

  step "a 2 GB disk, erased as exFAT the way Disk Utility does"
  hdiutil detach "$vol" > /dev/null 2>&1
  rm -f "$img" "$W/drive.vhd" && mkfile -n 2g "$img"
  disk=$(hdiutil attach -imagekey diskimage-class=CRawDiskImage -nomount "$img" | awk 'NR == 1 {print $1}')
  diskutil eraseDisk ExFAT TINFOIL GPT "$disk" || { fail "erase $disk"; kill "$mock"; return; }

  step "SETUP.command in the unzipped download, as on a Mac without Python: it gets the kit's own (the real"
  echo "build, from the mock internet); pick the drive; it moves the kit there and sets it up"
  src="$W/Downloads/tinfoilkit-main" kit="$vol/TinfoilKit"
  rm -rf "$py"
  download_kit "$src"
  n="$(drive_number "$src" TINFOIL)"
  echo "SETUP lists TINFOIL as drive ${n:-(not at all)}"
  # Answers: keep where it's for, an external drive, TINFOIL, start downloading, don't open the kit, close.
  KIT_OWN_PYTHON=1 setup "$src" setup.log "\n1\n${n:-1}\ny\nn\n\n"
  "$py/python/bin/python3" --version || fail "SETUP didn't get the kit's own Python"
  [ -d "$kit/models" ] || fail "the kit isn't set up on the drive, at $kit"
  [ -d "$src" ] && fail "the download is still in $src after the move"
  echo "$(find "$kit" -name '._*' | wc -l | tr -d ' ') ._ files on the drive"
  for f in START-HERE.command SETUP.command UNINSTALL.command tools/launch.sh; do
    xattr -p com.apple.quarantine "$kit/$f" > /dev/null 2>&1 && fail "$f is still marked as from the internet"
  done
  [ -f "$vol/.metadata_never_index" ] || fail "no .metadata_never_index, so Spotlight would index the drive"

  step "double-click START-HERE.command: Terminal runs it, and it opens the page in Safari"
  open "$kit/START-HERE.command"
  python3 "$TESTS/drive.py" check 8888 8080 || fail "the kit after a double-click"
  sleep 5
  screencapture -x "$SHOTS/mac-desktop.png" 2> /dev/null || echo "(no desktop screenshot here)"

  step "the page in WebKit, Safari's engine"
  KIT_BROWSER=webkit KIT_LIBRARY_PORT=8888 KIT_AI_PORT=8080 KIT_TEST_SHOTS="$SHOTS/mac" \
    python3 "$TESTS/ui_test.py" > "$L/mac_ui.log" 2>&1 || fail "the page in WebKit (logs/mac_ui.log)"
  grep -E "^FAIL" "$L/mac_ui.log"; tail -1 "$L/mac_ui.log"

  step "using it from Finder leaves ._ files beside books and models; then eject"
  for f in "$kit"/library/*.zim "$kit"/models/*/*.gguf; do xattr -w org.tinfoilkit.opened 1 "$f"; done
  stop_kit
  cp -R "$kit/logs" "$L/mac-drive-logs" 2> /dev/null
  hdiutil detach "$disk" || hdiutil detach -force "$disk" || fail "eject"
  python3 "$TESTS/drive.py" vhd "$img" && mv "$img" "$W/drive.vhd"    # a VHD, so Windows can mount it

  step "SETUP.command --home-server in a new download: this Mac; it moves the kit to ~/TinfoilKit, sets it up,"
  echo "shares it on the home network and has the Mac start it"
  kit="$HOME/TinfoilKit" agent="$HOME/Library/LaunchAgents/com.tinfoilkit.kit.plist"
  rm -rf "$kit"
  download_kit "$src"
  # Answers: keep where it's for, this Mac, all of it even if that leaves less free than SETUP likes (it asks then),
  # download, close.
  much=""; [ "$("$src/kit" space "$kit" | cut -f1)" = tight ] && much="2\n"
  setup "$src" setup-mac.log "\n2\n${much}y\n\n" --home-server
  [ -d "$kit/models" ] || fail "the kit isn't set up in $kit"
  [ -d "$src" ] && fail "the download is still in $src after the move"
  tmutil isexcluded "$kit" | grep -q Excluded || fail "Time Machine would back up $kit"
  [ -f "$agent" ] || fail "no LaunchAgent, so the kit won't start with the Mac"

  step "the Mac started the kit by itself, shared on its network behind the access code"
  python3 "$TESTS/drive.py" check 8888 8080 || fail "the kit the Mac started"
  share_check "$kit"
  cp -R "$kit/logs" "$L/mac-home-logs" 2> /dev/null

  step "UNINSTALL.command: type delete, and the kit, its downloads and its LaunchAgent are gone"
  printf 'delete\n\n' | /bin/bash "$kit/UNINSTALL.command" > "$L/uninstall-mac.log" 2>&1
  tail -4 "$L/uninstall-mac.log"
  [ -e "$kit" ] && fail "$kit is still there after UNINSTALL"
  [ -e "$agent" ] && fail "UNINSTALL left the LaunchAgent, which would start a kit that's gone"
  [ -e "$py" ] && fail "UNINSTALL left the kit's own Python in $py"
  sleep 2
  curl -s -o /dev/null -m 3 http://127.0.0.1:8888/ && fail "the kit is still running after UNINSTALL"
  stop_kit
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
  echo "$(find "$kit/library" "$kit/models" -name '._*' | wc -l | tr -d ' ') ._ files beside books and models"

  run_linux "this machine ($(. /etc/os-release && echo "$PRETTY_NAME"))" ""
  for img in ubuntu:24.04 ubuntu:22.04 debian:12 fedora:latest; do run_linux "$img" "$img"; done

  step "a home server, set up over SSH: ./kit share on, then ./kit autostart on (a systemd user service)"
  { "$kit/kit" share on && "$kit/kit" autostart on; } > "$L/home-server.log" 2>&1 || fail "./kit share on, ./kit autostart on"
  cat "$L/home-server.log"
  loginctl show-user "$USER" --property=Linger | grep -q yes || fail "the kit won't start at boot: lingering is off"
  python3 "$TESTS/drive.py" check 8888 8080 || fail "the kit systemd started"
  share_check "$kit"
  cp -R "$kit/logs" "$L/linux-drive-logs" 2> /dev/null

  step "UNINSTALL.command --yes: the kit and its systemd service go, and nothing else on the drive"
  echo mine > "$mnt/keep-me.txt"
  bash "$kit/UNINSTALL.command" --yes > "$L/uninstall-linux.log" 2>&1
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
  step "$name: bash START-HERE.command"
  if [ -z "$img" ]; then
    (cd "$kit" && exec bash START-HERE.command --no-browser > "$log" 2>&1) &
  else
    # Libraries a desktop install has and these bare images don't, plus the package GUIDE.md tells Fedora users
    # to add (Fedora 45 moved to OpenSSL 4; llama.cpp's Linux build needs 3). Not curl: Ubuntu's desktop lacks it.
    case "$img" in
      fedora*) prep="dnf install -y -q libgomp vulkan-loader openssl3-libs procps-ng findutils gawk > /dev/null" ;;
      *) prep="apt-get update -qq && apt-get install -y -qq libgomp1 libvulkan1 procps > /dev/null" ;;
    esac
    docker run -d --name kit --network host -v "$mnt:/media/user/TINFOIL" -w /media/user/TINFOIL/TinfoilKit \
      "$img" bash -c "$prep && exec bash START-HERE.command --no-browser" > /dev/null
  fi
  python3 "$TESTS/drive.py" check 8888 8080 || { fail "$name"; ok=0; }
  if [ -n "$img" ]; then docker logs kit > "$log" 2>&1; docker rm -f kit > /dev/null; else stop_kit; fi
  if [ "$ok" = 1 ]; then grep -E "Library:|AI:|!" "$log"; else tail -25 "$log"; fi
}

case "${1:-}" in
  mac) mac ;;
  linux) linux ;;
  *) sed -n '2,10p' "$0"; exit 2 ;;
esac
echo
[ "$FAILS" -eq 0 ] || { echo "DRIVE TEST: $FAILS FAILED (logs in $L)"; exit 1; }
echo "DRIVE TEST PASSED"
