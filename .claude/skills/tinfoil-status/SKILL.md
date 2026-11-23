---
name: tinfoil-status
description: Check a Tinfoil Kit and fix it. See what's installed, how big it is and when it last updated, check every file and that every part starts offline, find what's wrong in its logs, and open the kit. Use when someone asks what's in their kit, whether it works, why something doesn't, or how to start it.
---

# Check the kit, fix it, open it

The commands here only read, except `verify --fix`, so you can run them yourself if you can run commands. Run them in the kit's app folder: `./kit` on a Mac or Linux, `.\kit.cmd` in PowerShell on Windows. To find the kit, see the tinfoil-update skill.

## What's in it

    ./kit status   # every item with its version, size and date; unfinished downloads; free space; the last complete sync
    ./kit kits     # the other kits on this computer and on plugged-in drives: folder, where, GB, last sync
    ./kit fit      # which AI this computer runs (--json for you), and the switched-on models too big for it
    ./kit pick     # what's switched on, and the size of all of it and of the essentials

downloads/INVENTORY.md lists every item with its version and size.

## Does it work

    ./kit verify --quick   # every file is there and the right size: fast
    ./kit verify           # every file against its SHA-256: reads the whole kit, so it takes a while
    ./kit test             # starts each part offline for a moment and checks that it answers

- `./kit verify` exits 0 with "All N files OK", or 1 with a list of problems. `./kit verify --fix` deletes the bad files; the next `./kit sync -y`, while online, downloads fresh copies.
- `./kit test` checks the AI with the smallest model; `--model NAME` picks another (a folder name in downloads/models). It exits 0 when every part answers.
- `./kit status` says "Never fully synced" until a sync finishes with nothing left: `./kit sync -y` again resumes it.

## What went wrong

The logs are in data/logs: sync-*.log for downloads, llama-server.log for the AI, kiwix-serve.log for the library, tiles.log, geocoder.log and routing.log for the map, data.log for notes and pins, share.log for sharing, and test-geocoder.log and test-routing.log from `./kit test`.

- "Apple could not verify..." on a double-click: System Settings > Privacy & Security > Open Anyway, once. `bash "Open Tinfoil Kit.command"` in Terminal always works.
- "Windows protected your PC": More info, then Run anyway, once.
- "Operation not permitted" in Terminal on a Mac: System Settings > Privacy & Security > Files and Folders > Terminal, turn on Removable Volumes.
- Not enough space: sync stops short of keeping 50 GB free on the computer's own disk, or 25 GB on a drive. See the tinfoil-data skill.
- A program's publisher no longer has the build the kit names: `./kit update` first. If it says a program's file changed after the kit pinned it, don't work around it: report it at https://github.com/tudor-city-ventures/tinfoil-kit/security.
- A model won't load or is very slow: quit other apps, pick Gemma 4 E4B on the Ask page, or open the kit with `--no-maps` to free about 5 GB of memory. Search, beside Ask the AI, finds the best passages without the AI at all.
- Address search or directions "not running": they take up to a minute to start. If they never do, read geocoder.log and routing.log. A "lock" error in test-geocoder.log means the drive's exFAT format is the cause.
- The Notes or Map tab says notes or pins are saved in this browser: the kit couldn't start the server that keeps them. Read data.log. They move into the kit the next time it starts.
- Linux, Fedora 45 or later: the AI needs `sudo dnf install openssl3-libs`, installed while there's internet.
- The previous version of each program stays in downloads/bin and starts by itself if the newest won't.

## Open it

- Mac: double-click Open Tinfoil Kit.command in the app folder, or run `bash "Open Tinfoil Kit.command"`.
- Windows: double-click Open Tinfoil Kit for Windows.bat in the app folder, or run `& ".\Open Tinfoil Kit for Windows.bat"`.
- Linux: `bash "Open Tinfoil Kit.command"`.

It opens http://127.0.0.1:8888 in the browser, and needs no internet. Keep its window open: closing it stops everything. In a terminal in the app folder, `./kit open` (`.\kit.cmd open` on Windows) does the same. Each of them takes `--share` (phones and laptops at home, with the access code, this time only), `--no-maps` (frees about 5 GB of memory), `--model=NAME` (the model to load first) and `--no-browser`.
