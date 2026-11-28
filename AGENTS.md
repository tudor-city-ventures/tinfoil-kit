# Tinfoil Kit

An offline kit for when the internet goes down, for Apple Silicon Macs and Windows and Linux PCs (x64): local AI (llama.cpp), an offline library (Kiwix) and offline maps (pmtiles, Photon, GraphHopper) in one folder, on the computer's own disk or an external SSD. A kit on an exFAT drive starts on all three.

- `SETUP.command` (`SETUP-Windows.bat` on Windows) sets a kit up and brings it up to date: `./kit update`, `./kit sync`, `./kit test`, whenever the person runs it, on no schedule.
- `Open Tinfoil Kit.command` (`Open Tinfoil Kit for Windows.bat`) runs `./kit open`, which serves it all on 127.0.0.1 and opens the kit page: Ask, Map and Library, and under More: Notes, Share with family, Print the essentials, Make a copy, AI chat and Help.
- A kit is three folders. `TinfoilKit/app/` is this repo's `kit/` as released: only `./kit update` writes it, and it can be deleted any time for a new version's. `downloads/` holds everything sync gets, and `data/` the person's own files (kit.json, logs, notes and pins) with the kit's records in `data/.kit/`. Beside them, the program keeps a launcher for each computer and `Read me first.txt` (`topFiles`). In a git checkout, `kit/` is the app folder, with `downloads/` and `data/` inside it (git-ignored).

How it all works, and why: [docs/DESIGN.md](docs/DESIGN.md). Releases: [docs/RELEASING.md](docs/RELEASING.md). The maintainer is @travisbloom.

## Map

| Path | What it is |
| --- | --- |
| `kit/` | The kit's code. A release is this folder, with the license, README and THIRD-PARTY.md added (`build.sh archive`) |
| `kit/kit.json` | The standard list: settings, programs, models, maps, books and extras. A kit's own is `data/kit.json`, a copy that every command merges a new version's changes into |
| `kit/kit`, `kit/kit.cmd` | Run the kit's program for this computer (`tools/tinfoilkit-<computer> --root <kit folder>`). On Windows: `.\kit.cmd sync`. In a checkout with Go installed, `./kit` builds it first when it's missing or older than its source |
| `kit/tools/tinfoilkit/` | The kit's program, in Go: every `./kit` command, the launcher (`open.go`), sharing on the home network (`gate.go`, `qr.go`), the notes and pins server (`data.go`) and copies on another drive (`copy.go`). `build.sh` builds it for each computer, the same bytes anywhere; `build.sh check` runs gofmt, vet and its tests |
| `kit/tools/portal.html` | The kit page: one file, no build step, styled like the website (paper, ink, signal orange) in the computer's own fonts. Its logic is a `Kit` object, exported for the node tests. The website's Try it demo is a copy of it |
| `kit/tools/pins.json` | The exact build and SHA-256 of every program this version installs (`./kit pins`; the `pin program builds` workflow refreshes it weekly) |
| `kit/tools/regions.json` | The places "Where do you live?" offers, each with its map area, road data, address search, home and languages. `site/build_regions.py` makes it; the weekly `refresh builder sizes` workflow rebuilds it |
| `kit/tools/sources.json` | The kit builder's list, for `./kit pick`: a copy of the website's (`site/build_sources.py` writes both) |
| `kit/tools/release-signers` | The keys a release must be signed with to reach a kit |
| `kit/SETUP.command`, `kit/UNINSTALL.command`, `kit/Open Tinfoil Kit.command` | Setup and updates, removal, and the launcher, for a Mac or Linux: thin scripts around `./kit`. Every question SETUP asks is also an option (`--help`), and `--yes` asks nothing, so an AI agent can hand over one command |
| `kit/SETUP-Windows.bat`, `kit/UNINSTALL-Windows.bat`, `kit/Open Tinfoil Kit for Windows.bat` | The same for Windows, in cmd |
| `mac/` | The Mac app: a door to SETUP and the launcher (`TinfoilKit.m`, one Cocoa file, and `app.sh`), for the website's Mac download once Apple's signing is set up; until then releases leave it out and the website offers no download. `build.sh` builds it; `.github/release.sh` signs and notarizes it |
| `kit/.claude/skills/` | Skills for AI agents that set up or use a kit, with the exact commands, what they print and what to do when they fail: `tinfoil-install`, `tinfoil-update`, `tinfoil-data` (what goes in the kit), `tinfoil-status` (check it, fix it, open it), `tinfoil-home-server`, `tinfoil-copy` (a copy on another drive) and `tinfoil-uninstall`. They ship in releases, so an agent in a kit's app folder finds them |
| `kit/GUIDE.md` | The printable guide that lives in a kit |
| `site/` | The website, tinfoilkit.com: [The website](#the-website) |
| `mobile/` | The phone app, Tinfoil Kit for iPhone and Android: [The phone app](#the-phone-app) |
| `tests/` | Mocks of every download source and server, and the tests that run against them (DESIGN.md, "Tests") |
| `.github/` | The workflows, `release.sh`, and what contributors see: CONTRIBUTING, SECURITY, the code of conduct, issue and pull request templates, CODEOWNERS. `pr-gate.yml` enforces the contribution policy; Dependabot keeps the pinned actions current |
| `docs/` | DESIGN.md, RELEASING.md and the README's pictures |
| `package.json`, `eslint.config.mjs`, `ruff.toml`, `.editorconfig` | Developer tools and their settings: Prettier, ESLint and axe-core (`npm ci --ignore-scripts`), and ruff. Releases leave them out |
| `THIRD-PARTY.md` | Every model, source and program the kit downloads, with its license and use policy |

## Verify

Use the cheapest check that proves the change, and paste its output in the commit or reply. Visual changes to the page or the site come with screenshots.

| Check | Command | When |
| --- | --- | --- |
| Targeted | One test, like `node tests/map_logic_test.js kit/tools/portal.html` (start its mocks as `tests/check.sh` does) | While iterating |
| Format and lint | `npm run lint` (`npm run fix` repairs), `ruff check . && ruff format --check .` (`ruff format . && ruff check --fix .` repairs), `kit/tools/tinfoilkit/build.sh check` | After editing the page, the site, the tests or the program. The quick gate runs them when the tools are installed; CI always does |
| Quick gate | `tests/check.sh` | Before every push. CI runs it on every push |
| End to end | `tests/build_fixtures.sh` once, then `tests/run_all.sh` (Linux x86_64; needs GitHub and download.kiwix.org, which cloud sessions can't reach) | Changes to `kit/tools/` or `kit/kit.json`. CI runs it on those pushes |
| Drive | The `drive test` workflow (`drive.yml`): it sets a kit up on an exFAT disk on a Mac and on Windows, starts it on all three, and films each screen. Pushes to `main` and the nightly run start it when a file it covers changed, and Monday's always runs. By hand: Actions > drive test > Run workflow at `main` (`only: windows-setup` skips the Mac) | Once the bulk of a change to `kit/` or `mac/` is in, before calling it finished: check that its run passed, or run it by hand if a newer push cancelled it |
| Phone app | `cd mobile && npm ci --ignore-scripts && npm run check` (types, lint, unit tests), and `npm run check:android` for its Android code | Changes to `mobile/`. CI runs it and builds the app on push |
| Website | `python3 tests/site_test.py` (with `KIT_AXE=node_modules/axe-core/axe.min.js` it checks accessibility too) | Changes to `site/`. CI runs it on every push |
| Real Mac | `./kit sync && ./kit test` on a real drive | Before a release, by the maintainer |

## Rules

Writing:

- Keep code, docs and copy slim and written for humans. No filler. Comments explain why, not history.
- Keep the number of files small.
- Always "Tinfoil Kit" in full. Headings and buttons in sentence case.
- Never write "2 TB" or an update interval anywhere: the drive's size isn't the point, and people update whenever they like.

The kit:

- It needs nothing installed but curl: no Python, no Node. `kit/tools/tinfoilkit/` uses Go's standard library only, at the Go version `build.sh` pins, with all HTTP through curl.
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
- The kit page and the website's Try it demo of it (`site/components/demo.jsx`) stay the same to look at: a change to the kit page's tabs, menus, buttons, words or look changes the demo in the same commit. The demo only fakes what needs a server: the answers, the map, sharing. `tests/site_test.py` fails when their tabs, More menu, Ask, Notes, Share with family, Help or Print the essentials headings differ.

Workflows: actions pinned to a full commit SHA with the version as a comment; read-only tokens except the jobs `WRITES` lists in `tests/actions_test.py`; values reach `run:` and `script:` only through `env:`; GitHub's runners only; no secrets; `pull_request_target` and `issues` only in `pr-gate.yml`, which never touches the pull request's code. The quick gate checks it.

## The website

`site/` is a static Next.js app (App Router, JavaScript, `output: 'export'`), deployed by Vercel from `main` (project `tinfoilkit`, tudor-city-ventures team, root `site/`).

- Two pages, one for each way in, each with its own copy, metadata, canonical link and JSON-LD, so search and answer engines rank them apart. `app/page.jsx`, "My AI installs it", is the home page: setup with an AI first, in plain words up top (AI, never LLM, GGUF or ZIM): the headline and animation with what's on the drive, what it's for (what people need to know in a long outage), how it works, the Try it demo, the kit builder and the prompts; then how to check the code, and the FAQ. The site offers no download until the Mac app can be signed ([RELEASING.md](docs/RELEASING.md#signing-the-mac-app-once)): setup is the command the AI gives. `app/agents/page.jsx`, "I'm an AI": `public/llms.txt`, the setup instructions for AI agents, read as the site builds and shown as markdown, with no images or icons. The versions strip in `components/header.jsx` links them, and the head script in `app/layout.jsx` and the redirects in `vercel.json` still land the old links: `/?for=agent` and `#instructions` on `/agents`, and `/ai-setup`, once a third page, on the home page.
- `components/site.jsx` has what the pages share (metadata, JSON-LD, FAQ markup, the footer), `app/globals.css` the styles, and the rest of `components/` the interactive parts: the animated hero (`hero.jsx`, on a canvas), the kit builder (`builder.jsx`), Set up with your AI and its dialog with the prompt (`setup.jsx`) and the Try it demo of the kit page (`demo.jsx`, with answers written ahead of time and a sample town in `demo-data.js`, so it runs no AI and needs no server).
- shadcn/ui is only for form controls (`components/ui/`); everything else is plain CSS.
- `site/build_sources.py` makes the builder's data (`sources.json`, and the kit's copy in `kit/tools/`) from `kit/kit.json` and copies `kit/kit.json` and `kit/tools/regions.json` beside it; `app/[file]/route.js` serves them. The weekly `refresh builder sizes` workflow updates the sizes (`./kit plan --json`).
- `site/build_images.py` draws the favicons and link-preview cards from the mark, `public/icon.svg`.
- For search and AI answer engines: `app/robots.txt` lets every crawler in and names `app/sitemap.xml`, which lists the two pages; each page's JSON-LD describes it (the kit, how to set it up and its source, the instructions for agents), and each FAQ entry carries schema.org Question markup. A copy change that alters a fact in the JSON-LD (`jsonLd` in each page: what the kit needs or does) updates it too. New FAQ entries copy the others' markup, and "What is Tinfoil Kit?" stays first on the home page: answer engines quote it.
- Packages are exact versions in `site/package.json`, installed with `npm ci --ignore-scripts`. Add one only when the site needs it, a release at least a week old, and list it in `THIRD-PARTY.md`.
- To work on it: `cd site && npm ci --ignore-scripts && npm run dev`. Next.js's guides for the installed version are then in `site/node_modules/next/dist/docs/`. Also run `npm run skills` there: it installs agent skills for this stack (React and Next.js practices, web design review, shadcn/ui, answer-engine optimization, schema.org markup) from their publishers, at the commits `site/skills.py` pins, into `site/.claude/skills/`, which git ignores. Where a skill and this file disagree, this file wins. Move a pin only after reading what changed (`python3 site/skills.py --latest` prints the links).

## The phone app

`mobile/` is Tinfoil Kit for iPhone and Android: an Expo app (React Native, TypeScript, Expo Router) with its own releases, separate from the kit's. Its main way in is downloading from the internet, since most people have no drive; a kit on the home network is the other, behind the same access code as Share with family. A phone shares its books and map with another the same way, behind a code on its screen (Get more, Share with a phone: `src/kit/share.ts`).

- The phone gets the kit's books in their smallest editions (`src/kit/catalog.ts`, from `site/kit.json` and `site/sources.json`, which Metro reads from `../site`), its area's map, and Ask with the AI built into the phone where there is one, Search where there isn't. No accounts, nothing to pay, big downloads on Wi-Fi unless the person allows mobile data.
- The look is the kit page's on each platform's own controls: iOS's grouped lists, large titles and tab bar (Android's own on Android), on paper with signal orange as the only accent (`src/theme.ts`). Copy follows the rules above.
- Layout: `src/app/` holds routes only, since every file there is a screen (tabs Library, Ask, Map and Get more, and the first screen with the try-it kit); `src/screens/` the bigger screens' bodies, `src/components/` what screens share and `src/kit/` the logic, each test beside its file; `modules/kit-files/` is the native code Expo lacks: the downloads (books go to the phone's own downloader and are checked and filed with the app closed, `Books.swift` and `Books.kt`; the map comes in parts), keeping books out of iOS backups, the small server a phone shares with (`Home.swift` and `Home.kt`: only the files it lists, only with its code), and the page view that shows a book, asking the app for each file (`src/kit/books.ts` answers, from the app's own reader for Kiwix's ZIM files, `src/kit/zim.ts`) and reaching nothing else. `e2e/` has the Maestro tests CI runs on a simulator and an emulator, with `e2e/internet.py` standing in for Kiwix, serving the books `tests/make_zims.py` makes, and for Protomaps, serving the piece of its world map `src/kit/protomaps.test.ts` makes.
- Packages are exact versions in `mobile/package.json`, each a release at least a week old (`npm install --before=<a week ago> --save-exact`), installed with `npm ci --ignore-scripts`; match versions to the Expo SDK with `EXPO_OFFLINE=1 npx expo install --check`. List new ones in `THIRD-PARTY.md`.
- To work on it: `cd mobile && npm ci --ignore-scripts && npm run skills` (Expo's, Callstack's and Vercel's guides, pinned in `mobile/skills.py`, into the git-ignored `mobile/.claude/skills/`; this file wins where they disagree), then `npm run check`, which takes seconds: the logic's tests stand in for the phone (`src/kit/downloads.test.ts`). `npm run check:android` type-checks the Android code in about a minute, with a JDK. Nothing short of CI's iPhone build checks the Swift: about 30 minutes when native code changed, 10 when only JavaScript did, since CI then reuses the last build. A cloud session can't run a simulator: `npx expo export --platform web` and a browser give a rough look, and CI builds and tests the real apps.

## Workflow

Until the `main` ruleset requires pull requests ([RELEASING.md](docs/RELEASING.md#launch-once), step 4), the maintainer's agents commit straight to `main` in small increments, with no pull requests or review. Run the quick gate before each push and check CI after.

## Outside contributors

If you can't push to this repo, you're working for an outside contributor: [.github/CONTRIBUTING.md](.github/CONTRIBUTING.md) applies, and the Workflow section above doesn't.

- Open a pull request only for an open issue labeled `accepted`, and link it with `Closes #N`. Others are closed automatically.
- A feature, in an issue or a pull request, shows what it does in a screenshot or a short screen recording, which the person you work for makes or checks. Keep its description to a few plain sentences: the maintainer closes padded, AI-sounding text.
- The person you work for reads every issue and pull request before it's posted. Don't post on your own.
- Issues go through a form at `/issues/new/choose`, sent from the browser. Ones made with `gh` or the API skip the form and are closed automatically.
- Never add a `Signed-off-by` line. Only that person can sign off.

## From a cloud session

Cloud sessions can't reach library.kiwix.org, GitHub releases or most download hosts. Use the workflows instead: `kiwix search` (run by hand with search words) runs `./kit search`; `refresh builder sizes` runs `./kit plan --json`, lists any kit.json source that no longer resolves, and rebuilds `kit/tools/regions.json`; `pin program builds` runs `./kit pins`.

## Adding or replacing a library source

1. Find the exact ZIM name: run the `kiwix search` workflow (cloud) or `./kit search WORDS`.
2. Add it to `library` in `kit/kit.json` with a priority and a short note that ends with the rough size.
3. Give it a title and a one-line "why" in `COPY` in `site/build_sources.py`, and the page it comes from in `SOURCES` unless its name starts with that site's address, and check its group regex. If `THIRD-PARTY.md` doesn't cover its license yet, add it. Add its id to "What goes in" in `site/public/llms.txt`, where AIs find the ids for the setup command.
4. `python3 site/build_sources.py`, then `tests/check.sh`. After pushing, run `refresh builder sizes` to fill in the real size and confirm it resolves.

## Guardrails

- Never run a real `./kit sync` in CI or a cloud session: it downloads about 300 GB. Use the mocks in `tests/`.
- Vercel: touch only the `tinfoilkit` project in the tudor-city-ventures team. Never change other projects or team settings.
- A release reaches every kit at its next SETUP (`./kit update`). Publish one only with the maintainer's OK, from a commit that passed CI and a real-Mac run, with `.github/release.sh` on the maintainer's Mac ([docs/RELEASING.md](docs/RELEASING.md)). Kits install only releases signed with a key in `kit/tools/release-signers`, and that key never goes into GitHub or a workflow. Nor does the Developer ID certificate that signs the Mac app: it stays in that Mac's keychain.
- Ask the maintainer before buying anything and before anything that can't be undone.
- If missing access blocks you (GitHub, Vercel, anything else), stop and say exactly what to grant. Don't work around it.
