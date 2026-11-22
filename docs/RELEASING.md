# Releasing Tinfoil Kit

For the maintainer. A release reaches every kit at its next SETUP (`./kit update`), so it goes out only from the maintainer's own Mac, signed with a key that never goes into GitHub or a workflow. How updates work on a kit is in [DESIGN.md](DESIGN.md#updating-the-kits-own-code).

## What a release holds

| File | For |
| --- | --- |
| `tinfoilkit-vX.Y.Z.tar.gz` and `.sig` | `./kit update`: the app folder's files, signed with the release key. A kit refuses it unless a key in its own `tools/release-signers` signed it |
| `TinfoilKit-Mac.zip` | The website's Mac download: the Tinfoil Kit app, signed with the Developer ID and notarized |
| `TinfoilKit-Windows.zip`, `TinfoilKit.tar.gz` | The website's Windows and Linux downloads: `TinfoilKit/app/` |
| `SHA256SUMS` and `.sig` | The SHA-256 of every file above and of each computer's program as built, signed with the release key |

Everything is built from the tag and can be rebuilt byte for byte: `tools/tinfoilkit/build.sh verify SHA256SUMS` checks the programs, and `build.sh archive tar tinfoilkit-TAG TAG | shasum -a 256` the update archive (README, "Security", has the steps for anyone).

## Before a release

1. CI passed on the commit: `check` (a commit a workflow pushed starts no checks, so run `check` on `main` by hand then) and `e2e`.
2. The `drive test` workflow passed on it.
3. Run the `pin program builds` workflow, or wait for its Monday run, so `tools/pins.json` names the newest builds.
4. On a Mac with a real drive, from that commit: `./kit sync && ./kit test`. This is the only run against the real downloads and Apple Silicon's GPU, and it makes the pinned builds the tested ones.
5. Write `NOTES.txt`: a few plain lines on what's new. SETUP shows them before it installs the release.

## Publishing

```bash
.github/release.sh v1.2.0 NOTES.txt
```

It needs git, ssh-keygen, Go (`brew install go`), GitHub's `gh` signed in (`brew install gh && gh auth login`), the release key and the Mac app's signing (both below). Before anything goes out it:

- stops unless the checkout is `main` exactly as on GitHub, with nothing uncommitted, the tag is new, `check` passed on the commit and `tools/pins.json` pins the programs;
- builds each computer's program and stops unless they match CI's build of the same commit (CI prints their SHA-256s);
- builds the update archive and the three downloads from the tag, signs the archive, and checks the signature against this release's `tools/release-signers` and the last release's, since kits on the last release check it with their keys;
- builds the Mac app, has Apple notarize it, and checks that its copy of the program differs from the plain build only by Apple's signature;
- signs `SHA256SUMS`, shows what's new and asks for the version to be typed before it pushes the tag and creates the release.

GitHub's own source tarballs are never installed by anything.

## The release key (once)

```bash
.github/release.sh key
```

It makes an Ed25519 key at `~/.ssh/tinfoilkit-release` (or `KIT_RELEASE_KEY`), asks for a passphrase, and adds the public half to `tools/release-signers`; commit and push that. Back up the key and its passphrase in a password manager, with a copy offline: without them, no kit can update again. Each release brings the next `tools/release-signers`, so changing keys is a release signed with the old key that lists the new one.

## Signing the Mac app (once)

On the Mac that makes releases. The certificate and notarytool's password stay in its keychain, never in GitHub.

1. Enroll in the Apple Developer Program ($99 a year) at developer.apple.com/programs/enroll. As an organization, the app's signature names the company; that needs its D-U-N-S number (the enrollment looks it up) and takes longer. As an individual, it names the person, and Apple usually approves in a day or two.
2. In Keychain Access: Keychain Access > Certificate Assistant > Request a Certificate From a Certificate Authority. Your email and name, "Saved to disk". That puts the private key in the login keychain and saves a `.certSigningRequest` file.
3. At developer.apple.com > Account > Certificates, IDs & Profiles > Certificates > +: **Developer ID Application**, profile type **G2 Sub-CA**, upload the request, download the `.cer` and double-click it. Only the account holder can make this one. `security find-identity -v -p codesigning` should list "Developer ID Application: NAME (TEAMID)". If it doesn't, double-click "Developer ID - G2" from apple.com/certificateauthority (the intermediate certificate) and look again.
4. At account.apple.com > Sign-In and Security > App-Specific Passwords, make one called "Tinfoil Kit notarize".
5. Run `.github/release.sh mac`. It asks for the Apple account's email, then that password (notarytool keeps it in the keychain as the profile `tinfoilkit`), builds the app, has Apple notarize it and leaves `TinfoilKit-Mac.zip` on the Desktop, marked as downloaded. Open it to see what people will see: macOS should only ask whether to open an app from the internet.
6. Back up the certificate with its key: Keychain Access > My Certificates, right-click "Developer ID Application: …" > Export, as a `.p12` with a password, kept with the release key's backup. A lost one means making a new one (Apple allows a few); a leaked one gets revoked at developer.apple.com.

After that every release builds and notarizes the app by itself.

## Things that expire

- `site/public/.well-known/security.txt` expires 2027-10-31. The website test fails 30 days before; move its `Expires` a year on then.
- The Developer ID certificate lasts five years; the Apple Developer Program renews yearly.
- tinfoilkit.com renews yearly through Vercel.

## Going public (once)

Each step needs the maintainer's go-ahead, because none can be quietly undone. Delete this section once it's done.

1. A real `SETUP.command` run on a Mac with a real drive, and `./kit test` passes.
2. Vercel Authentication on the `tinfoilkit` project is "all except custom domains" (or off), so the public sees tinfoilkit.com. Previews stay protected.
3. Make the GitHub repo public. The site's GitHub buttons and llms.txt point at it. First delete the agents' leftover `claude/*` branches (everything is on `main`), and check that the history holds no personal email: `git log --format='%ae%n%ce' | sort -u`. Then turn on the settings below, all but the `main` ruleset's pull request rules (step 6). Several exist only for public repos, and the release protections must be on before step 4.
4. Make the release key and the Mac app's signing (above), then publish v1.0.0. Until the repo is public and has a release, `./kit update` finds nothing and kits keep their version.
5. Check the link-preview card (https://tinfoilkit.com/og.png) and that the kit builder loads `sources.json`.
6. Switch to pull requests and review: add the pull request rules to the `main` ruleset (below) and update AGENTS.md's Workflow section. The ruleset ends direct pushes, including the weekly sizes and pins commits, so in the same step switch the commit jobs of `sizes.yml` and `pins.yml` to push a `bot/sizes` or `bot/pins` branch, open a pull request, run the required checks on it with `workflow_dispatch` (pull requests opened with the Actions token don't start workflows; dispatching `pr-gate.yml` skips `protected-files`, which counts as passing) and auto-merge it. That needs "Allow GitHub Actions to create and approve pull requests" and auto-merge turned on. Keep the ruleset at no required approvals while that setting is on, or a workflow could approve its own pull request.
7. Tell search engines, once the repo is public so the site's GitHub links work: add tinfoilkit.com to Google Search Console and Bing Webmaster Tools (ChatGPT search and Copilot draw on Bing's index), verify it with a DNS record on Vercel, and submit https://tinfoilkit.com/sitemap.xml. Search Console will say the app markup can't get star ratings because the site has no reviews: expected, and never fill that in with made-up ratings.
8. GitHub build attestations for the programs: `actions/attest-build-provenance` at a verified commit SHA, in a job listed in `WRITES` in `tests/actions_test.py` (it needs `id-token` and `attestations` write). A private repo would need GitHub Enterprise Cloud for them.

## GitHub settings

The contribution policy and its reasons are in [CONTRIBUTING](../.github/CONTRIBUTING.md). In the repo's Settings:

- **General**
  - Pull requests: allow squash merging only; turn on auto-merge and "Automatically delete head branches".
  - Limit open pull requests for users without write access: 2.
  - Social preview: upload `docs/social-preview.png` (made by `site/build_images.py`), so shared repo links show the card. GitHub has no API for it.
  - About (the gear by About on the repo page), which GitHub search and AI answers quote: description "Free, open-source offline kit for Mac, Windows and Linux laptops: a local AI, all of Wikipedia, medical and repair guides, and maps with directions on one external drive. For when the internet goes down.", website https://tinfoilkit.com, and topics `offline`, `local-ai`, `llama-cpp`, `kiwix`, `wikipedia`, `offline-maps`, `openstreetmap`, `emergency-preparedness`, `macos`, `windows`, `linux`, `apple-silicon`.
  - Leave pull requests open to everyone. "Restrict pull requests to collaborators" is the brake for a flood: while it's on, only people with write access can open them.
  - Releases: turn on release immutability. Every kit installs the latest release, so its tag and files must never change.
  - Features: turn off Wikis and Projects.
- **Moderation options:** interaction limits stay off; in a flood, "Limit to existing users" (blocks accounts under a day old) or "Limit to prior contributors", for a day to a week. Code review limits on. Reported content: accept reports from everyone (the code of conduct sends people there).
- **Actions > General:**
  - Actions permissions: allow actions created by GitHub, plus `ossf/scorecard-action@*` (Scorecard), and tick "Require actions to be pinned to a full-length commit SHA". Every workflow already is; this makes GitHub refuse any that isn't.
  - Fork pull request workflows: the strictest approval option, so a person approves every outside contributor's run.
  - Workflow permissions: read repository contents only, and "Allow GitHub Actions to create and approve pull requests" off until step 6.
  - While the repo is private, "Fork pull request workflows in private repositories" must not send write tokens or secrets.
  - Never add a self-hosted runner: on a public repo it runs strangers' code on that machine.
- **Rules > Rulesets**
  - Tag ruleset `releases` on `v*`: restrict creations, updates and deletions; bypass: Repository admin. Before the first release.
  - Branch ruleset `main` on the default branch: restrict deletions and block force pushes from step 3 (direct pushes still work). With step 6, add: require a pull request (no approvals: the maintainer's agents open pull requests as the maintainer, who can't approve their own; conversations resolved), require the status checks `quick-gate`, `bash-3-2`, `site`, `sign-off` and `protected-files`; bypass: Repository admin, for pull requests only. `e2e` isn't required because it only runs when the kit changes. `protected-files` fails outside pull requests that change workflows or release signing, so merging one takes the admin bypass, on purpose.
- **Code security:** private vulnerability reporting (SECURITY.md sends reports there), Dependabot alerts and security updates, secret scanning with push protection, CodeQL default setup (it covers the workflows, the page's JavaScript, the Go program and the tests' Python).
- **Collaborators:** to vouch for someone, add them with the Read role; the contribution gate skips collaborators. Anyone who needs more than two open pull requests goes on the limit's bypass list.
- **Organization** (tudor-city-ventures): require two-factor authentication; base permission for members: Read; only owners install GitHub Apps. Installed apps reach this repo only if they need it (Claude and Vercel).
- **Labels:** `accepted`, `auto-closed` and `needs-triage` come from running the `contribution gate` workflow by hand. Run it again after changing them there.

Elsewhere:

- **Maintainer accounts:** passkeys or security keys rather than SMS codes on GitHub, Vercel, Apple and the email account their password resets go to.
- **Vercel** (`tinfoilkit` project): keep Git Fork Protection on, so pull requests from forks don't deploy previews until approved.
