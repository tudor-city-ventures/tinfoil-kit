# Tinfoil Kit

An offline AI assistant, a searchable library (Wikipedia, medical guides, repair manuals, survival books) and offline
maps with address search and directions. It all runs from one folder with no internet, on your computer or on an
external drive. Print this page and keep it handy (with the drive, if the kit is on one).

---

## In an outage: start it

1. If the kit is on a drive, plug it in: any Mac, Windows PC or Linux PC will do (ideally 32 GB memory; Windows and
   Linux are experimental for now). Plug the laptop into power if you can.
2. Open the `TinfoilKit` folder: at the top of the drive, or on the computer itself in your home folder (Mac: in
   Finder choose **Go > Home**. Windows: in File Explorer, your user folder, `C:\Users\<you>`). `Read me first.txt`
   there says what to open, and what each folder is for.
3. Start it:
   - **Mac**: double-click **`Open Tinfoil Kit.command`**. If macOS won't open it, open Terminal and type `bash ` (with
     a space), drag `Open Tinfoil Kit.command` into the window, and press Return. That always works.
   - **Windows**: double-click **`Open Tinfoil Kit for Windows`** (`.bat`). If Windows says it protected your PC, click
     **More info**, then **Run anyway**.
   - **Linux**: open a terminal in the `TinfoilKit` folder and run `bash "Open Tinfoil Kit.command"`.
4. A browser tab opens. **Keep the kit's window open** while you use it. Closing it stops everything.

Nothing here needs the internet, an account, or an install.

## Using it

The kit page has three tabs, Ask, Map and Library, and **More** for the rest: Notes, Share with family, Print the
essentials, AI chat and Help. The button beside the name says how the kit is: **Ready**, **Starting** while the AI
loads, or **AI off**, and **Shared** while others can use it. Click it for more.

- **Ask**: type a question, then pick one of two buttons:
  - **Search**: the best passages from your books in seconds, without the AI, on very little power. Use it to save
    battery, or to read for yourself. **Have the AI answer from these** then turns what it found into an answer.
  - **Ask the AI**: the kit searches your offline books, then the AI answers and cites them as [1], [2]. Click a source
    to read the original. It's slower, and it uses more power than Search.

  If the AI won't start, Ask the AI still shows the best passages from the books.
- **Library**: browse or search every book yourself.
- **Map**: search an address or place, get driving or walking directions, or find the nearest hospital, pharmacy, gas
  station and more. See [Maps](#maps).
- **Notes** (under More): write down what you'd need to know in an emergency: who lives here, allergies and medicines,
  doctors, where to meet. The AI reads them with every question on Ask. They're saved in the kit, in `data/notes.txt`
  (a plain text file you can also open in any text editor), and every browser and phone on the kit sees the same
  notes. They aren't encrypted, so leave out passwords and bank details.
- **Print the essentials** (under More): about 20 pages of the kit's books worth having on paper, most important
  first, from making water safe to first aid, and a page of your own with your notes, your pins and the nearest
  hospitals. Print them while you have power and keep them with the kit.
- **AI chat** (under More, in a tab of its own): plain chat with the AI. You can attach a photo (a broken part, a
  label). It doesn't search the library, so check anything important there, and never eat a wild plant or mushroom
  because an AI said it was safe.
- **Models**: pick from the list on the Ask page.
  - `Inkling-2-Mini` (default): fast, good quality, reads photos.
  - `Qwen3.8-27B` and `Gemma-4-26B-A4B`: second and third opinions from other labs. Worth asking twice on anything
    important.
  - `Gemma-4-12B`: mid-size. On a laptop with 16 to 24 GB of memory the kit starts with it, because the bigger models
    don't fit.
  - `Gemma-4-E4B`: small. Use it to **save battery**. On an 8 GB laptop the kit starts with it.
- The first answer after switching models takes up to a minute while it loads. After that it's quick.
- **Share with family** (under More): click **Turn on sharing**, then text the message it gives you: its link opens the
  kit on a phone or laptop on the same Wi-Fi, code included. Or they open the address it shows and type the access
  code, or scan the QR code. No internet needed, only a Wi-Fi network: your router on a battery backup, a small
  battery-powered travel router, or a phone's hotspot (an iPhone's may not turn on without cell service). Nobody
  without the code gets in. Sharing stays on, every time the kit starts, until you click **Turn off sharing**; **New
  code** signs every device out. Only the computer the kit runs on can do either. In the app folder, `./kit share on`
  and `./kit share off` do the same (`.\kit.cmd share on` on Windows), and `bash "Open Tinfoil Kit.command" --share`
  in the `TinfoilKit` folder shares for one run. If macOS asks whether to accept incoming connections, click
  **Allow**. If Windows asks about tinfoilkit-windows-x64.exe, click **Allow access**.

The AI can be wrong. Treat it like a well-read friend, not a doctor: check the sources, and get trained help whenever
you can.

## Maps

- **Search**: type an address or place name in the box at the top of the Map tab and pick a match. Click its pin for
  **Directions here** or **Set as home**. The box also takes coordinates, as GPS units and paper maps write them:
  `40.7128, -74.0060`, `40.7128 N 74.0060 W` or `40°42'46"N 74°0'22"W`.
- **Coordinates and pins**: click anywhere on the map to see its coordinates (with **Copy**), get directions there, or
  **Pin this place** with a name and a note, like where the family meets or a spring. Pins show on the map and under
  **Pins**, and search, directions and Ask find them by name ("directions to the meeting place"). They're saved in the
  kit, like home (`data/places.json`), so a phone using the shared kit sees them too. If the Map or Notes says
  they're saved in this browser, the kit couldn't start the part that keeps them: run SETUP once while online, which
  gets what it needs, and they move into the kit the next time it starts.
- **Directions**: fill in From (leave it blank for home) and To, pick Drive or Walk, press Go. Click a step to zoom to
  it.
- **Nearest**: the buttons (Hospital, Pharmacy, Gas station...) list the closest ones to home, or to the From address.
- **Set home** first: the laptop has no GPS, so "home" is where nearest-searches and directions start. Use **Set as
  home** on a search result, or move the map and click **Set home to the map center**.
- **Ask in plain words** on the Ask page: "How do I get to the nearest hospital?", "Directions from home to 350 Fifth
  Avenue, New York", "Where is the closest gas station?". The AI looks it up and the route appears on the Map tab. This
  works even when the AI is off, for simply worded questions.

Coverage: street-level map, addresses and directions for where you live (the US state, country or part of a big country
you told SETUP) and any places nearby you added, plus a low-detail world map. Address search covers your whole country,
or, where nobody publishes it for the country alone (much of Europe), the whole continent. To change it, run SETUP again
and type another place, or run `./kit region PLACE` (several with commas, where you live first, like
`./kit region "New York, New Jersey"`) and then `./kit sync`.

**For actually driving, use your phone.** Download offline maps on it now: Organic Maps (free, fully offline, spoken
directions) or offline areas in Google Maps or Apple Maps. A phone has GPS; this laptop doesn't. The kit's map is the
backup, and it's handy for planning on a big screen and for the AI questions.

## Update it (whenever you like, while you have internet)

There's no schedule. Double-click `SETUP.command` in the kit's app folder (`SETUP-Windows.bat` on Windows; on Linux,
`bash SETUP.command`). It gets the newest version of the kit itself, with any models and books added since, then the
newest editions of everything, checks every file, and starts it all once offline to make sure it works. Or open a
terminal in the app folder (Mac: drag the `app` folder onto the Terminal icon; Windows: right-click the folder, **Open
in Terminal**) and run these (on Windows, `.\kit.cmd` in place of `./kit`):

```
./kit update    # gets the newest signed version of the kit itself, keeping your kit.json changes
./kit sync      # shows what's new, downloads it, checks every file, then removes old versions
./kit test      # starts everything briefly and confirms it works
```

Either way it is safe to stop (Ctrl-C or close the window) and re-run; it picks up where it left off, and the kit keeps
working with what it has meanwhile. A normal update gets the newest version of the kit itself and the programs it was
released with (the AI engine and the rest), new library editions, any re-released models and fresh map data (rebuilding
the directions network takes 10 to 40 minutes). Wikipedia is the exception: at up to 127 GB, it keeps the edition it has
until that one is a year old. Then pull the plug on Wi-Fi and open the kit once for real.

A newer download of the kit finds this kit and updates it, so nothing it has downloads again. SETUP shows what's new
before anything downloads: say no, and the kit keeps working with what it has. You can also delete the kit's `app`
folder any time and put a new download's `app` folder in its place: what the kit downloaded (`downloads`) and your
settings, notes and pins (`data`) stay as they are.

Other commands:

```
./kit plan            # preview what sync would do (changes nothing)
./kit status          # what's in the kit and when it was last updated
./kit verify          # re-check every file for corruption (add --fix to remove bad ones, then sync)
./kit remove NAME     # delete something the kit downloaded, for its space, and switch it off
./kit search medical  # find more books to add
```

## Changing what's in the kit

Everything the kit keeps is listed in **`data/kit.json`** (open it in any text editor):

- Turn something off: set `"enabled": false` on its line. Turn every model off and the kit runs without the AI: the
  library and the map work as usual, and Search shows the best passages from the books. What it downloaded stays until
  `./kit remove NAME` deletes it.
- Add a book: `./kit search <words>`, then paste the line it prints into the `"library"` list.
- Swap a model: change its `"repo"` and `"files"` (Hugging Face repo and file name patterns). Each pattern must match
  exactly one file. A new model generation every few months is normal; check which GGUF models fit a 32 GB laptop (about
  20 GB or less) before swapping.

Then run `./kit plan` to preview and `./kit sync` to apply. Updates of the kit itself keep these changes, and add what's
new in the kit's own list (`app/kit.json`).

## First-time setup

1. On **tinfoilkit.com**, click **Set up with your AI**, copy the prompt into ChatGPT, Claude or any AI chat, and answer
   its questions. It gives you one command to paste into Terminal on a Mac (press Cmd-Space, type Terminal) or
   PowerShell on Windows (open Start, type PowerShell). The command downloads the kit and starts SETUP, which asks
   whatever the command didn't answer (with `--yes`, nothing).
2. SETUP asks where you live: type your US state or your country (like Texas, Ontario or Germany; a big town works too).
   That sets the maps' area, directions, address search and home, and offers Wikipedia in your language. Then it asks
   for places nearby to put on the map too, like the state next door: type one at a time, and press Return when that's
   all. Then it asks how much of Wikipedia: all of it (127 GB in English, with pictures), or just the best 50,000
   articles (7 GB with pictures, 3 GB as text).
3. SETUP says which AI model this computer can run, and asks before downloading any that are too big for it. Then it
   asks where the kit should go, says how much room each place has, and moves the kit there for you. If all of it won't
   fit, or would leave less than about 10% of the computer's disk (5% of a drive) free, it says so and offers just the
   essentials: the AI, the medical, preparedness and repair books, the map, and Wikipedia's best articles as text.
   - **An external drive** (recommended): it goes with you. Plug it into any Mac, Windows PC or Linux PC, and keep it
     somewhere safe. It goes in a `TinfoilKit` folder on the drive. The drive should be **exFAT**, which all three can
     use. Many new drives come as exFAT. FAT32 won't work (files over 4 GB don't fit), and SETUP shows how to erase the
     drive as exFAT. APFS works on Macs only, and NTFS on Windows and Linux only. Always eject the drive before
     unplugging, especially with exFAT. If macOS asks whether Terminal may access files on a removable volume, say yes.
   - **This computer**: nothing to plug in. It goes in the `TinfoilKit` folder in your home folder and leaves 50 GB free
     for the computer. On a Mac what it downloads stays out of Time Machine backups; your settings don't.
4. Before it downloads, it times your connection for a few seconds and says how long the kit to try and all of it take.
   It gets a small kit to try first (about 10 GB: a small AI, a few medical and how-to books, and your area's map),
   starts each part offline to check it answers, and offers to open it. Turn off Wi-Fi and try it: from then on, the kit
   works. It also says how big the rest is and how long it takes on your connection.
5. When you're ready for the rest, start SETUP again: run the command its last message gave, or double-click it in the
   kit's app folder. Unless you picked already, it asks what you want in the kit, the same choices as the kit builder on
   tinfoilkit.com. Then it shows what that comes to and how long it takes, gets it (about 200 to 300 GB for the
   recommended kit; from about 20 GB for just the essentials to about 900 GB for everything), showing the time left as
   it goes, and checks again. Then it removes the try-it files you didn't pick. Leave the laptop plugged in; it stays
   awake while this runs, and the kit works the whole time. If you stop it, start SETUP in the kit's app folder again
   and it picks up where it left off. If it ends with "some downloads didn't finish", the kit already works with what it
   has: run SETUP again later for the rest. With just the essentials, a later SETUP offers the rest once there's room.
   `./kit essentials off` asks for it any time.
6. Turn off Wi-Fi and start the kit (see the top of this page).

In a terminal, SETUP takes every answer as an option, and with `--yes` it asks nothing: for example
`bash SETUP.command --region texas --this-computer --yes` (on Windows, `.\SETUP-Windows.bat` with the same options) gets
the kit to try, and `bash ~/TinfoilKit/app/SETUP.command --yes` the rest. `--help` lists them, one for each setting of
the kit builder on tinfoilkit.com, which writes them for you: a preset (`--recommended`, `--essentials` or
`--everything`), where you live, how much of Wikipedia, which AI models and books, a drive or this computer, and sharing
on the home network.

## Removing it

Double-click `UNINSTALL.command` in the kit's app folder (`UNINSTALL-Windows.bat` on Windows; on Linux,
`bash UNINSTALL.command`). It shows what it will delete and how much space that frees, and deletes the kit and
everything it downloaded, your notes and pins too, only after you type `delete`. The files don't go to the Trash. To
keep your notes, copy `data/notes.txt` somewhere else first. On a drive, nothing else on the drive is touched.

## Power

Running a big model uses a lot of battery: expect a couple of hours of active use on a laptop battery. A USB-C power
station plus a folding solar panel keeps it going. Use `Gemma-4-E4B` when power is short. **Search** on the Ask page
and the Library tab don't use the AI, so they use almost nothing. Paper uses none: print the essentials while you can.

## If something doesn't work

- Close the kit's window and start it again.
- Terminal says "Operation not permitted": macOS is keeping it off the drive. Open **System Settings > Privacy &
  Security > Files and Folders**, turn on **Removable Volumes** under Terminal, and start again.
- Logs are in `data/logs`.
- Phones can't open the shared address: they need the same Wi-Fi as the computer (a guest network often keeps devices
  apart). `./kit share` shows the address and the access code again. On Windows, set the Wi-Fi as a private network
  (**Settings > Network & internet**, then the Wi-Fi's properties), and if tinfoilkit-windows-x64.exe was refused, allow
  it in **Windows Security > Firewall & network protection > Allow an app through firewall**, ticking **Private**.
- If a model won't load or is very slow, quit other apps (big models need most of a 32 GB laptop's memory), or use
  `Gemma-4-E4B`. Starting with `bash "Open Tinfoil Kit.command" --no-maps` frees about 5 GB by not starting the map
  servers.
- Map says address search or directions are "not running": they take up to a minute to start. If they never do, see
  `data/logs/geocoder.log` and `data/logs/routing.log`. If `./kit test` fails on address search with a "lock" error in
  `data/logs/test-geocoder.log`, the exFAT format is the cause: reformat the drive as APFS and copy the kit back.
  Advanced, on a Mac: `sudo sysctl iogpu.wired_limit_mb=26624` lets the GPU use up to 26 GB until the next restart.
- The previous version of each program is kept in `downloads/bin/` as a fallback and is used automatically if the newest
  one won't start.

## On another computer

A kit on an exFAT drive starts on any Mac, Windows PC or Linux PC, whichever one set it up: plug it in and start it as
at the top of this page. Without a good graphics card the AI is slow: use `Gemma-4-E4B`. Fedora 45 and later need one
extra package for the AI: run `sudo dnf install openssl3-libs` while you still have internet. If the window says another
library is missing, install that too.

## Make a copy for someone

A copy goes on another drive and starts on its own on any Mac, Windows PC or Linux PC, with no internet: one to give
to family or friends, or a spare. It takes as much of this kit as fits, and nothing downloads, so you can make one in an
outage. Plug in both drives, and in the app folder run `./kit copy` (`.\kit.cmd copy` on Windows). It asks:

- which drive;
- what goes on it: the essentials (the programs and the most important books), the essentials and the map, everything
  that fits, or each part, with the size of each;
- whether to add the AI (without it, Ask finds answers in the books), and whether to bring your notes and map pins.

It erases a drive only if it must, once you type the drive's name: one that isn't exFAT, or is too full, and a kit
already on it is replaced. A Mac erases it for you. On Windows, format it yourself first (in File Explorer, right-click
the drive, Format, exFAT); on Linux, use the Disks app. Then it reads every file back to check the drive, starts the
copy once to be sure it works, and opens a card to print and keep with the drive. If it stops partway, run it again: it
carries on.

## A home server (advanced)

A computer that stays on, like a Linux box, a Mac mini or a Windows PC, can serve the kit to every phone and laptop at
home. This is experimental for now. On Linux or a Mac it needs no screen. Over SSH, in the unzipped download's app
folder (or the kit folder of a `git clone`), run:

```
bash SETUP.command --home-server
```

(on Windows, `.\SETUP-Windows.bat --home-server` in a terminal there) and choose "This computer". It sets the kit up as
usual, then shares it on the home network behind an access code and starts it whenever the computer starts. At the end
it shows the address, the access code and a QR code; `./kit share` shows them again. Without the questions, in the app
folder: `./kit sync -y && ./kit test`, then `./kit share on` and `./kit autostart on` (`.\kit.cmd` on Windows).

- On Linux the kit runs as a systemd user service, from boot. On a Mac it starts when you log in, so turn on automatic
  login. On Windows it starts, minimized, when you sign in: keep the PC signed in (locking it is fine) and plugged in,
  and sign in again after a restart. Keep it on the computer's own disk.
- `./kit share new-code` makes a new code (every phone types it again), `./kit share off` stops sharing, and
  `./kit autostart off` stops the kit starting by itself. UNINSTALL does both.
- Another program already using port 8000: set `share_port` in `data/kit.json` to a free port.
- In an outage the router needs power too, even with no internet: keep it and the server on a battery backup.

## What's where

| Folder / file | What it is |
|---|---|
| `Open Tinfoil Kit.command` | Starts everything (Mac, Linux). It starts `app/Open Tinfoil Kit.command`, which works too |
| `Open Tinfoil Kit for Windows.bat` | The same, for Windows |
| `Read me first.txt` | How to start the kit, and what each folder is for |
| `app/` | The kit itself, as released. A new version replaces it, and it can be deleted any time for a new download's |
| `app/SETUP.command` | Sets the kit up, and updates it whenever you like (needs internet) |
| `app/UNINSTALL.command` | Removes the kit and everything it downloaded |
| `app/SETUP-Windows.bat`, `UNINSTALL-Windows.bat` | The same two, for Windows |
| `app/kit` (`kit.cmd` on Windows), `app/kit.json` | The kit's command line, and the standard list of what it keeps |
| `app/tools/` | The kit's own program (one for each kind of computer) and its web page |
| `app/THIRD-PARTY.md` | Where each model, book, map and program comes from, and its license |
| `downloads/` | Everything the kit downloaded. New versions use it as it is |
| `downloads/library/` | The books (`.zim` files) |
| `downloads/models/` | The AI models (`.gguf` files) |
| `downloads/maps/` | Map tiles, the address database, the road network for directions, and the map display code |
| `downloads/bin/` | The programs: llama.cpp (AI), kiwix-serve (library), and for maps pmtiles, Photon, GraphHopper and Java |
| `downloads/INVENTORY.md` | What's in the kit right now, with versions |
| `data/` | Yours: no new version touches it |
| `data/kit.json` | Your list of what to keep, with your changes |
| `data/notes.txt` | Your notes (Notes, under More) |
| `data/places.json` | The map's home and pins |
| `data/logs/` | What each update and start did |
