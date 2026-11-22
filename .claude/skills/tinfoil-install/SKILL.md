---
name: tinfoil-install
description: Set up Tinfoil Kit (offline AI, library and maps) for someone. Find their external drive and check its format, ask what goes in the kit, then give them the one command that installs it. Use when someone wants to install or set up Tinfoil Kit.
---

# Set up Tinfoil Kit

Don't run the setup yourself, even if you can run commands. Ask the person what they want, then give them one command to paste into their terminal (Terminal on a Mac, PowerShell on Windows). The first run gets a small kit to try, about 10 GB, and opens it. A second command gets the rest. The ids every option takes are in "What goes in" in the kit's instructions for AI agents: https://tinfoilkit.com/llms.txt (site/public/llms.txt in the repo).

## 1. Find the drive

An external drive is the best place: formatted exFAT, it plugs into any Mac, Windows or Linux computer and the kit starts there. If you can run commands, look with these, which only read. Otherwise ask the person.

| System | Commands | What to read |
| --- | --- | --- |
| Mac | `diskutil list external physical`, then `diskutil info /Volumes/NAME` | the partition scheme, File System Personality, free space |
| Windows (PowerShell) | `Get-Disk \| Where-Object BusType -eq USB`, then `Get-Volume` | PartitionStyle, FileSystemType, SizeRemaining |
| Linux | `lsblk -o NAME,SIZE,FSTYPE,MOUNTPOINT,TRAN` | TRAN usb, FSTYPE, then `df -h` for free space |

If the kit's code is already on the computer (a download, or a git checkout), `./kit drives --json` in its app folder (`.\kit.cmd drives --json` on Windows) lists every drive with path, format, free_bytes, problem, has_kit and space: "fits", "tight" or "no", for all of it and for the essentials.

- Room: about 300 GB for all of it, or 35 to 55 GB for the essentials, plus 25 GB to spare.
- Format: exFAT works on all three, best on a GUID partition map (MBR works too). APFS and Mac OS Extended work only on a Mac, a Mac can't write to NTFS, and FAT32 can't hold files over 4 GB.
- Wrong format: the drive needs erasing as exFAT, which deletes everything on it. Make sure it's the right drive, and get the person's explicit yes. Mac: Disk Utility > View > Show All Devices, select the drive itself (the top line), Erase, ExFAT, GUID Partition Map. Windows: File Explorer, right-click the drive, Format, exFAT, Start.
- No drive: ask whether they have one to plug in, or want to get one, before suggesting this computer. On this computer the kit goes in ~/TinfoilKit and needs its size plus 50 GB free.

## 2. Ask what goes in it

One or two questions at a time. For each, say what it's for and roughly how big it is, and recommend what suits their computer.

1. Their computer: a Mac with Apple Silicon, or a Windows or Linux PC on x64 (Intel Macs and ARM PCs can't run it), its memory and free space.
2. Where it lives: the drive, this computer, or a home server (see the tinfoil-home-server skill).
3. Where they live, for the map (`--region`), and any places nearby they want on it too, Wikipedia's languages (`--wikipedia`), and how much of Wikipedia (`--wikipedia-size`): all of it (127 GB in English) or just the best 50,000 articles (7 GB, or 2.7 GB as text).
4. The AI: the one their computer runs (the default), none (`--no-ai`), or exact models (`--models`).
5. The library, group by group. The huge collections are off unless added (`--add`).
6. All of it, or just the essentials (`--essentials`) when space is short.
7. Sharing with the phones and laptops at home behind an access code (`--share`), or a home server (`--home-server`).

If they pasted options from the website's kit builder (like `--region bayern --wikipedia de --skip mdwiki_en_all_maxi`), use them as they are and ask only about the rest.

## 3. Give them the command

Mac or Linux:

    mkdir -p ~/Downloads && cd ~/Downloads && curl -fsSL https://github.com/tudor-city-ventures/tinfoil-kit/releases/latest/download/TinfoilKit.tar.gz | tar -xz && bash TinfoilKit/app/SETUP.command --region texas --drive /Volumes/Kit --yes

Windows, in PowerShell:

    cd ~\Downloads; curl.exe -fsSL -o TinfoilKit.zip https://github.com/tudor-city-ventures/tinfoil-kit/releases/latest/download/TinfoilKit-Windows.zip; tar -xf TinfoilKit.zip; Remove-Item TinfoilKit.zip; .\TinfoilKit\app\SETUP-Windows.bat --region texas --drive E: --yes

If the kit's code is already there, it's `bash TinfoilKit/app/SETUP.command OPTIONS --yes` (`.\TinfoilKit\app\SETUP-Windows.bat OPTIONS --yes`).

| Option | What it does |
| --- | --- |
| `--region PLACES` | Where they live: "Texas", "Ontario", "Germany: Bayern", or an id from `./kit region --find WORDS`. Quote names with spaces. Places nearby for the map go after it as ids, with commas: `us/new-york,us/new-jersey` |
| `--wikipedia CODES` | Wikipedia's languages: `de`, or `de,en` |
| `--wikipedia-size SIZE` | How much of Wikipedia: `all` (the default), `all-text`, `top` (the best 50,000 articles), `top-text` or `top-intros` (their opening paragraphs). With `--essentials`, add `--add wikipedia` for anything bigger than `top-text` |
| `--drive PATH` | The drive: /Volumes/NAME on a Mac, E: on Windows, /media/USER/NAME on Linux. The kit goes in a TinfoilKit folder at its top |
| `--this-computer` | The kit goes in the home folder instead |
| `--no-ai`, `--models IDS` | No AI, or exactly these models |
| `--skip IDS`, `--add IDS` | Leave out or add items, comma-separated: ids, `maps`, or a whole part (`models`, `library`, `extras`) |
| `--essentials`, `--all` | Go straight on to the rest after the try-it kit: just the essentials, or all of it even if space gets tight |
| `--share` | Share it at home, behind an access code, whenever it's open |
| `--home-server` | Share it and start it with the computer. Goes straight on to the rest |
| `--yes` | Ask nothing. Without it, SETUP asks in the terminal whatever the options didn't answer |

Then tell them:

- How to open the terminal: on a Mac, Cmd-Space, type Terminal, press Return. On Windows, open Start, type PowerShell, press Enter. Paste the command and press Return.
- Keep the laptop plugged in and the terminal open.
- What success looks like: "The try-it kit works", how big the rest is and how long it takes on their connection, and "When you're ready for it:" with the command for the rest. Then the kit opens (on Linux, SETUP prints the command that opens it).
- If it stops, or the laptop sleeps, run the same command again: it picks up where it left off.

## 4. The rest

When they've tried it and are ready, give them the command SETUP printed: `bash "/Volumes/Kit/TinfoilKit/app/SETUP.command" --yes`, or on Windows `& "E:\TinfoilKit\app\SETUP-Windows.bat" --yes` (in ~/TinfoilKit on this computer). It gets everything they picked, a few hours for all of it, checks every file, and deletes the try-it files their picks left out. Add `--all` to get all of it even if that leaves less free space than SETUP likes, or `--essentials` for just those.

## When it fails

With `--yes`, SETUP never asks: it stops and says why. Fix that and run the same command again.

- Two places share the name: it lists their ids. Use one with `--region`.
- A wrong id in `--models`, `--skip` or `--add`: it stops before changing anything and lists the right ones.
- No room: use `--essentials`, leave parts out with `--skip`, or pick a bigger drive.
- A drive it can't use (FAT32, or NTFS on a Mac): erase it as exFAT, as in step 1.
- Mac, "Operation not permitted" with a drive: System Settings > Privacy & Security > Files and Folders > Terminal, turn on Removable Volumes, and run it again.
- Windows, "Windows protected your PC": More info, then Run anyway.
- Some downloads didn't finish: run it again. The kit already works with what it has.
