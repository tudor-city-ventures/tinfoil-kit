#!/bin/bash
# Double-click me (macOS) to set up Tinfoil Kit, and again whenever you want the newest models, books and maps.
# Linux: bash SETUP.command
# A home server, a computer that stays on (no screen needed): bash SETUP.command --home-server
# The first time, it asks whether the kit goes on an external drive or on this Mac, says how much fits there, and
# moves it there. Then it's ./kit update, ./kit sync and ./kit test (the first time, the essentials come first), with
# checks and plain-English prompts for first-timers.
# The whole script is one { } block, so bash reads all of it before running any: ./kit update can replace this
# file, and the first run moves it.
{
cd "$(dirname "$0")" || exit 1
# --home-server: at the end, share the kit on the home network behind an access code, and start it whenever the
# computer starts. It goes in the environment because this script starts itself again after moving or updating the kit.
for a in "$@"; do [ "$a" = --home-server ] && export KIT_HOME_SERVER=1; done
KIT="$(pwd)"
NAME=TinfoilKit    # the kit's folder: at the top of a drive, or in the home folder
MAC=0; [ "$(uname -s)" = Darwin ] && MAC=1
THIS="this computer"; [ $MAC = 1 ] && THIS="this Mac"
FIRST=1; grep -q '"last_sync"' .kit/state.json 2>/dev/null && FIRST=0    # 0: set up before, so this run is an update
# Steps are counted across the times this script starts itself again (after moving or updating the kit).
case "${1:-}" in --placed|--updated) ;; *) KIT_STEP=0; KIT_STEPS=3; export KIT_STEP KIT_STEPS ;; esac
# A Mac without Python gets this build of it (python-build-standalone, checked against its SHA-256), kept in the
# home folder's Library rather than in the kit: its files include symlinks, which a drive's exFAT can't hold.
# Changing these two gets Macs the new build at their next SETUP.
PY_URL="${KIT_MAC_PYTHON_URL:-https://github.com/astral-sh/python-build-standalone/releases/download/20260718/cpython-3.13.14%2B20260718-aarch64-apple-darwin-install_only_stripped.tar.gz}"
PY_SHA256="${KIT_MAC_PYTHON_SHA256:-06469835e1b0f73bcdb6c498a1d60ce579cc43a980754490a6f1e30062f43850}"
PY_HOME="$HOME/Library/Application Support/TinfoilKit"

say() { printf '\n%s\n' "$*"; }
ask() { printf '\n%s [Y/n] ' "$1"; read -r a; case "$a" in ""|y|Y|yes|Yes) return 0;; esac; return 1; }
ask_no() { printf '\n%s [y/N] ' "$1"; read -r a; case "$a" in y|Y|yes|Yes) return 0;; esac; return 1; }
step() { KIT_STEP=$((KIT_STEP + 1)); export KIT_STEP; say "Step $KIT_STEP of $KIT_STEPS: $*"; }
# A number from 1 to $2, in $pick. Stops if the window has nothing more to read, rather than asking forever.
choose() { while :; do printf '\n%s ' "$1"; read -r pick || exit 1
             case "$pick" in ""|*[!0-9]*) ;; *) [ "$pick" -ge 1 ] && [ "$pick" -le "$2" ] && return 0 ;; esac
             echo "Type a number from 1 to $2, then press Return."; done; }
finish() { printf '\a\nPress Return to close this window.'; read -r _; exit "${1:-0}"; }
gb() { awk -v g="$1" 'BEGIN { if (g >= 1000) printf "%.1f TB", g / 1000; else printf "%d GB", g }'; }
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

# The kit's tools run on python3 (3.9 or newer) and curl. A Mac has curl, but until Apple's developer tools (several
# GB) are installed its python3 only offers to install them: without them, SETUP gets a Python for the kit instead.
need_python() {
  if [ $MAC = 0 ]; then
    python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' >/dev/null 2>&1 && command -v curl >/dev/null && return
    say "The kit needs python3 (3.9 or newer) and curl. Install them, then run SETUP again:"
    echo "  Debian, Ubuntu, Mint:  sudo apt install python3 curl"
    echo "  Fedora:                sudo dnf install python3 curl"
    finish 1
  fi
  if [ -x "$PY_HOME/python/bin/python3" ]; then
    [ "$(cat "$PY_HOME/python/.kit-sha256" 2>/dev/null)" = "$PY_SHA256" ] && return
    say "First, a newer Python for the kit's tools (about 25 MB)."
    get_python || echo "The kit keeps using the Python it has."
    return
  fi
  if [ -z "${KIT_OWN_PYTHON:-}" ] && { [ "$(command -v python3)" != /usr/bin/python3 ] || xcode-select -p >/dev/null 2>&1; } &&
     python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' >/dev/null 2>&1; then
    return
  fi
  say "First, the kit gets the Python its tools run on (about 25 MB)."
  get_python || finish 1
}
# Downloads PY_URL, checks it and unpacks it into $PY_HOME/python. Says why not and returns 1 if it can't.
get_python() {
  local tgz="$PY_HOME/python.tar.gz" new="$PY_HOME/python.partial"
  rm -rf "$new" && mkdir -p "$new" || { say "Can't save anything in $PY_HOME."; return 1; }
  if ! curl -fL --retry 3 --progress-bar -o "$tgz" "$PY_URL"; then
    say "Couldn't download it. Check that $THIS is online (on hotel or cafe Wi-Fi, open any web page and sign in first), then double-click SETUP again."
  elif [ "$( (shasum -a 256 "$tgz" 2>/dev/null || sha256sum "$tgz") | awk '{print $1}')" != "$PY_SHA256" ]; then
    say "That download isn't the file it should be (its checksum doesn't match), so it wasn't used. Try again later."
  elif ! tar -xzf "$tgz" -C "$new" || ! "$new/python/bin/python3" -c "" >/dev/null 2>&1; then
    say "Couldn't unpack it. Double-click SETUP again."
  else
    echo "$PY_SHA256" > "$new/python/.kit-sha256"
    rm -rf "$PY_HOME/python" "$tgz" && mv "$new/python" "$PY_HOME/python" && rm -rf "$new" && return 0
  fi
  rm -rf "$new" "$tgz"
  return 1
}

# How the kit fits at a place (./kit space): FULL and ESS say whether all of it and just the essentials fit with room
# to spare ("fits"), only by leaving less than that ("tight"), or not at all ("no"). Then GB free, GB in all, GB all
# of it and the essentials need, and GB worth leaving free.
space() {
  IFS=$'\t' read -r FULL ESS FREE TOTAL NEED NEED_ESS LEAVE < <(./kit space "$1" 2>/dev/null)
  [ -n "$FULL" ] || { FULL=fits; ESS=fits; FREE=0; TOTAL=0; NEED=0; NEED_ESS=0; LEAVE=0; }
}
room_note() {
  case "$FULL/$ESS" in
    fits/*) echo "room for all of it" ;;
    tight/*) echo "room for all of it, but that leaves only $(gb $((FREE - NEED))) free" ;;
    */fits|*/tight) echo "room for the essentials, not all of it" ;;
    *) echo "not enough room, even for the essentials" ;;
  esac
}

# After space(): how much of the kit goes to the place it looked at ($1 names it). Sets ONLY to all or essentials,
# or returns 1 to choose somewhere else.
how_much() {
  local spare why=""
  spare="$(gb "$LEAVE")"
  [ "$1" = "$THIS" ] && why=", so $THIS keeps running well"
  case "$FULL/$ESS" in
    fits/*) ONLY=all; return 0 ;;
    tight/*)
      say "All of it fits on $1, but leaves only $(gb $((FREE - NEED))) free. Better to leave at least $spare$why."
      echo "  1  Just the essentials (about $(gb "$NEED_ESS"))"
      echo "  2  All of it anyway (about $(gb "$NEED"))"
      echo "  3  Somewhere else"
      choose "Type 1, 2 or 3, then press Return:" 3
      case "$pick" in 1) ONLY=essentials ;; 2) ONLY=all ;; *) return 1 ;; esac ;;
    */fits)
      say "All of it won't fit on $1: it needs about $(gb "$NEED") plus some to spare, and $(gb "$FREE") is free."
      echo "  1  Just the essentials (about $(gb "$NEED_ESS")). SETUP offers the rest later, once it fits."
      echo "  2  Somewhere else"
      choose "Type 1 or 2, then press Return:" 2
      [ "$pick" = 1 ] || return 1
      ONLY=essentials ;;
    */tight)
      say "Only the essentials fit on $1, and they leave only $(gb $((FREE - NEED_ESS))) free. Better to leave at least $spare$why."
      echo "  1  Just the essentials anyway (about $(gb "$NEED_ESS"))"
      echo "  2  Somewhere else"
      choose "Type 1 or 2, then press Return:" 2
      [ "$pick" = 1 ] || return 1
      ONLY=essentials ;;
    *)
      say "There isn't room on $1, even for the essentials: they need about $(gb "$NEED_ESS") plus some to spare, and $(gb "$FREE") is free."
      echo "Make room there, or choose somewhere else."
      return 1 ;;
  esac
}

# Lists the drives (./kit drives: folder, format, GB free, why it won't do or -, and name) with what fits on each,
# and sets VOL to the one picked and ONLY to how much goes there. Returns 1 when the person would rather use this Mac.
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
      else
        space "${paths[$i]}/$NAME"
        printf "  %d  %s (%s, %s free of %s): %s\n" $((i + 1)) "${paths[$i]##*/}" "${fmts[$i]}" "$(gb "$FREE")" \
               "$(gb "$TOTAL")" "$(room_note)"
      fi
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
    space "$VOL/$NAME"
    how_much "${VOL##*/}" || continue
    return 0
  done
}

# Where the person lives sets the maps (street detail, directions, address search, home) and Wikipedia's language.
# ./kit region does the work; this asks. The first run asks before the kit moves (its size depends on the answer),
# and hands the answer on in KIT_REGION and KIT_WIKIPEDIA to the copy of this script where the kit lands, in case a
# kit was there already. Updates ask after ./kit update, so a kit from before this question gets it too.
pick_region() {
  local now place n i id name c l g ids names codes labels sizes wiki
  now="$(./kit region 2>/dev/null)" || return 0
  export KIT_REGION_ASKED=1
  if [ "$1" = first ]; then
    step "where do you live?"
    echo "The maps show your area in street detail, with directions and address search, and Wikipedia comes in your language."
    echo "Right now: $now"
    printf '\nType your US state or your country (like Texas, Ontario or Germany), or press Return to keep that: '
  else
    say "$now"
    printf 'To change that, type where you live (a US state or a country), or press Return to keep it: '
  fi
  while :; do
    read -r place || return 0     # (nothing more to read: the next question stops it)
    [ -z "$place" ] && return 0
    ids=(); names=()
    while IFS=$'\t' read -r id name g; do ids+=("$id"); names+=("$name ($g)"); done < <(./kit region --find "$place" 2>/dev/null)
    n=${#ids[@]}
    if [ "$n" -eq 0 ]; then
      printf '\nNo place called "%s" here. Type a US state or a country, in English (or press Return to keep the maps as they are): ' "$place"
      continue
    fi
    if [ "$n" -gt 20 ]; then
      printf '\n"%s" matches %d places. Type your state, province or a nearby big town instead: ' "$place" "$n"
      continue
    fi
    id="${ids[0]}"
    if [ "$n" -gt 1 ]; then
      say "Which one?"
      for ((i = 0; i < n; i++)); do printf '  %d  %s\n' $((i + 1)) "${names[$i]}"; done
      echo "  $((n + 1))  None of these"
      choose "Type a number, then press Return:" $((n + 1))
      if [ "$pick" = $((n + 1)) ]; then printf '\nType where you live: '; continue; fi
      id="${ids[$((pick - 1))]}"
    fi
    break
  done
  codes=(); labels=(); sizes=()
  while IFS=$'\t' read -r c l g; do codes+=("$c"); labels+=("$l"); sizes+=("$g"); done < <(./kit region --languages "$id" 2>/dev/null)
  wiki="${codes[0]:-}"
  if [ ${#codes[@]} -gt 1 ]; then
    say "Which language should Wikipedia be in?"
    for ((i = 0; i < ${#codes[@]}; i++)); do printf '  %d  %s (%s)\n' $((i + 1)) "${labels[$i]}" "$(gb "${sizes[$i]}")"; done
    choose "Type a number, then press Return:" ${#codes[@]}
    wiki="${codes[$((pick - 1))]}"
  fi
  echo
  ./kit region "$id" ${wiki:+--wikipedia "$wiki"} || return 0
  export KIT_REGION="$id" KIT_WIKIPEDIA="$wiki"
}

# Put the kit at DEST: ./kit place moves it there (a git checkout is copied) and says so. If it's somewhere new,
# the copy there runs the rest of the setup.
put_kit() {
  local new
  export KIT_ESSENTIALS=off; [ "$ONLY" = essentials ] && KIT_ESSENTIALS=on    # the copy there says so in its kit.json
  new="$(./kit place "$1")" || finish 1
  [ "$new" = "$KIT" ] && { ./kit essentials "$KIT_ESSENTIALS" >/dev/null; return; }
  cd "$new" || exit 1
  exec bash "$new/SETUP.command" --placed
}

# First run only: ask where the kit should live, then carry on from there.
place() {
  step "where should the kit go?"
  ./kit fit --ask    # which AI model this computer runs, and whether to get the ones too big for it
  export KIT_FIT_ASKED=1
  space "$HOME/$NAME"
  say "All of the kit is about $(gb "$NEED"). Just the essentials (the AI, the medical, preparedness and repair"
  echo "books, and the map) are about $(gb "$NEED_ESS")."
  echo
  echo "  1  An external drive"
  echo "     Keep it somewhere safe and plug it in when you need it: into any Mac, or a Windows or Linux PC."
  if [ $MAC = 1 ]; then echo "  2  This Mac"; else echo "  2  This computer"; fi
  echo "     Nothing to plug in. Its disk has $(gb "$FREE") free of $(gb "$TOTAL"): $(room_note)."
  choose "Type 1 or 2, then press Return:" 2
  while :; do
    if [ "$pick" = 1 ] && pick_drive; then
      put_kit "$VOL/$NAME"
      return
    fi
    space "$HOME/$NAME"
    if how_much "$THIS"; then
      put_kit "$HOME/$NAME"
      return
    fi
    pick=1
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
  if [ "${KIT_HOME_SERVER:-}" = 1 ]; then
    :    # it starts by itself: home_server says so
  elif on_this_mac && [ "$KIT" = "$HOME/$NAME" ] && [ $MAC = 1 ]; then
    echo "In an outage: in Finder choose Go > Home, open $NAME and double-click Open Tinfoil Kit.command. No internet needed."
  elif on_this_mac; then
    echo "In an outage: open that folder and double-click Open Tinfoil Kit.command. No internet needed."
  else
    echo "In an outage: plug in the drive, open its ${KIT##*/} folder and double-click Open Tinfoil Kit.command. No internet needed."
  fi
  if [ $MAC = 1 ]; then again="double-click it again"; else again="run it again"; fi
  echo
  echo "Also in that folder:"
  echo "  GUIDE.md           a short guide. Print it and keep it handy."
  echo "  SETUP.command      $again whenever you want the newest AI models, books and maps (needs internet)."
  echo "  UNINSTALL.command  removes the kit and everything it downloaded."
  [ $MAC = 1 ] && open "$KIT" 2>/dev/null    # show where it lives
}

# Phones and laptops on the home network open the kit with its access code, and it starts with the computer.
home_server() {
  say "Home server: sharing the kit on your home network, and starting it whenever $THIS starts."
  ./kit share on >/dev/null
  ./kit autostart on
  echo
  ./kit share
}

# --placed: the first run's copy of this script chose this place and moved the kit here.
# --updated: the previous copy of this script did the checks and installed this one.
if [ "${1:-}" != "--updated" ]; then
  if [ "${1:-}" != "--placed" ]; then
    if [ $FIRST = 0 ]; then
      say "TINFOIL KIT UPDATE"
      echo "This gets the newest AI models, books and maps, including any added to the kit since you last ran it."
      echo "It downloads only what changed. If it's cut off, the kit keeps working with what it has."
    else
      say "TINFOIL KIT SETUP"
      echo "This gets an offline AI, library and maps ready for when the internet is down, then checks that they work."
      echo "The first time takes a few hours. Later runs only download what changed."
    fi
    need_python
    if [ -d .kit ]; then step "the kit is $(where_kit), in $KIT"; else KIT_STEPS=4; pick_region first; place; fi
  else
    [ -n "${KIT_ESSENTIALS:-}" ] && ./kit essentials "$KIT_ESSENTIALS" >/dev/null
    # a kit that was here already gets the answer to "where do you live?" too
    [ -n "${KIT_REGION:-}" ] && ./kit region "$KIT_REGION" ${KIT_WIKIPEDIA:+--wikipedia "$KIT_WIKIPEDIA"} >/dev/null 2>&1
  fi
  checks
  echo
  ./kit update
  [ $? -eq 3 ] && exec bash "$KIT/SETUP.command" --updated
fi
[ -n "${KIT_REGION_ASKED:-}" ] || pick_region    # (after ./kit update, so a kit from before this question gets it)

[ -n "${KIT_FIT_ASKED:-}" ] || ./kit fit --ask    # an update can bring models too big for this computer
ONLY=all; grep -q '"essentials_only": *true' kit.json 2>/dev/null && ONLY=essentials
if [ $FIRST = 0 ] && [ $ONLY = essentials ]; then
  space "$KIT"
  if [ "$FULL" = fits ]; then
    say "This kit has just the essentials, and now there's room for the rest (about $(gb "$NEED") more)."
    ask_no "Get the rest too?" && { ./kit essentials off >/dev/null; ONLY=all; }
  fi
fi

# The first time, the essentials come first and get checked, so the kit works hours before the rest is in.
if [ $FIRST = 1 ]; then
  step "the essentials. Here's what comes first:"
  ./kit plan --essentials || finish 1
else
  step "download. Here's what will change:"
  ./kit plan || finish 1
fi
say "Each item comes from its publisher under its own license, listed in THIRD-PARTY.md. Downloading means you accept them."
echo "Big downloads take hours. Keep $THIS plugged in with the lid open: it won't go to sleep while this runs."
echo "You can stop any time (press Control-C, or close this window) and double-click SETUP later to carry on."
on_battery && say "This Mac is running on battery. Plug it in before you start."
ask "Start downloading?" || finish
# Keep the Mac awake (not the screen) until the download and checks are done. caffeinate runs in the
# background so that Ctrl-C reaches the sync, which saves its progress, and this script carries on.
awake=""
if command -v caffeinate >/dev/null 2>&1; then caffeinate -i -w $$ & awake=$!; fi

# ./kit sync with these options, then start everything offline and check that it answers. Sets rc and tested.
get() {
  ./kit sync --yes "$@"
  rc=$?
  if [ $rc -eq 130 ]; then
    say "Stopped. Everything downloaded so far is kept. Double-click SETUP again to carry on where it left off."
    finish 130
  fi
  if [ $FIRST = 1 ]; then say "Now a check that it all starts offline and answers."
  else step "start everything offline and check that it answers."; fi
  ./kit test
  tested=$?
  [ $tested -eq 130 ] && { say "Stopped."; finish 130; }
}
if [ $FIRST = 0 ] || [ $ONLY = essentials ]; then
  get    # (with just the essentials in kit.json, that's all it gets)
  [ $FIRST = 1 ] && [ $tested -eq 0 ] &&
    step "everything else: not now. You chose just the essentials. Once there's room, SETUP offers the rest."
else
  get --essentials
  if [ $tested -eq 0 ]; then
    say "The essentials work: from now on, if the internet goes down, the kit is ready."
    space "$KIT"
    step "everything else (about $(gb "$NEED")). It takes hours, and the kit works the whole time."
    get
  fi
fi
[ -n "$awake" ] && kill "$awake" 2>/dev/null
if [ $tested -eq 0 ] && [ $rc -eq 0 ]; then
  all_set
  [ "${KIT_HOME_SERVER:-}" = 1 ] && { home_server; finish; }
  ask "Open the kit now?" && exec bash "Open Tinfoil Kit.command"
  finish
fi
if [ $tested -eq 0 ]; then
  say "Everything in the kit works, but some downloads didn't finish:"
  problems
  echo
  if [ "${KIT_HOME_SERVER:-}" = 1 ]; then
    home_server
    say "Run SETUP again later to get the rest."
  else
    echo "You can use the kit now: double-click Open Tinfoil Kit.command. Double-click SETUP again later to get the rest."
  fi
  finish 1
fi
say "Some checks failed. The messages above say which; logs are in the logs folder."
[ $rc -eq 0 ] || problems
echo "Running SETUP again often fixes a download that was cut off."
finish 1
}
