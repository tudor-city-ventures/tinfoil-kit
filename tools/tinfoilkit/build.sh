#!/bin/bash
# Builds Tinfoil Kit's program (this folder) for each kind of computer the kit runs on: tinfoilkit-macos-arm64,
# tinfoilkit-linux-x64 and tinfoilkit-windows-x64.exe. Go fetches the Go version pinned here and checks it against
# Go's checksum database, and the same source builds the same bytes on any computer, so anyone can rebuild a
# release's copies and compare them.
#   tools/tinfoilkit/build.sh [OUT]                        into OUT (tools/ if not given)
#   tools/tinfoilkit/build.sh archive FORMAT PREFIX REF    git archive of REF, with REF's programs in its tools/:
#                                                          the kit as people download it (tar or zip, to stdout)
#   tools/tinfoilkit/build.sh check                        gofmt, go vet and the Go tests
# Needs Go 1.21 or newer to start from (brew install go, or https://go.dev/dl/), and the internet the first time.
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
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
  git -C "$here" archive --format=tar "$ref" tools/tinfoilkit | tar -xf - -C "$tmp"   # REF's source, not the folder's
  build "$tmp/tools/tinfoilkit" "$tmp"
  git -C "$here" archive --format="$fmt" --prefix="$prefix/tools/" --add-file="$tmp/tinfoilkit-macos-arm64" \
    --add-file="$tmp/tinfoilkit-linux-x64" --add-file="$tmp/tinfoilkit-windows-x64.exe" --prefix="$prefix/" "$ref"
  exit 0
fi
out="${1:-$here/..}"
mkdir -p "$out"
build "$here" "$(cd "$out" && pwd)"
