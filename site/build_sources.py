"""Build site/sources.json (the kit builder's data) and site/kit.json from the repo's kit.json.

usage: python3 site/build_sources.py [sizes.json]
sizes.json (optional) maps a source id to bytes, e.g. from `./kit plan --json`. Without it,
sizes come from the "~N GB" in each kit.json note.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GB = 1e9

# What it is and why you'd want it, for the sources people ask about most. Everything else
# falls back to its kit.json note.
COPY = {
    "Inkling-2-Mini": ("Inkling 2 Mini", "The default AI. Fast, reads photos, built for a 32 GB Mac."),
    "Qwen3.8-27B": ("Qwen 3.8 27B", "A second opinion from a different lab. Slower, but strong."),
    "Gemma-4-26B-A4B": ("Gemma 4 26B", "A third opinion from Google. Quick and reads photos."),
    "Gemma-4-E4B": ("Gemma 4 E4B", "Small and light. Runs on an 8 to 16 GB laptop or on battery."),
    "maps": ("Offline maps", "Street maps, address search and driving or walking directions for your region."),
    "mdwiki_en_all_maxi": ("WikiMed", "A medical encyclopedia: conditions, drugs, procedures."),
    "wikem_en_all_maxi": ("WikEM", "Emergency medicine notes written for clinicians."),
    "zimgit-medicine_en": ("Field medicine books", "First aid and medicine for when help is far away."),
    "fas-military-medicine_en": ("Military medicine", "Trauma care manuals from the US military."),
    "zimgit-post-disaster_en": ("Post-disaster guides", "Shelter, sanitation and recovery after a disaster."),
    "zimgit-water_en": ("Water treatment", "How to find, filter and disinfect drinking water."),
    "zimgit-food-preparation_en": ("Food preparation", "Storing, preserving and cooking food without power."),
    "zimgit-knots_en": ("Knots", "Illustrated knots for rope, tarps and rescue."),
    "www.ready.gov_en": ("Ready.gov", "FEMA's guides for every kind of emergency."),
    "who.int_en_all": ("World Health Organization", "Public health guidance and disease facts."),
    "ifixit_en_all": ("iFixit", "Step-by-step repair guides for phones, appliances, cars and tools."),
    "appropedia_en_all_maxi": ("Appropedia", "Off-grid and low-tech solutions: solar, water, building."),
    "energypedia_en_all_nopic": ("Energypedia", "Solar panels, batteries and small power systems."),
    "armypubs_en_all": ("US Army publications", "Field manuals on survival, first aid, navigation and more."),
    "wikipedia_en_all_maxi": ("Wikipedia, with images", "All of English Wikipedia. The reference for nearly any question."),
    "wiktionary_en_all_nopic": ("Wiktionary", "A full dictionary and thesaurus."),
    "wikibooks_en_all_maxi": ("Wikibooks", "Open textbooks and how-tos."),
    "wikivoyage_en_all_maxi": ("Wikivoyage", "Travel guides for places you might need to go."),
    "survivorlibrary.com_en_all": ("Survivor Library", "Historical how-to books on farming, tools and trades."),
    "khanacademy_en_all": ("Khan Academy", "Video lessons for school-age kids."),
    "gutenberg_en_all": ("All of Project Gutenberg", "Every English public-domain book. Replaces the subsets."),
}

GROUPS = [
    ("Medical", r"med|mdwiki|wikem|who\.int"),
    ("Preparedness", r"ready|post-disaster|water|food|knots|army|outdoors"),
    ("Repair and skills", r"ifixit|appropedia|energypedia|diy|gardening|cooking|electronics|ham\.|mechanics|bicycles|sustainab"),
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


def group_for(zim):
    return next(g for g, rx in GROUPS if re.search(rx, zim))


def main():
    cfg = json.loads((ROOT / "kit.json").read_text())
    live = json.loads(Path(sys.argv[1]).read_text()) if len(sys.argv) > 1 else {}
    default_model = cfg["settings"]["default_model"]
    out = []

    def add(sid, group, note, enabled, essential):
        title, why = COPY.get(sid, (None, None))
        size = live.get(sid) or size_from_note(note)
        out.append({"id": sid, "group": group, "title": title or note.split(":")[0].split("(")[0].strip(),
                    "why": why or note, "bytes": int(size) if size else None, "estimated": sid not in live,
                    "presets": [p for p, on in (("essentials", essential), ("recommended", enabled), ("everything", True)) if on]})

    for m in cfg["models"]:
        add(m["id"], "AI models", m.get("note", ""), m.get("enabled", True),
            m["id"] in (default_model, "Gemma-4-E4B"))
    mp = cfg["maps"]
    add("maps", "Maps", f"{mp['label']}: about 20-30 GB", mp.get("enabled", True), True)
    if "maps" not in live:
        out[-1]["bytes"] = int(25 * GB)
    for z in cfg["library"]:
        add(z["zim"], group_for(z["zim"]), z.get("note", ""), z.get("enabled", True),
            z.get("enabled", True) and z.get("priority", 9) == 1)

    site = ROOT / "site"
    (site / "sources.json").write_text(json.dumps({"default_model": default_model, "sources": out}, indent=1) + "\n")
    (site / "kit.json").write_text((ROOT / "kit.json").read_text())
    print(f"wrote {len(out)} sources")


if __name__ == "__main__":
    main()
