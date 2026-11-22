# Security

Tinfoil Kit downloads programs and data and runs them on your computer, and `./kit update` installs new versions of its own code, so security problems matter. What protects people, and what doesn't, is in the README's [Security section](../README.md#security).

## Report one privately

Use [Report a vulnerability](https://github.com/tudor-city-ventures/tinfoilkit/security/advisories/new) on the Security tab, not a public issue. Say what you ran and what happened. Reports a person hasn't reproduced, such as unchecked output from an AI or a scanner, are closed.

One person maintains the kit. Expect a reply within a week. Then:

1. We agree on the problem and how serious it is, in the private advisory.
2. The fix ships in a signed release. Kits get it the next time their owners run SETUP, so a serious problem is also announced on tinfoilkit.com.
3. The advisory goes public with the release and credits you, unless you'd rather not be named.

Please keep it private until the fix is out, or for 90 days after your report if that comes first. Research in good faith is welcome: test on your own computer and your own copy of the kit, leave other people's data and networks alone, and don't load-test tinfoilkit.com.

## What counts

- Getting past the signature check in `./kit update` or the checksum checks in `./kit sync`, or anything either writes outside the kit folder.
- Another computer or a website reaching the kit's servers, or getting past the sharing gate's access code.
- Running code through the kit page, a book or a map.
- A source in `kit.json` serving something other than what it claims.
- tinfoilkit.com, and this repo's GitHub Actions: anything that gets a change into `main` or a release without the maintainer.

Not in scope: bugs in llama.cpp, Kiwix, Photon, GraphHopper or the other programs the kit downloads (report those to their projects), and someone on a network you share reading the sharing gate's traffic, which is plain HTTP (the README says to share on networks you trust).

## Supported versions

The latest release and `main`.
