# Third-party content and software

The kit's own code is [MIT](LICENSE). The models, books, maps and programs below are not part of it: `./kit sync` downloads each one onto your drive straight from its publisher, and each keeps its own license and terms. You're the one downloading them, so those terms apply to you. In short: all of it is free to download and use yourself, and some of it is not free to sell.

## AI models

| Model | Made by | License |
| --- | --- | --- |
| Inkling 2 Mini (default) | Thinking Machines | Apache 2.0, plus Thinking Machines' [Model Acceptable Use Policy](https://thinkingmachines.ai/model-acceptable-use-policy/), which binds anyone who downloads the weights |
| Qwen3.8 27B | Alibaba (Qwen) | Apache 2.0 |
| Gemma 4 26B-A4B, Gemma 4 12B, Gemma 4 E4B | Google | Apache 2.0 |

The files come from ggml-org's and Unsloth's Hugging Face repos, which repackage the makers' weights.

## Library (Kiwix ZIM files)

- Wikipedia, Wiktionary, Wikibooks, Wikivoyage, Wikiversity, WikiMed: CC BY-SA. Images carry their own licenses.
- Stack Exchange sites, Appropedia, Energypedia: CC BY-SA.
- iFixit: CC BY-NC-SA, no commercial use.
- LibreTexts: mostly CC BY-NC-SA, no commercial use. Some books differ.
- Khan Academy (off by default): mostly CC BY-NC-SA, no commercial use.
- Ready.gov, CDC Travelers' Health, US Army publications and the military medicine manuals: US government works, generally public domain.
- MedlinePlus: the National Library of Medicine's own pages are US government works. Its medical encyclopedia (A.D.A.M.) and drug information (from ASHP) are copyrighted and licensed to it: free to read, not to republish.
- Project Gutenberg (off by default): public domain in the US. "Project Gutenberg" is a trademark with its own rules for redistribution.
- Urban Prepper, Survivor Library, CD3WD, the Learning Self-Reliance videos and the collections of field medicine, post-disaster, water, food and knots guides belong to their authors, under mixed terms. Treat them as free to read, not free to republish.

## Maps

- Map tiles, address search and directions use OpenStreetMap data, © OpenStreetMap contributors, under the [Open Database License](https://www.openstreetmap.org/copyright). It arrives through Protomaps' daily builds, Geofabrik's extracts and the Photon exports GraphHopper hosts.
- Map style: Protomaps basemaps (BSD-3-Clause). Map fonts: Noto Sans (SIL Open Font License). Map icons: derived from tangrams/icons (MIT).

## Programs

| Program | License |
| --- | --- |
| llama.cpp (llama-server) | MIT |
| kiwix-tools (kiwix-serve) | GPL-3.0 |
| Eclipse Temurin (Java) | GPL-2.0 with Classpath Exception |
| go-pmtiles | BSD-3-Clause |
| GraphHopper | Apache 2.0 |
| Photon | Apache 2.0 |
| MapLibre GL JS | BSD-3-Clause |
| Ollama (optional, off by default) | MIT |

## In this repo

- `site/app/fonts/`: IBM Plex Sans and IBM Plex Mono, under the SIL Open Font License ([OFL.txt](site/app/fonts/OFL.txt)).
- The globe on the website is drawn from Natural Earth land data, which is public domain.
- The website is built with Next.js, React, Radix UI, Tailwind CSS, clsx and tailwind-merge (MIT), Lucide's icons (ISC), and two of shadcn/ui's components (MIT), copied into `site/components/ui/`. `site/package-lock.json` pins every package. None of it goes in the kit.
- `package.json` at the repo root lists developer tools: Prettier, ESLint, eslint-plugin-react-hooks and globals (MIT), eslint-plugin-html (ISC) and axe-core (MPL-2.0). `package-lock.json` pins every package. They format and check the kit page, the website and the tests, and ruff (MIT, the version `ruff.toml` names) does the same for the tests' Python; none of it goes in the kit.
- The phone app (`mobile/`) is built with Expo, React Native, React, Expo Router, react-native-screens, react-native-safe-area-context and react-native-web (MIT). Its own ZIM reader opens the books, decompressing them with fzstd (MIT), and its own reader of their full-text index (Xapian's format) searches them, cutting English words to their stems as Snowball's English stemmer (BSD-3-Clause) does, from its description. It cuts the map of where the person lives out of Protomaps' world map itself, compressing and decompressing the map file's directories with fflate (MIT), and draws it with MapLibre React Native (MIT), MapLibre Native (BSD-2-Clause) and the kit page's style from Protomaps basemaps (BSD-3-Clause), which bring maplibre-gl-style-spec (ISC) and Turf (MIT). On an iPhone with Apple Intelligence, Ask's answers come from Apple's own model, built into iOS, through its Foundation Models framework, under Apple's acceptable use requirements for it: the app downloads and carries no model. `mobile/package-lock.json` pins every package, and the app carries their notices. None of it goes in the kit.
- `mobile/skills.py` installs guides for AI coding agents working on the phone app, all MIT, the same way: eleven of Expo's from expo/skills, `react-native-best-practices` and `github-actions` from callstackincubator/agent-skills, `react-native-testing` from callstack/react-native-testing-library, and `vercel-react-native-skills` from vercel-labs/agent-skills.
- `site/skills.py` installs guides for AI coding agents working on the website, all MIT, straight from their publishers' repos at pinned commits: `vercel-react-best-practices` and `web-design-guidelines` from vercel-labs/agent-skills, `shadcn` from shadcn-ui/ui, and `ai-seo` and `schema` from coreyhaines31/marketingskills. They aren't in this repo, and the installed copies never run a command when they load.
- `tools/tinfoilkit-*`, the kit's own program, which releases carry, is built from `tools/tinfoilkit/` with Go. Go's runtime and standard library are compiled into it, under Go's license:

```text
Copyright 2009 The Go Authors.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are
met:

   * Redistributions of source code must retain the above copyright
notice, this list of conditions and the following disclaimer.
   * Redistributions in binary form must reproduce the above
copyright notice, this list of conditions and the following disclaimer
in the documentation and/or other materials provided with the
distribution.
   * Neither the name of Google LLC nor the names of its
contributors may be used to endorse or promote products derived from
this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
"AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

- `tools/regions.json`, the places SETUP offers for "Where do you live?": their outlines, names and download addresses come from Geofabrik's index of OpenStreetMap extracts (© OpenStreetMap contributors, Open Database License), and the towns that set each place's home and search names from [GeoNames](https://www.geonames.org/) (CC BY 4.0).

## Sharing or selling a filled drive

Giving someone a copy, or publishing something made from it, brings in each license's attribution and share-alike terms. Selling filled drives needs more than that: iFixit, LibreTexts and Khan Academy forbid commercial use, kiwix-serve's GPL comes with source-code duties, and the ODbL covers the map databases the kit builds. Check every license first.

## Trademarks

Product, site and company names here belong to their owners. Tinfoil Kit isn't affiliated with or endorsed by any of them. Mac is a trademark of Apple Inc.
