/// <reference types="node" />
import { expect, test } from "@jest/globals";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { Fulltext, porter2, sortable, unsortable, words } from "./fulltext";
import { book } from "./test-zim";
import { Zim } from "./zim";

// Xapian 1.4's English stems, which libzim's indexes have: checked against libzim's index of all 42,649 words of
// Snowball's test vocabulary. Snowball's own stemmer has changed since ("added" is "add" there now, "university"
// "universiti"), so its newer test output isn't the measure.
const STEMS: Record<string, string> = {
  caresses: "caress",
  ponies: "poni",
  ties: "tie",
  cries: "cri",
  gas: "gas",
  gaps: "gap",
  kiwis: "kiwi",
  bus: "bus",
  stress: "stress",
  "children's": "children",
  agreed: "agre",
  feed: "feed",
  plastered: "plaster",
  motoring: "motor",
  sing: "sing",
  hopping: "hop",
  hoping: "hope",
  luxuriating: "luxuri",
  filing: "file",
  cry: "cri",
  by: "by",
  say: "say",
  sayings: "say",
  yelling: "yell",
  fly: "fli",
  relational: "relat",
  conditional: "condit",
  valenci: "valenc",
  hesitanci: "hesit",
  digitizer: "digit",
  conformabli: "conform",
  radicalli: "radic",
  differentli: "differ",
  vileli: "vile",
  analogousli: "analog",
  vietnamization: "vietnam",
  predication: "predic",
  operator: "oper",
  feudalism: "feudal",
  decisiveness: "decis",
  hopefulness: "hope",
  callousness: "callous",
  formaliti: "formal",
  sensitiviti: "sensit",
  sensibiliti: "sensibl",
  archaeology: "archaeolog",
  triplicate: "triplic",
  formative: "format",
  formalize: "formal",
  electriciti: "electr",
  electrical: "electr",
  goodness: "good",
  revival: "reviv",
  allowance: "allow",
  inference: "infer",
  airliner: "airlin",
  gyroscopic: "gyroscop",
  adjustable: "adjust",
  defensible: "defens",
  irritant: "irrit",
  replacement: "replac",
  adjustment: "adjust",
  dependent: "depend",
  adoption: "adopt",
  communism: "communism",
  activate: "activ",
  angulariti: "angular",
  homologous: "homolog",
  effective: "effect",
  bowdlerize: "bowdler",
  probate: "probat",
  rate: "rate",
  cease: "ceas",
  controll: "control",
  roll: "roll",
  skies: "sky",
  dying: "die",
  news: "news",
  early: "earli",
  gently: "gentl",
  generously: "generous",
  communication: "communic",
  arsenal: "arsenal",
  inning: "inning",
  proceed: "proceed",
  succeeded: "succeed",
  purify: "purifi",
  purification: "purif",
  purified: "purifi",
  gallons: "gallon",
  dehydration: "dehydr",
  urine: "urin",
  // where Xapian 1.4 and Snowball now differ
  added: "ad",
  university: "univers",
  evening: "even",
  geologist: "geologist",
  internal: "intern",
  emergency: "emerg",
  paste: "past",
  hying: "hy",
};

test("English words cut to the stems libzim's indexes have", () => {
  for (const [word, stem] of Object.entries(STEMS)) expect([word, porter2(word)]).toEqual([word, stem]);
});

test("a query's words, split as Xapian splits them", () => {
  expect(words("How much BLEACH per gallon?")).toEqual(["how", "much", "bleach", "per", "gallon"]);
  expect(words("Don’t mix AT&T's 8.25% bleach, 2,000 ml; first-aid, C++ and C# at the café")).toEqual([
    "don't",
    "mix",
    "at&t's",
    "8.25",
    "bleach",
    "2,000",
    "ml",
    "first",
    "aid",
    "c++",
    "and",
    "c#",
    "at",
    "the",
    "cafe",
  ]);
  expect(words("  ...  ")).toEqual([]);
});

test("numbers in keys sort as the numbers do", () => {
  const values = [0, 1, 255, 256, 0x7fff, 0x8000, 2 ** 22 - 1, 2 ** 22, 2 ** 29 - 1, 2 ** 29, 2 ** 32 - 1, 2 ** 40];
  const keys = values.map(sortable);
  const before = (a: Uint8Array, b: Uint8Array) => {
    for (let i = 0; i < Math.min(a.length, b.length); i++) if (a[i] !== b[i]) return a[i] < b[i];
    return a.length < b.length;
  };
  for (let i = 1; i < keys.length; i++) expect(before(keys[i - 1], keys[i])).toBe(true);
  values.forEach((v, i) => expect(unsortable(keys[i], 0)).toBe(v));
});

test("a book without an index, or with one the app can't read, has no full-text search", () => {
  const page = { ns: "C", path: "Fever", body: "<p>A fever.</p>" };
  expect(Fulltext.of(new Zim(book([page])))).toBeUndefined();
  const junk = { ns: "X", path: "fulltext/xapian", mime: "application/octet-stream+xapian", body: "not an index" };
  expect(Fulltext.of(new Zim(book([page, junk])))).toBeUndefined();
});

// Real books made by libzim (tests/make_zims.py), when CI or a developer has built them
const real = process.env.ZIM_FIXTURES;
const open = (name: string) => {
  const bytes = new Uint8Array(readFileSync(join(real!, name)));
  return new Zim({ size: bytes.length, read: (o, n) => bytes.subarray(o, o + n) });
};
const words2026 = real && join(real, "testwords_en_2026-03.json");

(real && existsSync(real) ? test : test.skip)("libzim's index of a small book", () => {
  const med = Fulltext.of(open("testmed_en_all_maxi_2026-01.zim"))!;
  expect(med.pages).toBe(3);
  expect(med.metadata("language")).toBe("eng");
  const titles = (q: string) => med.search(q).map((e) => e.title);
  expect(titles("dark urine")).toEqual(["Dehydration"]);
  expect(titles("Fevers")[0]).toBe("Fever");
  expect(titles("aspirin children")).toEqual(["Fever"]);
  expect(titles("dehydration")).toEqual(["Dehydration", "Fever"]); // the page about it first
  expect(titles("quantum")).toEqual([]);
  expect(titles("")).toEqual([]);
  const survival = Fulltext.of(open("testsurvival_en_2026-05.zim"))!;
  expect(survival.search("bleach gallon").map((e) => e.path)).toEqual(["Water_purification"]);
});

(words2026 && existsSync(words2026) ? test : test.skip)(
  "ranked as libzim ranks them, in a book of thousands of pages",
  () => {
    const index = Fulltext.of(open("testwords_en_2026-03.zim"))!;
    expect(index.pages).toBe(2503);
    const answers = JSON.parse(readFileSync(words2026!, "utf8")) as Record<string, string[]>;
    for (const [query, paths] of Object.entries(answers))
      expect([query, index.search(query, 20).map((e) => e.path)]).toEqual([query, paths]);
    // A search that may read only a chunk or two of the index: still pages with the words, ranked as before
    for (const query of Object.keys(answers)) {
      const all = index.search(query, 3000).map((e) => e.path);
      const some = index.search(query, 20, 2).map((e) => e.path);
      expect([query, some]).toEqual([query, all.filter((p) => some.includes(p))]);
      if (all.length) expect([query, some.length]).not.toEqual([query, 0]);
    }
  },
);
