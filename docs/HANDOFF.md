# Tinfoil Kit: history and decisions

Handoff from the Claude chat where the kit was built (2026-11-21). The code moved into this repo; section 1 is the state at handoff. Agent rules live in `AGENTS.md`.

## Status (2026-11-21, after the move to Claude Code)

- Tasks 1, 2 and 4 below are done: the repo is set up, the end-to-end suite passes in GitHub Actions against the mocks, and the Field Manual design (variant A of 3) is built in `site/` and deployed by Vercel.
- The builder's sizes are live: a weekly Action runs `./kit plan --json`.
- Still open: a real sync on Travis's Mac, the domain (ask first), making the repo public at launch, and fixing kit.json entries the Kiwix catalog no longer has.

---

## 1. Where things stand

- **The kit works** and passes a full end-to-end test suite in a Linux sandbox, with every download source and map server replaced by a mock. Two zips were delivered earlier in the chat: OfflineKit v1 (AI and library) and v2 (adds maps). The code in this repo is v2, renamed to Tinfoil Kit, with the default home location changed to New York, NY.
- **Not yet tested anywhere real:** a real sync from the internet on a Mac. That means the Apple Silicon binaries, about 300 GB of downloads, and the real map servers running from an exFAT drive. The first real run will be on Travis's Mac.
- **GitHub:** the repo is `tudor-city-ventures/tinfoilkit`, private.
- **Website:** not designed or built yet. There is no Vercel project and no domain purchase.

**First tasks for the new project, in order:**
1. Done: commit `kit/` as the repo root and `tests/` as `tests/`. Add `AGENTS.md`, a `CLAUDE.md` that imports it, `README.md` and `LICENSE` (section 6).
2. Make the test suite portable and run it in GitHub Actions (section 4).
3. Design 3 website variants for Travis to choose from (section 7).
4. Build the chosen design and deploy a preview to Vercel (sections 7 and 8).

---

## 2. What the kit is

- **For:** technical people and non-technical preppers. Version 1 supports Apple Silicon Macs only and is designed around 32 GB of memory; smaller Macs can use the small model. Windows and Linux paths exist in the code but are untested.
- **On the drive:** AI models, the library, maps, the programs that serve them (llama.cpp, kiwix-serve, pmtiles, Photon, GraphHopper, Java), the launcher and the browser page.
- **Using it:** double-click `START-HERE.command`. A browser opens http://127.0.0.1:8888 with these tabs:
  - **Ask:** answers from the library, with numbered sources.
  - **AI chat:** plain chat with the model; photos can be attached.
  - **Library:** browse or search every book.
  - **Map:** search an address, get driving or walking directions, or find the nearest hospital, pharmacy and so on.
  - **Help.**
- **Updating:** run `./kit sync` and then `./kit test` about every 75 days.

---

## 3. How the kit works

### Files

| Path | What it is |
| --- | --- |
| `kit.json` | The single source of truth: `settings`, `runtimes`, `models`, `maps`, `library`, `extras` |
| `kit` | Wrapper that runs `python3 tools/kit.py --root <kit folder>` |
| `tools/kit.py` | Sync engine and CLI. Python 3.7+, standard library only; all HTTP goes through `curl` |
| `tools/launch.sh` | Offline launcher. Must stay compatible with macOS's bash 3.2 |
| `tools/portal.html` | The browser page. A single file; kiwix-serve serves it as its custom index |
| `START-HERE.command` | Double-click launcher for the Mac |
| `START-HERE-Windows.bat` | Windows fallback. Must keep CRLF line endings |
| `GUIDE.md` | Printable guide that lives on the drive |

After a sync, the drive also has `bin/`, `models/`, `library/`, `maps/`, `installers/`, `logs/`, `INVENTORY.md`, and `.kit/` (which holds `state.json`, caches, partial downloads and the built `portal.html`).

### Commands

- `./kit plan [--only WORDS]`: preview what sync would do.
- `./kit sync [-y] [--force] [--only WORDS]`: download and update everything. `--force` ignores the free-space margin.
- `./kit verify [--quick] [--fix]`: re-check checksums. `--quick` checks sizes only; `--fix` deletes corrupt files so the next sync replaces them.
- `./kit status`: what's installed, and the size of each item.
- `./kit search WORDS`: search the Kiwix catalog for more books to add.
- `./kit test [--model NAME]`: start every server offline and check that each one answers.
- Launcher: `bash START-HERE.command [--share] [--model=NAME] [--no-browser] [--no-maps]`.

### Sync engine rules (keep these)

- Each item is resolved to a version and a list of files with checksums, then compared with `.kit/state.json`. Sync then plans, checks free space (`keep_free_gb`), downloads, verifies, installs and prunes.
- Downloads resume after interruption: `curl -C -` with retries, or `aria2c` when it's installed.
- Each download is verified against what its source publishes:
  - Kiwix: a `.sha256` sidecar file.
  - Hugging Face: the LFS sha256.
  - GitHub: the release asset digest.
  - Maven: `.sha1`.
  - npm: the sha512 integrity hash.
  - Geofabrik and Photon: `.md5`.
- **The drive is exFAT, which has no symlinks.**
  - Runtime versions are tracked with `CURRENT` pointer files instead of symlinks.
  - Archives are extracted on the internal disk, then copied over with symlinks resolved.
- An old version is deleted only after the new one verifies. The previous runtime version is kept, and the launcher falls back to it if the current binary won't run.
- Items install in priority order. Runtimes (priority 0) go first because the map steps need Java and pmtiles.
- Every remote endpoint can be overridden with an environment variable. The tests use this to point the kit at mocks:
  `KIT_KIWIX_CATALOG`, `KIT_KIWIX_RELEASES`, `KIT_GITHUB_API`, `KIT_HF`, `KIT_ADOPTIUM_API`, `KIT_MAVEN`, `KIT_NPM`, `KIT_GITHUB_WEB`, `KIT_PROTOMAPS_BUILDS`, `KIT_PROTOMAPS_BUILD_BASE`, `KIT_PHOTON_DUMPS`.
- At the end of every sync, `.kit/portal.html` is rebuilt from the template with the map assets embedded.
- `plan` shows `~` before a size it estimates (map tiles) and `?` when the size is unknown.

### Launcher

- **Library:** kiwix-serve on port 8888, serving the library plus the portal page as `--customIndex`.
- **AI:** llama-server on port 8080 in router mode: `--models-dir`, a `presets.ini` with `load-on-startup` for the default model, and `--models-max 1`.
- **CORS:** llama-server echoes `--cors-origins` back verbatim, so the launcher sets exactly one origin: `http://127.0.0.1:8888`, or `*` with `--share`. That's also why the portal redirects `localhost` to `127.0.0.1`.
- **Maps:** `pmtiles serve` on 8090, Photon on 2322 and GraphHopper on 8989, all run by the bundled Java. Their memory comes from `kit.json` (`geocoder_heap` 3g, `routing_heap` 2g). `--no-maps` skips them and saves about 5 GB.
- **Sharing:** `--share` listens on all network interfaces so phones on the same Wi-Fi or hotspot can use the kit.
- `caffeinate` keeps the Mac awake while the kit runs.

### The browser page (`tools/portal.html`)

- Plain HTML and JS with no build step. The core logic is a `Kit` object, exported with `module.exports` so node tests can run it. Browser-only code is in a separate function.
- **Ask:**
  1. The AI writes search queries (fallback: keyword extraction).
  2. kiwix full-text search runs across every book. Queries stay short because Xapian ANDs every word.
  3. The top articles are read and an answer streams back with `[n]` citations.
  4. With the AI off, it shows the most relevant passages instead.
- **Map questions:**
  - `Kit.isMapQuestion` uses a deliberately strict regex. "How far should I stay from a downed power line" still goes to the library.
  - Map questions go to an AI tool-calling loop with the tools `search_places`, `find_nearby` and `get_directions`, and the results are drawn on the Map tab.
  - Falls back to the library when the AI calls no tool, or when the AI is off and search finds nothing.
  - With the AI off, `guessMapIntent` parses simple questions on its own.
- **Map tab:**
  - Map display: MapLibre GL 5.x as a UMD build (6.x ships ESM only) with the @protomaps/basemaps 5.x "light" style.
  - Fonts and map icons:
    - Fonts are Noto Sans Regular, Medium and Italic, ranges 0-255, 256-511 and 8192-8447.
    - Fonts and the "light" icon sprites are embedded as base64 and served through `maplibregl.addProtocol` (`kitglyph://`, `kitsprite://sprites/light`), because kiwix-serve can serve only one custom page.
  - Features: a search box with suggestions; Drive/Walk directions with clickable steps; "nearest" buttons by category; and "Set home", stored in `localStorage`. The Mac has no GPS, so home is where searches start.
- **Template tags:** kiwix-serve renders `--customIndex` as a Mustache template. The template contains exactly one tag, `{{root}}`. The built page starts with a set-delimiter tag (`{{=<% %>=}}`) so the embedded code survives rendering.

### Maps stack

- **Tiles:**
  - Source: Protomaps' daily planet build (list at `build-metadata.protomaps.dev/builds.json`, files at `build.protomaps.com`).
  - Build steps: `pmtiles extract` cuts the world at zoom 0–7 and the region bbox at zoom 8–15; `pmtiles merge` combines them (inputs must be clustered and must not overlap); `pmtiles verify` checks the result.
  - Served as `/basemap/{z}/{x}/{y}.mvt` and `/basemap.json`.
- **Address search (Photon 1.x):**
  - The database is a prebuilt dump from `download1.graphhopper.com/public/`, found by reading its region table: region → continent or country folder → `photon-db-<slug>-<major.minor>-latest.tar.bz2` with an `.md5`.
  - Photon refuses databases built for another version, so the kit picks the Photon release that matches the newest available dump.
  - Small countries no longer get dumps. If there's no US-only dump, the kit falls back to the North America one, which is bigger.
  - "Nearest" calls `/reverse?radius=40&include=osm.amenity.hospital,...` and falls back to `osm_tag=` filters for older databases.
- **Directions (GraphHopper 11.x, pinned):**
  - `kit.py` writes the config:
    - Profiles: `car` (with CH speed-up) and `foot`.
    - Encoded values match the built-in `car.json` and `foot.json` at tag 11.1.
    - `graph.locktype: simple`, because exFAT can't do native file locks.
  - The import uses `RAM_STORE` with `routing_import_heap` 12g; serving uses `MMAP`.
  - Road data is Geofabrik's `us-northeast` PBF (about 1.6 GB). The network is rebuilt whenever the PBF or the GraphHopper version changes, which takes 10–40 minutes.
- **Java:** Adoptium Temurin 21 JRE, from `api.adoptium.net`.
- **Default coverage:**
  - Street detail and directions for the US Northeast (bbox -80.6, 38.8, -66.8, 47.6), meaning New England, New York, New Jersey and Pennsylvania.
  - Address search for the whole US, and a low-detail world map.
  - Adds about 20–30 GB to the drive.
- **Default home:** New York, NY. Users set their own.

### Content in `kit.json`

- **Models:** llama.cpp **nightly** builds are required, because stable releases can't run Inkling yet.
  - `Inkling-2-Mini` is the default (`ggml-org/Inkling-2-Mini-GGUF`, `*-IQ4_NL.gguf` plus `mmproj-*-Q8_0.gguf`).
  - `Qwen3.8-27B` (unsloth, `UD-Q4_K_M`).
  - `Gemma-4-26B-A4B` (unsloth QAT, `UD-Q4_K_XL`, plus an MTP draft model).
  - `Gemma-4-E4B` is the small, fast one.
  - MTP files are matched at the repo's top level first, because the `MTP/` subfolder has duplicates.
- **Library:** about 40 ZIM files, by priority:
  - Medical: WikiMed (mdwiki), WikEM, military medicine, LibreTexts medicine.
  - Preparedness: Ready.gov, WHO, post-disaster, water treatment, food, knots.
  - Repair: iFixit, US Army publications, and Stack Exchange sites (home improvement, cars, bikes, electronics).
  - Reference: Wikipedia with images (about 115 GB), Wiktionary, Wikibooks, Wikivoyage, Wikiversity, LibreTexts.
  - Project Gutenberg subsets.
  - Off by default: Survivor Library, Khan Academy, all of Gutenberg.
- **Extras:** the Kiwix macOS app installer.
- **First sync:** about 280–330 GB.

### Gotchas worth knowing

- Kiwix's `_ftindex:no` tag shows up even on books that do have a search index, so the kit searches every book.
- kiwix-serve requests a favicon, so the page sets `<link rel="icon" href="data:,">`.
- macOS bash 3.2: no `set -u` with empty arrays, and no `mapfile`.
- `pmtiles` has no `--version` flag. Use `pmtiles version`.
- MapLibre rewrites `kitsprite://light` to `kitsprite://light/.json`, so the sprite URL needs a path: `kitsprite://sprites/light`.
- A CSS `display:flex` overrides the `hidden` attribute, so the page has a global `[hidden]{display:none !important}`.
- Archive items without a `binary` used to re-download on every sync. Fixed in `evaluate()`.
- go-pmtiles names its Mac assets `go-pmtiles-<version>_Darwin_arm64.zip`; they are signed.
- Map data uses its Last-Modified date (YYYY-MM-DD) as its version.
- Downloaded files are untrusted. Inspect them as text; never run downloaded code to see what it does.

---

## 4. Tests as they exist

Everything passed on 2026-11-21 in the Linux sandbox. The scripts are in `tests/`.

- **Logic tests (node):**
  - `map_logic_test.js` runs the page's `Kit` code against a mock Photon, a mock GraphHopper and a mock tool-calling AI (`mock_services.py`).
  - `portal_test.js` runs the Ask logic against a live kiwix-serve and llama-server.
- **End to end (`run_all.sh`):** copies the kit onto a fake drive, then runs:
  - `plan` and `sync`, including a download that fails partway and resumes;
  - a second sync that should do nothing, `verify`, `kit test` and `search`;
  - the launcher, then the logic tests and the headless Chrome UI tests (Playwright: `ui_test.py`, `map_ui_test.py`);
  - `--no-maps`;
  - a "3 months later" update with a new catalog and new map builds, then `kit test` again.
- **`mock_remote.py`** fakes every download source: the Kiwix catalog and releases, the GitHub API, Hugging Face, Adoptium, Maven, npm, Protomaps builds, Geofabrik and the Photon dumps. Flag files switch its behavior:
  - `STATE_V2`: "3 months later".
  - `FLAKY`: a download breaks partway.
  - `PHOTON_OLD_DUMP`: only an older database version is published.
- **`tests/fakes/`:** a fake `java` (pretends to be GraphHopper's import and server, and Photon, by running the mocks) and a fake `pmtiles`.
- **Real software in the tests:**
  - kiwix-serve and llama-server, built from source for Linux.
  - A tiny random-weight GGUF model (`make_tiny_model.py`, uses gguf-py) and test ZIM files (`make_zims.py`, uses python-libzim).
  - MapLibre and basemaps from npm, fonts and icons from `protomaps/basemaps-assets`, and a pmtiles fixture from go-pmtiles.
- `tests/FIXTURES.txt` lists every file the mock served.

**Portability work needed. The suite doesn't run outside that sandbox yet:**
- Hardcoded paths (`/home/claude/test`, `/home/claude/OfflineKit`, `/home/claude/src/...`) in:
  - `run_all.sh`;
  - the screenshot paths in the UI tests;
  - `make_tiny_model.py` (path to gguf-py);
  - the fake `java` and `pmtiles` (path to `mock_services.py`).
- Building fixtures isn't scripted. Write `tests/build_fixtures.sh` that:
  - downloads the Linux release binaries of llama.cpp and kiwix-tools;
  - pip-installs `gguf`, `libzim` and `playwright`;
  - generates the tiny model and the ZIMs;
  - fetches the npm tarballs and basemaps-assets;
  - packs the fake release archives the mock serves.
- `run_all.sh` still copies the kit from the old `OfflineKit` folder. Point it at the repo root.
- Done: the mock places are made up and sit around the New York default.
- Then add GitHub Actions: the quick gate on every pull request, and the end-to-end suite on pull requests that touch `tools/` or `kit.json`.

**Never verified. Needs a real Mac and the internet:**
- Real downloads and checksums from each source.
- The Apple Silicon binaries.
- Photon and GraphHopper on real data, including from exFAT. Photon's search engine (OpenSearch) may fail to lock its files on exFAT; the guide says to reformat as APFS if `./kit test` shows a lock error.
- GraphHopper's import memory for car plus foot.
- The exact name of the Photon US dump.

---

## 5. Agent-driven development setup (keep it slim)

Inspired by the Do They Support It repo, but much smaller and written for people.

- **`AGENTS.md`** is the one set of agent instructions; Codex and Cursor read it natively. **`CLAUDE.md`** contains a single line, `@AGENTS.md`, which Claude Code reads as an import. No symlinks, because people will copy this repo onto exFAT drives.
- **Verification tiers** go in `AGENTS.md`. Use the cheapest one that proves the change, and paste its output:

  | Tier | Command | When |
  | --- | --- | --- |
  | Targeted | `node tests/map_logic_test.js tools/portal.html` (with the mocks running) | While iterating |
  | Quick gate | `tests/check.sh`: py_compile, `bash -n`, shellcheck, the page script parses, `kit.json` is valid, logic tests against the mocks | Before calling anything done |
  | End to end | `tests/e2e/run.sh` | Changes to `tools/` or `kit.json`, and in CI |
  | Real Mac | `./kit sync && ./kit test` on a real drive | Before a release. Travis runs it |

- **Visual changes** to the page or the website include screenshots in the pull request. The UI tests already save them.
- **CI (GitHub Actions):**
  - The quick gate on every pull request and on `main`.
  - The end-to-end suite once it's portable.
  - For the website, a smoke test against the Vercel preview URL.
- **Conventions:**
  - Comments explain why, not history.
  - Python uses only the standard library; bash stays 3.2-compatible; no symlinks.
  - Keep the number of files small.
- **Guardrails:** no real sync in CI or cloud sessions; only the Tinfoil Kit Vercel project; ask before purchases, before going public and before anything irreversible; flag access problems instead of working around them.
- **Skills:** at most one or two, and only if they earn their keep. For example, "add a data source" would cover the `kit.json` entry, the website builder's data and a test.

---

## 6. First commit plan

- **Layout:** the kit files go at the repo root, so cloning onto a drive just works:
  - `kit`, `kit.json`, `START-HERE.command`, `START-HERE-Windows.bat`, `tools/`, `GUIDE.md`.
  - New: `README.md` (for GitHub readers), `LICENSE`, `AGENTS.md`, `CLAUDE.md`, `tests/`, `docs/`, and `site/` for the website later.
- **LICENSE:** MIT. Holder: "Tinfoil Kit contributors", unless Travis prefers Tudor City Ventures.
- **`.gitignore`:** `.kit/ logs/ bin/ models/ library/ maps/ installers/ INVENTORY.md __pycache__/`
- **Repo owner:** in the Q&A Travis first chose his personal account, then agreed the repo should live under tudor-city-ventures to match the credit and hosting. It now lives at `tudor-city-ventures/tinfoilkit`.

---

## 7. Website plan (Travis's answers, 2026-11-21)

- **Name:** Tinfoil Kit. "Tinfoil" alone collides with tinfoil.sh, a YC-backed private-AI company with its own AI chat app and a `tinfoilsh` GitHub org.
- **Domain:** tinfoilkit.com, $12.03 a year through Vercel on the tudor-city-ventures team. **Ask before buying.**
  - Also available on 2026-11-21: tinfoilkit.org, tinfoilkit.dev, tinfoilkit.app, usetinfoil.com, tinfoilhq.com, tinfoil.computer, tinfoil.tools.
  - Taken: tinfoil.app, tinfoil.dev, tinfoil.org, gettinfoil.com.
- **Hosting:** a new Vercel project in the tudor-city-ventures team. The site credits a company, and Vercel's free Hobby plan is for non-commercial use only. Don't touch other projects.
- **Credit:** the footer says it's a side project from the team behind Do They Support It, with a link to dotheysupportit.com. Do They Support It is not the main brand.
- **Open source up front:** a very clear button to the GitHub repo, and the site talks prominently about being open source.
- **Audience:** technical people and non-technical preppers.
- **Platforms:** Apple Silicon Macs only for v1.
- **Setup for non-technical people:** a double-click guided setup. macOS asks them to approve it once in System Settings.
- **Tone:** techno-optimist prepper: prepared, concerned about AI, optimistic about the future. **Don't say this in the copy.** It's the aesthetic and the vibe for the design.
- **Hero:** a striking SVG visualization of the world's knowledge compressing onto a tiny external drive, then someone picking up the drive and exploring the earth.
- **Sections:**
  - What's inside.
  - The kit builder.
  - Two copy-paste prompts.
  - The GitHub button.
  - The footer credit.
- **Kit builder:**
  - Starts from presets (Essentials, Recommended, Everything); users then turn individual sources on or off.
  - Each source is an informative card explaining what it is, why you'd want it, and its size, so the selector doubles as an explainer.
  - A running total shows the space needed.
  - It gives back both a copy-paste setup prompt with the person's picks built in and a `kit.json` to download.
- **Two copy-paste prompts:**
  1. **Install ours:** works with any chat AI and walks a person through setup step by step.
  2. **Build your own:** concise principles to paste into any AI.
  Drafts are below.
- **Analytics:** none.
- **License:** MIT. **The repo goes public when the site launches.**
- **Design process:** make several variants (3) for Travis to choose from before building. In the chat these were going to be Claude Design artifacts; Vercel has a tool that imports a Claude design.
- **Builder data:**
  - Generate `sources.json` (id, title, what it is, why you'd want it, size) from `kit.json` plus live sizes.
  - Sizes need internet access, so add `./kit plan --json` and a scheduled GitHub Action that refreshes the file.
- **Open question:** Travis's message "When you do actually design the website, make sure that you give me multiple variants to pick from. And then" was cut off. Ask him what came after "And then".

### Draft: install prompt (any chat AI)

```
I want to set up Tinfoil Kit on my Mac. It's an offline AI assistant, an offline library (Wikipedia, medical and repair guides) and offline maps, all on an external drive, for when the internet is down. The project is at https://github.com/tudor-city-ventures/tinfoilkit. Read its README and GUIDE, then walk me through setup one step at a time:

1. Which drive to buy and how to format it.
2. How to download the kit and run the first sync, which takes a few hours.
3. How to check that it works with Wi-Fi off.
4. How to keep it updated every few months.

I'm not a programmer. Tell me exactly what to click or paste, and wait for me to confirm each step before moving on.
```

When the builder is used, it appends the person's picks or their `kit.json`.

### Draft: build your own (principles)

```
Help me build my own offline kit for an internet outage, on an external SSD. Principles:

- Everything works with zero internet: local AI models, an offline library and offline maps, served on localhost and opened in a browser.
- One config file lists every source. One command refreshes everything every 2-3 months. It resumes interrupted downloads, verifies checksums, and keeps the old version until the new one checks out.
- AI: a few open-weight models sized to my computer's memory (one capable default, one small and fast), run with llama.cpp's server.
- Library: Kiwix ZIM files (Wikipedia, medical references, iFixit, preparedness guides) served by kiwix-serve with full-text search.
- The AI answers from the library: it searches it, reads the top passages and cites them. It still works with the AI off.
- Maps: vector tiles for my region plus a low-detail world map, offline address search and offline directions. The AI can use them as tools.
- An offline self-test, and a one-page printed guide kept with the drive.
- Use exFAT so any computer can read the drive, and avoid symlinks.

First ask me about my computer, drive size, region and priorities. Then propose a plan before writing any code.
```

---

## 8. Accounts and access

- **GitHub:** `tudor-city-ventures/tinfoilkit`, private. The Claude GitHub app has access.
- **Vercel**, connected as travisbloom:
  - Teams: "Travis Bloom's projects", the personal Hobby team, and "tudor-city-ventures". The site goes in tudor-city-ventures.
  - Confirm that team is on Pro, which commercial use requires.
  - The Vercel connector can create projects, deploy and check or buy domains. It can't create teams.
  - A Vercel account can have only one free Hobby team; extra teams need Pro.
- **Claude Code:**
  - Connectors set up in claude.ai, including Vercel, work in Claude Code cloud sessions.
  - Cloud sessions can reach only package registries and other approved sites by default. Real kit downloads need Claude Code running on Travis's Mac.
- **Domain purchase:** only with Travis's OK.

---

## 9. How we got here

1. Travis asked about local LLMs for "end of the world" prep and whether to get a rugged drive. He settled on a 2 TB SSD and his 32 GB Apple Silicon Mac.
2. He asked for a well-thought-out process that's easy to refresh every 2–3 months. That became OfflineKit v1: the sync engine, launcher, page and library, with the full test suite.
3. He asked about Inkling 2 Mini. It became the default model, and the kit switched to llama.cpp nightly builds.
4. He asked for maps "just like Google Maps" that work with the AI. That became v2: tiles, address search, directions, nearest places and map tools for the AI, tested with mocks and real MapLibre in headless Chrome.
5. He asked what else he was missing; the result is a personal prep checklist, kept out of this repo.
6. He decided to open-source it as Tinfoil Kit, with a marketing site on Vercel, and answered a round of questions to pin down the details (section 7).
7. He wants agent-driven development like the Do They Support It repo, but slim and readable (section 5).
8. He moved the work to a Claude Code project. This file is the handoff.
