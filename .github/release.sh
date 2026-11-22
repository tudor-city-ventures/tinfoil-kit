#!/bin/bash
# Publishes a release of Tinfoil Kit. Every drive installs it at its next SETUP (./kit update), and only if it's
# signed with a key in that drive's tools/release-signers. Run it on the maintainer's own computer, never in CI,
# so that the signing key never goes near GitHub.
#   .github/release.sh key                 make the signing key and add it to tools/release-signers (once)
#   .github/release.sh v1.2.0 NOTES.txt    sign and publish main as v1.2.0, with NOTES.txt as what's new
# Needs git, ssh-keygen and GitHub's gh, signed in (brew install gh && gh auth login).
set -eu
cd "$(dirname "$0")/.."
KEY="${KIT_RELEASE_KEY:-$HOME/.ssh/tinfoilkit-release}"
NS=tinfoilkit-release
die() { echo "release: $*" >&2; exit 1; }

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
echo "$TAG" | grep -Eq '^v[0-9]+\.[0-9]+\.[0-9]+$' || die "usage: .github/release.sh vX.Y.Z NOTES.txt   (or: .github/release.sh key)"
[ -s "$NOTES" ] || die "write what's new in a file and pass it after the version"
command -v gh > /dev/null || die "needs GitHub's gh: brew install gh && gh auth login"
[ -e "$KEY" ] || die "no signing key at $KEY. Make one with: .github/release.sh key (or set KIT_RELEASE_KEY)"
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
# Drives on the last release check this one with that release's keys, so a key change needs both to accept it.
for ref in "$TAG" $prev; do
  git show "$ref:tools/release-signers" > "$out/signers" 2> /dev/null || continue
  ssh-keygen -Y verify -f "$out/signers" -I "$NS" -n "$NS" -s "$asset.sig" < "$asset" > /dev/null \
    || die "the signature doesn't match a key in $ref's tools/release-signers"
done

echo
echo "Ready: $TAG, $(git log -1 --format='%h %s' "$sha")"
echo "  $asset and .sig"
echo "  tar SHA-256 $(gunzip -c "$asset" | shasum -a 256 | cut -d' ' -f1)"
echo "  (rebuild it: git archive --format=tar --prefix=tinfoilkit-$TAG/ $TAG | shasum -a 256)"
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
gh release create "$TAG" --verify-tag --title "Tinfoil Kit $TAG" --notes-file "$NOTES" "$asset" "$asset.sig" \
  || die "the tag is on GitHub but the release isn't. Finish with: gh release create $TAG --verify-tag --notes-file $NOTES $asset $asset.sig"
echo "Published $TAG."
