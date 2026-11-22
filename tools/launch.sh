#!/bin/bash
# Starts the offline library server (kiwix-serve) and the AI server (llama-server),
# then opens the portal in the browser. Started by START-HERE.command.
#
#   bash tools/launch.sh [--share] [--model=NAME] [--no-browser] [--no-maps]
#
#   --share       also serve phones and laptops on the home network, behind the access code (this time
#                 only; ./kit share on turns it on for good: kit.json's share_on_network)
#   --model=NAME  model to load first (a folder name in models/)
#   --no-browser  don't open the browser
#   --no-maps     don't start the map servers (saves about 5 GB of memory)
# (no "set -u": macOS ships bash 3.2, which mishandles empty arrays with it)
KIT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$KIT" || exit 1
mkdir -p "$KIT/logs" "$KIT/.kit"
SHARE=0; NO_BROWSER=0; NO_MAPS=0; MODEL=""; CHOSEN=0
for a in "$@"; do
  case "$a" in
    --share) SHARE=1 ;;
    --no-browser) NO_BROWSER=1 ;;
    --no-maps) NO_MAPS=1 ;;
    --model=*) MODEL="${a#*=}"; CHOSEN=1 ;;
  esac
done

say() { printf '%s\n' "$*"; }
setting() { # key default: a simple "key": value from kit.json, read without needing python
  local v
  v="$(sed -n "s/.*\"$1\"[[:space:]]*:[[:space:]]*\"\{0,1\}\([^\",}]*\)\"\{0,1\}.*/\1/p" "$KIT/kit.json" 2>/dev/null | head -1)"
  printf '%s' "${v:-$2}"
}
LIB_PORT="$(setting library_port 8888)"
AI_PORT="$(setting ai_port 8080)"
CTX="$(setting context_size 16384)"
MODEL="${MODEL:-$(setting default_model)}"
TILES_PORT="$(setting tiles_port 8090)"
GEO_PORT="$(setting geocoder_port 2322)"
ROUTE_PORT="$(setting routing_port 8989)"
GEO_HEAP="$(setting geocoder_heap 3g)"
ROUTE_HEAP="$(setting routing_heap 2g)"
SHARE_PORT="$(setting share_port 8000)"
[ "$(setting share_on_network false)" = true ] && SHARE=1

case "$(uname -s)-$(uname -m)" in
  Darwin-arm64) PLAT=macos-arm64 ;;
  Darwin-x86_64) PLAT=macos-x64 ;;
  Linux-x86_64) PLAT=linux-x64 ;;
  Linux-aarch64) PLAT=linux-arm64 ;;
  *) PLAT=unknown ;;
esac

works() { "$1" --version >/dev/null 2>&1 || "$1" version >/dev/null 2>&1; }

# Find a runnable copy of a program: the current version first, then any older one kept as a fallback.
pick_bin() { # product binary
  local base="$KIT/bin/$1-$PLAT" cur="" d p f
  local cands=()
  [ -d "$base" ] || return 1
  if [ -f "$base/CURRENT" ]; then
    cur="$(tr -d '\r\n' < "$base/CURRENT")"
    [ -d "$base/$cur" ] && cands+=("$base/$cur")
  fi
  for d in "$base"/*/; do
    [ "${d%/}" = "$base/$cur" ] || cands+=("${d%/}")
  done
  for d in "${cands[@]}"; do
    p="$(find "$d" -type f -name "$2" 2>/dev/null | head -1)"
    [ -n "$p" ] || continue
    chmod +x "$p" 2>/dev/null
    if [ "$(uname -s)" = Darwin ]; then xattr -dr com.apple.quarantine "$d" 2>/dev/null; fi
    if works "$p"; then printf '%s\n' "$p"; return 0; fi
    if [ "$(uname -s)" = Darwin ]; then   # unsigned build: sign it locally (ad hoc) and retry
      for f in "$(dirname "$p")"/*; do [ -f "$f" ] && codesign --force --sign - "$f" >/dev/null 2>&1; done
      if works "$p"; then printf '%s\n' "$p"; return 0; fi
    fi
  done
  return 1
}

# Say why a program is missing, or why the copy on the drive won't run here (such as a library Linux lacks).
missing() { # name product binary
  local p out rc
  p="$(find "$KIT/bin/$2-$PLAT" -type f -name "$3" 2>/dev/null | head -1)"
  if [ -z "$p" ]; then say "  ! $1 not found for $PLAT (bin/$2-$PLAT). Run ./kit sync while online."; return; fi
  out="$("$p" --version 2>&1)"; rc=$?
  out="$(printf '%s\n' "$out" | grep -m1 -iE 'error|not found|cannot')"
  out="${out#*"$3": }"
  say "  ! $1 won't start on this computer: ${out:-it stops with code $rc}"
}

# Fetch a local URL: curl when there is one, else bash's own /dev/tcp (a stock Ubuntu desktop has no curl).
# Exits 7 when nothing listens on the port, as curl does.
get() { # http://127.0.0.1:PORT/PATH
  if command -v curl >/dev/null; then curl -sL --max-time 2 "$1" 2>/dev/null; return; fi
  local hp="${1#http://}" path
  path="/${hp#*/}"; hp="${hp%%/*}"
  (: <>"/dev/tcp/${hp%:*}/${hp##*:}") 2>/dev/null || return 7
  (exec 3<>"/dev/tcp/${hp%:*}/${hp##*:}" && printf 'GET %s HTTP/1.0\r\nHost: %s\r\n\r\n' "$path" "$hp" >&3 && timeout 2 cat <&3) 2>/dev/null
}
up() { get "$1" >/dev/null; }
# Is anything listening on this port, ours or not?
taken() { get "http://127.0.0.1:$1/" >/dev/null; [ $? -ne 7 ]; }
our_library() { get "http://127.0.0.1:$1/" | grep -q "Tinfoil Kit"; }
our_ai() { get "http://127.0.0.1:$1/v1/models" | grep -q '"data"'; }
# Another program can hold a port (Jupyter takes 8888, many developer tools 8080): use the next free one.
free_port() { local p="$1"; while taken "$p" && [ "$p" -lt $(( $1 + 9 )) ]; do p=$(( p + 1 )); done; printf '%s' "$p"; }

KIWIX="${KIT_KIWIX_TOOLS_BIN:-$(pick_bin kiwix-tools kiwix-serve)}"
LLAMA="${KIT_LLAMACPP_BIN:-$(pick_bin llama.cpp llama-server)}"
# macOS keeps Finder metadata for files on exFAT drives in "._name" files beside them. The servers
# scan library/ and models/ and could take ._name.zim or ._name.gguf for a book or a model.
find "$KIT/library" "$KIT/models" -name '._*' -type f -delete 2>/dev/null
shopt -s nullglob
ZIMS=("$KIT"/library/*.zim)
MODELS=("$KIT"/models/*/)
shopt -u nullglob

say ""
say "  TINFOIL KIT"
say "  ==========="
[ -n "$KIWIX" ] || missing "Library server" kiwix-tools kiwix-serve
[ -n "$LLAMA" ] || missing "AI server" llama.cpp llama-server
[ ${#ZIMS[@]} -gt 0 ] || say "  ! No library files in library/. Run ./kit sync while online."
[ ${#MODELS[@]} -gt 0 ] || say "  ! No models in models/. Run ./kit sync while online."

# A model has to fit in memory with room for everything else. On a computer with less memory than the
# first model needs, or without that model, start with the biggest one that fits (./kit fit picks the same way);
# the Ask page still lists them all.
model_mb() { ls -ln "$1"/*.gguf 2>/dev/null | awk '{s += $5} END {print int(s / 1048576)}'; }
MEM_MB="${KIT_MEMORY_MB:-}"
if [ -z "$MEM_MB" ]; then
  case "$(uname -s)" in
    Darwin) MEM_MB=$(( $(sysctl -n hw.memsize 2>/dev/null || echo 0) / 1048576 )) ;;
    Linux) MEM_MB="$(awk '/^MemTotal/ {print int($2 / 1024)}' /proc/meminfo 2>/dev/null)" ;;
  esac
fi
ROOM=$(( ${MEM_MB:-0} * 6 / 10 ))
too_big() { [ "$CHOSEN" = 0 ] && [ "$ROOM" -gt 0 ] && [ "$(model_mb "$KIT/models/$MODEL")" -gt "$ROOM" ]; }
if [ ${#MODELS[@]} -gt 0 ] && { [ ! -d "$KIT/models/$MODEL" ] || too_big; }; then
  FIT=""; FIT_MB=0; SMALL=""; SMALL_MB=""
  for d in "${MODELS[@]}"; do
    mb="$(model_mb "${d%/}")"
    [ "$mb" -gt 0 ] || continue
    if { [ "$ROOM" -eq 0 ] || [ "$mb" -le "$ROOM" ]; } && [ "$mb" -gt "$FIT_MB" ]; then FIT="$(basename "$d")"; FIT_MB="$mb"; fi
    if [ -z "$SMALL_MB" ] || [ "$mb" -lt "$SMALL_MB" ]; then SMALL="$(basename "$d")"; SMALL_MB="$mb"; fi
  done
  FIT="${FIT:-${SMALL:-$(basename "${MODELS[0]}")}}"
  if [ "$FIT" != "$MODEL" ]; then
    [ -d "$KIT/models/$MODEL" ] && say "  This computer has $(( MEM_MB / 1024 )) GB of memory, too little for $MODEL. Starting with $FIT."
    MODEL="$FIT"
  fi
fi

# Every server listens on 127.0.0.1 only. Sharing puts tools/share.py in front of them on the home network:
# it asks for the access code, then passes requests on.
HOST=127.0.0.1

PIDS=()
cleanup() {
  [ ${#PIDS[@]} -gt 0 ] && kill "${PIDS[@]}" 2>/dev/null
  say ""; say "  Stopped."
}
trap cleanup EXIT
trap 'exit 0' INT TERM HUP

# --- library
LIB_PID=""
if our_library "$LIB_PORT"; then
  say "  Library already running on port $LIB_PORT."
elif [ -n "$KIWIX" ] && [ ${#ZIMS[@]} -gt 0 ]; then
  if taken "$LIB_PORT"; then
    p="$(free_port "$LIB_PORT")"; say "  Another program is using port $LIB_PORT, so the library uses $p."; LIB_PORT="$p"
  fi
  # The page ./kit sync builds has the map inside; the bare template has no map. A newer template
  # (kit code updated, no sync since) shows up after the next sync, which rebuilds the page.
  PORTAL="$KIT/.kit/portal.html"
  [ -f "$PORTAL" ] || PORTAL="$KIT/tools/portal.html"
  KARGS=(--port "$LIB_PORT" --address "$HOST" --customIndex "$PORTAL" --threads 4)
  "$KIWIX" --help 2>&1 | grep -q -- --skipInvalid && KARGS+=(--skipInvalid)
  "$KIWIX" "${KARGS[@]}" "${ZIMS[@]}" > "$KIT/logs/kiwix-serve.log" 2>&1 &
  LIB_PID=$!; PIDS+=($!)
  say "  Starting library (${#ZIMS[@]} books)..."
fi

# --- AI
AI_PID=""
if our_ai "$AI_PORT"; then
  say "  AI already running on port $AI_PORT."
elif [ -n "$LLAMA" ] && [ ${#MODELS[@]} -gt 0 ]; then
  if taken "$AI_PORT"; then
    p="$(free_port "$AI_PORT")"; say "  Another program is using port $AI_PORT, so the AI uses $p."; AI_PORT="$p"
  fi
  # Browsers accept exactly one allowed origin (llama-server would echo a list verbatim): the page at
  # 127.0.0.1. Through the sharing gate, the page and the AI share one address, so that needs none.
  CORS="http://127.0.0.1:$LIB_PORT"
  PRESET="$KIT/.kit/presets.ini"
  printf 'version = 1\n\n[%s]\nload-on-startup = true\n' "$MODEL" > "$PRESET"
  "$LLAMA" --models-dir "$KIT/models" --models-preset "$PRESET" --models-max 1 -c "$CTX" \
    --host "$HOST" --port "$AI_PORT" --cors-origins "$CORS" > "$KIT/logs/llama-server.log" 2>&1 &
  AI_PID=$!; PIDS+=($!)
  say "  Starting AI (loading $MODEL)..."
fi

# --- maps: tiles, address search, directions
newest() { local f last=""; for f in "$@"; do [ -f "$f" ] && last="$f"; done; printf '%s' "$last"; }  # sync keeps one copy
MAPS_STARTED=""
if [ "$NO_MAPS" = 0 ] && [ -d "$KIT/maps" ]; then
  PMTILES="$(pick_bin pmtiles pmtiles)"
  JAVA="$(pick_bin java java)"
  PHOTON_JAR="$(newest "$KIT"/bin/photon/photon-*.jar)"
  GH_JAR="$(newest "$KIT"/bin/graphhopper/graphhopper-web-*.jar)"
  if [ -n "$PMTILES" ] && [ -f "$KIT/maps/tiles/basemap.pmtiles" ] && ! up "http://127.0.0.1:$TILES_PORT/basemap.json"; then
    "$PMTILES" serve "$KIT/maps/tiles" --port "$TILES_PORT" --interface "$HOST" --cors '*' > "$KIT/logs/tiles.log" 2>&1 &
    PIDS+=($!); MAPS_STARTED="$MAPS_STARTED map"
  fi
  if [ -n "$JAVA" ] && [ -n "$PHOTON_JAR" ] && [ -d "$KIT/maps/geocoder/photon_data" ] && ! up "http://127.0.0.1:$GEO_PORT/status"; then
    "$JAVA" "-Xmx$GEO_HEAP" -jar "$PHOTON_JAR" serve -data-dir "$KIT/maps/geocoder" -listen-ip "$HOST" \
      -listen-port "$GEO_PORT" -cors-any > "$KIT/logs/geocoder.log" 2>&1 &
    PIDS+=($!); MAPS_STARTED="$MAPS_STARTED address-search"
  fi
  if [ -n "$JAVA" ] && [ -n "$GH_JAR" ] && [ -f "$KIT/maps/routing/graph-cache/properties" ] && ! up "http://127.0.0.1:$ROUTE_PORT/health"; then
    (cd "$KIT/maps/routing" && exec "$JAVA" "-Xmx$ROUTE_HEAP" \
      "-Ddw.server.application_connectors[0].bind_host=$HOST" "-Ddw.server.application_connectors[0].port=$ROUTE_PORT" \
      -jar "$GH_JAR" server gh-serve.yml) > "$KIT/logs/routing.log" 2>&1 &
    PIDS+=($!); MAPS_STARTED="$MAPS_STARTED directions"
  fi
  [ -n "$MAPS_STARTED" ] && say "  Starting maps:$MAPS_STARTED (address search and directions take up to a minute)..."
fi

# --- sharing on the home network
GATE_PID=""; SHARE_OK=0
our_gate() { get "http://127.0.0.1:$1/" | grep -q "Tinfoil Kit"; }
if [ "$SHARE" = 1 ]; then
  if ! python3 -c "" >/dev/null 2>&1; then
    say "  ! Sharing needs python3. On a Mac: xcode-select --install. On Linux: install the python3 package."
  elif our_gate "$SHARE_PORT"; then
    say "  Sharing already on, on port $SHARE_PORT."; SHARE_OK=1
  else
    if taken "$SHARE_PORT"; then
      p="$(free_port "$SHARE_PORT")"; say "  Another program is using port $SHARE_PORT, so sharing uses $p."; SHARE_PORT="$p"
    fi
    GARGS=(--root "$KIT" --port "$SHARE_PORT" --library "$LIB_PORT" --ai "$AI_PORT")
    [ "$NO_MAPS" = 0 ] && GARGS+=(--tiles "$TILES_PORT" --geocoder "$GEO_PORT" --routing "$ROUTE_PORT")
    python3 "$KIT/tools/share.py" serve "${GARGS[@]}" > "$KIT/logs/share.log" 2>&1 &
    GATE_PID=$!; PIDS+=($!)
  fi
fi

# Keep the computer awake while the kit runs (the screen may still sleep).
if [ "$(uname -s)" = Darwin ] && command -v caffeinate >/dev/null; then
  caffeinate -i -w $$ & PIDS+=($!)
elif command -v systemd-inhibit >/dev/null; then
  # (tail --pid ends with this script, even if systemd-inhibit is stopped first)
  systemd-inhibit --what=sleep --who="Tinfoil Kit" --why="The kit is running" tail --pid=$$ -f /dev/null >/dev/null 2>&1 &
  PIDS+=($!)
fi

# Wait for each server to answer, unless this window didn't start it or it has already quit.
LIB_OK=0
for _ in $(seq 1 60); do
  our_library "$LIB_PORT" && { LIB_OK=1; break; }
  { [ -n "$LIB_PID" ] && kill -0 "$LIB_PID" 2>/dev/null; } || break
  sleep 1
done
AI_OK=0
for _ in $(seq 1 30); do
  our_ai "$AI_PORT" && { AI_OK=1; break; }
  { [ -n "$AI_PID" ] && kill -0 "$AI_PID" 2>/dev/null; } || break
  sleep 1
done
if [ -n "$GATE_PID" ]; then
  for _ in $(seq 1 10); do
    our_gate "$SHARE_PORT" && { SHARE_OK=1; break; }
    kill -0 "$GATE_PID" 2>/dev/null || break
    sleep 1
  done
fi

URL="http://127.0.0.1:$LIB_PORT/?model=$MODEL&ai=$AI_PORT"
say ""
if [ "$LIB_OK" = 1 ]; then say "  Library:  ready"; else say "  Library:  NOT running (see logs/kiwix-serve.log)"; fi
if [ "$AI_OK" = 1 ]; then say "  AI:       ready (the first answer takes longer while the model loads)"
else say "  AI:       NOT running (see logs/llama-server.log). The library still works."; fi
say ""
say "  Open:     $URL"
say "  AI chat:  http://127.0.0.1:$AI_PORT/"
[ -n "$MAPS_STARTED" ] && say "  Maps:     on the Map tab of the page above"
say ""
if [ "$SHARE_OK" = 1 ]; then
  python3 "$KIT/tools/share.py" banner --root "$KIT" --port "$SHARE_PORT"
  say ""
elif [ -n "$GATE_PID" ]; then
  say "  Sharing:  NOT running (see logs/share.log)"; say ""
fi
say "  Keep this window open. Close it or press Ctrl-C to stop everything."

if [ "$NO_BROWSER" = 0 ] && [ "$LIB_OK" = 1 ]; then
  if command -v open >/dev/null; then open "$URL"; elif command -v xdg-open >/dev/null; then xdg-open "$URL" >/dev/null 2>&1; fi
fi

if [ ${#PIDS[@]} -gt 0 ]; then wait; else say "  (Nothing was started by this window.)"; fi
