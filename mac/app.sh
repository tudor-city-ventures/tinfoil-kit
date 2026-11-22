#!/bin/bash
# The file work behind the Mac app. Its window code (mac/TinfoilKit.m) runs this from the app's Resources folder:
#   app.sh find           the kits it can open, one per line: STATUS<TAB>FOLDER<TAB>WHERE. STATUS is ready (it has
#                         books), unfinished (setup stopped before it got any) or unplugged (the drive the app last
#                         opened it on isn't plugged in). WHERE is "this Mac" or "the drive NAME".
#   app.sh setup [KIT]    SETUP in a Terminal window: in KIT, or in a fresh copy of the kit inside the app
#                         (KIT is a kit folder: its code is in its app folder, or at its top in an older kit)
#   app.sh update KIT     SETUP in a Terminal window, in KIT
#   app.sh remove KIT     UNINSTALL in a Terminal window, in KIT
#   app.sh remember KIT   look for KIT next time, and name its drive when it isn't plugged in
#   app.sh move APP       copy the app into Applications (the user's own if they can't write to the main one)
#                         and print where it went
# Tests: KIT_APP_OPEN replaces "open -a Terminal", KIT_VOLUMES the folder drives appear in, KIT_APPLICATIONS
# the Applications folder.
RES="$(cd "$(dirname "$0")" && pwd)"
VOLUMES="${KIT_VOLUMES:-/Volumes}"
# SETUP keeps a Mac's own Python here too, and UNINSTALL deletes the folder, which also forgets the kit.
SUPPORT="$HOME/Library/Application Support/TinfoilKit"
LAST="$SUPPORT/last-kit"

drive_of() { local d="${1#"$VOLUMES"/}"; [ "$d" != "$1" ] && echo "${d%%/*}"; }
where() { local d; d="$(drive_of "$1")"; if [ -n "$d" ]; then echo "the drive $d"; else echo "this Mac"; fi; }
# The code in the kit folder $1: its app folder, or the folder itself in a kit from before the app folder.
code_of() { if [ -f "$1/app/SETUP.command" ]; then echo "$1/app"; else echo "$1"; fi; }

find_kits() {
  local last k seen="|" st d c
  last="$(cat "$LAST" 2>/dev/null)"
  for k in "$last" "$HOME/TinfoilKit" "$VOLUMES"/*/TinfoilKit; do
    [ -n "$k" ] || continue
    case "$seen" in *"|$k|"*) continue ;; esac
    seen="$seen$k|"
    d="$(drive_of "$k")"
    c="$(code_of "$k")"
    if [ -f "$c/kit" ] && [ -f "$c/tools/kit.py" ]; then
      if { ls "$k"/downloads/library/*.zim || ls "$k"/library/*.zim; } > /dev/null 2>&1; then st=ready; else st=unfinished; fi
    elif [ "$k" = "$last" ] && [ -n "$d" ] && [ ! -d "$VOLUMES/$d" ]; then
      st=unplugged
    else
      continue
    fi
    printf '%s\t%s\t%s\n' "$st" "$k" "$(where "$k")"
  done
}

# A Terminal window running one of the kit's scripts. The kit inside the app carries the mark macOS puts on
# downloads, and macOS won't open a marked script: the copies this app makes, and the kit's own scripts, lose it.
terminal() {
  xattr -d com.apple.quarantine "$1" 2> /dev/null
  ${KIT_APP_OPEN:-open -a Terminal} "$1"
}

case "${1:-}" in
  find) find_kits ;;
  setup)
    kit="${2:-}"
    if [ -z "$kit" ]; then
      # SETUP's first question moves it from here to the drive or the home folder the person picks.
      kit="$SUPPORT/Setup/TinfoilKit"
      rm -rf "$SUPPORT/Setup" && mkdir -p "$kit" && cp -pR "$RES/kit" "$kit/app" || exit 1
      xattr -dr com.apple.quarantine "$kit" 2> /dev/null
    fi
    terminal "$(code_of "$kit")/SETUP.command" ;;
  update) terminal "$(code_of "$2")/SETUP.command" ;;
  remove) terminal "$(code_of "$2")/UNINSTALL.command" ;;
  remember) mkdir -p "$SUPPORT" && printf '%s\n' "$2" > "$LAST" ;;
  move)
    dest="${KIT_APPLICATIONS:-/Applications}"
    [ -w "$dest" ] || { dest="$HOME/Applications"; mkdir -p "$dest" || exit 1; }
    dest="$dest/Tinfoil Kit.app"
    rm -rf "$dest.partial"
    # (the person said yes to opening this app: its copy needn't be asked about again)
    ditto --noqtn "$2" "$dest.partial" && rm -rf "$dest" && mv "$dest.partial" "$dest" || { rm -rf "$dest.partial"; exit 1; }
    echo "$dest" ;;
  *) sed -n '2,14p' "$0"; exit 2 ;;
esac
