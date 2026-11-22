#!/bin/bash
# Builds "Tinfoil Kit.app", the Mac app (TinfoilKit.m and app.sh around a copy of the kit), and zips it as
# TinfoilKit-Mac.zip, the website's Mac download. Runs on a Mac with Apple's command line tools.
#   mac/build.sh KIT OUT [VERSION]
# KIT is the kit: a folder, or a release archive with one top folder. KIT_MAC_SIGN names a Developer ID Application
# certificate in the keychain: the app is signed with it for Gatekeeper (hardened runtime, secure timestamp). Add
# KIT_MAC_NOTARY, a notarytool keychain profile, and Apple notarizes it and the ticket is stapled on, so it opens on
# any Mac, offline too. Without them it's signed ad hoc, which this Mac and CI run and other Macs refuse.
# .github/release.sh builds each release's with this.
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
src="${1:?usage: mac/build.sh KIT OUT [VERSION]}" out="${2:?usage: mac/build.sh KIT OUT [VERSION]}" version="${3:-0.0.0}"
app="$out/Tinfoil Kit.app"
res="$app/Contents/Resources"
die() { echo "mac/build.sh: $*" >&2; exit 1; }

rm -rf "$app" "$out/TinfoilKit-Mac.zip"
mkdir -p "$app/Contents/MacOS" "$res/kit"
if [ -d "$src" ]; then cp -R "$src/." "$res/kit/"; else tar -xzf "$src" -C "$res/kit" --strip-components 1; fi
[ -f "$res/kit/SETUP.command" ] && [ -f "$res/kit/tools/pins.json" ] || die "$src isn't a kit"
clang -arch arm64 -mmacosx-version-min=12.0 -fobjc-arc -O2 -Wall -Wno-deprecated-declarations -framework Cocoa \
  -o "$app/Contents/MacOS/Tinfoil Kit" "$here/TinfoilKit.m"
cp "$here/app.sh" "$here/AppIcon.icns" "$res/"
cat > "$app/Contents/Info.plist" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key><string>en</string>
  <key>CFBundleDisplayName</key><string>Tinfoil Kit</string>
  <key>CFBundleExecutable</key><string>Tinfoil Kit</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundleIdentifier</key><string>com.tinfoilkit.TinfoilKit</string>
  <key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
  <key>CFBundleName</key><string>Tinfoil Kit</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$version</string>
  <key>CFBundleVersion</key><string>$version</string>
  <key>LSApplicationCategoryType</key><string>public.app-category.reference</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSHumanReadableCopyright</key><string>Tudor City Ventures LLC. MIT License.</string>
  <key>NSRemovableVolumesUsageDescription</key><string>A kit on a drive runs from there: its AI, books and maps are on it.</string>
  <key>NSLocalNetworkUsageDescription</key><string>When you share the kit on your home network, phones and laptops there open it with its access code.</string>
</dict>
</plist>
EOF
plutil -lint -s "$app/Contents/Info.plist" || die "Info.plist doesn't parse"

# codesign refuses files carrying Finder info or resource forks, which a copied download can have.
xattr -cr "$app"
if [ -n "${KIT_MAC_SIGN:-}" ]; then
  # The kit's own program for a Mac is code too, which Apple checks: it's signed first, and the app seals it in. Its
  # signature is all that changes (tinfoilkit compare checks the rest). Unsigned by us, it keeps Go's ad hoc one.
  prog="$res/kit/tools/tinfoilkit-macos-arm64"
  [ ! -f "$prog" ] || codesign --force --options runtime --timestamp --sign "$KIT_MAC_SIGN" "$prog"
  codesign --force --options runtime --timestamp --sign "$KIT_MAC_SIGN" "$app"
else
  codesign --force --sign - "$app"
fi
codesign --verify --strict --deep "$app" || die "the signature doesn't check out"

if [ -n "${KIT_MAC_SIGN:-}" ] && [ -n "${KIT_MAC_NOTARY:-}" ]; then
  echo "Sending the app to Apple to notarize. It usually takes a few minutes..."
  ditto -c -k --keepParent "$app" "$out/notarize.zip"
  xcrun notarytool submit "$out/notarize.zip" --keychain-profile "$KIT_MAC_NOTARY" --wait > "$out/notarize.log" 2>&1 || true
  rm -f "$out/notarize.zip"
  sed 's/^/  /' "$out/notarize.log"
  if ! grep -q "status: Accepted" "$out/notarize.log"; then
    id="$(sed -n 's/^ *id: *//p' "$out/notarize.log" | head -1)"
    [ -n "$id" ] && xcrun notarytool log "$id" --keychain-profile "$KIT_MAC_NOTARY"
    die "Apple didn't notarize the app. What it said is above."
  fi
  xcrun stapler staple "$app" > /dev/null || die "couldn't staple the notarization ticket to the app"
  spctl --assess --type execute -vv "$app" 2>&1 | grep -q "Notarized Developer ID" ||
    die "Gatekeeper doesn't accept the notarized app: $(spctl --assess --type execute -vv "$app" 2>&1)"
fi
ditto -c -k --keepParent "$app" "$out/TinfoilKit-Mac.zip"
echo "Built $out/TinfoilKit-Mac.zip ($(du -k "$out/TinfoilKit-Mac.zip" | cut -f1) KB)"
