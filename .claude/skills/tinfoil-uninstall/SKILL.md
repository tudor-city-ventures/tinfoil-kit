---
name: tinfoil-uninstall
description: Remove a Tinfoil Kit and everything it downloaded. Use when someone wants to delete or uninstall Tinfoil Kit, or get all of its space back.
---

# Remove Tinfoil Kit

This deletes the kit for good: the files don't go to the Trash. Give the person the command only once they've said yes to deleting all of it, models, books, maps and their own settings, notes and pins. To find the kit, see the tinfoil-update skill.

## What it removes

- The kit folder, TinfoilKit: app, downloads and data.
- Starting with the computer, if it was on.
- The Python SETUP got for the kit: on Windows, and on a Mac that had none.
- Nothing else. On a drive, the rest of the drive stays. If the app folder sits in a folder with other things in it, it deletes nothing and says so.

## The command

    bash ~/TinfoilKit/app/UNINSTALL.command --yes
    & "$HOME\TinfoilKit\app\UNINSTALL-Windows.bat" --yes

On a drive: `bash /Volumes/NAME/TinfoilKit/app/UNINSTALL.command --yes`, or `E:\TinfoilKit\app\UNINSTALL-Windows.bat --yes`. `--yes` skips the question. Without it, the uninstaller says what it will delete and how much space that frees, and deletes only after the person types delete. Double-clicking UNINSTALL in the app folder, or Remove in the Mac app, does the same.

## Before they run it

- Close the kit's window first.
- To keep their notes (the Notes tab), copy data/notes.txt somewhere else first: it's plain text. data/places.json holds the map's home and pins, and data/kit.json their picks, for a later kit.
- The Mac app stays in Applications until it's dragged to the Trash.
- To free some space and keep the kit, see the tinfoil-data skill instead.
