# Tinfoil Kit

An offline kit for when the internet goes down, for Apple Silicon Macs and Windows and Linux PCs (x64): local AI (llama.cpp), an offline library (Kiwix) and offline maps (pmtiles, Photon, GraphHopper) in one folder, on the computer's own disk or an external SSD. A kit on an exFAT drive starts on all three.

- `SETUP.command` (`SETUP-Windows.bat` on Windows) sets a kit up and brings it up to date: `./kit update`, `./kit sync`, `./kit test`, whenever the person runs it, on no schedule.
- `Open Tinfoil Kit.command` (`Open Tinfoil Kit for Windows.bat`) runs `./kit open`, which serves it all on 127.0.0.1 and opens the kit page: Ask, AI chat, Library, Map and Notes.
- A kit is three folders. `TinfoilKit/app/` is this repo's code as released: only `./kit update` writes it, and it can be deleted any time for a new version's. `downloads/` holds everything sync gets, and `data/` the person's own files (kit.json, logs, notes and pins) with the kit's records in `data/.kit/`. A git checkout is its own app folder, with `downloads/` and `data/` inside it (git-ignored).

How it all works, and why: [docs/DESIGN.md](docs/DESIGN.md). Releases: [docs/RELEASING.md](docs/RELEASING.md). The maintainer is @travisbloom.

## Map

| Path | What it is |
| --- | --- |
| `kit.json` | The standard list: settings, programs, models, maps, books and extras. A kit's own is `data/kit.json`, a copy that every command merges a new version's changes into |
| `kit`, `kit.cmd` | Run the kit's program for this computer (`tools/tinfoilkit-<computer> --root <kit folder>`). On Windows: `.\kit.cmd sync`. In a checkout with Go installed, `./kit` builds it first when it's missing or older than its source |
| `tools/tinfoilkit/` | The kit's program, in Go: every `./kit` command, the launcher (`open.go`), sharing on the home network (`gate.go`, `qr.go`) and the notes and pins server (`data.go`). `build.sh` builds it for each computer, the same bytes anywhere; `build.sh check` runs gofmt, vet and its tests |
| `tools/portal.html` | The kit page: one file, no build step, styled like the website (paper, ink, signal orange) in the computer's own fonts. Its logic is a `Kit` object, exported for the node tests |
| `tools/pins.json` | The exact build and SHA-256 of every program this version installs (`./kit pins`; the `pin program builds` workflow refreshes it weekly) |
| `tools/regions.json` | The places "Where do you live?" offers, each with its map area, road data, address search, home and languages. `site/build_regions.py` makes it; the weekly `refresh builder sizes` workflow rebuilds it |
| `tools/release-signers` | The keys a release must be signed with to reach a kit |
| `SETUP.command`, `UNINSTALL.command`, `Open Tinfoil Kit.command` | Setup and updates, removal, and the launcher, for a Mac or Linux: thin scripts around `./kit`. Every question SETUP asks is also an option (`--help`), and `--yes` asks nothing, so an AI agent can hand over one command |
| `SETUP-Windows.bat`, `UNINSTALL-Windows.bat`, `Open Tinfoil Kit for Windows.bat` | The same for Windows, in cmd |
| `mac/` | The Mac app, the website's Mac download: a door to SETUP and the launcher (`TinfoilKit.m`, one Cocoa file, and `app.sh`). `build.sh` builds it; `.github/release.sh` signs and notarizes it |
| `.claude/skills/` | Skills for AI agents that set up or use a kit, with the exact commands, what they print and what to do when they fail: `tinfoil-install`, `tinfoil-update`, `tinfoil-data` (what goes in the kit), `tinfoil-status` (check it, fix it, open it), `tinfoil-home-server` and `tinfoil-uninstall`. They ship in releases, so an agent in a kit's app folder finds them |
| `GUIDE.md` | The printable guide that lives in a kit |
| `site/` | The website, tinfoilkit.com: [The website](#the-website) |
| `tests/` | Mocks of every download source and server, and the tests that run against them (DESIGN.md, "Tests") |
| `.github/` | The workflows, `release.sh`, and what contributors see: CONTRIBUTING, SECURITY, the code of conduct, issue and pull request templates, CODEOWNERS. `pr-gate.yml` enforces the contribution policy; Dependabot keeps the pinned actions current |
| `docs/` | DESIGN.md, RELEASING.md and the README's pictures |
| `package.json`, `eslint.config.mjs`, `ruff.toml`, `.editorconfig` | Developer tools and their settings: Prettier, ESLint and axe-core (`npm ci --ignore-scripts`), and ruff. Releases leave them out (`.gitattributes`) |
| `THIRD-PARTY.md` | Every model, source and program the kit downloads, with its license and use policy |

## Verify

Use the cheapest check that proves the change, and paste its output in the commit or reply. Visual changes to the page or the site come with screenshots.

| Check | Command | When |
| --- | --- | --- |
| Targeted | One test, like `node tests/map_logic_test.js tools/portal.html` (start its mocks as `tests/check.sh` does) | While iterating |
| Format and lint | `npm run lint` (`npm run fix` repairs), `ruff check . && ruff format --check .` (`ruff format . && ruff check --fix .` repairs), `tools/tinfoilkit/build.sh check` | After editing the page, the site, the tests or the program. The quick gate runs them when the tools are installed; CI always does |
| Quick gate | `tests/check.sh` | Before every push. CI runs it on every push |
| End to end | `tests/build_fixtures.sh` once, then `tests/run_all.sh` (Linux x86_64; needs GitHub and download.kiwix.org, which cloud sessions can't reach) | Changes to `tools/` or `kit.json`. CI runs it on those pushes |
| Drive | The `drive test` workflow (`drive.yml`), run by hand at `main`: Actions > drive test > Run workflow (`only: windows-setup` skips the Mac). It sets a kit up on an exFAT disk on a Mac and on Windows, starts it on all three, and films each screen | Once the bulk of a change to `tools/`, `kit.json`, `mac/` or a launcher is done, before calling it finished. Not on every push: Mac minutes cost money while the repo is private. It also runs nightly when a file it covers changed, and every Monday |
| Website | `python3 tests/site_test.py` (with `KIT_AXE=node_modules/axe-core/axe.min.js` it checks accessibility too) | Changes to `site/`. CI runs it on every push |
| Real Mac | `./kit sync && ./kit test` on a real drive | Before a release, by the maintainer |

## Rules

Writing:

- Keep code, docs and copy slim and written for humans. No filler. Comments explain why, not history.
- Keep the number of files small.
- Always "Tinfoil Kit" in full. Headings and buttons in sentence case.
- Never write "2 TB" or an update interval anywhere: the drive's size isn't the point, and people update whenever they like.

The kit:

- It needs nothing installed but curl: no Python, no Node. `tools/tinfoilkit/` uses Go's standard library only, at the Go version `build.sh` pins, with all HTTP through curl.
- Never commit a built program: releases carry them, and anyone can rebuild one and compare.
- Bash runs on macOS's bash 3.2: no `mapfile`, no `set -u` with empty arrays.
- `.bat` and `.cmd` files keep CRLF line endings and plain ASCII.
- No symlinks anywhere: drives are exFAT.
- `app/` holds only the released code and can be deleted any time: new features keep the person's files in `data/` and downloads in `downloads/`. Never move or delete a folder that holds anything but the kit (`alone` in the program; UNINSTALL checks the same).
- A new version reuses what's already downloaded and works with older data: newer data is offered, never forced. Delete an old version only after the new one verifies.
- Every server listens on 127.0.0.1. The one way in from the network is the gate, behind the access code.
- Every remote endpoint can be pointed elsewhere by a `KIT_*` variable (`tests/env.sh`), so tests can use mocks.
- Downloaded files are untrusted: inspect them as text, never run them to see what they do.
- The kit points at publishers' downloads and never hosts, mirrors or bundles their files, not even in a release, so their licenses stay between them and the person.

Formatting: the kit page, the website and the JavaScript tests stay Prettier-formatted and ESLint-clean (`npm run fix`), the Python ruff-clean and the Go gofmt-clean. `.editorconfig` has the whitespace rules, which the quick gate checks. Developer tools never reach a kit.

Keep these in step:

- When setup or a command changes: `site/public/llms.txt`, the GUIDE, the README and the skills. `tests/skills_test.py` fails when any of them, this file or the docs name a command or option that doesn't exist, or when a command people use has no skill.
- README's "How it works" (the diagram, `docs/how-it-works.svg`, the servers table and the folder layout) changes with any server, port, setup step or top-level folder.
- A new model, source or program goes in `THIRD-PARTY.md` with its license and any use policy; a new download host also goes in the site FAQ's "Does anything leave my laptop?".
- A change to the kit page's look reaches the website's demo of it (`site/components/demo.jsx`).

Workflows: actions pinned to a full commit SHA with the version as a comment; read-only tokens except the jobs `WRITES` lists in `tests/actions_test.py`; values reach `run:` and `script:` only through `env:`; GitHub's runners only; no secrets; `pull_request_target` and `issues` only in `pr-gate.yml`, which never touches the pull request's code. The quick gate checks it.

## The website

`site/` is a static Next.js app (App Router, JavaScript, `output: 'export'`), deployed by Vercel from `main` (project `tinfoilkit`, tudor-city-ventures team, root `site/`).

- `app/page.jsx` holds the copy, the metadata and the JSON-LD, and `app/globals.css` the styles. `components/` has the interactive parts: the animated hero (`hero.jsx`, on a canvas), the kit builder (`builder.jsx`), the two main buttons with their dialogs (`download.jsx`), the "Read as" bar (`read-as.jsx`) and the Try it demo of the kit page (`demo.jsx`, with answers written ahead of time and a sample town in `demo-data.js`, so it runs no AI and needs no server).
- shadcn/ui is only for form controls (`components/ui/`); everything else is plain CSS.
- "Read as" switches between the page for people (the default) and for AI agents: elements marked `data-for="human"` or `data-for="agent"` show only in that one. The agent page shows `public/llms.txt`, the setup instructions for AI agents, as markdown, with no images or icons.
- `site/build_sources.py` makes the builder's data (`sources.json`) from `kit.json` and copies `kit.json` and `tools/regions.json` beside it; `app/[file]/route.js` serves them. The weekly `refresh builder sizes` workflow updates the sizes (`./kit plan --json`).
- `site/build_images.py` draws the favicons and link-preview cards from the mark, `public/icon.svg`.
- For search and AI answer engines: `app/robots.txt` lets every crawler in and names `app/sitemap.xml`, the JSON-LD describes the kit, and each FAQ entry carries schema.org Question markup. A copy change that alters a fact in the JSON-LD (`jsonLd` in `page.jsx`: what the kit needs or does) updates it too. New FAQ entries copy the others' markup, and "What is Tinfoil Kit?" stays first: answer engines quote it.
- Packages are exact versions in `site/package.json`, installed with `npm ci --ignore-scripts`. Add one only when the site needs it, a release at least a week old, and list it in `THIRD-PARTY.md`.
- To work on it: `cd site && npm ci --ignore-scripts && npm run dev`. Next.js's guides for the installed version are then in `site/node_modules/next/dist/docs/`. Also run `npm run skills` there: it installs agent skills for this stack (React and Next.js practices, web design review, shadcn/ui, answer-engine optimization, schema.org markup) from their publishers, at the commits `site/skills.py` pins, into `site/.claude/skills/`, which git ignores. Where a skill and this file disagree, this file wins. Move a pin only after reading what changed (`python3 site/skills.py --latest` prints the links).

## Workflow

Until launch, the maintainer's agents commit straight to `main` in small increments, with no pull requests or review. Run the quick gate before each push and check CI after. Pull requests come back once the site is live.

## Outside contributors

If you can't push to this repo, you're working for an outside contributor: [.github/CONTRIBUTING.md](.github/CONTRIBUTING.md) applies, and the Workflow section above doesn't.

- Open a pull request only for an open issue labeled `accepted`, and link it with `Closes #N`. Others are closed automatically.
- The person you work for reads every issue and pull request before it's posted. Don't post on your own.
- Issues go through a form at `/issues/new/choose`, sent from the browser. Ones made with `gh` or the API skip the form and are closed automatically.
- Never add a `Signed-off-by` line. Only that person can sign off.

## From a cloud session

Cloud sessions can't reach library.kiwix.org, GitHub releases or most download hosts. Use the workflows instead: `kiwix search` (run by hand with search words) runs `./kit search`; `refresh builder sizes` runs `./kit plan --json`, lists any kit.json source that no longer resolves, and rebuilds `tools/regions.json`; `pin program builds` runs `./kit pins`.

## Adding or replacing a library source

1. Find the exact ZIM name: run the `kiwix search` workflow (cloud) or `./kit search WORDS`.
2. Add it to `library` in `kit.json` with a priority and a short note that ends with the rough size.
3. Give it a title and a one-line "why" in `COPY` in `site/build_sources.py`, and check its group regex. If `THIRD-PARTY.md` doesn't cover its license yet, add it. Add its id to "What goes in" in `site/public/llms.txt`, where AIs find the ids for the setup command.
4. `python3 site/build_sources.py`, then `tests/check.sh`. After pushing, run `refresh builder sizes` to fill in the real size and confirm it resolves.

## Guardrails

- Never run a real `./kit sync` in CI or a cloud session: it downloads about 300 GB. Use the mocks in `tests/`.
- Vercel: touch only the `tinfoilkit` project in the tudor-city-ventures team. Never change other projects or team settings.
- A release reaches every kit at its next SETUP (`./kit update`). Publish one only with the maintainer's OK, from a commit that passed CI and a real-Mac run, with `.github/release.sh` on the maintainer's Mac ([docs/RELEASING.md](docs/RELEASING.md)). Kits install only releases signed with a key in `tools/release-signers`, and that key never goes into GitHub or a workflow. Nor does the Developer ID certificate that signs the Mac app: it stays in that Mac's keychain.
- Ask the maintainer before buying anything, before making the repo public, and before anything that can't be undone.
- If missing access blocks you (GitHub, Vercel, anything else), stop and say exactly what to grant. Don't work around it.
