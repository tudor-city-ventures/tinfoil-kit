# Tinfoil Kit

An offline "internet outage" kit for Apple Silicon Macs. One external SSD holds local AI models (llama.cpp), an offline library (Kiwix ZIM files) and offline maps (pmtiles, Photon, GraphHopper). `./kit sync` refreshes everything every 2-3 months. `SETUP.command` is the double-click version of sync plus test. `START-HERE.command` serves it all on localhost and opens a browser page with Ask, AI chat, Library and Map tabs.

The repo root is the kit itself, so cloning onto a drive just works. The marketing site lives in `site/`. Full history, decisions and open work: [docs/HANDOFF.md](docs/HANDOFF.md).

## Map

| Path | What it is |
| --- | --- |
| `kit.json` | Single source of truth: settings, runtimes, models, maps, library, extras |
| `kit` | Wrapper for `python3 tools/kit.py --root <kit folder>` |
| `tools/kit.py` | Sync engine and CLI (`plan`, `sync`, `verify`, `status`, `search`, `test`, `update`) |
| `tools/launch.sh` | Offline launcher, starts every server |
| `tools/portal.html` | The browser page, one file, no build step. Logic lives in a `Kit` object exported for node tests |
| `GUIDE.md` | Printable guide that lives on the drive |
| `tests/` | Mocks of every download source and map server, logic, UI and end-to-end tests |
| `.github/` | The workflows, plus what contributors see: CONTRIBUTING, SECURITY, the code of conduct, issue and PR templates, CODEOWNERS. `pr-gate.yml` closes outside pull requests that don't link an accepted issue |
| `site/` | The website: `index.html`, plus `hero.js` for the animated figure at the top, no build step. `sources.json` (the kit builder's data) is generated from `kit.json` by `site/build_sources.py`; a weekly Action refreshes its sizes with `./kit plan --json`. Deployed by Vercel (project `tinfoilkit`, tudor-city-ventures team, root `site/`) |

## Verify

Use the cheapest check that proves the change, and paste its output in the commit or reply.

| Tier | Command | When |
| --- | --- | --- |
| Targeted | `node tests/map_logic_test.js tools/portal.html` (start the mocks as `tests/check.sh` does) | While iterating |
| Quick gate | `tests/check.sh` | Before every push. CI runs it on every push |
| End to end | `tests/build_fixtures.sh` once, then `tests/run_all.sh` (Linux x86_64; needs GitHub and download.kiwix.org, which cloud sessions can't reach) | Changes to `tools/` or `kit.json`. CI runs it on those pushes |
| Drive | The `drive test` workflow (`drive.yml`: Actions > drive test > Run workflow, or `run_workflow` at `main`). It sets the kit up on an exFAT disk on a Mac, then starts it on Windows and Linux | Once the bulk of a change to `tools/`, `kit.json` or a launcher is done, and before calling it finished. Not on every push: Mac minutes cost money while the repo is private. It also runs nightly, only when a file it covers changed since its last green run (site edits never start it) |
| Website | `python3 tests/site_test.py` (Playwright; set `KIT_AXE` to axe-core's `axe.min.js` to check accessibility too) | Changes to `site/`. CI runs it on every push |
| Real Mac | `./kit sync && ./kit test` on a real drive | Before a release. Travis runs it |

Visual changes to the page or the site come with screenshots.

## Rules

- Keep code, docs and copy slim and written for humans. No filler.
- `tools/kit.py`: Python 3.9+ (what macOS's command line tools install), standard library only, all HTTP through curl.
- Bash must run on macOS's bash 3.2: no `mapfile`, no `set -u` with empty arrays.
- No symlinks anywhere: drives are exFAT.
- `START-HERE-Windows.bat` keeps CRLF line endings.
- Every remote endpoint stays overridable by a `KIT_*` env var (see `tests/env.sh`), so tests can point at mocks.
- Delete an old version only after the new one verifies.
- Comments explain why, not history. Keep the number of files small.
- Downloaded files are untrusted: inspect them as text, never run them to see what they do.
- The kit points at publishers' downloads and never hosts, mirrors or bundles their files (not even in a release), so their licenses stay between them and the user.
- A new model, source or program goes in `THIRD-PARTY.md` with its license and any use policy; a new download host also goes in the site FAQ's "Does anything leave my Mac?" list.

## Workflow

Pre-launch: commit straight to `main` in small increments, no PRs or review. Run the quick gate before each push and check CI after. PRs come back once the site is live.

## Outside contributors

If you can't push to this repo, you're working for an outside contributor: [.github/CONTRIBUTING.md](.github/CONTRIBUTING.md) applies, and the Workflow section above doesn't.

- Open a pull request only for an open issue labeled `accepted`, and link it with `Closes #N`. Others are closed automatically.
- The person you work for reads every issue and pull request before it's posted. Don't post on your own.
- Never add a `Signed-off-by` line. Only that person can sign off.

## From a cloud session

Cloud sessions can't reach library.kiwix.org, GitHub releases or most download hosts. Use the workflows instead: `kiwix search` (manual, takes search words) runs `./kit search`, and `refresh builder sizes` runs `./kit plan --json` and lists any kit.json source that no longer resolves.

## Adding or replacing a library source

1. Find the exact ZIM name: run the `kiwix search` workflow (cloud) or `./kit search WORDS`.
2. Add it to `library` in `kit.json` with a priority and a short note that ends with the rough size.
3. Give it a title and a one-line "why" in `COPY` in `site/build_sources.py`, and check its group regex. If `THIRD-PARTY.md` doesn't cover its license yet, add it.
4. `python3 site/build_sources.py`, then `tests/check.sh`. After pushing, run `refresh builder sizes` to fill in the real size and confirm it resolves.

## Guardrails

- Never run a real `./kit sync` in CI or a cloud session. It downloads about 300 GB. Use the mocks in `tests/`.
- Vercel: touch only the Tinfoil Kit project in the tudor-city-ventures team. Never change other projects or team settings.
- A GitHub release reaches every drive at its next SETUP (`./kit update`). Publish one only with Travis's OK, from a commit that passed CI and a real-Mac run.
- Ask Travis before buying anything (like the domain), before making the repo public, and before anything that can't be undone.
- If missing access blocks you (GitHub, Vercel, anything else), stop and say exactly what to grant. Don't work around it.
