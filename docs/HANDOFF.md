# Tinfoil Kit: history and decisions

Handoff from the Claude chat where the kit was built (2026-11-21). The code moved into this repo; section 1 is the state at handoff. Agent rules live in `AGENTS.md`.

## Status (2026-11-21, second Claude Code thread)

**Done**
- Repo set up for agents (AGENTS.md, CLAUDE.md), quick gate and CI. The end-to-end suite passes in GitHub Actions against the mocks and also runs `SETUP.command`.
- Site: the Field Manual design (variant A of 3) is in `site/`, deployed by Vercel from `main`. It has an animated hero (`site/hero.js`: a dotted globe streams into the drive, then the Wi-Fi drops; it pauses, and holds a still frame for reduced motion), the kit builder with live sizes (weekly `refresh builder sizes` Action), a questions section, a mark (`icon.svg`, the world in a foil hat) with the favicons, Apple touch icon and social card (`og.png`) rendered from it by `build_images.py`, canonical URLs for tinfoilkit.com, and security headers in `site/vercel.json`. CI checks it with Playwright and axe, served with the production headers. The headers were checked on a live deployment.
- `SETUP.command`: the double-click guided setup and refresh, with checks for the drive format and the Command Line Tools. GUIDE, README and the site point to it.
- kit.json matches the Kiwix catalog. WikEM, WHO and the Gutenberg subject subsets were dropped upstream, two entries were renamed, and Urban Prepper was added. All 60 sources resolve.
- tinfoilkit.com: bought 2026-11-21 through Vercel on the tudor-city-ventures team (registrant Tudor City Ventures LLC, auto-renews yearly). It's on the `tinfoilkit` project, and `www` redirects to it (308).
- `./kit update` (Travis chose to build it before launch): `SETUP.command` first installs the newest GitHub release of the kit's code and keeps each drive's kit.json changes. Design in section 3. It does nothing until the repo is public and has a release (launch day, step 5).
- Ready for outside contributors: CONTRIBUTING, SECURITY, the code of conduct, issue forms, a PR template and CODEOWNERS are in `.github/`, out of sight on drives. Outside pull requests need an open issue labeled `accepted`, and `pr-gate.yml` closes the rest (members, collaborators and past contributors skip it). Fork PRs need DCO sign-off (the `sign-off` job in `check.yml`). Workflow tokens are read-only except in the sizes refresh and the gate. GitHub's own settings go on at launch (step 4).
- Launch-day checklist: see section 7.
- Second thread (robustness, tests, accessibility):
  - Sync tells the truth: it exits 1 when anything failed or couldn't be looked up, stops with one message when offline or behind a Wi-Fi sign-in page, and never resumes a half-download of an older version into a new file. Leftover half-downloads of old versions are cleaned up.
  - `SETUP.command` says "All set" only when everything finished and passed, lists what didn't finish otherwise, handles Ctrl-C, and rejects FAT32 and NTFS drives up front. (Sync already lifts the downloaded-from-internet mark from the launchers, so `START-HERE.command` opens without a Gatekeeper prompt in an outage.)
  - `tests/sync_test.py` runs the real sync against the mocks in the quick gate (about 10 seconds): resume, checksums, updates, leftovers, `verify --fix`, lost state, offline, and every ending of `SETUP.command`.
  - The page works from the keyboard and with screen readers, and dark mode buttons are readable; e2e runs axe on every tab in light and dark mode.
  - The site serves its own fonts (no Google requests); the CSP allows nothing third-party. The kit builder fits phones down to 320px wide.
  - The launcher starts with a model that fits the Mac's memory, reuses only its own servers (another program on 8888 or 8080 makes it move to the next free port), and clears the `._` files macOS leaves on exFAT before the servers scan their folders.
  - CI also runs the sync test on Python 3.9 (via uv) and with bash 3.2 (the official `bash:3.2` image), the versions macOS ships.
- Drive test (`drive.yml`, by hand and nightly; Travis chose nightly until launch, every kit change once public, and no run when the kit hasn't changed): the kit set up on a real exFAT disk on one of GitHub's Apple Silicon Macs, with the real llama.cpp and kiwix-tools builds, then started from that same drive on Windows and Linux. Details in section 4. It found that the launcher needed curl, which stock Ubuntu and Debian desktops don't have; it now falls back to bash's `/dev/tcp`. And Fedora 45 moved to OpenSSL 4, while llama.cpp's Linux build needs OpenSSL 3, so the AI needs `openssl3-libs` there (GUIDE says so).

**Waiting on Travis**
- Whether tinfoilkit.com stays public before launch. The project's Vercel Authentication covers everything except custom domains, so the site is public there, and its GitHub buttons 404 until the repo is public. Hiding it means setting protection to all deployments; that needs his OK.
- Switch GitHub's default branch to `main`. Until then, push `main` to `claude/project-thread-ew0j18` too, because scheduled workflows run from the default branch's copy of `.github/`. (Vercel deploys production from `main`; the sizes workflow checks out and pushes `main`.)
- A real `SETUP.command` run on his Mac. This is the only test against real downloads and Apple Silicon.
- Going public: turn off Vercel Authentication for production and make the repo public. Ask first.
- Contribution policy, in place as recommended until Travis says otherwise: the issue-first gate (not label-only or invite-only), DCO sign-off (not a CLA or nothing), and AI tools allowed with disclosure and a person answering for every PR.

**Decided for now (Travis, 2026-11-21):** llama-server is the only AI runtime (no Ollama or LM Studio), Ask stays one library search then an answer (only map questions use tools), and "AI chat" stays llama-server's own page.

**Ideas not started**
- Real product screenshots on the site. CI's e2e screenshots use test data (a tiny model, mock places), so they would need real data from Travis's Mac.
- The CI artifact host (blob.core.windows.net) is blocked from cloud sessions, so artifacts can't be downloaded there.

---

## 1. Where things stood at the handoff

Written before the first Claude Code thread. The Status section above is current.

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

- **For:** technical people and non-technical preppers. Version 1 supports Apple Silicon Macs only and is designed around 32 GB of memory; smaller Macs can use the small model. Windows and Linux are fallbacks: the nightly drive test starts the kit on both from a drive a Mac set up, with test data.
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
| `tools/kit.py` | Sync engine and CLI. Python 3.9+, standard library only; all HTTP goes through `curl` |
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
- `./kit update [--force]`: install the newest release of the kit's own code, keeping kit.json changes. `--force` reinstalls the current one.
- Launcher: `bash START-HERE.command [--share] [--model=NAME] [--no-browser] [--no-maps]`.

### Updating the kit's own code (`./kit update`)

Why: a drive set up once kept its `tools/` and `kit.json` forever, so a source renamed or dropped upstream (four were in November 2026) failed on every sync until someone edited kit.json by hand.

- `SETUP.command` runs it first. It installs the newest GitHub release of this repo (the tarball GitHub makes for `releases/latest`), then SETUP starts over once on its new copy of itself. Exit codes: 3 installed, 0 nothing to do, 1 failed (SETUP carries on with the old code).
- The archive is untrusted: plain files and folders only, all inside its one top folder, under 500 MB. It's unpacked into `.kit/update` and checked before anything moves: the needed files exist, `kit.py` compiles on this Mac's Python, `kit.json` parses, the scripts pass `bash -n`. The drive's own folders (`models`, `library`, `maps`, `bin`, `logs`, `.kit` and so on) are never touched.
- kit.json merges three ways: the release's, the drive's, and `site/kit.json` (the untouched copy every version ships) as the base. The drive's changes win and the release's changes land everywhere else. An item the release dropped goes, unless its owner changed more than `enabled`. A changed kit.json is rewritten as plain 2-space JSON, the format the website builder makes.
- A copy from GitHub knows its commit: `.gitattributes` sets `export-subst` on `tools/kit.py`, so `git archive` (releases and Code > Download ZIP) writes it into `KIT_COMMIT`. If GitHub says that commit is newer than the latest release (a ZIP of `main`), the copy stays.
- Files the previous release installed and the new one lacks are deleted. A drive set up from a ZIP has no such list, so its first update deletes nothing.
- A git checkout is told to run `git pull` instead.

### Sync engine rules (keep these)

- Each item is resolved to a version and a list of files with checksums, then compared with `.kit/state.json`. Sync then plans, checks free space (`keep_free_gb`), downloads, verifies, installs and prunes.
- Downloads resume after interruption: `curl -C -` with retries, or `aria2c` when it's installed.
- Half-finished downloads are `<file>.partial` next to their destination (archives and the Photon dump: `.kit/downloads/`). `state.json` records each one's version under `partials`:
  - a partial of a different version under the same file name (models often keep their names) is discarded, not resumed into a corrupt file;
  - at the start of a sync, partials that a newer version made useless are deleted (they can be 100 GB); those of switched-off items are kept;
  - free-space checks count what a partial already has.
- Exit codes: `sync` exits 1 if any item failed or couldn't be looked up, and 130 on Ctrl-C (everything finished is saved). `last_sync` is set only after a fully clean run. `plan` and `sync` exit 1 straight away when nothing could be looked up (offline, or a Wi-Fi sign-in page answering instead).
- The Kiwix catalog is cached only after it parses, so a sign-in page can't poison the cache.
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
- **First model:** the default, unless its files take more than 60% of memory; then the biggest model that fits, else the smallest. `--model=NAME` overrides. `KIT_MEMORY_MB` fakes the memory size for tests.
- **Ports:** a server already on a port counts as the kit's only if it answers like one (the page's title, or `/v1/models` JSON). Otherwise the library or AI starts on the next free port, and the page's address carries it. Map ports are baked into the page at sync time, so they don't move.
- It serves the page `./kit sync` built (`.kit/portal.html`, with the map inside) whenever it exists, and the bare template otherwise. The launcher never needs python, so a drive works on a Mac without the Command Line Tools. It doesn't need curl either: without it (stock Ubuntu and Debian), it checks its servers through bash's `/dev/tcp`. When a program on the drive won't run (say, a library Linux lacks), it prints the reason.

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
- **Tabs** are links (`#ask`, `#map`, `#library`, `#help`), so the keyboard reaches them and the address remembers the tab. The status line is `role="status"`; map results, nearest places and route steps are buttons.
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
  - Medical: WikiMed (mdwiki), military medicine, LibreTexts medicine.
  - Preparedness: Ready.gov, Urban Prepper, post-disaster, water treatment, food, knots.
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
- On exFAT, macOS keeps Finder metadata in `._name` files beside the real ones (opening a book from Finder is enough). Python's `Path.glob("*.zim")` matches them; bash's `*` doesn't. The launcher and `./kit test` delete them from `library/` and `models/`.
- `actions/setup-python` has no Python 3.9 for current Ubuntu runners; CI gets 3.9 from uv.

---

## 4. Tests as they exist

The scripts are in `tests/`; AGENTS.md says which to run when.

- **Quick gate (`check.sh`, every push):** compile and parse checks, shellcheck when installed, kit.json validity, `site/sources.json` freshness, CRLF on the Windows launcher, then:
  - `sync_test.py`: the real `kit.py` against `mock_remote.py` with tiny random files: downloads, a download that breaks and resumes, checksums, a second sync that does nothing, `verify --fix`, lost `state.json`, a "3 months later" update with planted leftovers, offline and Wi-Fi sign-in runs, and every ending of `SETUP.command` with a stand-in `./kit`, the launcher's first-model choice by memory, and its move off a port another program holds. Needs only python3 and curl, so it runs in cloud sessions.
  - `map_logic_test.js`: the page's `Kit` map code against a mock Photon, GraphHopper and tool-calling AI (`mock_services.py`).
- **End to end (`build_fixtures.sh` then `run_all.sh`, CI on changes to the kit):** copies the kit onto a fake drive with real kiwix-serve and llama-server binaries, a tiny GGUF model and test ZIMs, then:
  - `plan` and `sync` (three entries are broken on purpose: sync must finish the rest, name them and exit 1), `verify`, `SETUP.command`, `search`;
  - the launcher, then `portal_test.js`, `map_logic_test.js` and the Playwright UI tests (`ui_test.py`, `map_ui_test.py`), with axe on every tab in light and dark mode when `KIT_AXE` is set;
  - `--no-maps`;
  - a "3 months later" update with a new catalog and new map builds, then `kit test` again.
- **Drive (`drive.yml`, by hand, and nightly when the kit changed):** `build_fixtures.sh drive` adds the newest real llama.cpp and kiwix-tools builds for Mac, Windows and Linux to the mock internet, then `drive_test.sh` uses one disk image the whole way:
  - Mac (GitHub's macOS 26 on Apple Silicon): erase the image as exFAT, copy the kit on as Download ZIP leaves it (marked as from the internet, with `._` files), run `SETUP.command` with a stock PATH and `/bin/bash`, double-click `START-HERE.command` (Terminal, then Safari), check the page in WebKit, add Finder-style `._` files beside the books and the model, and eject.
  - Windows: mount the same drive as a VHD, double-click `START-HERE-Windows.bat`, check the page in Edge. macOS marks its `._` files hidden on exFAT, and the .bat's `for` skips hidden files, so they do no harm there.
  - Linux: mount it as a desktop does (udisks2 options), start the kit on GitHub's Ubuntu (26.04 now), then in Ubuntu 24.04 and 22.04, Debian 12 and Fedora containers. 22.04 is the oldest the llama.cpp build runs on.
  - Nightly and push runs start only when a file the test covers changed since the last green run (or the push before), so site edits never cost Mac minutes. Runs by hand always go.
  - Screenshots and logs are run artifacts. A run takes about 3 Mac minutes (about $0.25 with the other jobs while the repo is private; free once public).
  - Not covered: maps, real models on a real GPU, and the first-run prompts a person clicks through (Open Anyway for `SETUP.command`, Terminal's removable-volume permission, the Command Line Tools install).
- **Website (`site_test.py`, every push):** serves `site/` with the production headers and drives the kit builder on desktop and phone sizes: presets, totals, no sideways scroll, fonts load from the site, nothing loads from other sites, both Copy paths, the kit.json download, and axe.
- **`mock_remote.py`** fakes every download source. Flag files switch its behavior: `STATE_V2` ("3 months later"), `FLAKY` (a download breaks partway), `PHOTON_OLD_DUMP` (only an older database version is published). `/wifi-sign-in` answers like a hotel network's sign-in page.
- **`tests/fakes/`:** a fake `java` (pretends to be GraphHopper's import and server, and Photon, by running the mocks) and a fake `pmtiles`.

**Never verified. Needs a real Mac and the internet:**
- Real downloads and checksums from each source.
- The map programs' Apple Silicon builds (Java, pmtiles). The drive test runs llama-server and kiwix-serve on an Apple Silicon VM, but on a virtual GPU with a tiny model.
- First-run prompts on a fresh Mac and a physical USB drive.
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
- **Domain:** tinfoilkit.com, $12.03 a year through Vercel on the tudor-city-ventures team. Bought 2026-11-21.
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

### Launch day

Each step needs Travis's go-ahead, because none of them can be quietly undone.

1. Travis runs `SETUP.command` on his Mac and `./kit test` passes.
2. Done: tinfoilkit.com and `www` (redirecting to it) are on the `tinfoilkit` project.
3. Make sure the public can see tinfoilkit.com: Vercel Authentication on the `tinfoilkit` project must be "all except custom domains" (or off). Previews stay protected.
4. Make the GitHub repo public. The site's GitHub button and the install prompt point at it. First:
   - switch the default branch to `main` (visitors land on it) and delete `claude/project-thread-ew0j18`;
   - decide whether this file stays public. Sections 8 and 9 are internal (accounts, how the project started); trim them if not. Commit authors are all `Claude <noreply@anthropic.com>` or the Actions bot, so no personal email is in the history.
   Then turn on the settings in "GitHub settings at launch" below, all but the `main` ruleset (step 7). Several exist only for public repos, and the release protections must be on before step 5.
5. Publish the first GitHub release from `main` (for example `v1.0.0`), with a few lines on what's in it: SETUP shows them after updating. Until the repo is public and has a release, `./kit update` finds nothing and drives keep their version.
6. Check the social card (https://tinfoilkit.com/og.png) with a link preview, and that the builder loads sources.json.
7. Switch to PRs and review from then on: turn on the `main` ruleset (below) and update AGENTS.md's Workflow section. The ruleset ends direct pushes, including the weekly sizes commit, so in the same step switch `sizes.yml` to open a pull request, run the checks on it with `workflow_dispatch` (pull requests opened with the Actions token don't trigger workflows) and auto-merge it. That needs "Allow GitHub Actions to create and approve pull requests" and auto-merge turned on.

#### GitHub settings at launch

The policy and its reasons are in `.github/CONTRIBUTING.md`. In the repo's Settings:

- **General**
  - Pull requests: allow squash merging only; turn on auto-merge and "Automatically delete head branches".
  - Limit open pull requests for users without write access: 2.
  - Social preview: upload `docs/social-preview.png` (made by `site/build_images.py`), so shared repo links show the card. GitHub has no API for it, and it can go up any time.
  - Leave pull requests open to everyone. "Restrict pull requests to collaborators" is the brake for a flood: while it's on, only people with write access can open them.
  - Releases: turn on release immutability. Every drive installs the latest release, so its tag and files must never change.
  - Features: turn off Wikis and Projects.
- **Moderation options:** interaction limits stay off; in a flood, "Limit to existing users" (blocks accounts under a day old) or "Limit to prior contributors", for a day to a week. Code review limits on. Reported content: accept reports from everyone (the code of conduct sends people there).
- **Actions > General:** allow only actions created by GitHub (every workflow uses `actions/*`). Fork pull request workflows: the strictest approval option, every outside contributor. Workflow permissions: read-only.
- **Rules > Rulesets**
  - Tag ruleset `releases` on `v*`: restrict creations, updates and deletions; bypass: Repository admin. Before the first release.
  - Branch ruleset `main` on the default branch: restrict deletions, block force pushes, require a pull request (no approvals: Travis's agents open PRs as Travis, and an author can't approve their own; conversations resolved), require the status checks `quick-gate`, `oldest-python`, `bash-3-2`, `site` and `sign-off`; bypass: Repository admin, for pull requests only. With step 7, not before. `e2e` isn't required because it only runs when the kit changes.
- **Code security:** private vulnerability reporting (SECURITY.md sends reports there), Dependabot alerts, secret scanning with push protection, CodeQL default setup.
- **Collaborators:** to vouch for someone, add them with the Read role; the pull request gate skips collaborators. Anyone who needs more than two open PRs goes on the limit's bypass list.
- **Organization** (tudor-city-ventures): require two-factor authentication.
- **Vercel** (`tinfoilkit` project): keep Git Fork Protection on, so pull requests from forks don't deploy previews until approved.
- **Labels:** `accepted` and `auto-closed` come from running the `pull request gate` workflow by hand. Run it again after changing them there.

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
- **Purchases:** only with Travis's OK.

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
