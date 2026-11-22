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
- Ready.gov, US Army publications and the military medicine manuals: US government works, generally public domain.
- Project Gutenberg (off by default): public domain in the US. "Project Gutenberg" is a trademark with its own rules for redistribution.
- Urban Prepper, Survivor Library and the collections of field medicine, post-disaster, water, food and knots guides gather work from many authors under mixed terms. Treat them as free to read, not free to republish.

## Maps

- Map tiles, address search and directions use OpenStreetMap data, © OpenStreetMap contributors, under the [Open Database License](https://www.openstreetmap.org/copyright). It arrives through Protomaps' daily builds, Geofabrik's extracts and the Photon exports GraphHopper hosts.
- Map style: Protomaps basemaps (BSD-3-Clause). Map fonts: Noto Sans (SIL Open Font License). Map icons: derived from tangrams/icons (MIT).

## Programs

| Program | License |
| --- | --- |
| llama.cpp (llama-server) | MIT |
| kiwix-tools (kiwix-serve), Kiwix for macOS | GPL-3.0 |
| Eclipse Temurin (Java) | GPL-2.0 with Classpath Exception |
| go-pmtiles | BSD-3-Clause |
| GraphHopper | Apache 2.0 |
| Photon | Apache 2.0 |
| MapLibre GL JS | BSD-3-Clause |
| Python, which SETUP-Windows.bat gets from nuget.org for the kit's tools on Windows (it stays outside the kit) | PSF License |
| Ollama (optional, off by default) | MIT |

## In this repo

- `site/fonts/`: IBM Plex Sans and IBM Plex Mono, under the SIL Open Font License ([OFL.txt](site/fonts/OFL.txt)).
- The globe on the website is drawn from Natural Earth land data, which is public domain.

## Sharing or selling a filled drive

Giving someone a copy, or publishing something made from it, brings in each license's attribution and share-alike terms. Selling filled drives needs more than that: iFixit, LibreTexts and Khan Academy forbid commercial use, kiwix-serve's GPL comes with source-code duties, and the ODbL covers the map databases the kit builds. Check every license first.

## Trademarks

Product, site and company names here belong to their owners. Tinfoil Kit isn't affiliated with or endorsed by any of them. Mac is a trademark of Apple Inc.
