---
name: tinfoil-update
description: Update a Tinfoil Kit. Install the newest signed release of the kit's code, then download the newest models, books, maps and programs, check them and remove the old ones. Use when someone wants the newest version, newer data, or asks how to update their kit.
---

# Update Tinfoil Kit

There's no schedule: update whenever the person wants, while online. It's safe to stop at any point and run again: it picks up where it left off, and the old files keep working until the new ones check out. Updates take from minutes to hours, so give the person the command to run in their own terminal.

## Find the kit

The kit is a folder called TinfoilKit with app, downloads and data inside, in the home folder (~/TinfoilKit) or at the top of a drive (/Volumes/NAME/TinfoilKit on a Mac, E:\TinfoilKit on Windows). Commands run in its app folder: `./kit` on a Mac or Linux, `.\kit.cmd` in PowerShell on Windows. `./kit kits` lists the other kits on this computer and on plugged-in drives. A git checkout is its own app folder.

## The command

SETUP does all of it (update, plan, sync, test), and `--yes` asks nothing:

    bash ~/TinfoilKit/app/SETUP.command --yes
    & "$HOME\TinfoilKit\app\SETUP-Windows.bat" --yes

On a drive: `bash /Volumes/NAME/TinfoilKit/app/SETUP.command --yes`, or `E:\TinfoilKit\app\SETUP-Windows.bat --yes`. Double-clicking SETUP does the same, as does Update in the Mac app.

Step by step, in the app folder:

    ./kit update -y   # the newest release of the kit's code, only if it's signed with the kit's release key
    ./kit plan        # what's new or changed, and how much will download
    ./kit sync -y     # download it, check every file, then remove the old versions
    ./kit test        # start everything offline and check that it answers

In a git checkout, `git pull` replaces `./kit update`.

## Reading the results

- `./kit update` exits 0 when the kit is already the newest, and 3 after installing a newer version. 3 is success: carry on with the next command. Anything else failed: read its last lines.
- If it says a release isn't signed with the kit's key, stop. Don't install it another way. Tell the person, and report it at https://github.com/tudor-city-ventures/tinfoil-kit/security.
- `./kit plan` marks each item ok, NEW, UPDATE, later or ERROR. later is a big book keeping the edition it has until its refresh_days pass: Wikipedia keeps its edition for a year.
- `./kit sync` exits 0 when everything finished, 1 when something failed or couldn't be looked up, and 130 after Ctrl-C. On 1, run it again: it resumes and names what's left. The kit works with what it has meanwhile.
- `./kit test` exits 0 when every part starts offline and answers. If not, see the tinfoil-status skill.
- Only what changed downloads. A newer download of the kit (a new ZIP, or a new Mac app) finds this kit and updates it, so nothing downloads twice.

## Choices along the way

- One item now, like a newer Wikipedia: `./kit sync -y --only wikipedia`.
- An update can bring models too big for this computer: `./kit fit` names them, and `./kit fit --skip` switches them off.
- A kit with just the essentials: `./kit space . --json` says when all of it fits. Then `./kit essentials off` before syncing.
- The person never has to take a newer edition: the plan lists what's new before anything downloads, and they can say no.
