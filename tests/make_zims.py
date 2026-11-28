"""Build small but real ZIM files (with full-text index) to test the kit and the phone app."""

import json
import random
import struct
import zlib

from libzim.reader import Archive
from libzim.search import Query, Searcher
from libzim.writer import Creator, Hint, Item, StringProvider

ARTICLES = {
    "testmed_en_all_maxi": (
        "Test Medical Library",
        {
            "Fever": (
                "Fever",
                """<p>A <b>fever</b> is a body temperature above the normal range, usually 38 &deg;C (100.4 &deg;F) or higher.</p>
<h2>When to seek urgent help</h2><ul><li>A baby younger than 3 months with a temperature of 38 &deg;C or more.</li>
<li>A stiff neck, confusion, a rash that does not fade when pressed, or difficulty breathing.</li><li>A fever above 40 &deg;C (104 &deg;F).</li></ul>
<h2>Treatment</h2><p>Give plenty of fluids to prevent dehydration. Paracetamol (acetaminophen) or ibuprofen can reduce discomfort; follow the dose on the package by weight.
Do not give aspirin to children. Remove extra clothing and keep the room comfortably cool.</p>""",
            ),
            "Dehydration": (
                "Dehydration",
                """<p><b>Dehydration</b> is a lack of total body water. Signs include thirst, dark urine, dizziness and dry mouth.</p>
<p>Oral rehydration solution can be made from 1 litre of clean water, 6 level teaspoons of sugar and half a level teaspoon of salt.
Give small frequent sips. Severe dehydration with confusion or no urine for 8 hours needs urgent care.</p>""",
            ),
            "Tourniquet": (
                "Tourniquet",
                """<p>A <b>tourniquet</b> stops severe limb bleeding when direct pressure fails. Place it 5 to 7 cm (2 to 3 inches) above the wound,
not on a joint, and tighten until the bleeding stops. Note the time it was applied.</p>""",
            ),
        },
    ),
    "testsurvival_en": (
        "Test Survival Guide",
        {
            "Water_purification": (
                "Water purification",
                """<p><b>Water purification</b> makes water safe to drink.</p>
<h2>Boiling</h2><p>Bring water to a rolling boil for 1 minute (3 minutes above 2,000 metres / 6,500 feet), then let it cool.</p>
<h2>Bleach</h2><p>Use unscented household bleach with 6 to 8.25% sodium hypochlorite: 8 drops (about 1/2 teaspoon per 2 gallons) per gallon of clear water.
Stir and wait 30 minutes. The water should have a slight chlorine smell. Double the amount if the water is cloudy or very cold.</p>""",
            ),
            "Fire_starting": (
                "Fire starting",
                """<p>To start a <b>fire</b>, gather tinder, kindling and fuel wood. Dry grass, birch bark and cotton with petroleum jelly make good tinder.</p>""",
            ),
        },
    ),
}


class Page(Item):
    def __init__(self, path, title, html):
        super().__init__()
        self.path, self.title, self.html = path, title, html

    def get_path(self):
        return self.path

    def get_title(self):
        return self.title

    def get_mimetype(self):
        return "text/html"

    def get_contentprovider(self):
        return StringProvider(self.html)

    def get_hints(self):
        return {Hint.FRONT_ARTICLE: True}


def png48():
    raw = b"".join(b"\x00" + b"\x1f\x5f\x8b\xff" * 48 for _ in range(48))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 48, 48, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def build(prefix, date, extra=""):
    title, pages = ARTICLES[prefix]
    fname = f"{prefix}_{date}.zim"
    with Creator(fname).config_indexing(True, "eng") as c:
        c.set_mainpath(list(pages)[0])
        for k, v in {
            "Name": prefix,
            "Title": title,
            "Language": "eng",
            "Creator": "test",
            "Publisher": "test",
            "Date": f"{date}-01",
            "Description": f"{title} for testing{extra}",
        }.items():
            c.add_metadata(k, v)
        c.add_illustration(png48(), 48)
        for path, (t, body) in pages.items():
            c.add_item(
                Page(path, t, f"<html><head><title>{t}</title></head><body><h1>{t}</h1>{body}{extra}</body></html>")
            )
    print("built", fname)


ROOTS = (
    "water fire bleach boil cook heat cold rain snow wind storm flood river well pump filter cloth bandage wound burn "
    "bone splint fever cough sleep food grain bean rice salt sugar milk seed plant garden tool knife rope knot shelter "
    "tent stove fuel wood radio battery light candle lamp map road bridge trail walk climb swim fish hunt trap horse "
    "sheep goat farm field fence house roof wall door window glass metal iron copper wire nail hammer paint soap wash"
).split()
SUFFIXES = ["", "s", "ed", "ing", "er", "ers", "ly", "ness", "ation", "ations", "ful", "less", "able", "ment", "ize"]


def build_words():
    """Thousands of pages of words, so the full-text index has B-trees of more than one block and words in more pages
    than a chunk of its lists holds. The phone app checks its own reader of the index against libzim's search, whose
    answers to a few searches go beside the book."""
    rng = random.Random(1)
    words = [r + s for r in ROOTS for s in SUFFIXES]
    rng.shuffle(words)
    weights = [1 / (i + 1) for i in range(len(words))]  # a few words in most pages, most in a few
    fname = "testwords_en_2026-03.zim"
    with Creator(fname).config_indexing(True, "eng") as c:
        c.set_mainpath("Test_words")
        for k, v in {
            "Name": "testwords_en",
            "Title": "Test words",
            "Language": "eng",
            "Creator": "test",
            "Publisher": "test",
            "Date": "2026-03-01",
            "Description": "Pages of words for testing",
        }.items():
            c.add_metadata(k, v)
        pages = [("Test_words", "Test words", "Pages of words, for testing search.")]
        for i in range(2500):
            title = " ".join(rng.choices(words, weights, k=rng.randint(1, 3))).capitalize()
            pages.append((f"Page_{i}", title, " ".join(rng.choices(words, weights, k=rng.randint(20, 300)))))
        # paths too long for one item of the index, one that compresses well and one that doesn't
        pages.append(("Long_" + "water_" * 400, "Long", "lamplighter " * 3))
        pages.append(
            ("Mixed_" + "".join(rng.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(3000)), "Mixed", "lamplighter")
        )
        for path, title, body in pages:
            c.add_item(
                Page(
                    path,
                    title,
                    f"<html><head><title>{title}</title></head><body><h1>{title}</h1><p>{body}</p></body></html>",
                )
            )
    searcher = Searcher(Archive(fname))
    queries = [words[0], words[2], words[30], words[300], f"{words[0]} {words[1]}", f"{words[3]} {words[40]}"]
    queries += [f"{words[5]} {words[60]} {words[200]}", "lamplighters", "nowhere"]
    answers = {q: [r.path for r in searcher.search(Query().set_query(q)).get_results(0, 20)] for q in queries}
    with open("testwords_en_2026-03.json", "w") as f:
        json.dump(answers, f, indent=1)
    print("built", fname)


if __name__ == "__main__":
    build("testmed_en_all_maxi", "2026-01")
    build("testsurvival_en", "2026-02")
    build("testsurvival_en", "2026-05", extra="<p>Updated edition.</p>")
    build_words()
