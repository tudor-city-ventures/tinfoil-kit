#!/bin/bash
# Starts the offline library server (kiwix-serve) and the AI server (llama-server),
# then opens the portal in the browser. Started by START-HERE.command.
#
#   bash tools/launch.sh [--share] [--model=NAME] [--no-browser]
#
#   --share       also serve phones/laptops on the same Wi-Fi or hotspot
#   --model=NAME  model to load first (a folder name in models/)
#   --no-browser  don't open the browser
#   --no-maps     don't start the map servers (saves about 5 GB of memory)
# (no "set -u": macOS ships bash 3.2, which mishandles empty arrays with it)
KIT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$KIT" || exit 1
mkdir -p "$KIT/logs" "$KIT/.kit"
SHARE=0; NO_BROWSER=0; NO_MAPS=0; MODEL=""
for a in "$@"; do
  case "$a" in
    --share) SHARE=1 ;;
    --no-browser) NO_BROWSER=1 ;;
    --no-maps) NO_MAPS=1 ;;
    --model=*) MODEL="${a#*=}" ;;
  esac
done

say() { printf '%s\n' "$*"; }
setting() { # read a simple "key": value from kit.json without needing python
  sed -n "s/.*\"$1\"[[:space:]]*:[[:space:]]*\"\{0,1\}\([^\",}]*\)\"\{0,1\}.*/\1/p" "$KIT/kit.json" 2>/dev/null | head -1
}
LIB_PORT="$(setting library_port)"; LIB_PORT="${LIB_PORT:-8888}"
AI_PORT="$(setting ai_port)"; AI_PORT="${AI_PORT:-8080}"
CTX="$(setting context_size)"; CTX="${CTX:-16384}"
MODEL="${MODEL:-$(setting default_model)}"
TILES_PORT="$(setting tiles_port)"; TILES_PORT="${TILES_PORT:-8090}"
GEO_PORT="$(setting geocoder_port)"; GEO_PORT="${GEO_PORT:-2322}"
ROUTE_PORT="$(setting routing_port)"; ROUTE_PORT="${ROUTE_PORT:-8989}"
GEO_HEAP="$(setting geocoder_heap)"; GEO_HEAP="${GEO_HEAP:-3g}"
ROUTE_HEAP="$(setting routing_heap)"; ROUTE_HEAP="${ROUTE_HEAP:-2g}"

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

up() { curl -s -o /dev/null --max-time 2 "$1"; }

KIWIX="${KIT_KIWIX_TOOLS_BIN:-$(pick_bin kiwix-tools kiwix-serve)}"
LLAMA="${KIT_LLAMACPP_BIN:-$(pick_bin llama.cpp llama-server)}"
shopt -s nullglob
ZIMS=("$KIT"/library/*.zim)
MODELS=("$KIT"/models/*/)
shopt -u nullglob

say ""
say "  OFFLINE KIT"
say "  ==========="
[ -n "$KIWIX" ] || say "  ! Library server not found for $PLAT (bin/kiwix-tools-$PLAT). Run ./kit sync while online."
[ -n "$LLAMA" ] || say "  ! AI server not found for $PLAT (bin/llama.cpp-$PLAT). Run ./kit sync while online."
[ ${#ZIMS[@]} -gt 0 ] || say "  ! No library files in library/. Run ./kit sync while online."
[ ${#MODELS[@]} -gt 0 ] || say "  ! No models in models/. Run ./kit sync while online."
if [ ${#MODELS[@]} -gt 0 ] && [ ! -d "$KIT/models/$MODEL" ]; then
  MODEL="$(basename "${MODELS[0]}")"   # default model missing: fall back to whatever is there
fi

HOST=127.0.0.1
LAN_IP=""
if [ "$SHARE" = 1 ]; then
  HOST=0.0.0.0
  # Wi-Fi or Ethernet, else the Mac's own network when Internet Sharing is on (bridge100), else Linux
  LAN_IP="$( (ipconfig getifaddr en0 || ipconfig getifaddr en1 || ipconfig getifaddr bridge100 || hostname -I | awk '{print $1}') 2>/dev/null | head -1)"
fi

PIDS=()
cleanup() {
  [ ${#PIDS[@]} -gt 0 ] && kill "${PIDS[@]}" 2>/dev/null
  say ""; say "  Stopped."
}
trap cleanup EXIT
trap 'exit 0' INT TERM HUP

# --- library
if up "http://127.0.0.1:$LIB_PORT/"; then
  say "  Library already running on port $LIB_PORT."
elif [ -n "$KIWIX" ] && [ ${#ZIMS[@]} -gt 0 ]; then
  # The page ./kit sync builds has the map inside; the bare template has no map. A newer template
  # (kit code updated, no sync since) shows up after the next sync, which rebuilds the page.
  PORTAL="$KIT/.kit/portal.html"
  [ -f "$PORTAL" ] || PORTAL="$KIT/tools/portal.html"
  KARGS=(--port "$LIB_PORT" --customIndex "$PORTAL" --threads 4)
  [ "$SHARE" = 1 ] || KARGS+=(--address 127.0.0.1)
  "$KIWIX" --help 2>&1 | grep -q -- --skipInvalid && KARGS+=(--skipInvalid)
  "$KIWIX" "${KARGS[@]}" "${ZIMS[@]}" > "$KIT/logs/kiwix-serve.log" 2>&1 &
  PIDS+=($!)
  say "  Starting library (${#ZIMS[@]} books)..."
fi

# --- AI
if up "http://127.0.0.1:$AI_PORT/v1/models"; then
  say "  AI already running on port $AI_PORT."
elif [ -n "$LLAMA" ] && [ ${#MODELS[@]} -gt 0 ]; then
  # Browsers accept exactly one allowed origin (llama-server would echo a list verbatim):
  # the portal at 127.0.0.1 locally, or any origin when sharing with other devices.
  CORS="http://127.0.0.1:$LIB_PORT"
  [ "$SHARE" = 1 ] && CORS="*"
  PRESET="$KIT/.kit/presets.ini"
  printf 'version = 1\n\n[%s]\nload-on-startup = true\n' "$MODEL" > "$PRESET"
  "$LLAMA" --models-dir "$KIT/models" --models-preset "$PRESET" --models-max 1 -c "$CTX" \
    --host "$HOST" --port "$AI_PORT" --cors-origins "$CORS" > "$KIT/logs/llama-server.log" 2>&1 &
  PIDS+=($!)
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
  IFACE=127.0.0.1; [ "$SHARE" = 1 ] && IFACE=0.0.0.0
  if [ -n "$PMTILES" ] && [ -f "$KIT/maps/tiles/basemap.pmtiles" ] && ! up "http://127.0.0.1:$TILES_PORT/basemap.json"; then
    "$PMTILES" serve "$KIT/maps/tiles" --port "$TILES_PORT" --interface "$IFACE" --cors '*' > "$KIT/logs/tiles.log" 2>&1 &
    PIDS+=($!); MAPS_STARTED="$MAPS_STARTED map"
  fi
  if [ -n "$JAVA" ] && [ -n "$PHOTON_JAR" ] && [ -d "$KIT/maps/geocoder/photon_data" ] && ! up "http://127.0.0.1:$GEO_PORT/status"; then
    "$JAVA" "-Xmx$GEO_HEAP" -jar "$PHOTON_JAR" serve -data-dir "$KIT/maps/geocoder" -listen-ip "$IFACE" \
      -listen-port "$GEO_PORT" -cors-any > "$KIT/logs/geocoder.log" 2>&1 &
    PIDS+=($!); MAPS_STARTED="$MAPS_STARTED address-search"
  fi
  if [ -n "$JAVA" ] && [ -n "$GH_JAR" ] && [ -f "$KIT/maps/routing/graph-cache/properties" ] && ! up "http://127.0.0.1:$ROUTE_PORT/health"; then
    (cd "$KIT/maps/routing" && exec "$JAVA" "-Xmx$ROUTE_HEAP" \
      "-Ddw.server.application_connectors[0].bind_host=$IFACE" "-Ddw.server.application_connectors[0].port=$ROUTE_PORT" \
      -jar "$GH_JAR" server gh-serve.yml) > "$KIT/logs/routing.log" 2>&1 &
    PIDS+=($!); MAPS_STARTED="$MAPS_STARTED directions"
  fi
  [ -n "$MAPS_STARTED" ] && say "  Starting maps:$MAPS_STARTED (address search and directions take up to a minute)..."
fi

# keep the Mac awake while the kit runs (the screen may still sleep)
if [ "$(uname -s)" = Darwin ] && command -v caffeinate >/dev/null; then
  caffeinate -i -w $$ & PIDS+=($!)
fi

for _ in $(seq 1 60); do up "http://127.0.0.1:$LIB_PORT/" && break; sleep 1; done
LIB_OK=0; up "http://127.0.0.1:$LIB_PORT/" && LIB_OK=1
AI_OK=0
for _ in $(seq 1 30); do up "http://127.0.0.1:$AI_PORT/v1/models" && { AI_OK=1; break; }; sleep 1; done

URL="http://127.0.0.1:$LIB_PORT/?model=$MODEL&ai=$AI_PORT"
say ""
if [ "$LIB_OK" = 1 ]; then say "  Library:  ready"; else say "  Library:  NOT running (see logs/kiwix-serve.log)"; fi
if [ "$AI_OK" = 1 ]; then say "  AI:       ready (the first answer takes longer while the model loads)"
else say "  AI:       NOT running (see logs/llama-server.log). The library still works."; fi
say ""
say "  Open:     $URL"
[ -n "$LAN_IP" ] && say "  Others on this Wi-Fi/hotspot:  http://$LAN_IP:$LIB_PORT/?model=$MODEL&ai=$AI_PORT"
say "  AI chat:  http://127.0.0.1:$AI_PORT/"
[ -n "$MAPS_STARTED" ] && say "  Maps:     on the Map tab of the page above"
say ""
say "  Keep this window open. Close it or press Ctrl-C to stop everything."

if [ "$NO_BROWSER" = 0 ] && [ "$LIB_OK" = 1 ]; then
  if command -v open >/dev/null; then open "$URL"; elif command -v xdg-open >/dev/null; then xdg-open "$URL" >/dev/null 2>&1; fi
fi

if [ ${#PIDS[@]} -gt 0 ]; then wait; else say "  (Nothing was started by this window.)"; fi
