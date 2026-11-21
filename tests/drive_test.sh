#!/bin/bash
# The drive test: the kit on a real exFAT disk, set up on a Mac, then plugged into Windows and Linux.
# CI runs it nightly and on demand (.github/workflows/drive.yml). Fixtures: tests/build_fixtures.sh drive.
#   tests/drive_test.sh mac     erase a disk image as exFAT the way Disk Utility does, copy the kit on as
#                               Download ZIP leaves it, run SETUP against the mock internet, double-click
#                               START-HERE, check the page in WebKit, eject. Leaves tests/work/drive.vhd.
#   tests/drive_test.sh linux   mount that drive the way a Linux desktop does, start the kit on this
#                               machine (Ubuntu 24.04 in CI), then in Ubuntu 22.04, Debian 12 and Fedora.
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

mac() {
  local img="$W/drive.img" vol=/Volumes/TINFOIL disk kit src mock f
  python3 "$TESTS/mock_remote.py" 19000 > "$L/mock_remote.log" 2>&1 &
  mock=$!

  step "a 2 GB disk, erased as exFAT the way Disk Utility does"
  hdiutil detach "$vol" > /dev/null 2>&1
  rm -f "$img" "$W/drive.vhd" && mkfile -n 2g "$img"
  disk=$(hdiutil attach -imagekey diskimage-class=CRawDiskImage -nomount "$img" | awk 'NR == 1 {print $1}')
  diskutil eraseDisk ExFAT TINFOIL GPT "$disk" || { fail "erase $disk"; kill "$mock"; return; }

  step "the kit as Download ZIP leaves it, every file marked as from the internet, copied onto the drive"
  src="$W/download/TinfoilKit" kit="$vol/TinfoilKit"
  rm -rf "$W/download" && mkdir -p "$src"
  git -C "$ROOT" archive HEAD | tar -xf - -C "$src"
  xattr -r -w com.apple.quarantine "0083;$(printf %x "$(date +%s)");Safari;" "$src"
  ditto "$src" "$kit"    # exFAT has no extended attributes: macOS keeps the marks in ._ files
  python3 - "$TESTS/drive_kit.json" "$ROOT/kit.json" > "$kit/kit.json" <<'EOF'
import json, sys
t, k = (json.load(open(p)) for p in sys.argv[1:3])
t["runtimes"] = [r for r in k["runtimes"] if not r.get("requires")]    # the real Mac, Windows and Linux programs
t["models"] = [m for m in t["models"] if m["id"] == "Tiny"]
t["library"] = [z for z in t["library"] if z["zim"] in ("testmed_en_all_maxi", "testsurvival_en")]
t["settings"].update(library_port=8888, ai_port=8080)    # the ports START-HERE-Windows.bat uses
print(json.dumps(t, indent=2))
EOF
  echo "$(find "$kit" -name '._*' | wc -l | tr -d ' ') ._ files on the drive"

  step "SETUP.command against the mock internet, with a stock Mac's PATH and bash"
  (cd "$kit" && . "$TESTS/env.sh" && printf 'y\nn\n\n' | PATH=/usr/bin:/bin:/usr/sbin:/sbin /bin/bash SETUP.command) > "$L/setup.log" 2>&1
  echo "exit $?"
  grep -E "PASS|FAIL|All set|Problems|^  - " "$L/setup.log" | tail -20
  grep -q "All set" "$L/setup.log" || fail "SETUP didn't end with All set (logs/setup.log)"
  for f in START-HERE.command SETUP.command tools/launch.sh; do
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
  for img in ubuntu:22.04 debian:12 fedora:latest; do run_linux "$img" "$img"; done
  cp -R "$kit/logs" "$L/linux-drive-logs" 2> /dev/null
  sudo umount "$mnt" && sudo losetup -d "$loop"
}

run_linux() { # NAME IMAGE: start the kit from the drive, in a container when IMAGE is set, and check it
  local name="$1" img="$2" log prep
  log="$L/linux-$(printf '%s' "${img:-host}" | tr -c 'a-zA-Z0-9.' '-').log"
  step "$name: bash START-HERE.command"
  if [ -z "$img" ]; then
    (cd "$kit" && exec bash START-HERE.command --no-browser > "$log" 2>&1) &
  else
    # Libraries a desktop install has and these bare images don't. Not curl: Ubuntu's desktop doesn't ship it.
    case "$img" in
      fedora*) prep="dnf install -y -q libgomp vulkan-loader procps-ng findutils gawk > /dev/null" ;;
      *) prep="apt-get update -qq && apt-get install -y -qq libgomp1 libvulkan1 procps > /dev/null" ;;
    esac
    docker run -d --name kit --network host -v "$mnt:/media/user/TINFOIL" -w /media/user/TINFOIL/TinfoilKit \
      "$img" bash -c "$prep && exec bash START-HERE.command --no-browser" > /dev/null
  fi
  python3 "$TESTS/drive.py" check 8888 8080 || fail "$name"
  if [ -n "$img" ]; then docker logs kit > "$log" 2>&1; docker rm -f kit > /dev/null; else stop_kit; fi
  grep -E "Library:|AI:|!" "$log"
}

case "${1:-}" in
  mac) mac ;;
  linux) linux ;;
  *) sed -n '2,9p' "$0"; exit 2 ;;
esac
echo
[ "$FAILS" -eq 0 ] || { echo "DRIVE TEST: $FAILS FAILED (logs in $L)"; exit 1; }
echo "DRIVE TEST PASSED"
