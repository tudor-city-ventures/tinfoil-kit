#!/bin/bash
# Build everything the end-to-end suite's mock internet serves, into tests/work/remote.
# With "drive", also the real Mac, Windows and Linux Vulkan builds the drive test installs (tests/drive_test.sh),
# and the Python SETUP-Windows.bat gets (tests/drive_windows.ps1).
# Linux x86_64 only. Needs internet (GitHub, download.kiwix.org, npm, PyPI) the first time.
# Python deps: pip install gguf numpy libzim playwright && playwright install chromium
set -eo pipefail
TESTS="$(cd "$(dirname "$0")" && pwd)"
W="${KIT_TEST_WORK:-$TESTS/work}"
R="$W/remote"
DL="$W/downloads"      # real upstream files, kept between runs
TMP="$W/tmp"
MAPLIBRE=5.24.1        # the newest 5.x the mock offers; 6.x ships ESM only
BASEMAPS=5.7.2
GH_AUTH=(); [ -n "${GITHUB_TOKEN:-}" ] && GH_AUTH=(-H "Authorization: Bearer $GITHUB_TOKEN")

get() {   # get URL FILE: download once, reuse on later runs. The GitHub token goes to GitHub only.
  [ -s "$2" ] && return
  local auth=(); case "$1" in https://api.github.com/*|https://github.com/*) auth=("${GH_AUTH[@]}") ;; esac
  curl -fsSL --retry 3 "${auth[@]}" -o "$2.part" "$1" || { echo "download failed: $1" >&2; return 1; }
  mv -f "$2.part" "$2"
}
md5() { (cd "$(dirname "$1")" && md5sum "$(basename "$1")" > "$(basename "$1").md5"); }
rand() { python3 -c "import os,sys; sys.stdout.buffer.write(os.urandom($2))" > "$1"; }

rm -rf "$R" "$TMP"
mkdir -p "$DL" "$TMP" "$R"/{zim,gh,gh2,hf/tiny,hf/tiny_v2,hf/two,npm,adoptium,files,geofabrik,release/kiwix-tools,release/kiwix-macos,photon/north-america/usa,maven/com/graphhopper/graphhopper-web/11.1}

echo "== llama.cpp (real Linux CPU build, repacked as two fake nightly builds)"
url=$(curl -fsSL "${GH_AUTH[@]}" "https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=15" |
      python3 -c '
import json, re, sys
# "latest" is a stub release; the builds are on the nightly prereleases, newest first.
# A release still uploading lists only some builds, so take the newest one that has the CPU build.
for rel in json.load(sys.stdin):
    names = {a["name"]: a["browser_download_url"] for a in rel["assets"]}
    # the plain CPU build for x86_64 Linux; skip GPU and other-arch variants
    ok = [n for n in names if re.search(r"bin-ubuntu-x64", n) and n.endswith((".zip", ".tar.gz"))]
    ok = ok or [n for n in names if "ubuntu" in n and "x64" in n and not re.search(r"vulkan|cuda|rocm|sycl|hip|openvino", n)]
    if ok:
        print(names[sorted(ok)[0]])
        break
else:
    sys.exit("no Linux x64 CPU asset in the last 15 llama.cpp releases")')
get "$url" "$DL/$(basename "$url")"
mkdir -p "$TMP/llama"
case "$url" in *.zip) unzip -q "$DL/$(basename "$url")" -d "$TMP/llama";; *) tar -xzf "$DL/$(basename "$url")" -C "$TMP/llama";; esac
bin=$(dirname "$(find "$TMP/llama" -name llama-server -type f | head -1)")
for tag in b99990 b99999; do
  rm -rf "$TMP/pack" && mkdir -p "$TMP/pack/build" && cp -a "$bin" "$TMP/pack/build/bin" && echo "$tag" > "$TMP/pack/build/bin/VERSION"
  tar -czf "$R/gh/llama-$tag-bin-ubuntu-x64.tar.gz" -C "$TMP/pack" build
done

echo "== kiwix-tools (real Linux build, published under two versions)"
get https://download.kiwix.org/release/kiwix-tools/kiwix-tools_linux-x86_64.tar.gz "$DL/kiwix-tools.tar.gz"
mkdir -p "$TMP/kiwix" && tar -xzf "$DL/kiwix-tools.tar.gz" -C "$TMP/kiwix"
for v in 3.8.2 3.9.0; do
  rm -rf "$TMP/pack" && mkdir -p "$TMP/pack" && cp -a "$TMP"/kiwix/*/ "$TMP/pack/kiwix-tools_linux-x86_64-$v"
  tar -czf "$R/release/kiwix-tools/kiwix-tools_linux-x86_64-$v.tar.gz" -C "$TMP/pack" "kiwix-tools_linux-x86_64-$v"
done
echo "fake dmg" > "$R/release/kiwix-macos/kiwix-macos_3.8.0.dmg"

echo "== fake Java and pmtiles (the scripts in tests/fakes)"
rm -rf "$TMP/pack" && mkdir -p "$TMP/pack/jdk-21.0.9+10-jre/bin" && cp "$TESTS/fakes/java" "$TMP/pack/jdk-21.0.9+10-jre/bin/java"
tar -czf "$R/adoptium/OpenJDK21U-jre_x64_linux_hotspot_21.0.9_10.tar.gz" -C "$TMP/pack" "jdk-21.0.9+10-jre"
rm -rf "$TMP/pack" && mkdir -p "$TMP/pack" && cp "$TESTS/fakes/pmtiles" "$TMP/pack/pmtiles"
tar -czf "$R/gh2/go-pmtiles_1.31.2_Linux_x86_64.tar.gz" -C "$TMP/pack" pmtiles
get https://raw.githubusercontent.com/protomaps/go-pmtiles/main/pmtiles/fixtures/test_fixture_1.pmtiles "$W/test_fixture_1.pmtiles"

echo "== map servers and data (placeholders; the fakes run the mocks instead)"
echo "fake photon 1.3.0" > "$R/gh2/photon-1.3.0.jar"
echo "fake photon 1.2.1" > "$R/gh2/photon-1.2.1.jar"
G="$R/maven/com/graphhopper/graphhopper-web"
echo "fake graphhopper 11.1" > "$G/11.1/graphhopper-web-11.1.jar"
sha1sum "$G/11.1/graphhopper-web-11.1.jar" | cut -d' ' -f1 > "$G/11.1/graphhopper-web-11.1.jar.sha1"
printf '<metadata><versioning><versions><version>10.2</version><version>11.0</version><version>11.1</version><version>12.0-pre1</version></versions></versioning></metadata>\n' > "$G/maven-metadata.xml"
rand "$R/geofabrik/us-northeast-latest.osm.pbf" 2000000 && md5 "$R/geofabrik/us-northeast-latest.osm.pbf"
mkdir -p "$TMP/photon/photon_data" && echo "fake index" > "$TMP/photon/photon_data/README"
P="$R/photon/north-america/usa/photon-db-usa-1.3-latest.tar.bz2"
tar -cjf "$P" -C "$TMP/photon" photon_data && md5 "$P"
rand "$R/files/guide.pdf" 300000

echo "== map viewer: MapLibre and Protomaps style from npm, fonts and icons from basemaps-assets"
get "https://registry.npmjs.org/maplibre-gl/-/maplibre-gl-$MAPLIBRE.tgz" "$R/npm/maplibre-gl-$MAPLIBRE.tgz"
get "https://registry.npmjs.org/@protomaps/basemaps/-/basemaps-$BASEMAPS.tgz" "$R/npm/basemaps-$BASEMAPS.tgz"
sha=$(curl -fsSL "${GH_AUTH[@]}" https://api.github.com/repos/protomaps/basemaps-assets/commits/main | python3 -c 'import json,sys; print(json.load(sys.stdin)["sha"])')
get "https://github.com/protomaps/basemaps-assets/archive/$sha.tar.gz" "$DL/basemaps-assets-$sha.tar.gz"
# keep only what the page embeds, so the fixture stays small
B="basemaps-assets-$sha"
tar -xzf "$DL/$B.tar.gz" -C "$TMP" "$B/fonts/Noto Sans Regular" "$B/fonts/Noto Sans Medium" "$B/fonts/Noto Sans Italic" "$B/sprites/v4"
tar -czf "$R/gh2/$B.tar.gz" -C "$TMP" "$B"
echo "$sha" > "$R/gh2/basemaps-assets.sha"

echo "== tiny models and test books"
python3 "$TESTS/make_tiny_model.py" "$R/hf/tiny/Tiny-Q4_K_M.gguf" 0
python3 "$TESTS/make_tiny_model.py" "$R/hf/tiny/Tiny-Q8_0.gguf" 1
python3 "$TESTS/make_tiny_model.py" "$R/hf/tiny_v2/Tiny-Q4_K_M.gguf" 2
cp "$R/hf/tiny/Tiny-Q8_0.gguf" "$R/hf/tiny_v2/"
python3 "$TESTS/make_tiny_model.py" "$R/hf/two/Two-Q4_K_M.gguf" 3
(cd "$R/zim" && python3 "$TESTS/make_zims.py")

if [ "${1:-}" = drive ]; then
  echo "== drive test: the Mac, Windows and Linux builds kit.json names, as published (one version each)"
  curl -fsSL "${GH_AUTH[@]}" "https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=15" > "$TMP/llama.json"
  for suffix in macos-arm64.tar.gz win-vulkan-x64.zip ubuntu-vulkan-x64.tar.gz; do
    url=$(python3 -c '
import json, sys
for rel in json.load(open(sys.argv[1])):    # newest nightly that has this build
    hits = sorted(a["browser_download_url"] for a in rel["assets"] if a["name"].endswith("-bin-" + sys.argv[2]))
    if hits:
        print(hits[0])
        break
else:
    sys.exit("no llama.cpp build ends in -bin-" + sys.argv[2])' "$TMP/llama.json" "$suffix")
    get "$url" "$DL/$(basename "$url")"
    cp "$DL/$(basename "$url")" "$R/gh/llama-b99990-bin-$suffix"
  done
  curl -fsSL https://download.kiwix.org/release/kiwix-tools/ > "$TMP/kiwix.html"
  for plat in macos-arm64.tar.gz win-x86_64.zip; do
    name=$(python3 -c '
import re, sys
plat, ext = sys.argv[2].split(".", 1)
found = re.findall(r"kiwix-tools_%s-([0-9.]+)\.%s" % (re.escape(plat), re.escape(ext)), open(sys.argv[1]).read())
if not found:
    sys.exit("no kiwix-tools build for " + sys.argv[2])
newest = max(set(found), key=lambda v: [int(x) for x in v.split(".")])
print("kiwix-tools_%s-%s.%s" % (plat, newest, ext))' "$TMP/kiwix.html" "$plat")
    get "https://download.kiwix.org/release/kiwix-tools/$name" "$DL/$name"
    cp "$DL/$name" "$R/release/kiwix-tools/kiwix-tools_${plat%%.*}-3.8.2.${plat#*.}"
  done
  # The very Python SETUP-Windows.bat names, which must match the checksum there
  pyv=$(tr -d '\r' < "$TESTS/../SETUP-Windows.bat" | sed -n 's/^set "PYV=\(.*\)"$/\1/p')
  pysha=$(tr -d '\r' < "$TESTS/../SETUP-Windows.bat" | sed -n 's/^set "PYSHA=\(.*\)"$/\1/p')
  get "https://api.nuget.org/v3-flatcontainer/python/$pyv/python.$pyv.nupkg" "$DL/python.$pyv.nupkg"
  mkdir -p "$R/nuget" && cp "$DL/python.$pyv.nupkg" "$R/nuget/python.nupkg"
  python3 -c 'import hashlib, sys; sys.exit(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest() != sys.argv[2])' \
    "$R/nuget/python.nupkg" "$pysha" || { echo "python.$pyv.nupkg doesn't match the checksum in SETUP-Windows.bat"; exit 1; }
fi

rm -rf "$TMP"
(cd "$R" && find . -type f | sed 's|^\./||' | sort | while read -r f; do printf '%s\t%s bytes\n' "$f" "$(wc -c < "$f" | tr -d ' ')"; done) > "$W/FIXTURES.txt"
echo "fixtures ready in $R ($(wc -l < "$W/FIXTURES.txt") files)"
