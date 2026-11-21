#!/bin/bash
# Double-click me (macOS) to fill the drive, or to refresh it every 2-3 months.
# Same as ./kit sync then ./kit test, with checks and plain-English prompts for first-timers.
cd "$(dirname "$0")" || exit 1
KIT="$(pwd)"

say() { printf '\n%s\n' "$*"; }
ask() { printf '\n%s [Y/n] ' "$1"; read -r a; case "$a" in ""|y|Y|yes|Yes) return 0;; esac; return 1; }
finish() { printf '\nPress Return to close this window.'; read -r _; exit "${1:-0}"; }

say "TINFOIL KIT SETUP"
echo "This downloads the AI models, library and maps onto this drive, then checks that they all start."
echo "The first time takes a few hours and about 300 GB. Later runs only download what changed."

if [ "$(uname -s)" = "Darwin" ]; then
  [ "$(uname -m)" = "arm64" ] || say "Note: this Mac doesn't have Apple Silicon (M1 or newer). The kit is built for those and may not run here."
  case "$KIT" in
    /Volumes/*) ;;
    *) say "Note: this folder is on the Mac's own disk, not an external drive ($KIT)."
       echo "That works, but the point of the kit is a drive you can grab. Copy this folder to the drive and run SETUP there."
       ask "Continue here anyway?" || finish ;;
  esac
  fs="$(diskutil info "$KIT" 2>/dev/null | awk -F: '/File System Personality/ {gsub(/^ +/, "", $2); print $2}')"
  case "$fs" in
    ""|*ExFAT*|*exFAT*|*APFS*) ;;
    *) say "This drive is formatted as $fs. Use exFAT (works on Windows and Linux too) or APFS (Macs only)."
       echo "Reformat it in Disk Utility, copy this folder back, and run SETUP again."
       finish 1 ;;
  esac
fi

if ! command -v python3 >/dev/null 2>&1 || ! python3 -c "" >/dev/null 2>&1; then
  say "The kit needs Apple's free Command Line Tools (for python3). A window will ask to install them."
  xcode-select --install >/dev/null 2>&1
  echo "When that install finishes, double-click SETUP again."
  finish 1
fi

say "Step 1 of 2: download. Here's what will change:"
./kit plan || finish 1
ask "Start downloading? Keep the Mac plugged in. It's fine to stop and run SETUP again later; downloads resume." || finish
# caffeinate keeps the Mac awake (not the screen) for the length of the sync.
if command -v caffeinate >/dev/null 2>&1; then caffeinate -i ./kit sync --yes; else ./kit sync --yes; fi

say "Step 2 of 2: start everything offline and check that it answers."
if ./kit test; then
  say "All set. To use the kit, double-click START-HERE.command (no internet needed)."
  ask "Open it now?" && exec bash START-HERE.command
  finish
fi
say "Some checks failed. The messages above say which; logs are in the logs folder."
echo "Running SETUP again often fixes a download that was cut off."
finish 1
