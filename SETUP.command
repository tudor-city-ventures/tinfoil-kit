#!/bin/bash
# Double-click me (macOS) to set up Tinfoil Kit, and again every 2-3 months to refresh it. Linux: bash SETUP.command
# The first time, it asks whether the kit goes on an external drive or on this Mac, and moves it there.
# Then it's ./kit update, ./kit sync and ./kit test, with checks and plain-English prompts for first-timers.
# The whole script is one { } block, so bash reads all of it before running any: ./kit update can replace this
# file, and the first run moves it.
{
cd "$(dirname "$0")" || exit 1
KIT="$(pwd)"
NAME=TinfoilKit    # the kit's folder: at the top of a drive, or in the home folder
MAC=0; [ "$(uname -s)" = Darwin ] && MAC=1
THIS="this computer"; [ $MAC = 1 ] && THIS="this Mac"
ROOM=50            # GB the computer's own disk keeps free (kit.json: keep_free_gb_this_computer)

say() { printf '\n%s\n' "$*"; }
ask() { printf '\n%s [Y/n] ' "$1"; read -r a; case "$a" in ""|y|Y|yes|Yes) return 0;; esac; return 1; }
# A number from 1 to $2, in $pick. Stops if the window has nothing more to read, rather than asking forever.
choose() { while :; do printf '\n%s ' "$1"; read -r pick || exit 1
             case "$pick" in ""|*[!0-9]*) ;; *) [ "$pick" -ge 1 ] && [ "$pick" -le "$2" ] && return 0 ;; esac
             echo "Type a number from 1 to $2, then press Return."; done; }
finish() { printf '\a\nPress Return to close this window.'; read -r _; exit "${1:-0}"; }
gb() { awk -v g="$1" 'BEGIN { if (g >= 1000) printf "%.1f TB", g / 1000; else printf "%d GB", g }'; }
free_gb() { df -Pk "$1" 2>/dev/null | awk 'NR == 2 {print int($4 * 1024 / 1e9)}'; }
dev_of() { stat -c %d "$1" 2>/dev/null || stat -f %d "$1" 2>/dev/null; }    # Linux, then macOS
same_disk() { [ "$(dev_of "$1")" = "$(dev_of "$2")" ]; }
on_this_mac() { same_disk "$KIT" "$HOME"; }
format_of() { # a drive's format, as macOS (or Linux) names it
  if [ $MAC = 1 ]; then diskutil info "$1" 2>/dev/null | awk -F': *' '/File System Personality/ {print $2; exit}'
  else stat -f -c %T "$1" 2>/dev/null; fi
}
problem_of() { # why the kit can't live on a drive of this format, if it can't
  case "$1" in
    *ExFAT*|*exFAT*|exfat) ;;
    *FAT*|*MS-DOS*|msdos|vfat) echo "it's formatted as $1, which can't hold files over 4 GB, and the AI models and books are bigger" ;;
    *NTFS*|*Windows*|ntfs*) echo "it's formatted as $1, which a Mac can read but can't save to" ;;
  esac
}
drive_name() { # the name of the drive a folder is on
  local p="$1"
  case "$p" in
    /Volumes/*) p="${p#/Volumes/}" ;;
    /run/media/*/*) p="${p#/run/media/*/}" ;;
    /media/*/*) p="${p#/media/*/}" ;;
    "${KIT_DRIVES:-/nowhere}"/*) p="${p#"$KIT_DRIVES"/}" ;;
  esac
  echo "${p%%/*}"
}
where_kit() { if on_this_mac; then echo "on $THIS"; else echo "on the drive $(drive_name "$KIT")"; fi; }
on_battery() { [ $MAC = 1 ] && pmset -g batt 2>/dev/null | grep -q "Battery Power"; }
# The list of what failed, from the newest sync log: the sync's own copy has scrolled far up by now.
problems() {
  log="$(ls -t logs/sync-*.log 2>/dev/null | head -1)"
  [ -n "$log" ] && awk '/^===== sync started/ {buf = ""; on = 0} /^Problems/ {on = 1}
                        on && /^  - / {buf = buf $0 "\n"} /^Re-run/ {on = 0} END {printf "%s", buf}' "$log"
}

# The kit's tools run on python3, which comes with Apple's free Command Line Tools. Wait for the install
# instead of making the person find SETUP and start it again.
need_python() {
  python3 -c "" >/dev/null 2>&1 && return
  if [ $MAC = 0 ]; then
    say "The kit needs python3 3.9 or newer. Install it (for example: sudo apt install python3), then run SETUP again."
    finish 1
  fi
  say "First, the kit needs Apple's free Command Line Tools. A window will ask to install them: click Install."
  echo "It takes about 5 to 15 minutes."
  xcode-select --install >/dev/null 2>&1
  until python3 -c "" >/dev/null 2>&1; do
    printf '\nWhen the install has finished, press Return. '; read -r _ || exit 1
  done
}

# The drives plugged in, one mount point per line (KIT_DRIVES: look in that folder instead, for tests). In /Volumes
# the Mac's own disk is a link to /. Disks that can't be written to (installer disk images, backups) are left out,
# except NTFS ones, so we can say why those won't do.
drives() {
  local base v
  if [ -n "${KIT_DRIVES:-}" ]; then set -- "$KIT_DRIVES"; else set -- /Volumes "/media/${USER:-none}" "/run/media/${USER:-none}"; fi
  for base in "$@"; do
    for v in "$base"/*; do
      [ -d "$v" ] && [ ! -L "$v" ] || continue
      if [ -w "$v" ]; then printf '%s\n' "$v"
      else case "$(format_of "$v")" in *NTFS*|*Windows*|ntfs*) printf '%s\n' "$v" ;; esac; fi
    done
  done
}

# Lists the drives and sets VOL to the one picked. Returns 1 when the person would rather use this Mac.
pick_drive() {
  local list v n why free
  while :; do
    list=()
    while IFS= read -r v; do list+=("$v"); done < <(drives)
    say "Which drive?"
    if [ ${#list[@]} -eq 0 ]; then
      echo "No external drive is plugged in."
      echo "  1  Look again (plug the drive in first, and give it a few seconds)"
      echo "  2  Put the kit on $THIS instead"
      choose "Type 1 or 2, then press Return:" 2
      [ "$pick" = 2 ] && return 1
      continue
    fi
    n=0
    for v in "${list[@]}"; do
      n=$((n + 1))
      why="$(problem_of "$(format_of "$v")")"
      if [ -n "$why" ]; then printf "  %d  %s (won't work: %s)\n" "$n" "${v##*/}" "$(format_of "$v")"
      else printf "  %d  %s (%s, %s free)\n" "$n" "${v##*/}" "$(format_of "$v")" "$(gb "$(free_gb "$v")")"; fi
    done
    echo "  $((n + 1))  Look again (just plugged one in?)"
    echo "  $((n + 2))  Put the kit on $THIS instead"
    choose "Type a number, then press Return:" $((n + 2))
    [ "$pick" = $((n + 2)) ] && return 1
    [ "$pick" = $((n + 1)) ] && continue
    VOL="${list[$((pick - 1))]}"
    why="$(problem_of "$(format_of "$VOL")")"
    if [ -n "$why" ]; then
      say "${VOL##*/} won't work: $why."
      echo "To use it, erase it as exFAT. Erasing deletes everything on it, so copy off anything you want to keep first."
      echo "In Disk Utility: click ${VOL##*/} in the sidebar, click Erase, choose ExFAT as the format, and click Erase."
      if [ $MAC = 1 ] && ask "Open Disk Utility now?"; then open -a "Disk Utility"; fi
      printf '\nWhen the drive is ready, press Return to look again. '; read -r _ || exit 1
      continue
    fi
    free="$(free_gb "$VOL")"
    if [ "${free:-0}" -lt "$NEED" ]; then
      say "${VOL##*/} has $(gb "${free:-0}") free, and the kit needs about $NEED GB."
      echo "The most important things download first, and what doesn't fit is skipped. A bigger drive holds it all."
      ask "Use ${VOL##*/} anyway?" || continue
    fi
    return 0
  done
}

# Carry on with the kit at a new place: the copy there runs the rest of the setup.
carry_on() { mkdir -p "$1/.kit"; cd "$1" || exit 1; exec bash "$1/SETUP.command" --placed; }

# Put the kit's own files (never downloads) at DEST, on WHERE (this Mac, or the drive NAME). A fresh download
# is moved there, so there's one copy. A git checkout is a developer's: it stays put, and is copied to another disk.
move_kit() { # DEST WHERE
  local dest="$1" where="$2" f
  if [ "$dest" = "$KIT" ] || [ "${dest%/*}" = "$KIT" ]; then mkdir -p .kit; return; fi
  if [ -d .git ] && same_disk "$KIT" "${dest%/*}"; then mkdir -p .kit; return; fi
  if [ -e "$dest" ]; then
    if [ -f "$dest/kit" ] && [ -f "$dest/SETUP.command" ]; then
      say "There's already a Tinfoil Kit on $where ($dest). Carrying on with that one."
      carry_on "$dest"
    fi
    say "There's already a folder called $NAME on $where ($dest), and it isn't a Tinfoil Kit."
    echo "Rename it or move it somewhere else, then double-click SETUP again."
    finish 1
  fi
  if [ ! -d .git ] && same_disk "$KIT" "${dest%/*}" && mv "$KIT" "$dest" 2>/dev/null; then
    say "Moved the kit to $where: $dest"
    carry_on "$dest"
  fi
  rm -rf "$dest.partial"
  if ! mkdir "$dest.partial" 2>/dev/null; then
    say "Couldn't save anything on $where."
    echo "If macOS asked whether Terminal may use files there, it needs a yes. Open System Settings > Privacy & Security >"
    echo "Files and Folders, turn on Removable Volumes under Terminal, then double-click SETUP again."
    finish 1
  fi
  # Without macOS's extended attributes: no ._ files on exFAT, and no "from the internet" marks on the copy.
  for f in "$KIT"/* "$KIT"/.[!.]*; do
    [ -e "$f" ] || continue
    case "${f##*/}" in .kit|bin|installers|library|logs|maps|models|INVENTORY.md|._*) continue ;; esac
    if [ $MAC = 1 ]; then cp -RX "$f" "$dest.partial/"; else cp -R "$f" "$dest.partial/"; fi || {
      rm -rf "$dest.partial"; say "Copying the kit to $where stopped partway. Is the drive full, or was it unplugged?"; finish 1; }
  done
  mv "$dest.partial" "$dest" || finish 1
  if [ -d .git ] || [ "$KIT" = "$HOME" ] || [ ! -f "$KIT/SETUP.command" ]; then
    say "Copied the kit to $where: $dest. Use that copy from now on."
  else
    rm -rf "$KIT"    # the download isn't needed now that the kit is in its place
    say "Moved the kit to $where: $dest"
  fi
  carry_on "$dest"
}

# First run only: ask where the kit should live, then carry on from there.
place() {
  local home_free
  NEED="$(./kit estimate 2>/dev/null)"
  case "$NEED" in ""|*[!0-9]*) NEED=300 ;; esac
  home_free="$(free_gb "$HOME")"; home_free="${home_free:-0}"
  say "Step 1 of 3: where should the kit go?"
  echo "Your kit needs about $NEED GB."
  echo
  echo "  1  An external drive"
  echo "     Keep it somewhere safe and plug it in when you need it: into any Mac, or a Windows or Linux PC."
  if [ $MAC = 1 ]; then echo "  2  This Mac"; else echo "  2  This computer"; fi
  if [ "$home_free" -ge $((NEED + ROOM)) ]; then echo "     Nothing to plug in. Its disk has $(gb "$home_free") free."
  else echo "     Nothing to plug in, but its disk has only $(gb "$home_free") free, too little for all of it."; fi
  choose "Type 1 or 2, then press Return:" 2
  while :; do
    if [ "$pick" = 1 ] && pick_drive; then
      move_kit "$VOL/$NAME" "the drive ${VOL##*/}"
      return
    fi
    pick=2
    if [ "$home_free" -lt $((NEED + ROOM)) ]; then
      say "$(gb "$home_free") is free on $THIS. The kit needs about $NEED GB, and leaves $ROOM GB free so $THIS keeps working."
      echo "The most important things download first, and what doesn't fit is skipped."
      ask "Put the kit on $THIS anyway?" || { pick=1; continue; }
    fi
    move_kit "$HOME/$NAME" "$THIS"
    return
  done
}

checks() {
  local why=""
  if [ $MAC = 1 ]; then
    [ "$(uname -m)" = "arm64" ] || say "Note: this Mac doesn't have Apple Silicon (M1 or newer). The kit is built for those and may not run here."
    case "$KIT" in /Volumes/*) why="$(problem_of "$(format_of "/Volumes/$(drive_name "$KIT")")")" ;; esac
    if [ -n "$why" ]; then
      say "The kit can't work on this drive: $why."
      echo "Erase the drive as exFAT in Disk Utility (this deletes everything on it), copy this folder back, and run SETUP again."
      finish 1
    fi
  fi
  if ! ( : > .kit-write-test ) 2>/dev/null; then
    say "Can't save anything in $KIT. If it's on a drive, the drive may be locked or read-only."
    echo "Check the drive in Disk Utility (First Aid), or move this folder somewhere else, and run SETUP again."
    finish 1
  fi
  rm -f .kit-write-test
}

all_set() {
  say "All set. Tinfoil Kit is $(where_kit), in $KIT"
  if on_this_mac && [ "$KIT" = "$HOME/$NAME" ] && [ $MAC = 1 ]; then
    echo "In an outage: in Finder choose Go > Home, open $NAME and double-click START-HERE.command. No internet needed."
  elif on_this_mac; then
    echo "In an outage: open that folder and double-click START-HERE.command. No internet needed."
  else
    echo "In an outage: plug in the drive, open its ${KIT##*/} folder and double-click START-HERE.command. No internet needed."
  fi
  echo "GUIDE.md in the same folder is a short guide to print and keep handy."
  echo "To remove the kit and everything it downloaded, double-click UNINSTALL.command there."
  [ $MAC = 1 ] && open "$KIT" 2>/dev/null    # show where it lives
}

# --placed: the first run's copy of this script chose this place and moved the kit here.
# --updated: the previous copy of this script did the checks and installed this one.
if [ "${1:-}" != "--updated" ]; then
  if [ "${1:-}" != "--placed" ]; then
    say "TINFOIL KIT SETUP"
    echo "This gets an offline AI, library and maps ready for when the internet is down, then checks that they work."
    echo "The first time takes a few hours. Later runs only download what changed."
    need_python
    if [ -d .kit ]; then say "Step 1 of 3: the kit is $(where_kit), in $KIT"; else place; fi
  fi
  checks
  echo
  ./kit update
  [ $? -eq 3 ] && exec bash "$KIT/SETUP.command" --updated
fi

say "Step 2 of 3: download. Here's what will change:"
./kit plan || finish 1
say "Each item comes from its publisher under its own license, listed in THIRD-PARTY.md. Downloading means you accept them."
echo "It takes a few hours. Keep $THIS plugged in with the lid open: it won't go to sleep while this runs."
echo "You can stop any time (press Control-C, or close this window) and double-click SETUP later to carry on."
on_battery && say "This Mac is running on battery. Plug it in before you start."
ask "Start downloading?" || finish
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

say "Step 3 of 3: start everything offline and check that it answers."
./kit test
tested=$?
[ -n "$awake" ] && kill "$awake" 2>/dev/null
[ $tested -eq 130 ] && { say "Stopped."; finish 130; }
if [ $tested -eq 0 ] && [ $rc -eq 0 ]; then
  all_set
  ask "Open the kit now?" && exec bash START-HERE.command
  finish
fi
if [ $tested -eq 0 ]; then
  say "Everything in the kit works, but some downloads didn't finish:"
  problems
  echo
  echo "You can use the kit now: double-click START-HERE.command. Double-click SETUP again later to get the rest."
  finish 1
fi
say "Some checks failed. The messages above say which; logs are in the logs folder."
[ $rc -eq 0 ] || problems
echo "Running SETUP again often fixes a download that was cut off."
finish 1
}
