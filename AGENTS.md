# Tinfoil Kit

An offline "internet outage" kit for modern laptops: Apple Silicon Macs, and Windows and Linux PCs (x64). One folder, on the computer's own disk or an external SSD, holds local AI models (llama.cpp), an offline library (Kiwix ZIM files) and offline maps (pmtiles, Photon, GraphHopper). It sets up and runs on all three, and a kit on an exFAT drive starts on any of them. `./kit sync` brings everything up to date whenever the person runs it, on no schedule. `SETUP.command` (`SETUP-Windows.bat` on Windows) is the double-click version of update, sync and test. `Open Tinfoil Kit.command` (`Open Tinfoil Kit for Windows.bat`) serves it all on localhost and opens a browser page with Ask, AI chat, Library and Map tabs.

The repo root is the kit itself, so cloning it onto a drive or into `~/TinfoilKit` just works. The marketing site lives in `site/`. Full history, decisions and open work: [docs/HANDOFF.md](docs/HANDOFF.md).

## Map

| Path | What it is |
| --- | --- |
| `kit.json` | Single source of truth: settings, runtimes, models, maps, library, extras |
| `kit`, `kit.cmd` | Wrapper for `python3 tools/kit.py --root <kit folder>`, on the Python SETUP got if this Mac has none. `kit.cmd` is the same on Windows (`.\kit.cmd sync`), on SETUP-Windows.bat's Python or the PC's own |
| `tools/kit.py` | Sync engine and CLI (`plan`, `sync`, `verify`, `status`, `search`, `test`, `update`, `pins`, `estimate`, `fit`, `space`, `essentials`, `drives`, `place`, `region`, `pick`, `share`, `autostart`) |
| `tools/pins.json` | The exact build and SHA-256 of every program this version installs. `./kit pins` writes it; the `pin program builds` workflow refreshes it weekly |
| `tools/regions.json` | The places "Where do you live?" offers (US states, countries, parts of big countries), each with its map area, road data, address search, home and Wikipedia languages. Made by `site/build_regions.py` from Geofabrik, Photon, Kiwix and GeoNames; the weekly `refresh builder sizes` Action rebuilds it. `./kit region` points kit.json at one |
| `SETUP.command`, `UNINSTALL.command` | Double-click setup and update: on a Mac without Python it first gets a pinned, checksum-checked one into `~/Library/Application Support/TinfoilKit`. The first run asks where you live (`region`), says which AI fits (`fit`), asks for a drive or this computer with what fits where (`drives`, `space`, `essentials`) and moves the kit there (`place`), then every run does `update`, `sync`, `test` (the first time, the essentials first). Every answer also comes as an option, and `--yes` asks nothing, so an AI agent can ask the questions and hand over one command (`--help` lists them; what goes in is `./kit pick`). Removal deletes the kit folder, and that Python, after a typed `delete` |
| `SETUP-Windows.bat`, `Open Tinfoil Kit for Windows.bat`, `UNINSTALL-Windows.bat` | The same for Windows, in cmd. SETUP first gets python.org's Python from nuget.org (checked against `PYSHA`) into `%LOCALAPPDATA%\TinfoilKit`, outside the kit; Open Tinfoil Kit for Windows needs no Python, except to share on the home network |
| `tools/launch.sh` | Offline launcher, starts every server |
| `mac/` | The Mac app, the website's Mac download: `TinfoilKit.m` (its windows, Cocoa, one file) and `app.sh` (its file work) around a copy of the kit. It moves itself to Applications, opens SETUP in Terminal the first time and the kit after that. `build.sh` builds it; `.github/release.sh` signs and notarizes it on Travis's Mac (`release.sh mac` sets that up once) |
| `tools/share.py` | Sharing on the home network (off by default): the gate on port 8000 that asks for the access code and passes requests to the servers, its QR code, and starting the kit with the computer (systemd user service, LaunchAgent, Windows' Startup folder). `SETUP.command --home-server` (`SETUP-Windows.bat --home-server`) turns both on |
| `tools/portal.html` | The browser page, one file, no build step. Logic lives in a `Kit` object exported for node tests |
| `GUIDE.md` | Printable guide that lives in the kit folder |
| `tests/` | Mocks of every download source and map server, logic, UI and end-to-end tests |
| `.github/` | The workflows, plus what contributors see: CONTRIBUTING, SECURITY, the code of conduct, issue and PR templates, CODEOWNERS. `pr-gate.yml` closes outside pull requests that don't link an accepted issue and outside issues filed without a form, and fails a check on pull requests that change workflows or release signing. Dependabot keeps the pinned actions current. `release.sh` signs and publishes a release, with the notarized Mac app, from Travis's computer |
| `site/` | The website: a static Next.js app (App Router, JavaScript, `output: 'export'`). `app/page.jsx` holds the page's copy, its metadata and the JSON-LD; `components/` the interactive parts (`hero.jsx`, the animated figure at the top, on a canvas; `builder.jsx`, the kit builder; `download.jsx`, the download button and dialog; `read-as.jsx`); `app/globals.css` the styles. shadcn/ui is only for form controls (`components/ui/`: the builder's Select and Checkbox); everything else is plain CSS. A "Read as" bar switches between the human page (the default) and the AI agent page: elements marked `data-for="human"` or `data-for="agent"` show only in that one. The agent page shows `public/llms.txt`, the setup instructions for AI agents, as markdown, with no images or icons. `sources.json` (the kit builder's data) is generated from `kit.json` by `site/build_sources.py`; a weekly Action refreshes its sizes with `./kit plan --json`; it, `kit.json` and `regions.json` stay in `site/` and are served by `app/[file]/route.js`. The favicons and link-preview cards are rendered from the mark, `public/icon.svg`, by `site/build_images.py`. For search and AI answer engines, `app/robots.txt` lets every crawler in and names `app/sitemap.xml`, a JSON-LD block in the page describes the kit, and each FAQ entry carries schema.org Question markup. Deployed by Vercel (project `tinfoilkit`, tudor-city-ventures team, root `site/`, framework Next.js). `cd site && npm ci --ignore-scripts && npm run dev` runs it locally, and Next.js's guides for the installed version are then in `site/node_modules/next/dist/docs/`. Before working on the site, also run `npm run skills` there: it installs agent skills for this stack (Vercel's React and Next.js best practices and web design review, shadcn/ui, AI answer-engine optimization, schema.org markup) from their publishers' repos, at the commits pinned in `site/skills.py`, into `site/.claude/skills/`, which git ignores. Where a skill and this file disagree, this file wins. Move a pin only after reading what changed (`python3 site/skills.py --latest` prints the links) |

## Verify

Use the cheapest check that proves the change, and paste its output in the commit or reply.

| Tier | Command | When |
| --- | --- | --- |
| Targeted | `node tests/map_logic_test.js tools/portal.html` (start the mocks as `tests/check.sh` does) | While iterating |
| Quick gate | `tests/check.sh` | Before every push. CI runs it on every push |
| End to end | `tests/build_fixtures.sh` once, then `tests/run_all.sh` (Linux x86_64; needs GitHub and download.kiwix.org, which cloud sessions can't reach) | Changes to `tools/` or `kit.json`. CI runs it on those pushes |
| Drive | The `drive test` workflow (`drive.yml`: Actions > drive test > Run workflow, or `run_workflow` at `main`). It sets the kit up on an exFAT disk on a Mac, with a small real map (Andorra), and opens it with the Mac app, then starts it on Windows and Linux, and sets it up on Windows from a download (`only: windows-setup` runs just that, with no Mac minutes). Each machine's screen is filmed, and the run's page links the videos | Once the bulk of a change to `tools/`, `kit.json`, `mac/` or a launcher is done, and before calling it finished. Not on every push: Mac minutes cost money while the repo is private. It also runs nightly, only when a file it covers changed since its last green run (site edits never start it), and every Monday regardless, for new llama.cpp builds |
| Website | `python3 tests/site_test.py` (builds `site/` with Node, then Playwright; set `KIT_AXE` to axe-core's `axe.min.js` to check accessibility too) | Changes to `site/`. CI runs it on every push |
| Real Mac | `./kit sync && ./kit test` on a real drive | Before a release. Travis runs it |

Visual changes to the page or the site come with screenshots.

## Rules

- Keep code, docs and copy slim and written for humans. No filler.
- `tools/kit.py`: Python 3.9+ (what macOS's command line tools install), standard library only, all HTTP through curl.
- Bash must run on macOS's bash 3.2: no `mapfile`, no `set -u` with empty arrays.
- No symlinks anywhere: drives are exFAT.
- `.bat` and `.cmd` files keep CRLF line endings and plain ASCII.
- Every remote endpoint stays overridable by a `KIT_*` env var (see `tests/env.sh`), so tests can point at mocks.
- Every server listens on 127.0.0.1 only. The one way in from the network is `tools/share.py`, behind the access code.
- Workflows: actions pinned to a full commit SHA with the version as a comment, read-only tokens except the jobs `WRITES` lists in `tests/actions_test.py`, values into `run:` and `script:` only through `env:`, GitHub's runners only, no secrets, and `pull_request_target` and `issues` only in `pr-gate.yml`, which never touches the pull request's code. The quick gate checks it.
- Delete an old version only after the new one verifies.
- Comments explain why, not history. Keep the number of files small.
- The website's packages are exact versions in `site/package.json`, installed with `npm ci --ignore-scripts`. Add one only when the site needs it, a release at least a week old, and list it in `THIRD-PARTY.md`. Headings and buttons stay in sentence case.
- Downloaded files are untrusted: inspect them as text, never run them to see what they do.
- The kit points at publishers' downloads and never hosts, mirrors or bundles their files (not even in a release), so their licenses stay between them and the user.
- A new model, source or program goes in `THIRD-PARTY.md` with its license and any use policy; a new download host also goes in the site FAQ's "Does anything leave my laptop?" list.
- When setup or a command changes, update `site/public/llms.txt` with the GUIDE and README.
- README's "How it works" (diagram, servers table, folder layout) is the architecture overview: change it with any server, port, setup step or top-level folder.
- A copy change that alters a fact in the page's JSON-LD (`jsonLd` in `site/app/page.jsx`: what the kit needs or does) updates it too. New FAQ entries copy the others' Question markup, and "What is Tinfoil Kit?" stays first: answer engines quote it.

## Workflow

Pre-launch: commit straight to `main` in small increments, no PRs or review. Run the quick gate before each push and check CI after. PRs come back once the site is live.

## Outside contributors

If you can't push to this repo, you're working for an outside contributor: [.github/CONTRIBUTING.md](.github/CONTRIBUTING.md) applies, and the Workflow section above doesn't.

- Open a pull request only for an open issue labeled `accepted`, and link it with `Closes #N`. Others are closed automatically.
- The person you work for reads every issue and pull request before it's posted. Don't post on your own.
- Issues go through a form at `/issues/new/choose`, sent from the browser. Ones made with `gh` or the API skip the form and are closed automatically.
- Never add a `Signed-off-by` line. Only that person can sign off.

## From a cloud session

Cloud sessions can't reach library.kiwix.org, GitHub releases or most download hosts. Use the workflows instead: `kiwix search` (manual, takes search words) runs `./kit search`, `refresh builder sizes` runs `./kit plan --json`, lists any kit.json source that no longer resolves, and rebuilds `tools/regions.json`, and `pin program builds` runs `./kit pins`.

## Adding or replacing a library source

1. Find the exact ZIM name: run the `kiwix search` workflow (cloud) or `./kit search WORDS`.
2. Add it to `library` in `kit.json` with a priority and a short note that ends with the rough size.
3. Give it a title and a one-line "why" in `COPY` in `site/build_sources.py`, and check its group regex. If `THIRD-PARTY.md` doesn't cover its license yet, add it.
4. `python3 site/build_sources.py`, then `tests/check.sh`. After pushing, run `refresh builder sizes` to fill in the real size and confirm it resolves.

## Guardrails

- Never run a real `./kit sync` in CI or a cloud session. It downloads about 300 GB. Use the mocks in `tests/`.
- Vercel: touch only the Tinfoil Kit project in the tudor-city-ventures team. Never change other projects or team settings.
- A GitHub release reaches every drive at its next SETUP (`./kit update`). Publish one only with Travis's OK, from a commit that passed CI and a real-Mac run, with `.github/release.sh` on Travis's computer: drives install only releases signed with a key in `tools/release-signers`, and that key never goes into GitHub or a workflow. Nor does the Developer ID certificate that signs the Mac app: it stays in that Mac's keychain.
- Ask Travis before buying anything (like the domain), before making the repo public, and before anything that can't be undone.
- If missing access blocks you (GitHub, Vercel, anything else), stop and say exactly what to grant. Don't work around it.
