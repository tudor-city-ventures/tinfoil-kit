#!/bin/bash
# Publishes a release of Tinfoil Kit. Every drive installs it at its next SETUP (./kit update), and only if it's
# signed with a key in that drive's tools/release-signers. Run it on the maintainer's own computer, never in CI,
# so that the signing key never goes near GitHub.
#   .github/release.sh key                 make the signing key and add it to tools/release-signers (once)
#   .github/release.sh v1.2.0 NOTES.txt    sign and publish main as v1.2.0, with NOTES.txt as what's new
#   .github/release.sh mac                 set up and try the Mac app's signing (once): it builds the app, Apple
#                                          notarizes it, and a copy lands on the Desktop as if downloaded
# Needs git, ssh-keygen and GitHub's gh, signed in (brew install gh && gh auth login). And for the Mac download, the
# Tinfoil Kit app: a Mac with Apple's command line tools, a Developer ID Application certificate in its keychain and
# notarytool's password for it (docs/HANDOFF.md, "The Mac app").
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
  [ -n "$id" ] || die "this Mac's keychain has no Developer ID Application certificate. docs/HANDOFF.md, \"The Mac app\", says how to make one"
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
[ -e "$KEY" ] || die "no signing key at $KEY. Make one with: .github/release.sh key (or set KIT_RELEASE_KEY)"
id="${KIT_MAC_SIGN:-$(mac_identity)}"
[ -n "$id" ] && mac_notary ||
  die "the Mac download is the Tinfoil Kit app, and this Mac can't sign and notarize it yet. Set that up once: .github/release.sh mac"
git fetch -q origin main --tags
[ -z "$(git status --porcelain)" ] || die "commit or stash your changes first"
sha=$(git rev-parse HEAD)
[ "$sha" = "$(git rev-parse origin/main)" ] || die "check out main as it is on GitHub first: git checkout main && git pull"
! git rev-parse -q --verify "refs/tags/$TAG" > /dev/null || die "$TAG already exists"
ci=$(gh run list --commit "$sha" --workflow check.yml --json conclusion --jq '.[0].conclusion')
[ "$ci" = success ] || die "the quick gate (check.yml) hasn't passed on this commit (${ci:-no run yet}). A commit a workflow made starts no checks: run check on main (Actions > check > Run workflow), then try again"
python3 -c 'import json, sys; sys.exit(len(json.load(open("tools/pins.json"))) < 2)' ||
  die "tools/pins.json pins no programs: run the pin program builds workflow, then a real-Mac sync and test"
prev=$(git describe --tags --abbrev=0 2> /dev/null || true)

out=$(mktemp -d)
asset="$out/tinfoilkit-$TAG.tar.gz"
git tag "$TAG"
trap '[ -n "${pushed:-}" ] || git tag -d "$TAG" > /dev/null' EXIT
# git archive is reproducible: anyone can rebuild the tar from the tag and compare (gzip output can vary by version).
git archive --format=tar --prefix="tinfoilkit-$TAG/" "$TAG" | gzip -n -9 > "$asset"
ssh-keygen -Y sign -f "$KEY" -n "$NS" "$asset"
# What the website's download buttons and llms.txt fetch (releases/latest/download/NAME): the same kit files from the
# same tag, in a folder called TinfoilKit (on a Mac, inside the app); the tar.gz is for Linux and the command line.
# Not signed with the release key, since they're only a first install: ./kit update takes the signed archive.
git archive --format=zip --prefix=TinfoilKit/ "$TAG" > "$out/TinfoilKit-Windows.zip"
git archive --format=tar --prefix=TinfoilKit/ "$TAG" | gzip -n -9 > "$out/TinfoilKit.tar.gz"
downloads=("$out/TinfoilKit-Mac.zip" "$out/TinfoilKit-Windows.zip" "$out/TinfoilKit.tar.gz")
# Drives on the last release check this one with that release's keys, so a key change needs both to accept it.
for ref in "$TAG" $prev; do
  git show "$ref:tools/release-signers" > "$out/signers" 2> /dev/null || continue
  ssh-keygen -Y verify -f "$out/signers" -I "$NS" -n "$NS" -s "$asset.sig" < "$asset" > /dev/null \
    || die "the signature doesn't match a key in $ref's tools/release-signers"
done
# The Mac download is the app, notarized so it opens with a double-click: macOS sends a script from the internet to
# System Settings first, which people miss.
KIT_MAC_SIGN="$id" KIT_MAC_NOTARY="$NOTARY" mac/build.sh "$asset" "$out/mac" "${TAG#v}" || die "the Mac app didn't build (above is why)"
mv "$out/mac/TinfoilKit-Mac.zip" "$out/TinfoilKit-Mac.zip"

echo
echo "Ready: $TAG, $(git log -1 --format='%h %s' "$sha")"
echo "  $asset and .sig"
echo "  tar SHA-256 $(gunzip -c "$asset" | shasum -a 256 | cut -d' ' -f1)"
echo "  (rebuild it: git archive --format=tar --prefix=tinfoilkit-$TAG/ $TAG | shasum -a 256)"
echo "  downloads for the website: TinfoilKit-Mac.zip (the app, signed by $id and notarized), TinfoilKit-Windows.zip,"
echo "  TinfoilKit.tar.gz"
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
  || die "the tag is on GitHub but the release isn't. Finish with: gh release create $TAG --verify-tag --notes-file $NOTES $asset $asset.sig ${downloads[*]}"
echo "Published $TAG."
