---
name: tinfoil-copy
description: Copy a Tinfoil Kit onto another drive, as much as fits, so the copy runs on its own on any computer, to give to family and friends or keep as a spare. Pick a preset or each part, add the AI, bring the notes and pins, and print a card for it. Use when someone wants a copy of their kit on another drive, a smaller kit from a big one, or a spare.
---

# Copy the kit to another drive

A copy is a kit of its own: plug its drive into a Mac, Windows PC or Linux PC and double-click Open Tinfoil Kit there, with no internet. It takes as much of this kit as fits on the other drive: the programs for all three kinds of computer always, then a preset, or each part picked. Nothing downloads, so it works in an outage. To find the kit, see the tinfoil-update skill.

The kit page has the same under More: Make a copy opens a page of its own, on the computer the kit runs on (not through Share with family), with the drives, the presets and each part with their sizes, then the copy as it goes, with Stop. A copy started with `./kit copy` shows there too. For a person who'd rather click, point them there.

## The command

In the kit's app folder, with the other drive plugged in (`.\kit.cmd` for `./kit` in PowerShell on Windows):

    ./kit copy                                  # at a keyboard: asks which drive, what goes on it, the AI and the notes
    ./kit copy --json                           # what this kit has, each part's size, and the drives a copy can go on
    ./kit copy "LITTLE ONE" --maps --json       # what that copy would be, and whether it erases the drive, without copying
    ./kit copy "LITTLE ONE" --maps --yes        # to the drive LITTLE ONE: the essentials, then the map, as much as fits

What goes on it, the most important first, until the drive is full:

- `--essentials`: the programs and the most important books: medicine, preparedness, water, food and repair.
- `--maps` (the default): the essentials, then the map with directions, then its address search.
- `--everything`: the most important first, until the drive is full.
- `--ai` adds the smallest AI model. It's off unless asked for: without it, Ask finds answers in the books. `--models IDS` adds those models instead.
- `--only IDS`: just those, and the programs. `--add IDS` adds these, which must fit; `--skip IDS` leaves these out. Names as `./kit copy --json` lists them: an AI model, a book (or a word in its name, like wikipedia or water), map, addresses, or a whole part (models, books, extras).
- `--notes` brings the person's notes, home and map pins. Without it the copy starts clean, and a copy never overwrites the notes on a kit it replaces.

Ask the person which drive and what goes on it, check it with `--json`, then give them the command, or run it with `--yes`.

## Erasing

It erases nothing unless it must, and only once the drive's name is typed (`--erase NAME` types it ahead):

- A drive with a kit on it: the copy replaces that kit. What's the same stays, and so do its notes and pins.
- A drive that isn't exFAT (FAT32 can't hold files over 4 GB, APFS and Mac OS Extended are for Macs only, and Macs can't save to NTFS), or one too full for what goes on it: it's erased first, as exFAT, which all three use. Everything on it goes. A drive with room keeps its other files.
- On a Mac the kit erases the drive itself (diskutil), but only one that's plugged in and holds just that one volume. Windows and Linux need an administrator to erase a drive, so the kit says how: in File Explorer, right-click the drive, Format, exFAT; on Linux, the Disks app. Then run it again.
- Never pass `--erase` without the person's go-ahead in their own words, for that drive by name.

## What it does

1. Copies into TinfoilKit.partial on the drive. A copy that stopped (Ctrl-C, or the drive was unplugged) carries on where it left off, run again with the same drive.
2. Reads every file back from the drive and checks it against what went in, so a failing drive, or a fake one that's smaller than it says, shows up now. A file that reads back wrong is copied again; if it's still wrong, it stops and says to try another drive.
3. Names the folder TinfoilKit and starts the copy once from the drive (its own `./kit test`, on ports of its own, so a kit that's open keeps running).
4. Writes a card to print and keep with the drive: how to start it on each computer and what's on it. It's data/.kit/card.html in the copy, and in this kit's data/.kit too; at a keyboard it opens in the browser.

The copy's kit.json switches on just what it has, with sharing off (it's for someone else's home) and its default AI one it has, so SETUP there, online, keeps that up to date.

## When it fails

- `There's no drive NAME plugged in that a copy can go on`: `./kit copy` lists them. The drive this kit is on can't take a copy of it.
- `Pick less`: what was asked for doesn't fit, even with the drive erased: a smaller preset, or `--skip`.
- `This kit's own copy of BOOK is damaged`: run `./kit verify --fix`, then SETUP while online to get it again, or leave it out with `--skip`.
- `This kit is busy`: a sync or another copy is running on it. One copy at a time.
- `didn't start when tested`: the copy's logs are in TinfoilKit/data/logs on that drive; see the tinfoil-status skill.
- What each copy did is in data/logs/copy.log.
