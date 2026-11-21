# Security

Tinfoil Kit downloads programs and data and runs them on your Mac, and every drive installs the newest release of this repo. Security problems matter.

## Report one privately

Use [Report a vulnerability](https://github.com/tudor-city-ventures/tinfoilkit/security/advisories/new) on the Security tab, not a public issue. Say what you ran and what happened. Reports a person hasn't reproduced, such as unchecked output from an AI or a scanner, are closed.

One person maintains the kit. Expect a reply within a week.

## What counts

- Getting past the checksum checks in `./kit sync`, or anything sync or `./kit update` writes outside the kit folder.
- Another computer or a web page reaching the kit's servers when `--share` is off, or running code through the page.
- A source in `kit.json` serving something other than what it claims.
- tinfoilkit.com and this repo's GitHub Actions.

Not in scope: bugs in llama.cpp, Kiwix, Photon, GraphHopper or the other programs the kit downloads (report those to their projects), and `--share` serving the kit to everyone on your network without a password, which is what it's for.

## Supported versions

The latest release and `main`.
