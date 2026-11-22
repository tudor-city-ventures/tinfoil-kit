---
name: tinfoil-data
description: Change what a Tinfoil Kit downloads. Add or remove AI models, books and maps, switch to just the essentials, change the map's region or Wikipedia's languages and size, find more Kiwix books, see what fits, and download the changes. Use when someone wants more or less in their kit, or asks how much space something takes.
---

# Change what's in the kit

What the kit gets is listed in data/kit.json, the person's copy. Never edit app/kit.json: a new version replaces it. These commands change data/kit.json for you. Run them in the kit's app folder (`./kit` on a Mac or Linux, `.\kit.cmd` in PowerShell on Windows), then download with `./kit sync -y`. To find the kit, see the tinfoil-update skill.

## See what's there and what fits

    ./kit pick              # what's on, the size of all of it and of the essentials, and how long it takes to download
    ./kit estimate          # GB the kit needs as it's set now, with no internet (--essentials: just those)
    ./kit estimate --rest   # GB still to download, then how long that takes on this connection, tab-separated
    ./kit space . --json    # whether all of it, or just the essentials, fit where the kit is
    ./kit plan --json       # every item with its size and version, switched-off ones too (needs internet)
    ./kit fit --json        # which AI this computer runs, and the models too big for it

The ids are in "What goes in" at https://tinfoilkit.com/llms.txt, and in data/kit.json.

## Change it

| To | Run |
| --- | --- |
| Have no AI | `./kit pick --no-ai` |
| Have exactly these models | `./kit pick --models Gemma-4-12B,Gemma-4-E4B` |
| Leave things out | `./kit pick --skip khanacademy_en_all,maps` |
| Delete something, for its space | `./kit remove khanacademy_en_all` (asks first; `--yes` doesn't) |
| Add things, like the huge collections | `./kit pick --add gutenberg_en_all` |
| Keep only the models this computer runs | `./kit fit --skip` (`./kit fit --restore` puts them back) |
| Get just the essentials, or everything again | `./kit essentials on`, `./kit essentials off` |
| Go from the try-it kit to everything picked | `./kit starter off` |
| Change where they live, and Wikipedia's languages | `./kit region "Germany: Bayern" --wikipedia de,en` |
| Find a place's id | `./kit region --find georgia` |
| See the Wikipedia languages offered for a place | `./kit region bayern --languages` |
| Take less of Wikipedia, or more: all, all-text, top (the best 50,000 articles), top-text or top-intros | `./kit region --wikipedia-size top-text` |
| See the sizes Wikipedia comes in, in the kit's languages, with GB | `./kit region --sizes` |
| Add a Kiwix book that isn't listed | `./kit search WORDS`, then paste the line it prints into "library" in data/kit.json |

- `--skip` and `--add` take ids, `maps`, or a whole part (`models`, `library`, `extras`). A book's name up to its first underscore catches every book that starts with it (`wikipedia` is Wikipedia in any language), and a site's name catches all its books (`stackexchange`, `libretexts`). A wrong name changes nothing and lists the right ones.
- `--skip` and `--add` change only what they name. `--models` and `--no-ai` replace the whole set of models.
- Then `./kit sync -y`. Big downloads take hours, so give the person that command to run. `./kit sync -y --only ID` gets just one item.

## What happens to files already downloaded

Switching an item off stops it downloading and updating. What it already downloaded stays, and sync never deletes it, with two exceptions: the try-it kit's extras once the full kit is in, and Wikipedia in a language or size `./kit region` switched away from, once the new one is in (also the smaller Wikipedia the try-it kit and the essentials get until then). `./kit plan` and `./kit status` list what's switched off but still in the kit, with its size.

To get the space back, `./kit remove NAME` deletes what an item downloaded, its unfinished downloads too, and switches it off. It takes the same names as `--skip`. It lists what it deletes and asks first; without a keyboard it needs `--yes`, so get the person's OK before adding it. Close the kit first on Windows, which won't delete a file the kit has open. `./kit pick --add NAME`, then `./kit sync -y`, gets it back. Never delete the kit's files by hand, or anything in data/.
