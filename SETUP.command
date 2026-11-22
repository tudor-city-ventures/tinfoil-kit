#!/bin/bash
# Double-click me (macOS) to set up Tinfoil Kit, and again whenever you want the newest models, books and maps.
# Linux: bash SETUP.command
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

# The kit's tools run on python3 and curl. A Mac has curl, and python3 comes with Apple's free Command Line Tools:
# wait for that install instead of making the person find SETUP and start it again.
need_python() {
  if [ $MAC = 0 ]; then
    python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' >/dev/null 2>&1 && command -v curl >/dev/null && return
    say "The kit needs python3 (3.9 or newer) and curl. Install them, then run SETUP again:"
    echo "  Debian, Ubuntu, Mint:  sudo apt install python3 curl"
    echo "  Fedora:                sudo dnf install python3 curl"
    finish 1
  fi
  python3 -c "" >/dev/null 2>&1 && return
  say "First, the kit needs Apple's free Command Line Tools. A window will ask to install them: click Install."
  echo "It takes about 5 to 15 minutes."
  xcode-select --install >/dev/null 2>&1
  until python3 -c "" >/dev/null 2>&1; do
    printf '\nWhen the install has finished, press Return. '; read -r _ || exit 1
  done
}

# Lists the drives (./kit drives: folder, format, GB free, why it won't do or -, and name) and sets VOL to the one
# picked. Returns 1 when the person would rather use this Mac.
pick_drive() {
  local paths fmts frees whys p f g w n i
  while :; do
    paths=(); fmts=(); frees=(); whys=()
    while IFS=$'\t' read -r p f g w _; do
      paths+=("$p"); fmts+=("$f"); frees+=("$g"); whys+=("$w")
    done < <(./kit drives 2>/dev/null)
    say "Which drive?"
    n=${#paths[@]}
    if [ "$n" -eq 0 ]; then
      echo "No external drive is plugged in."
      echo "  1  Look again (plug the drive in first, and give it a few seconds)"
      echo "  2  Put the kit on $THIS instead"
      choose "Type 1 or 2, then press Return:" 2
      [ "$pick" = 2 ] && return 1
      continue
    fi
    for ((i = 0; i < n; i++)); do
      if [ "${whys[$i]}" != "-" ]; then printf "  %d  %s (won't work: %s)\n" $((i + 1)) "${paths[$i]##*/}" "${fmts[$i]}"
      else printf "  %d  %s (%s, %s free)\n" $((i + 1)) "${paths[$i]##*/}" "${fmts[$i]}" "$(gb "${frees[$i]}")"; fi
    done
    echo "  $((n + 1))  Look again (just plugged one in?)"
    echo "  $((n + 2))  Put the kit on $THIS instead"
    choose "Type a number, then press Return:" $((n + 2))
    [ "$pick" = $((n + 2)) ] && return 1
    [ "$pick" = $((n + 1)) ] && continue
    i=$((pick - 1)); VOL="${paths[$i]}"
    if [ "${whys[$i]}" != "-" ]; then
      say "${VOL##*/} won't work: ${whys[$i]}."
      echo "To use it, erase it as exFAT. Erasing deletes everything on it, so copy off anything you want to keep first."
      if [ $MAC = 1 ]; then
        echo "In Disk Utility: click ${VOL##*/} in the sidebar, click Erase, choose ExFAT as the format, and click Erase."
        ask "Open Disk Utility now?" && open -a "Disk Utility"
      else
        echo "In Disks (or your system's disk tool): select ${VOL##*/}, choose Format Partition, and pick exFAT (under Other)."
      fi
      printf '\nWhen the drive is ready, press Return to look again. '; read -r _ || exit 1
      continue
    fi
    if [ "${frees[$i]}" -lt "$NEED" ]; then
      say "${VOL##*/} has $(gb "${frees[$i]}") free, and the kit needs about $NEED GB."
      echo "The most important things download first, and what doesn't fit is skipped. A bigger drive holds it all."
      ask "Use ${VOL##*/} anyway?" || continue
    fi
    return 0
  done
}

# Put the kit at DEST: ./kit place moves it there (a git checkout is copied) and says so. If it's somewhere new,
# the copy there runs the rest of the setup.
put_kit() {
  local new
  new="$(./kit place "$1")" || finish 1
  [ "$new" = "$KIT" ] && return
  cd "$new" || exit 1
  exec bash "$new/SETUP.command" --placed
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
      put_kit "$VOL/$NAME"
      return
    fi
    pick=2
    if [ "$home_free" -lt $((NEED + ROOM)) ]; then
      say "$(gb "$home_free") is free on $THIS. The kit needs about $NEED GB, and leaves $ROOM GB free so $THIS keeps working."
      echo "The most important things download first, and what doesn't fit is skipped."
      ask "Put the kit on $THIS anyway?" || { pick=1; continue; }
    fi
    put_kit "$HOME/$NAME"
    return
  done
}

checks() {
  local why
  if [ $MAC = 1 ] && [ "$(uname -m)" != "arm64" ]; then
    say "Note: this Mac doesn't have Apple Silicon (M1 or newer). The kit is built for those and may not run here."
  fi
  # The drive the kit is on, if its format can't hold the kit
  why="$(./kit drives 2>/dev/null | awk -F'\t' -v k="$KIT/" 'index(k, $1 "/") == 1 && $4 != "-" {print $4; exit}')"
  if [ -n "$why" ]; then
    say "The kit can't work on this drive: $why."
    if [ $MAC = 1 ]; then echo "Erase the drive as exFAT in Disk Utility (this deletes everything on it), copy this folder back, and run SETUP again."
    else echo "Format the drive as exFAT (this deletes everything on it), copy this folder back, and run SETUP again."; fi
    finish 1
  fi
  if ! ( : > .kit-write-test ) 2>/dev/null; then
    say "Can't save anything in $KIT. If it's on a drive, the drive may be locked or read-only."
    if [ $MAC = 1 ]; then echo "Check the drive in Disk Utility (First Aid), or move this folder somewhere else, and run SETUP again."
    else echo "Check that the drive isn't mounted read-only, or move this folder somewhere else, and run SETUP again."; fi
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
  if [ $MAC = 1 ]; then again="double-click it again"; else again="run it again"; fi
  echo
  echo "Also in that folder:"
  echo "  GUIDE.md           a short guide. Print it and keep it handy."
  echo "  SETUP.command      $again whenever you want the newest AI models, books and maps (needs internet)."
  echo "  UNINSTALL.command  removes the kit and everything it downloaded."
  [ $MAC = 1 ] && open "$KIT" 2>/dev/null    # show where it lives
}

# --placed: the first run's copy of this script chose this place and moved the kit here.
# --updated: the previous copy of this script did the checks and installed this one.
if [ "${1:-}" != "--updated" ]; then
  if [ "${1:-}" != "--placed" ]; then
    if grep -q '"last_sync"' .kit/state.json 2>/dev/null; then    # set up before: this run is an update
      say "TINFOIL KIT UPDATE"
      echo "This gets the newest AI models, books and maps, including any added to the kit since you last ran it."
      echo "It downloads only what changed. If it's cut off, the kit keeps working with what it has."
    else
      say "TINFOIL KIT SETUP"
      echo "This gets an offline AI, library and maps ready for when the internet is down, then checks that they work."
      echo "The first time takes a few hours. Later runs only download what changed."
    fi
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
echo "Big downloads take hours. Keep $THIS plugged in with the lid open: it won't go to sleep while this runs."
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
