# Tinfoil Kit

An offline kit for when the internet goes down. One external SSD holds:

- **Local AI** (llama.cpp) that answers from the library and cites its sources.
- **An offline library** (Kiwix): Wikipedia, medical references, repair guides, preparedness manuals.
- **Offline maps** with address search, driving and walking directions, and "nearest hospital".

Plug in the drive, double-click `START-HERE.command`, and a browser page opens with Ask, AI chat, Library and Map tabs. No internet, account or install needed.

![The Ask tab](docs/screenshots/shot_ask.png)

## Requirements

- An Apple Silicon Mac. Built around 32 GB of memory; smaller Macs start with the small model.
- A 2 TB external SSD. The first sync downloads about 300 GB.

Windows and Linux paths exist in the code but are untested.

## Set up

Copy this folder onto the drive (**Code > Download ZIP** on GitHub, then unzip) and double-click `SETUP.command`. It checks the drive, downloads everything and tests it. Or from Terminal:

```sh
git clone https://github.com/tudor-city-ventures/tinfoilkit /Volumes/<drive>/TinfoilKit
cd /Volumes/<drive>/TinfoilKit
./kit plan    # preview what will download
./kit sync    # download everything (a few hours)
./kit test    # start every server offline and check it answers
```

Then turn Wi-Fi off and double-click `START-HERE.command`. [GUIDE.md](GUIDE.md) is the printable guide that lives on the drive.

## Keep it fresh

Double-click `SETUP.command` (or run `./kit sync` and then `./kit test`) every two to three months. Downloads resume, every file is checked against its published checksum, and the old version stays until the new one verifies.

## Customize

Everything the kit keeps is listed in [kit.json](kit.json). Set `"enabled": false` to skip an item, or find more books with `./kit search WORDS`.

## Contributing

Agent and contributor rules are in [AGENTS.md](AGENTS.md). Design history is in [docs/HANDOFF.md](docs/HANDOFF.md).

## License

[MIT](LICENSE)
