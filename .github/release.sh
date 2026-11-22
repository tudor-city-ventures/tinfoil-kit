#!/bin/bash
# Publishes a release of Tinfoil Kit. Every drive installs it at its next SETUP (./kit update), and only if it's
# signed with a key in that drive's tools/release-signers. Run it on the maintainer's own computer, never in CI,
# so that the signing key never goes near GitHub.
#   .github/release.sh key                 make the signing key and add it to tools/release-signers (once)
#   .github/release.sh v1.2.0 NOTES.txt    sign and publish main as v1.2.0, with NOTES.txt as what's new
#   .github/release.sh mac                 set up and try the Mac app's signing (once): it builds the app, Apple
#                                          notarizes it, and a copy lands on the Desktop as if downloaded
# Needs git, ssh-keygen, Go (brew install go) and GitHub's gh, signed in (brew install gh && gh auth login). The Mac
# app, the website's Mac download, goes in only when this Mac can sign and notarize it: that takes Apple's command line
# tools, a Developer ID Application certificate in the keychain and notarytool's password for it (docs/RELEASING.md,
# "Signing the Mac app"). Without it, the release leaves the app out, and people set the kit up with the command their
# AI gives them (site/public/llms.txt), which works on a Mac without Apple's signature.
set -eu
cd "$(dirname "$0")/.."
KEY="${KIT_RELEASE_KEY:-$HOME/.ssh/tinfoilkit-release}"
NS=tinfoilkit-release
die() { echo "release: $*" >&2; exit 1; }
NOTARY="${KIT_MAC_NOTARY:-tinfoilkit}"    # the keychain profile notarytool keeps the password in
mac_identity() { security find-identity -v -p codesigning 2> /dev/null | sed -n 's/.*"\(Developer ID Application: .*\)"$/\1/p' | head -1; }
mac_notary() { xcrun notarytool history --keychain-profile "$NOTARY" > /dev/null 2>&1; }

if [ "${1:-}" = mac ]; then
  [ "$(uname -s)" = Darwin ] || die "the Mac app is built on a Mac"
  xcrun --find notarytool > /dev/null 2>&1 || die "needs Apple's command line tools: run  xcode-select --install"
  id="${KIT_MAC_SIGN:-$(mac_identity)}"
  [ -n "$id" ] || die "this Mac's keychain has no Developer ID Application certificate. docs/RELEASING.md, \"Signing the Mac app\", says how to make one"
  echo "Signing with: $id"
  if ! mac_notary; then
    printf "The email of the Apple account in the developer program: "
    read -r apple_id
    echo "Now paste the app-specific password you made for notarizing. It isn't shown as you paste."
    xcrun notarytool store-credentials "$NOTARY" --apple-id "$apple_id" --team-id "$(echo "$id" | sed 's/.*(\(.*\))$/\1/')" ||
      die "notarytool didn't save the password. Check the email and the password, then run this again"
  fi
  out=$(mktemp -d)
  git archive --format=tar --prefix=TinfoilKit/ HEAD | gzip -n > "$out/kit.tar.gz"
  KIT_MAC_SIGN="$id" KIT_MAC_NOTARY="$NOTARY" mac/build.sh "$out/kit.tar.gz" "$out"
  zip="$HOME/Desktop/TinfoilKit-Mac.zip"
  cp "$out/TinfoilKit-Mac.zip" "$zip"
  xattr -w com.apple.quarantine "0083;$(printf %x "$(date +%s)");Safari;" "$zip"    # as Safari leaves a download
  echo
  echo "It works: $zip is signed, notarized and marked as downloaded. Double-click it, then open Tinfoil Kit."
  echo "macOS should only ask whether to open an app from the internet. From now on every release's Mac download is the app."
  exit 0
fi

if [ "${1:-}" = key ]; then
  [ -e "$KEY" ] || ssh-keygen -t ed25519 -C "Tinfoil Kit releases" -f "$KEY"
  if ! grep -qF "$(cut -d' ' -f2 "$KEY.pub")" tools/release-signers; then
    echo "$NS namespaces=\"$NS\" $(cut -d' ' -f1,2 "$KEY.pub")" >> tools/release-signers
  fi
  echo "tools/release-signers has the key. Commit and push it, then make the first release."
  echo "Back up $KEY and its passphrase in your password manager: without them, no drive can update again."
  exit 0
fi

TAG="${1:-}" NOTES="${2:-}"
echo "$TAG" | grep -Eq '^v[0-9]+\.[0-9]+\.[0-9]+$' || die "usage: .github/release.sh vX.Y.Z NOTES.txt   (or: .github/release.sh key, or mac)"
[ -s "$NOTES" ] || die "write what's new in a file and pass it after the version"
command -v gh > /dev/null || die "needs GitHub's gh: brew install gh && gh auth login"
command -v go > /dev/null || die "needs Go to build the kit's own program: brew install go"
[ -e "$KEY" ] || die "no signing key at $KEY. Make one with: .github/release.sh key (or set KIT_RELEASE_KEY)"
id="${KIT_MAC_SIGN:-$(mac_identity)}"
if [ -n "$id" ] && mac_notary; then
  app=1
else
  app=""
  echo "This Mac can't sign and notarize the Mac app (.github/release.sh mac sets that up), so this release leaves it out."
fi
git fetch -q origin main --tags
[ -z "$(git status --porcelain)" ] || die "commit or stash your changes first"
sha=$(git rev-parse HEAD)
[ "$sha" = "$(git rev-parse origin/main)" ] || die "check out main as it is on GitHub first: git checkout main && git pull"
! git rev-parse -q --verify "refs/tags/$TAG" > /dev/null || die "$TAG already exists"
ci=$(gh run list --commit "$sha" --workflow check.yml --json conclusion --jq '.[0].conclusion')
run=$(gh run list --commit "$sha" --workflow check.yml --json databaseId --jq '.[0].databaseId')
[ "$ci" = success ] || die "the quick gate (check.yml) hasn't passed on this commit (${ci:-no run yet}). A commit a workflow made starts no checks: run check on main (Actions > check > Run workflow), then try again"
python3 -c 'import json, sys; sys.exit(len(json.load(open("tools/pins.json"))) < 2)' ||
  die "tools/pins.json pins no programs: run the pin program builds workflow, then a real-Mac sync and test"
prev=$(git describe --tags --abbrev=0 2> /dev/null || true)

out=$(mktemp -d)
asset="$out/tinfoilkit-$TAG.tar.gz"
# The kit's own program for each computer (tools/tinfoilkit), built from this commit. The same source gives the same
# bytes on any computer, and CI built it too and printed its SHA-256s: they must match, or something on one of the two
# computers changed it.
tools/tinfoilkit/build.sh "$out/programs"
(cd "$out/programs" && shasum -a 256 tinfoilkit-*) | sort > "$out/programs.sha256"
gh run view "$run" --log 2> /dev/null | grep -Eo '[0-9a-f]{64}  tinfoilkit-[a-z0-9.-]+$' | sort -u > "$out/ci.sha256"
[ -s "$out/ci.sha256" ] ||
  die "CI's log for this commit doesn't have the kit's own program's SHA-256s (check.yml prints them): run check on main, then try again"
cmp -s "$out/programs.sha256" "$out/ci.sha256" ||
  die "the kit's own program built here isn't the same as CI's build of this commit (see $out/programs.sha256 and $out/ci.sha256). Don't publish until you know why"
git tag "$TAG"
trap '[ -n "${pushed:-}" ] || git tag -d "$TAG" > /dev/null' EXIT
# The archives are reproducible: git archive of the tag, with the programs built from it in tools/ (build.sh archive),
# so anyone can rebuild them and compare (gzip output can vary by version, so compare the tar).
tools/tinfoilkit/build.sh archive tar "tinfoilkit-$TAG" "$TAG" > "$out/update.tar"
mkdir "$out/inside"
tar -xf "$out/update.tar" -C "$out/inside"
for f in "$out/programs"/tinfoilkit-*; do
  cmp -s "$f" "$out/inside/tinfoilkit-$TAG/tools/$(basename "$f")" || die "the archive's $(basename "$f") isn't the one just built"
done
gzip -n -9 < "$out/update.tar" > "$asset"
ssh-keygen -Y sign -f "$KEY" -n "$NS" "$asset"
# What the setup command in llms.txt fetches (releases/latest/download/NAME): the same kit files from the same tag, as
# the app folder of a folder called TinfoilKit. The tar.gz is for a Mac and Linux, the zip for Windows, and the Mac app,
# when there is one, holds them too. Not signed with the release key, since they're only a first install: ./kit update
# takes the signed archive, which holds just the app folder's files. SHA256SUMS, which is signed, lists them all.
tools/tinfoilkit/build.sh archive zip TinfoilKit/app "$TAG" > "$out/TinfoilKit-Windows.zip"
tools/tinfoilkit/build.sh archive tar TinfoilKit/app "$TAG" > "$out/TinfoilKit.tar"
gzip -n -9 < "$out/TinfoilKit.tar" > "$out/TinfoilKit.tar.gz"
downloads=("$out/TinfoilKit.tar.gz" "$out/TinfoilKit-Windows.zip")
# Drives on the last release check this one with that release's keys, so a key change needs both to accept it.
for ref in "$TAG" $prev; do
  git show "$ref:tools/release-signers" > "$out/signers" 2> /dev/null || continue
  ssh-keygen -Y verify -f "$out/signers" -I "$NS" -n "$NS" -s "$asset.sig" < "$asset" > /dev/null \
    || die "the signature doesn't match a key in $ref's tools/release-signers"
done
# The Mac app, notarized so it opens with a double-click: macOS sends a script from a browser's download to System
# Settings first, which people miss. (A script curl downloaded carries no such mark, so the setup command needs none.)
if [ -n "$app" ]; then
  KIT_MAC_SIGN="$id" KIT_MAC_NOTARY="$NOTARY" mac/build.sh "$asset" "$out/mac" "${TAG#v}" || die "the Mac app didn't build (above is why)"
  mv "$out/mac/TinfoilKit-Mac.zip" "$out/TinfoilKit-Mac.zip"
  # The app's copy of the program carries Apple's signature as well. build.sh verify tells people it's the same program
  # apart from that: make sure it is.
  same=$("$out/programs/tinfoilkit-macos-arm64" compare "$out/programs/tinfoilkit-macos-arm64" \
    "$out/mac/Tinfoil Kit.app/Contents/Resources/kit/tools/tinfoilkit-macos-arm64")
  [ "$same" = "the same apart from the code signature" ] || die "the Mac app's copy of the kit's own program: $same"
  downloads+=("$out/TinfoilKit-Mac.zip")
fi
# The SHA-256 of every file this release publishes, and of the programs as built, signed like the update.
(cd "$out/programs" && shasum -a 256 tinfoilkit-*) > "$out/SHA256SUMS"
(cd "$out" && for f in "$asset" "${downloads[@]}"; do shasum -a 256 "$(basename "$f")"; done) >> "$out/SHA256SUMS"
ssh-keygen -Y sign -f "$KEY" -n "$NS" "$out/SHA256SUMS"

echo
echo "Ready: $TAG, $(git log -1 --format='%h %s' "$sha")"
echo "  $asset and .sig"
echo "  tar SHA-256 $(shasum -a 256 < "$out/update.tar" | cut -d' ' -f1)"
echo "  (rebuild it: tools/tinfoilkit/build.sh archive tar tinfoilkit-$TAG $TAG | shasum -a 256)"
echo "  SHA256SUMS and .sig: the programs and every download"
echo "  downloads for the setup command: TinfoilKit.tar.gz (Mac, Linux), TinfoilKit-Windows.zip"
if [ -n "$app" ]; then
  echo "  and the website's Mac download: TinfoilKit-Mac.zip (the app, signed by $id and notarized)"
else
  echo "  no Mac app: the website's downloads stay \"coming soon\""
fi
echo "What's new:"
sed 's/^/  /' "$NOTES"
echo
echo "Every drive installs this at its next SETUP. Publish only if CI and a real-Mac run"
echo "(./kit sync && ./kit test on a real drive) passed on this commit."
printf "Type %s to publish it: " "$TAG"
read -r answer
[ "$answer" = "$TAG" ] || die "not published"
git push -q origin "$TAG"
pushed=1
gh release create "$TAG" --verify-tag --title "Tinfoil Kit $TAG" --notes-file "$NOTES" "$asset" "$asset.sig" "${downloads[@]}" \
  "$out/SHA256SUMS" "$out/SHA256SUMS.sig" \
  || die "the tag is on GitHub but the release isn't. Finish with: gh release create $TAG --verify-tag --notes-file $NOTES $asset $asset.sig ${downloads[*]} $out/SHA256SUMS $out/SHA256SUMS.sig"
echo "Published $TAG."
