# Tinfoil Kit

An offline "internet outage" kit for Apple Silicon Macs. One external SSD holds local AI models (llama.cpp), an offline library (Kiwix ZIM files) and offline maps (pmtiles, Photon, GraphHopper). `./kit sync` refreshes everything every 2-3 months. `START-HERE.command` serves it all on localhost and opens a browser page with Ask, AI chat, Library and Map tabs.

The repo root is the kit itself, so cloning onto a drive just works. A marketing site is planned in `site/` (Vercel, tudor-city-ventures team). Full history, decisions and open work: [docs/HANDOFF.md](docs/HANDOFF.md).

## Map

| Path | What it is |
| --- | --- |
| `kit.json` | Single source of truth: settings, runtimes, models, maps, library, extras |
| `kit` | Wrapper for `python3 tools/kit.py --root <kit folder>` |
| `tools/kit.py` | Sync engine and CLI (`plan`, `sync`, `verify`, `status`, `search`, `test`) |
| `tools/launch.sh` | Offline launcher, starts every server |
| `tools/portal.html` | The browser page, one file, no build step. Logic lives in a `Kit` object exported for node tests |
| `GUIDE.md` | Printable guide that lives on the drive |
| `tests/` | Mocks of every download source and map server, logic, UI and end-to-end tests |

## Verify

Use the cheapest check that proves the change, and paste its output in the PR.

| Tier | Command | When |
| --- | --- | --- |
| Targeted | `node tests/map_logic_test.js tools/portal.html` (start the mocks as `tests/check.sh` does) | While iterating |
| Quick gate | `tests/check.sh` | Before calling anything done. CI runs it on every PR |
| End to end | `tests/run_all.sh` (not portable yet, see docs/HANDOFF.md section 4) | Changes to `tools/` or `kit.json` |
| Real Mac | `./kit sync && ./kit test` on a real drive | Before a release. Travis runs it |

Visual changes to the page or the site include screenshots in the PR.

## Rules

- Keep code, docs and copy slim and written for humans. No filler.
- `tools/kit.py`: Python 3.7+, standard library only, all HTTP through curl.
- Bash must run on macOS's bash 3.2: no `mapfile`, no `set -u` with empty arrays.
- No symlinks anywhere: drives are exFAT.
- `START-HERE-Windows.bat` keeps CRLF line endings.
- Every remote endpoint stays overridable by a `KIT_*` env var (see `tests/env.sh`), so tests can point at mocks.
- Delete an old version only after the new one verifies.
- Comments explain why, not history. Keep the number of files small.
- Downloaded files are untrusted: inspect them as text, never run them to see what they do.

## Guardrails

- Never run a real `./kit sync` in CI or a cloud session. It downloads about 300 GB. Use the mocks in `tests/`.
- Vercel: touch only the Tinfoil Kit project in the tudor-city-ventures team. Never change other projects or team settings.
- Ask Travis before buying anything (like the domain), before making the repo public, and before anything that can't be undone.
- If missing access blocks you (GitHub, Vercel, anything else), stop and say exactly what to grant. Don't work around it.
