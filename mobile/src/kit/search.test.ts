/// <reference types="node" />
import { expect, test } from "@jest/globals";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { chunks, keywords, search, text, type Book } from "./search";
import { book, type Item } from "./test-zim";
import { Zim, type Source } from "./zim";

const med = (ns: string): Item[] => [
  {
    ns,
    path: "Fever",
    body: `<html><head><title>Fever</title><style>p{}</style></head><body><h1>Fever</h1>
<p>A <b>fever</b> is a body temperature above the normal range, usually 38 &deg;C (100.4 &deg;F) or higher.<sup>[1]</sup></p>
<h2>When to seek urgent help</h2><ul><li>A baby younger than 3 months with a temperature of 38 &deg;C or more.</li>
<li>A stiff neck, confusion, or a rash that does not fade when pressed.</li></ul>
<h2>Treatment</h2><p>Give plenty of fluids to prevent dehydration. Paracetamol or ibuprofen can reduce discomfort.
Do not give aspirin to children.</p><script>var x = "fever fever fever";</script></body></html>`,
  },
  { ns, path: "Temperature", to: `${ns}Fever` },
  { ns, path: "Fever_of_unknown_origin", title: "Fever of unknown origin", body: "<p>A fever that lasts weeks.</p>" },
  {
    ns,
    path: "Dehydration",
    body: `<p><b>Dehydration</b> is a lack of total body water.</p><p>Oral rehydration solution: 1 litre of clean water,
6 level teaspoons of sugar and half a level teaspoon of salt.</p>`,
  },
  { ns: "M", path: "Title", mime: "text/plain", body: "Test Medical Library" },
];
const survival: Item[] = [
  {
    ns: "C",
    path: "Water_purification",
    title: "Water purification",
    body: `<p><b>Water purification</b> makes water safe to drink.</p><h2>Boiling</h2><p>Bring water to a rolling boil for
1 minute, then let it cool.</p>`,
  },
  { ns: "C", path: "Water_tower", title: "Water tower", body: "<p>A tower that holds water for a town.</p>" },
  { ns: "C", path: "Watermelon", body: "<p>A fruit that is mostly water.</p>" },
];
// Opened anew each time it's asked for, as the phone may have closed it since
const opener = (src: Source) => () => new Zim(src);
const books = (): Book[] => [
  { id: "med", title: "Medical library", zim: opener(book(med("C"))) },
  { id: "survival", title: "Survival guide", zim: opener(book(survival)) },
];

test("the words that find something, as the kit page picks them", () => {
  expect(keywords("How do I purify water? It's what we're out of")).toEqual(["purify", "water"]);
  expect(keywords("¿Cómo purificar el agua?")).toEqual(["cómo", "purificar", "agua"]);
  expect(keywords("what can I do")).toEqual([]);
});

test("a page's words, without its scripts, notes and markup", () => {
  const t = text(med("C")[0].body as string);
  expect(t).toContain("usually 38 °C (100.4 °F) or higher.");
  expect(t).toContain("- A stiff neck");
  expect(t).not.toMatch(/\[1\]|var x|p\{\}/);
  expect(chunks("a\nb\nc", 3)).toEqual(["a\nb", "c"]);
});

test("a question finds the passages that answer it, from every book, the best first", () => {
  const water = search("How do I purify water?", books());
  expect(water[0]).toMatchObject({ book: "survival", bookTitle: "Survival guide", title: "Water purification" });
  expect(water[0].page).toBe("/Water_purification");
  expect(water[0].text).toContain("rolling boil");

  const fever = search("what helps a child with a fever", books());
  expect(fever[0]).toMatchObject({ book: "med", title: "Fever", page: "/Fever" });
  expect(fever[0].text).toContain("aspirin to children");
  expect(fever.map((p) => p.title)).toContain("Fever of unknown origin");

  expect(search("what can I do", books())).toEqual([]);
  expect(search("quantum chromodynamics", books())).toEqual([]);
});

test("a book from before 2021: its pages are in A, and its title list has redirects", () => {
  const old: Book = { id: "old", title: "Old library", zim: opener(book(med("A"), { old: true })) };
  expect(search("fever", [old])[0]).toMatchObject({ title: "Fever", page: "/A/Fever" });
  expect(search("is my temperature too high", [old])[0]).toMatchObject({ title: "Fever", page: "/A/Fever" });
});

// Real books made by libzim (tests/make_zims.py), when CI or a developer has built them
const real = process.env.ZIM_FIXTURES;
(real && existsSync(real) ? test : test.skip)("books libzim made", () => {
  const books = readdirSync(real!)
    .filter((n) => n.endsWith(".zim"))
    .map((name): Book => {
      const bytes = new Uint8Array(readFileSync(join(real!, name)));
      const zim = new Zim({ size: bytes.length, read: (o, n) => bytes.subarray(o, o + n) });
      return { id: name, title: zim.metadata("Title") ?? name, zim: () => zim };
    });
  const bleach = search("How much bleach do I put in a gallon of water?", books);
  expect(bleach[0]).toMatchObject({ title: "Water purification", page: "/Water_purification" });
  expect(bleach[0].text).toContain("8 drops");
  expect(search("signs of dehydration", books)[0].text).toContain("dark urine");
});
