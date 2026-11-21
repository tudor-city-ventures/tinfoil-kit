# Tinfoil Kit

An offline AI assistant, a searchable library (Wikipedia, medical guides, repair manuals,
survival books) and offline maps with address search and directions. It all runs from this drive with no internet.
Print this page and keep it with the drive.

---

## In an outage: start it

1. Plug the drive into the Mac (Apple Silicon, ideally 32 GB memory). Plug the Mac into power if you can.
2. Open the drive in Finder and **double-click `START-HERE.command`**.
   - If macOS won't open it: open Terminal and type `bash ` (with a space), drag `START-HERE.command` into the
     window, and press Return. That always works.
3. A browser tab opens. **Keep the Terminal window open** while you use it. Closing it stops everything.

Nothing here needs the internet, an account, or an install.

## Using it

- **Ask**: type a question. The kit searches your offline books, then the AI answers and cites them as [1], [2].
  Click a source to read the original. If the AI won't start, Ask still shows the best passages from the books.
- **Library**: browse or search every book yourself.
- **Map**: search an address or place, get driving or walking directions, or find the nearest hospital, pharmacy,
  gas station and more. See [Maps](#maps).
- **AI chat**: plain chat with the AI. You can attach a photo (a plant, a rash, a broken part).
- **Models**: pick from the list on the Ask page.
  - `Inkling-2-Mini` (default): fast, good quality, reads photos.
  - `Qwen3.8-27B` and `Gemma-4-26B-A4B`: second and third opinions from other labs. Worth asking twice on anything important.
  - `Gemma-4-E4B`: small. Use it to **save battery**. On a Mac with less than 32 GB of memory the kit starts
    with it, because the bigger models don't fit.
- The first answer after switching models takes up to a minute while it loads. After that it's quick.
- **Share with family**: start with `bash START-HERE.command --share`. It prints an address that phones on the same
  Wi-Fi or hotspot can open (turn on the Mac's hotspot if the router is down). If macOS asks whether to accept
  incoming connections, click **Allow**.

The AI can be wrong. Treat it like a well-read friend, not a doctor: check the sources, and get trained help whenever you can.

## Maps

- **Search**: type an address or place name in the box at the top of the Map tab and pick a match.
  Click its pin for **Directions here** or **Set as home**.
- **Directions**: fill in From (leave it blank for home) and To, pick Drive or Walk, press Go. Click a step to zoom to it.
- **Nearest**: the buttons (Hospital, Pharmacy, Gas station...) list the closest ones to home, or to the From address.
- **Set home** first: the Mac has no GPS, so "home" is where nearest-searches and directions start.
  Use **Set as home** on a search result, or move the map and click **Set home to the map center**.
- **Ask in plain words** on the Ask page: "How do I get to the nearest hospital?", "Directions from home to
  350 Fifth Avenue, New York", "Where is the closest gas station?". The AI looks it up and the route appears on the Map tab.
  This works even when the AI is off, for simply worded questions.

Coverage: street-level map, addresses and directions for the US Northeast (New England, New York, New Jersey,
Pennsylvania), plus a low-detail world map. Address search covers the whole US. Change the region in `kit.json`
under `"maps"` (see its notes), then run `./kit sync`.

**For actually driving, use your phone.** Download offline maps on it now: Organic Maps (free, fully offline,
spoken directions) or offline areas in Google Maps or Apple Maps. A phone has GPS; this laptop doesn't.
The kit's map is the backup, and it's handy for planning on a big screen and for the AI questions.

## Every 2 to 3 months: update it (while you still have internet)

Double-click `SETUP.command`. Or open Terminal in the kit folder (drag the `TinfoilKit` folder onto the
Terminal icon) and run:

```
./kit sync      # shows what's new, downloads it, checks every file, then removes old versions
./kit test      # starts everything briefly and confirms it works
```

Either way it is safe to stop (Ctrl-C or close the window) and re-run; it picks up where it left off. A normal update downloads
new library editions, the latest AI engine, any re-released models and fresh map data (rebuilding the
directions network takes 10 to 40 minutes). Then pull the plug on Wi-Fi and open the kit once for real.

Other commands:

```
./kit plan            # preview what sync would do (changes nothing)
./kit status          # what's on the drive and when it was last updated
./kit verify          # re-check every file for corruption (add --fix to remove bad ones, then sync)
./kit search medical  # find more books to add
```

## Changing what's on the drive

Everything the kit keeps is listed in **`kit.json`** (open it in any text editor):

- Turn something off: set `"enabled": false` on its line.
- Add a book: `./kit search <words>`, then paste the line it prints into the `"library"` list.
- Swap a model: change its `"repo"` and `"files"` (Hugging Face repo and file name patterns). Each pattern must
  match exactly one file. A new model generation every few months is normal; check which GGUF models fit a
  32 GB Mac (about 20 GB or less) before swapping.

Then run `./kit plan` to preview and `./kit sync` to apply.

## First-time setup

1. Format the drive in Disk Utility: **exFAT** if you want a Windows or Linux PC to be able to read it
   (recommended for an emergency drive), **APFS** if it will only ever be used with Macs.
   Many new drives come as exFAT already. FAT32 (files over 4 GB don't fit) and NTFS (Macs can't write to it)
   won't work; SETUP checks. Always eject the drive before unplugging, especially with exFAT.
2. Copy the `TinfoilKit` folder onto the drive. (From GitHub: **Code > Download ZIP**, then copy the unzipped folder.)
3. Double-click **`SETUP.command`** in that folder. It checks the drive, downloads everything (about 280 to
   330 GB the first time, a few hours; maps are 20 to 30 GB of that), then starts each part offline to check
   it answers. Leave the Mac plugged in. If you stop it, double-click it again and it picks up where it left off.
   If it ends with "some downloads didn't finish", the kit already works with what it has: double-click
   `SETUP.command` again later and it fetches the rest.
   - If macOS says it can't be opened because it's from the internet: open **System Settings > Privacy &
     Security**, scroll down and click **Open Anyway**. You only do this once.
   - If macOS asks whether Terminal may access files on a removable volume, say yes.
   - If it asks to install the Command Line Tools, say yes, then double-click `SETUP.command` again.
4. Turn off Wi-Fi and double-click `START-HERE.command`.

Optional: `brew install aria2` makes downloads faster.

## Power

Running a big model uses a lot of battery: expect a couple of hours of active use on a laptop battery.
A USB-C power station plus a folding solar panel keeps it going. Use `Gemma-4-E4B` when power is short,
and the Library tab (no AI) uses almost nothing.

## If something doesn't work

- Close the Terminal window and double-click `START-HERE.command` again.
- Terminal says "Operation not permitted": macOS is keeping it off the drive. Open **System Settings > Privacy &
  Security > Files and Folders**, turn on **Removable Volumes** under Terminal, and start again.
- Logs are in the `logs` folder.
- If a model won't load or is very slow, quit other apps (big models need most of a 32 GB Mac's memory), or use `Gemma-4-E4B`.
  Starting with `bash START-HERE.command --no-maps` frees about 5 GB by not starting the map servers.
- Map says address search or directions are "not running": they take up to a minute to start. If they never do,
  see `logs/geocoder.log` and `logs/routing.log`. If `./kit test` fails on address search with a "lock" error in
  `logs/test-geocoder.log`, the exFAT format is the cause: reformat the drive as APFS and copy the kit back.
  Advanced: `sudo sysctl iogpu.wired_limit_mb=26624` lets the GPU use up to 26 GB until the next restart.
- The previous version of each program is kept in `bin/` as a fallback and is used automatically if the newest one won't start.
- The Kiwix app in `installers/` opens the `.zim` books in `library/` directly, without the rest of the kit.

## If the Mac is gone

On a Windows PC, double-click `START-HERE-Windows.bat` (the drive must be exFAT). On Linux, run
`bash START-HERE.command`. These fallbacks are less tested than the Mac path, and without a good graphics card
the AI is slow: use `Gemma-4-E4B`. The map works on the Mac only.

## What's where

| Folder / file | What it is |
|---|---|
| `START-HERE.command` | Starts everything (Mac, Linux) |
| `START-HERE-Windows.bat` | Starts everything (Windows fallback) |
| `kit`, `kit.json` | Update tool and the list of what to keep |
| `INVENTORY.md` | What's on the drive right now, with versions |
| `library/` | The books (`.zim` files) |
| `models/` | The AI models (`.gguf` files) |
| `maps/` | Map tiles, the address database, the road network for directions, and the map display code |
| `bin/` | The programs: llama.cpp (AI), kiwix-serve (library), and for maps pmtiles, Photon, GraphHopper and Java |
| `installers/` | Optional apps (Kiwix for Mac) |
| `tools/` | The kit's own scripts and web page |
