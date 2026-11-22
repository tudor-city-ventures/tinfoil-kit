#!/bin/bash
# Double-click me (macOS) to remove Tinfoil Kit and everything it downloaded. Linux: bash UNINSTALL.command
# It says what it will delete and asks first. --yes skips the question, for scripts and AI agents.
# The whole script is one { } block, so bash reads all of it before it deletes this file.
{
cd "$(dirname "$0")" || exit 1
KIT="$(pwd)"
YES=0; [ "${1:-}" = "--yes" ] && YES=1
THIS="this computer"; [ "$(uname -s)" = Darwin ] && THIS="this Mac"
say() { printf '\n%s\n' "$*"; }
finish() { [ $YES = 1 ] || { printf '\nPress Return to close this window.'; read -r _; }; exit "${1:-0}"; }
dev_of() { stat -c %d "$1" 2>/dev/null || stat -f %d "$1" 2>/dev/null; }    # Linux, then macOS

say "REMOVE TINFOIL KIT"
# This deletes the folder it's in, so make sure that folder is a kit, and not a home folder or a whole drive.
if [ ! -f "$KIT/kit" ] || [ ! -f "$KIT/tools/kit.py" ] || [ "$KIT" = "$HOME" ] || [ "$KIT" = / ]; then
  echo "This folder ($KIT) doesn't look like a Tinfoil Kit, so nothing was deleted."
  finish 1
fi
if [ "$(dev_of "$KIT")" != "$(dev_of "$KIT/..")" ]; then
  echo "The kit fills this whole drive ($KIT), and deleting it would delete everything on the drive."
  echo "To start over, erase the drive in Disk Utility instead."
  finish 1
fi

drive=""
if [ "$(dev_of "$KIT")" != "$(dev_of "$HOME")" ]; then
  case "$KIT" in
    /Volumes/*) drive="${KIT#/Volumes/}"; drive="${drive%%/*}" ;;
    /run/media/*/*) drive="${KIT#/run/media/*/}"; drive="${drive%%/*}" ;;
    /media/*/*) drive="${KIT#/media/*/}"; drive="${drive%%/*}" ;;
    *) drive="${KIT%/*}"; drive="${drive##*/}" ;;
  esac
fi
echo "Adding up what's here..."
size="$(du -sk "$KIT" 2>/dev/null | awk '{g = $1 * 1024 / 1e9; if (g < 1) print "under 1 GB"; else printf "%.0f GB\n", g}')"
if [ -n "$drive" ]; then where="from the drive $drive"; else where="from $THIS"; fi
echo
echo "This deletes Tinfoil Kit $where: the folder $KIT,"
echo "with the AI models, books, maps and programs it downloaded ($size in all)."
echo "It can't be undone. The files don't go to the Trash."
[ -n "$drive" ] && echo "Nothing else on the drive is touched."
if [ $YES = 0 ]; then
  printf '\nTo delete it, type delete and press Return. To keep it, just press Return: '
  read -r answer
  case "$answer" in delete|Delete|DELETE) ;; *) say "Kept. Nothing was deleted."; finish 0 ;; esac
fi

# A home server starts the kit with the computer (./kit autostart): undo that, which also stops it.
./kit autostart off >/dev/null 2>&1
# Stop the kit if it's running (its programs run from its bin folder), so nothing holds its files open.
pids="$(ps -axo pid=,command= 2>/dev/null | awk -v k="$KIT/bin/" 'index($0, k) {print $1}')"
if [ -n "$pids" ]; then
  echo "Stopping the kit, which is running..."
  # shellcheck disable=SC2086
  kill $pids 2>/dev/null; sleep 2
fi
echo "Deleting... (a few hundred GB can take a minute)"
cd / || exit 1
rm -rf "$KIT" 2>/dev/null
if [ -e "$KIT" ]; then
  say "Some files couldn't be deleted. What's left is in $KIT."
  echo "If Terminal said \"Operation not permitted\", open System Settings > Privacy & Security > Files and Folders,"
  echo "turn on Removable Volumes under Terminal, and run this again. Or drag the folder to the Trash."
  finish 1
fi
# The kit told Spotlight to skip the drive it's at the top of (it would index hundreds of GB of downloads). Undo that.
top="${KIT%/*}"
[ -n "$drive" ] && [ "$(dev_of "$top")" != "$(dev_of "$top/..")" ] && rm -f "$top/.metadata_never_index"
say "Done. Tinfoil Kit is gone, and $size is free again."
[ -n "$drive" ] && echo "You can eject the drive now."
finish 0
}
