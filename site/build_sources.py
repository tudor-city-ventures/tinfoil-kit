"""Build site/sources.json (the kit builder's data), and copy kit.json and tools/regions.json (the places it offers
for "Where do you live?") into site/.

usage: python3 site/build_sources.py [plan.json]
plan.json (optional) is the output of `./kit plan --json`: live sizes for every item. Without it,
sizes measured by the last run are kept; anything never measured comes from the "~N GB" in each kit.json note.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GB = 1e9

# What it is and why you'd want it. A source missing here falls back to its kit.json note.
COPY = {
    "Inkling-2-Mini": ("Inkling 2 Mini", "The default AI. Fast, reads photos, built for 32 GB of memory."),
    "Qwen3.8-27B": ("Qwen 3.8 27B", "A second opinion from a different lab. Slower, but strong."),
    "Gemma-4-26B-A4B": ("Gemma 4 26B", "A third opinion from Google. Quick and reads photos."),
    "Gemma-4-12B": ("Gemma 4 12B", "Mid-size, from Google. The AI for 16 to 24 GB laptops. Reads photos."),
    "Gemma-4-E4B": ("Gemma 4 E4B", "Small and light. The AI for 8 GB laptops, or to save battery."),
    "maps": ("Offline maps", "Street maps, address search and driving or walking directions for your region."),
    "mdwiki_en_all_maxi": ("WikiMed", "A medical encyclopedia: conditions, drugs, procedures."),
    "zimgit-medicine_en": ("Field medicine books", "First aid and medicine for when help is far away."),
    "irp.fas.org_en_military-medicine": ("Military medicine", "Trauma care manuals from the US military."),
    "medlineplus.gov_en_all": (
        "MedlinePlus",
        "Plain-language guides to illnesses, tests and medicines, from the US National Library of Medicine.",
    ),
    "wwwnc.cdc.gov_en_all": ("CDC Travelers' Health", "The CDC's guide to diseases, vaccines and safe food and water."),
    "zimgit-post-disaster_en": ("Post-disaster guides", "Shelter, sanitation and recovery after a disaster."),
    "zimgit-water_en": ("Water treatment", "How to find, filter and disinfect drinking water."),
    "zimgit-food-preparation_en": ("Food preparation", "Storing, preserving and cooking food without power."),
    "zimgit-knots_en": ("Knots", "Illustrated knots for rope, tarps and rescue."),
    "ready.gov_en_all": ("Ready.gov", "FEMA's guides for every kind of emergency."),
    "urban-prepper_en_all": ("Urban Prepper", "Getting through an emergency in a city."),
    "lrnselfreliance_en_all": (
        "Learning Self-Reliance",
        "Videos on homesteading, beekeeping and getting ready for emergencies.",
    ),
    "ifixit_en_all": ("iFixit", "Step-by-step repair guides for phones, appliances, cars and tools."),
    "appropedia_en_all_maxi": ("Appropedia", "Off-grid and low-tech solutions: solar, water, building."),
    "cd3wdproject.org_en_all": (
        "CD3WD",
        "Over 900 practical manuals on farming, water, health and building, from aid groups.",
    ),
    "energypedia_en_all_nopic": ("Energypedia", "Solar panels, batteries and small power systems."),
    "armypubs_en_all": ("US Army publications", "Field manuals on survival, first aid, navigation and more."),
    "wikipedia_en_all_maxi": (
        "Wikipedia, with images",
        "All of English Wikipedia. The reference for nearly any question.",
    ),
    "wiktionary_en_all_nopic": ("Wiktionary", "A full dictionary and thesaurus."),
    "wikibooks_en_all_maxi": ("Wikibooks", "Open textbooks and how-tos."),
    "wikivoyage_en_all_maxi": ("Wikivoyage", "Travel guides for places you might need to go."),
    "survivorlibrary.com_en_all": ("Survivor Library", "Historical how-to books on farming, tools and trades."),
    "khanacademy_en_all": ("Khan Academy", "Video lessons for school-age kids."),
    "gutenberg_en_all": ("All of Project Gutenberg", "Every English public-domain book."),
    "wikiversity_en_all_maxi": ("Wikiversity", "Free courses and study guides on hundreds of subjects."),
    "libretexts.org_en_med": ("LibreTexts Medicine", "College textbooks on anatomy, nursing, pharmacology and more."),
    "libretexts.org_en_bio": ("LibreTexts Biology", "College biology textbooks, from cells to ecosystems."),
    "libretexts.org_en_chem": ("LibreTexts Chemistry", "College chemistry textbooks, general to organic."),
    "libretexts.org_en_eng": ("LibreTexts Engineering", "Engineering textbooks: circuits, materials, mechanics."),
    "libretexts.org_en_phys": ("LibreTexts Physics", "College physics textbooks."),
    "libretexts.org_en_geo": ("LibreTexts Earth Science", "Geology, weather and climate textbooks."),
    "libretexts.org_en_math": ("LibreTexts Math", "Math textbooks from arithmetic to calculus and statistics."),
    "diy.stackexchange.com_en_all": ("Home improvement Q&A", "Plumbing, wiring, heating and repairs around the house."),
    "gardening.stackexchange.com_en_all": (
        "Gardening Q&A",
        "Growing food, plant problems and soil, answered by gardeners.",
    ),
    "cooking.stackexchange.com_en_all": (
        "Cooking Q&A",
        "Food safety, substitutions and techniques, answered by cooks.",
    ),
    "outdoors.stackexchange.com_en_all": ("Outdoors Q&A", "Camping, hiking, navigation and wilderness safety."),
    "electronics.stackexchange.com_en_all": ("Electronics Q&A", "Circuits, batteries, solar and fixing electronics."),
    "ham.stackexchange.com_en_all": ("Amateur radio Q&A", "Ham radio licenses, antennas and emergency communication."),
    "mechanics.stackexchange.com_en_all": ("Car repair Q&A", "Diagnosing and fixing cars, answered by mechanics."),
    "bicycles.stackexchange.com_en_all": (
        "Bicycle repair Q&A",
        "Keeping a bike running when it's your only way around.",
    ),
    "sustainability.stackexchange.com_en_all": (
        "Sustainable living Q&A",
        "Saving energy and water, composting, living on less.",
    ),
    "medicalsciences.stackexchange.com_en_all": ("Medical sciences Q&A", "How the body, diseases and medicines work."),
}

# Where each item comes from, which the builder links so people can see what it is. Models link their Hugging Face
# repo, LibreTexts its library, and a name that starts with a site's address that site; the rest are here. Kiwix put
# the field medicine, post-disaster, water, food and knots collections together itself, so they have no page to link,
# and Urban Prepper and Learning Self-Reliance have none we could confirm.
SOURCES = {
    "maps": "https://www.openstreetmap.org/",
    "mdwiki_en_all_maxi": "https://mdwiki.org/",
    "irp.fas.org_en_military-medicine": "https://irp.fas.org/doddir/milmed",
    "wwwnc.cdc.gov_en_all": "https://wwwnc.cdc.gov/travel",
    "ready.gov_en_all": "https://www.ready.gov/",
    "ifixit_en_all": "https://www.ifixit.com/",
    "appropedia_en_all_maxi": "https://www.appropedia.org/",
    "cd3wdproject.org_en_all": "http://www.cd3wdproject.org/",
    "energypedia_en_all_nopic": "https://energypedia.info/",
    "armypubs_en_all": "https://armypubs.army.mil/",
    "wikipedia_en_all_maxi": "https://en.wikipedia.org/",
    "wiktionary_en_all_nopic": "https://en.wiktionary.org/",
    "wikibooks_en_all_maxi": "https://en.wikibooks.org/",
    "wikivoyage_en_all_maxi": "https://en.wikivoyage.org/",
    "wikiversity_en_all_maxi": "https://en.wikiversity.org/",
    "survivorlibrary.com_en_all": "https://www.survivorlibrary.com/",
    "khanacademy_en_all": "https://www.khanacademy.org/",
    "gutenberg_en_all": "https://www.gutenberg.org/",
}

GROUPS = [
    ("Medical", r"med|mdwiki|cdc\."),
    ("Preparedness", r"ready|prepper|reliance|post-disaster|water|food|knots|army|outdoors"),
    (
        "Repair and skills",
        r"ifixit|appropedia|cd3wd|energypedia|diy|gardening|cooking|electronics|ham\.|mechanics|bicycles|sustainab",
    ),
    ("Books and courses", r"gutenberg|survivor|khan|libretexts|wikiversity|wikibooks"),
    ("Reference", r"."),
]


def size_from_note(note):
    m = re.search(r"~\s*([\d.]+)\s*GB", note or "")
    if m:
        return float(m.group(1)) * GB
    if "small" in (note or ""):
        return 0.1 * GB
    return None


def load_plan(path):
    """`./kit plan --json` keys are section/id; the builder uses bare ids, with every map part summed."""
    live, maps = {}, 0
    for key, v in json.loads(path.read_text()).items():
        section, ident = key.split("/", 1)
        if not v.get("bytes") or v.get("error"):
            continue
        if section == "maps":
            maps += v["bytes"]
        elif section in ("models", "library"):
            live[ident] = v["bytes"]
    if maps:
        live["maps"] = maps
    return live


def previous_live():
    """Keep the live sizes the last plan run measured, so editing kit.json doesn't drop them."""
    try:
        old = json.loads((ROOT / "site" / "sources.json").read_text())["sources"]
    except (OSError, ValueError, KeyError):
        return {}
    return {s["id"]: s["bytes"] for s in old if s.get("bytes") and not s.get("estimated")}


def group_for(zim):
    return next(g for g, rx in GROUPS if re.search(rx, zim))


def source_for(zim):
    if zim in SOURCES:
        return SOURCES[zim]
    lib = re.match(r"libretexts\.org_en_(\w+)$", zim)
    site = re.match(r"([a-z0-9-]+(?:\.[a-z0-9-]+)+)_", zim)
    return f"https://{lib[1]}.libretexts.org/" if lib else f"https://{site[1]}/" if site else None


def main():
    cfg = json.loads((ROOT / "kit.json").read_text())
    live = load_plan(Path(sys.argv[1])) if len(sys.argv) > 1 else previous_live()
    default_model = cfg["settings"]["default_model"]
    out = []

    def add(sid, group, note, enabled, essential, source):
        title, why = COPY.get(sid, (None, None))
        size = live.get(sid) or size_from_note(note)
        out.append(
            {
                "id": sid,
                "group": group,
                "title": title or note.split(":")[0].split("(")[0].strip(),
                "why": why or note,
                "source": source,
                "bytes": int(size) if size else None,
                "estimated": sid not in live,
                "presets": [
                    p
                    for p, on in (
                        ("essentials", essential),
                        ("recommended", enabled),
                        ("no-ai", enabled and group != "AI models"),
                        ("everything", True),
                    )
                    if on
                ],
            }
        )

    for m in cfg["models"]:
        add(
            m["id"],
            "AI models",
            m.get("note", ""),
            m.get("enabled", True),
            m["id"] in (default_model, "Gemma-4-E4B"),
            "https://huggingface.co/" + m["repo"] if m.get("type") == "hf" else None,
        )
    mp = cfg["maps"]
    regions = json.loads((ROOT / "tools" / "regions.json").read_text(encoding="utf-8"))
    place = next(r for r in regions["regions"] if r["id"] == mp["region"])
    add("maps", "Maps", place["name"], mp.get("enabled", True), True, SOURCES["maps"])
    if "maps" not in live:  # the map viewer, fonts and icons, and the place's map, road data and address search
        out[-1]["bytes"] = int(0.1 * GB + sum(place["mb"].values()) * 1e6)
    for z in cfg["library"]:  # Essentials takes Wikipedia too, in a smaller size (builder.jsx's WIKI_PRESET)
        add(
            z["zim"],
            group_for(z["zim"]),
            z.get("note", ""),
            z.get("enabled", True),
            z.get("enabled", True) and (z.get("priority", 9) == 1 or z["zim"].startswith("wikipedia_")),
            source_for(z["zim"]),
        )

    site = ROOT / "site"
    (site / "sources.json").write_text(json.dumps({"default_model": default_model, "sources": out}, indent=1) + "\n")
    (site / "kit.json").write_text((ROOT / "kit.json").read_text())
    (site / "regions.json").write_text((ROOT / "tools" / "regions.json").read_text(encoding="utf-8"), encoding="utf-8")
    print(f"wrote {len(out)} sources")


if __name__ == "__main__":
    main()
