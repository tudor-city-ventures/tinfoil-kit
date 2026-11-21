#!/bin/bash
# Double-click me (macOS) to fill the drive, or to refresh it every 2-3 months.
# Same as ./kit sync then ./kit test, with checks and plain-English prompts for first-timers.
cd "$(dirname "$0")" || exit 1
KIT="$(pwd)"

say() { printf '\n%s\n' "$*"; }
ask() { printf '\n%s [Y/n] ' "$1"; read -r a; case "$a" in ""|y|Y|yes|Yes) return 0;; esac; return 1; }
finish() { printf '\nPress Return to close this window.'; read -r _; exit "${1:-0}"; }
# The list of what failed, from the newest sync log: the sync's own copy has scrolled far up by now.
problems() {
  log="$(ls -t logs/sync-*.log 2>/dev/null | head -1)"
  [ -n "$log" ] && awk '/^===== sync started/ {buf = ""; on = 0} /^Problems/ {on = 1}
                        on && /^  - / {buf = buf $0 "\n"} /^Re-run/ {on = 0} END {printf "%s", buf}' "$log"
}

say "TINFOIL KIT SETUP"
echo "This downloads the AI models, library and maps onto this drive, then checks that they all start."
echo "The first time takes a few hours and about 300 GB. Later runs only download what changed."

if [ "$(uname -s)" = "Darwin" ]; then
  [ "$(uname -m)" = "arm64" ] || say "Note: this Mac doesn't have Apple Silicon (M1 or newer). The kit is built for those and may not run here."
  case "$KIT" in
    /Volumes/*)
      vol="${KIT#/Volumes/}"
      fs="$(diskutil info "/Volumes/${vol%%/*}" 2>/dev/null | awk -F: '/File System Personality/ {gsub(/^ +/, "", $2); print $2}')" ;;
    *) say "Note: this folder is on the Mac's own disk, not an external drive ($KIT)."
       echo "That works, but the point of the kit is a drive you can grab. Copy this folder to the drive and run SETUP there."
       ask "Continue here anyway?" || finish ;;
  esac
  case "$fs" in
    *ExFAT*|*exFAT*) ;;
    *FAT*|*MS-DOS*)
      say "This drive is formatted as $fs, which can't hold files over 4 GB. The AI models and books are bigger."
      echo "Reformat it as exFAT in Disk Utility (this erases the drive), copy this folder back, and run SETUP again."
      finish 1 ;;
    *NTFS*|*Windows*)
      say "This drive is formatted as $fs. Macs can read it but not write to it."
      echo "Reformat it as exFAT in Disk Utility (this erases the drive), copy this folder back, and run SETUP again."
      finish 1 ;;
  esac
fi

if ! ( : > .kit-write-test ) 2>/dev/null; then
  say "Can't save anything on this drive. It may be locked or read-only."
  echo "Check the drive in Disk Utility (First Aid), or copy this folder to another drive, and run SETUP again."
  finish 1
fi
rm -f .kit-write-test

if ! command -v python3 >/dev/null 2>&1 || ! python3 -c "" >/dev/null 2>&1; then
  say "The kit needs Apple's free Command Line Tools (for python3). A window will ask to install them."
  xcode-select --install >/dev/null 2>&1
  echo "When that install finishes, double-click SETUP again."
  finish 1
fi

say "Step 1 of 2: download. Here's what will change:"
./kit plan || finish 1
ask "Start downloading? Keep the Mac plugged in. It's fine to stop (Ctrl-C) and run SETUP again later; downloads resume." || finish
# Keep the Mac awake (not the screen) until the download and checks are done. caffeinate runs in the
# background so that Ctrl-C reaches the sync, which saves its progress, and this script carries on.
awake=""
if command -v caffeinate >/dev/null 2>&1; then caffeinate -i -w $$ & awake=$!; fi
./kit sync --yes
rc=$?
if [ $rc -eq 130 ]; then
  say "Stopped. Everything downloaded so far is kept. Double-click SETUP again to carry on where it left off."
  finish 130
fi

say "Step 2 of 2: start everything offline and check that it answers."
./kit test
tested=$?
[ -n "$awake" ] && kill "$awake" 2>/dev/null
[ $tested -eq 130 ] && { say "Stopped."; finish 130; }
if [ $tested -eq 0 ] && [ $rc -eq 0 ]; then
  say "All set. To use the kit, double-click START-HERE.command (no internet needed)."
  ask "Open it now?" && exec bash START-HERE.command
  finish
fi
if [ $tested -eq 0 ]; then
  say "Everything on the drive works, but some downloads didn't finish:"
  problems
  echo
  echo "You can use the kit now: double-click START-HERE.command. Double-click SETUP again later to retry the rest."
  finish 1
fi
say "Some checks failed. The messages above say which; logs are in the logs folder."
[ $rc -eq 0 ] || problems
echo "Running SETUP again often fixes a download that was cut off."
finish 1
