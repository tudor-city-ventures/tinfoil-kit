#!/bin/bash
# Builds Tinfoil Kit's program (this folder) for each kind of computer the kit runs on: tinfoilkit-macos-arm64,
# tinfoilkit-linux-x64 and tinfoilkit-windows-x64.exe. Go fetches the Go version pinned here and checks it against
# Go's checksum database, and the same source builds the same bytes on any computer, so anyone can rebuild a
# release's copies and compare them.
#   tools/tinfoilkit/build.sh [OUT]                        into OUT (tools/ if not given)
#   tools/tinfoilkit/build.sh archive FORMAT PREFIX REF    git archive of REF's kit/, with REF's programs in its
#                                                          tools/: the kit as people download it (tar or zip, to
#                                                          stdout)
#   tools/tinfoilkit/build.sh verify [SHA256SUMS]          rebuild from this source and compare with the programs in
#                                                          tools/, and with a release's SHA256SUMS if given
#   tools/tinfoilkit/build.sh check                        gofmt, go vet and the Go tests
# Needs Go 1.21 or newer to start from (brew install go, or https://go.dev/dl/), and the internet the first time.
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
top="$(cd "$here/../.." && pwd)"    # the kit's code: the app folder, or a git checkout's kit/
export GOTOOLCHAIN=go1.27.4 CGO_ENABLED=0
TARGETS="darwin/arm64/macos-arm64 linux/amd64/linux-x64 windows/amd64/windows-x64.exe"
command -v go > /dev/null || { echo "build.sh: needs Go: brew install go, or https://go.dev/dl/" >&2; exit 1; }

build() { # SOURCE OUT
  local t goos goarch name
  for t in $TARGETS; do
    IFS=/ read -r goos goarch name <<< "$t"
    (cd "$1" && GOOS="$goos" GOARCH="$goarch" go build -trimpath -buildvcs=false -ldflags "-s -w -buildid=" \
      -o "$2/tinfoilkit-$name" .)
  done
}

sha() { if command -v sha256sum > /dev/null; then sha256sum "$1"; else shasum -a 256 "$1"; fi | cut -d' ' -f1; }

if [ "${1:-}" = verify ]; then
  sums="${2:-}"
  [ -z "$sums" ] || [ -f "$sums" ] || { echo "build.sh: no file $sums" >&2; exit 2; }
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  build "$here" "$tmp"
  case "$(uname -s)-$(uname -m)" in
    Darwin-arm64) me="$tmp/tinfoilkit-macos-arm64" ;;
    Linux-x86_64) me="$tmp/tinfoilkit-linux-x64" ;;
    *) me="" ;;
  esac
  bad=0
  for f in "$tmp"/tinfoilkit-*; do
    name="$(basename "$f")" want="$(sha "$f")"
    echo "$name, built from this source: $want"
    if [ -n "$sums" ]; then
      if grep -q "^$want  $name\$" "$sums"; then echo "  the same as in $sums"; else echo "  NOT what $sums says"; bad=1; fi
    fi
    have="$top/tools/$name"
    [ -f "$have" ] || continue
    if [ "$(sha "$have")" = "$want" ]; then
      echo "  the same as tools/$name"
    elif [ -n "$me" ] && [ "$("$me" compare "$f" "$have")" = "the same apart from the code signature" ]; then
      echo "  the same as tools/$name, apart from the code signature Apple's signing put on the Mac app's copy"
    else
      echo "  DIFFERENT from tools/$name"
      bad=1
    fi
  done
  [ "$bad" = 0 ] && echo "All the same." || echo "Not the same: see above."
  exit "$bad"
fi

if [ "${1:-}" = check ]; then
  cd "$here" || exit 1
  bad="$("$(go env GOROOT)/bin/gofmt" -l .)"
  [ -z "$bad" ] || { echo "build.sh: not formatted, run gofmt -w on: $bad" >&2; exit 1; }
  go vet ./... && go test ./...
  exit
fi

if [ "${1:-}" = archive ]; then
  fmt="$2" prefix="$3" ref="$4"
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  git -C "$top" archive --format=tar "$ref" tools/tinfoilkit | tar -xf - -C "$tmp"   # REF's source, not the folder's
  build "$tmp/tools/tinfoilkit" "$tmp"
  # Run in kit/, git archive takes kit/ alone; a release also carries REF's license, README and THIRD-PARTY.md from
  # beside it (the GUIDE and SETUP point to it).
  mkdir "$tmp/x"
  git -C "$top/.." archive --format=tar "$ref" LICENSE README.md THIRD-PARTY.md | tar -xf - -C "$tmp/x"
  git -C "$top" archive --format="$fmt" --prefix="$prefix/tools/" --add-file="$tmp/tinfoilkit-macos-arm64" \
    --add-file="$tmp/tinfoilkit-linux-x64" --add-file="$tmp/tinfoilkit-windows-x64.exe" --prefix="$prefix/" \
    --add-file="$tmp/x/LICENSE" --add-file="$tmp/x/README.md" --add-file="$tmp/x/THIRD-PARTY.md" "$ref"
  exit 0
fi
out="${1:-$here/..}"
mkdir -p "$out"
build "$here" "$(cd "$out" && pwd)"
