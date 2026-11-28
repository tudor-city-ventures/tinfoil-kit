// A book's full-text search: the index libzim builds into Kiwix's books (X/fulltext/xapian), a Xapian database in its
// Glass format. Xapian, like libzim, is GPL, so the app has its own reader of the format. The index lists, for each
// word cut to its stem, the pages it's in; Search takes the pages with every word of a query, ranked as Kiwix ranks
// them (BM25, with Xapian's defaults).
import { inflateSync } from "fflate";

import { utf8, type Entry, type Source, type Zim } from "./zim";

const MAGIC = [0x0f, 0x0d, ...Array.from("Xapian Glass", (ch) => ch.charCodeAt(0)), 0x04, 0x6e]; // format 2016-03-14
const DIR_START = 11; // in a block: a header, then the offsets of its items, sorted by key
const BLOCKS = 256; // blocks kept for the next search: 2 MB
const CHUNKS = 2000; // of postings, the most a pass of a search reads: 4 MB
const encoder = new TextEncoder();

function corrupt(): never {
  throw new Error("This book's search index can't be read");
}

const u16 = (b: Uint8Array, at: number) => (b[at] << 8) | b[at + 1];
const u32 = (b: Uint8Array, at: number) => b[at] * 2 ** 24 + ((b[at + 1] << 16) | (b[at + 2] << 8) | b[at + 3]);

function compare(a: Uint8Array, b: Uint8Array): number {
  const n = Math.min(a.length, b.length);
  for (let i = 0; i < n; i++) if (a[i] !== b[i]) return a[i] - b[i];
  return a.length - b.length;
}

const startsWith = (a: Uint8Array, prefix: Uint8Array) =>
  a.length >= prefix.length && compare(a.subarray(0, prefix.length), prefix) === 0;

function concat(parts: Uint8Array[]): Uint8Array {
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let at = 0;
  for (const p of parts) {
    out.set(p, at);
    at += p.length;
  }
  return out;
}

// A number in a key, written so keys sort as their numbers do: two bytes below 0x8000, else a byte whose leading ones
// say how many more follow
export function sortable(v: number): Uint8Array {
  if (v < 0x8000) return Uint8Array.of(v >> 8, v & 0xff);
  let len = 3;
  for (let x = Math.floor(v / 2 ** 22); x; x = Math.floor(x / 128)) len++;
  const out = new Uint8Array(len);
  for (let i = len - 1; i >= 1; i--) {
    out[i] = v % 256;
    v = Math.floor(v / 256);
  }
  out[0] = (v | (0xff << (10 - len))) & 0xff;
  return out;
}

export function unsortable(b: Uint8Array, at: number): number {
  const first = b[at];
  if (first === undefined) corrupt();
  if (first < 0x80) return (first << 8) | b[at + 1];
  let len = 2; // bytes after the first
  for (let m = 0x40; first & m; m >>= 1) len++;
  let v = first & ~(0xff << (9 - len)) & 0xff;
  for (let i = 1; i <= len; i++) v = v * 256 + b[at + i];
  return v;
}

// A word as a key: a zero byte inside it is doubled with 0xff, so keys still sort as their words do
function termKey(term: string): Uint8Array {
  const bytes = encoder.encode(term);
  const out: number[] = [];
  for (const b of bytes) out.push(...(b === 0 ? [0, 0xff] : [b]));
  return Uint8Array.from(out);
}

type Table = { root: number; level: number; empty: boolean };

// The database: a header, then its tables' blocks, block n at n times the block size. Two tables matter here: the
// postings (for each word, the pages it's in, and each page's length) and each page's path.
class Glass {
  readonly blocksize: number;
  readonly postlist: Table;
  readonly docdata: Table;
  readonly docs: number; // pages
  readonly words: number; // in all of them
  private readonly cache = new Map<number, Uint8Array>(); // most recently used last

  constructor(
    private readonly src: Source,
    private readonly at: number,
    private readonly size: number,
  ) {
    const head = src.read(at, Math.min(size, 256));
    if (MAGIC.some((b, i) => head[i] !== b)) corrupt();
    let pos = 32; // after the magic and the database's id
    const uint = () => {
      let v = 0;
      let mul = 1;
      let b: number;
      do {
        if (pos >= head.length) corrupt();
        b = head[pos++];
        v += (b & 0x7f) * mul;
        mul *= 128;
      } while (b & 0x80);
      return v;
    };
    uint(); // the revision
    const tables: (Table & { blocksize: number })[] = [];
    for (let i = 0; i < 6; i++) {
      const root = uint();
      const flags = uint();
      uint(); // entries
      const blocksize = uint() << 11;
      uint(); // the smallest tag it compresses
      const free = uint(); // its free list
      pos += free;
      tables.push({ root, level: flags >> 2, empty: (flags & 1) === 1, blocksize });
    }
    [this.postlist, this.docdata] = tables;
    this.blocksize = tables[0].blocksize;
    if (this.postlist.empty || this.blocksize < 2048 || tables.some((t) => !t.empty && t.blocksize !== this.blocksize))
      corrupt();
    this.docs = uint();
    uint(); // the last page's number, less the pages
    uint(); // the shortest page
    uint(); // the most times a word is in a page
    uint(); // the longest page, less that
    uint(); // the oldest change kept
    this.words = uint();
  }

  block(n: number, level: number): Uint8Array {
    let b = this.cache.get(n);
    if (b) {
      this.cache.delete(n);
    } else {
      if (n < 1 || (n + 1) * this.blocksize > this.size) corrupt();
      b = this.src.read(this.at + n * this.blocksize, this.blocksize);
      if (b.length !== this.blocksize) corrupt();
    }
    if (b[4] !== level) corrupt();
    this.cache.set(n, b);
    if (this.cache.size > BLOCKS) this.cache.delete(this.cache.keys().next().value!);
    return b;
  }
}

// A place in a table, from its root down to an item in a leaf block. A key's tag can be split across items that follow
// each other, its components, numbered from 1: keys sort by their bytes, then by component.
class Cursor {
  private path: { b: Uint8Array; c: number }[] = [];

  constructor(
    private readonly db: Glass,
    private readonly t: Table,
  ) {}

  // To the last item at or before the key's first component: true when it's the key's
  find(key: Uint8Array): boolean {
    let n = this.t.root;
    for (let level = this.t.level; ; level--) {
      const b = this.db.block(n, level);
      let i = level ? DIR_START : DIR_START - 2; // in a leaf, before the first item
      let j = u16(b, 9);
      let exact = false;
      while (j - i > 2) {
        const k = i + ((j - i) >> 2) * 2;
        const o = u16(b, k);
        let r: number;
        if (level) {
          const len = b[o + 4];
          r = compare(key, b.subarray(o + 5, o + 5 + len)) || 1 - u16(b, o + 5 + len);
        } else {
          const len = b[o + 2];
          r = compare(key, b.subarray(o + 3, o + 3 + len)) || (b[o] & 0x20 ? 0 : 1 - u16(b, o + 3 + len));
        }
        if (r < 0) j = k;
        else {
          i = k;
          if (r === 0) {
            exact = true;
            break;
          }
        }
      }
      this.path[level] = { b, c: i };
      if (level === 0) return exact;
      n = u32(b, u16(b, i));
    }
  }

  // To the last key at or before this one: false when there's none
  findBefore(key: Uint8Array): boolean {
    if (!this.find(key)) {
      if (this.path[0].c < DIR_START && !this.prev()) return false;
      while (!this.first()) if (!this.prev()) corrupt();
    }
    return true;
  }

  next(level = 0): boolean {
    const p = this.path[level];
    if (p.c + 2 < u16(p.b, 9)) {
      p.c += 2;
      return true;
    }
    if (level === this.t.level || !this.next(level + 1)) return false;
    const up = this.path[level + 1];
    this.path[level] = { b: this.db.block(u32(up.b, u16(up.b, up.c)), level), c: DIR_START };
    return true;
  }

  prev(level = 0): boolean {
    const p = this.path[level];
    if (p.c > DIR_START) {
      p.c -= 2;
      return true;
    }
    if (level === this.t.level || !this.prev(level + 1)) return false;
    const up = this.path[level + 1];
    const b = this.db.block(u32(up.b, u16(up.b, up.c)), level);
    this.path[level] = { b, c: u16(b, 9) - 2 };
    return true;
  }

  // To the next key's first component
  nextKey(): boolean {
    do if (!this.next()) return false;
    while (!this.first());
    return true;
  }

  private item() {
    const { b, c } = this.path[0];
    return { b, o: u16(b, c) };
  }

  private first(): boolean {
    const { b, o } = this.item();
    return (b[o] & 0x20) !== 0;
  }

  key(): Uint8Array {
    const { b, o } = this.item();
    return b.subarray(o + 3, o + 3 + b[o + 2]);
  }

  // The key's whole tag, from its first component to its last, where the cursor is left
  tag(): Uint8Array {
    const parts: Uint8Array[] = [];
    const zipped = (this.item().b[this.item().o] & 0x80) !== 0;
    for (;;) {
      const { b, o } = this.item();
      const start = o + 3 + b[o + 2] + (b[o] & 0x20 ? 0 : 2);
      parts.push(b.subarray(start, o + (u16(b, o) & 0x1fff) + 3));
      if (b[o] & 0x40) break;
      if (!this.next()) corrupt();
    }
    const tag = parts.length === 1 ? parts[0] : concat(parts);
    return zipped ? inflateSync(tag) : tag;
  }
}

// The pages a word is in, in order, with the times it's in each (its wdf): in chunks of about 2 KB, the first under
// the word, the others under the word and their first page. The word "" lists every page with its length.
class Postings {
  did = 0;
  wdf = 0;
  end = false;
  readonly freq: number = 0; // pages
  private readonly cur: Cursor;
  private readonly firstKey: Uint8Array;
  private readonly prefix: Uint8Array;
  private chunk: Uint8Array = new Uint8Array();
  private pos = 0;
  private lastDid = 0;
  private lastChunk = true;

  constructor(
    db: Glass,
    term: string,
    private readonly budget: Budget = { chunks: Infinity }, // the chunks it may read, shared with a search's other lists
  ) {
    this.cur = new Cursor(db, db.postlist);
    this.firstKey = term ? termKey(term) : Uint8Array.of(0, 0xe0);
    this.prefix = term ? concat([this.firstKey, Uint8Array.of(0)]) : this.firstKey;
    if (!this.cur.find(this.firstKey)) {
      this.end = true;
      return;
    }
    this.chunk = this.cur.tag();
    this.freq = this.uint();
    this.uint(); // the times it's in them all
    this.did = this.uint() + 1;
    this.header();
  }

  private uint(): number {
    let v = 0;
    let mul = 1;
    let b: number;
    do {
      if (this.pos >= this.chunk.length) corrupt();
      b = this.chunk[this.pos++];
      v += (b & 0x7f) * mul;
      mul *= 128;
    } while (b & 0x80);
    return v;
  }

  // Whether it's the last chunk, its last page, and its first page's wdf
  private header() {
    const last = this.chunk[this.pos++];
    if (last !== 0x30 && last !== 0x31) corrupt();
    this.lastChunk = last === 0x31;
    this.lastDid = this.did + this.uint();
    this.wdf = this.uint();
  }

  private open(key: Uint8Array) {
    this.chunk = this.cur.tag();
    this.pos = 0;
    if (compare(key, this.firstKey) === 0) {
      this.uint();
      this.uint();
      this.did = this.uint() + 1;
    } else if (startsWith(key, this.prefix)) {
      this.did = unsortable(key, this.prefix.length);
    } else corrupt();
    this.header();
  }

  next(): boolean {
    if (this.pos < this.chunk.length) {
      this.did += this.uint() + 1;
      this.wdf = this.uint();
      return true;
    }
    if (this.end || this.lastChunk || --this.budget.chunks < 0 || !this.cur.nextKey()) {
      this.end = true;
      return false;
    }
    this.open(this.cur.key());
    return true;
  }

  // In this chunk, to the first page at or after `did` that it's in at least `least` times: false at the chunk's end.
  // The hot loop of a search, so its numbers are read here rather than with uint().
  private scan(did: number, least: number): boolean {
    const c = this.chunk;
    const n = c.length;
    let p = this.pos;
    let d = this.did;
    while (p < n) {
      let b = c[p++];
      let v = b & 0x7f;
      for (let m = 128; b & 0x80; m *= 128) {
        if (p >= n) corrupt();
        b = c[p++];
        v += (b & 0x7f) * m;
      }
      d += v + 1;
      if (p >= n) corrupt();
      b = c[p++];
      v = b & 0x7f;
      for (let m = 128; b & 0x80; m *= 128) {
        if (p >= n) corrupt();
        b = c[p++];
        v += (b & 0x7f) * m;
      }
      if (d >= did && v >= least) {
        this.did = d;
        this.wdf = v;
        this.pos = p;
        return true;
      }
    }
    this.did = d;
    this.pos = p;
    return false;
  }

  // To the next page it's in at least `least` times
  nextAtLeast(least: number): boolean {
    for (;;) {
      if (this.scan(0, least)) return true;
      if (!this.next()) return false;
      if (this.wdf >= least) return true;
    }
  }

  // To the first page at or after this one
  skipTo(did: number): boolean {
    if (this.end) return false;
    if (did <= this.did) return true;
    if (did > this.lastDid) {
      if (--this.budget.chunks < 0) {
        this.end = true;
        return false;
      }
      // The last chunk that starts at or before it: it has it, or it falls between that chunk and the next
      if (!this.cur.findBefore(concat([this.prefix, sortable(did)]))) corrupt();
      this.open(this.cur.key());
      if (this.did >= did) return true;
      if (this.lastDid < did) this.pos = this.chunk.length; // between this chunk and the next: on to the next
    }
    for (;;) {
      if (this.scan(did, 0)) return true;
      if (!this.next()) return false;
      if (this.did >= did) return true;
    }
  }
}

// English words cut to their stems, as Xapian cuts them: Snowball's English stemmer (Porter2, its 2006 version, which
// Xapian 1.4 has), from snowballstem.org's description of it
const VOWELS = "aeiouy";
const isV = (ch: string | undefined) => ch !== undefined && VOWELS.includes(ch);
const SPECIAL: Record<string, string> = {
  skis: "ski",
  skies: "sky",
  dying: "die",
  lying: "lie",
  tying: "tie",
  idly: "idl",
  gently: "gentl",
  ugly: "ugli",
  early: "earli",
  only: "onli",
  singly: "singl",
  sky: "sky",
  news: "news",
  howe: "howe",
  atlas: "atlas",
  cosmos: "cosmos",
  bias: "bias",
  andes: "andes",
};
const STEP2: Record<string, string> = {
  tional: "tion",
  enci: "ence",
  anci: "ance",
  abli: "able",
  entli: "ent",
  izer: "ize",
  ization: "ize",
  ational: "ate",
  ation: "ate",
  ator: "ate",
  alism: "al",
  aliti: "al",
  alli: "al",
  fulness: "ful",
  ousli: "ous",
  ousness: "ous",
  iveness: "ive",
  iviti: "ive",
  biliti: "ble",
  bli: "ble",
  ogi: "og",
  fulli: "ful",
  lessli: "less",
  li: "",
};
const STEP3: Record<string, string> = {
  tional: "tion",
  ational: "ate",
  alize: "al",
  icate: "ic",
  iciti: "ic",
  ical: "ic",
  ful: "",
  ness: "",
  ative: "",
};
const STEP4 = "al ance ence er ic able ible ant ement ment ent ism ate iti ous ive ize ion".split(" ");

export function porter2(word: string): string {
  const special = SPECIAL[word];
  if (special !== undefined) return special;
  const s = Array.from(word);
  if (s.length < 3) return word;
  const ends = (suffix: string) => s.length >= suffix.length && s.slice(-suffix.length).join("") === suffix;
  const longest = (list: string[]) => list.filter(ends).sort((a, b) => b.length - a.length)[0];
  const cut = (n: number, add = "") => s.splice(s.length - n, n, ...add);
  // A short syllable ending at `end`: a consonant, a vowel and a consonant other than w, x or Y, or a vowel and a
  // consonant at the start
  const short = (end: number) =>
    (end >= 3 && !isV(s[end - 1]) && !"wxY".includes(s[end - 1]) && isV(s[end - 2]) && !isV(s[end - 3])) ||
    (end === 2 && isV(s[0]) && !isV(s[1]));

  if (s[0] === "'") s.shift();
  let ys = false; // a y that's a consonant, as Y
  for (let i = 0; i < s.length; i++)
    if (s[i] === "y" && (i === 0 || isV(s[i - 1]))) {
      s[i] = "Y";
      ys = true;
    }
  // R1 starts after the first consonant that follows a vowel, R2 the same again after it
  const past = (from: number) => {
    let i = from;
    while (i < s.length && !isV(s[i])) i++;
    while (i < s.length && isV(s[i])) i++;
    return i < s.length ? i + 1 : -1;
  };
  const start = s.join("");
  let p1 = s.length;
  let p2 = s.length;
  const r1 = ["gener", "commun", "arsen"].find((p) => start.startsWith(p))?.length ?? past(0);
  if (r1 >= 0) {
    p1 = r1;
    const r2 = past(r1);
    if (r2 >= 0) p2 = r2;
  }

  // Step 1a: possessives and plurals
  const apostrophe = longest(["'s'", "'s", "'"]);
  if (apostrophe) cut(apostrophe.length);
  const plural = longest(["sses", "ied", "ies", "s", "us", "ss"]);
  if (plural === "sses") cut(2);
  else if (plural === "ied" || plural === "ies") cut(3, s.length > 4 ? "i" : "ie");
  else if (plural === "s" && s.slice(0, -2).some(isV)) cut(1);

  if (!["inning", "outing", "canning", "herring", "earring", "proceed", "exceed", "succeed"].includes(s.join(""))) {
    // Step 1b: -ed, -ing and -ly
    const ed = longest(["eed", "eedly", "ed", "edly", "ing", "ingly"]);
    if (ed === "eed" || ed === "eedly") {
      if (s.length - ed.length >= p1) cut(ed.length, "ee");
    } else if (ed && s.slice(0, -ed.length).some(isV)) {
      cut(ed.length);
      if (ends("at") || ends("bl") || ends("iz")) s.push("e");
      else if (["bb", "dd", "ff", "gg", "mm", "nn", "pp", "rr", "tt"].some(ends)) s.pop();
      else if (s.length === p1 && short(s.length)) s.push("e");
    }
    // Step 1c: y after a consonant
    const last = s[s.length - 1];
    if ((last === "y" || last === "Y") && s.length > 2 && !isV(s[s.length - 2])) s[s.length - 1] = "i";
    // Steps 2 to 4: suffixes in R1, then R2
    const two = longest(Object.keys(STEP2));
    if (two && s.length - two.length >= p1) {
      const before = s[s.length - two.length - 1];
      if (two === "ogi" ? before === "l" : two === "li" ? "cdeghkmnrt".includes(before ?? "-") : true)
        cut(two.length, STEP2[two]);
    }
    const three = longest(Object.keys(STEP3));
    if (three && s.length - three.length >= p1 && (three !== "ative" || s.length - three.length >= p2))
      cut(three.length, STEP3[three]);
    const four = longest(STEP4);
    if (four && s.length - four.length >= p2) {
      if (four !== "ion" || "st".includes(s[s.length - 4] ?? "-")) cut(four.length);
    }
    // Step 5: a final e or l
    const at = s.length - 1;
    if (s[at] === "e" && (at >= p2 || (at >= p1 && !short(at)))) s.pop();
    else if (s[at] === "l" && at >= p2 && s[at - 1] === "l") s.pop();
  }
  const out = s.join("");
  return ys ? out.replace(/Y/g, "y") : out;
}

// libzim's: lower case, without accents
function plain(text: string): string {
  const lower = text.toLowerCase();
  try {
    return lower.normalize("NFD").replace(/\p{M}/gu, "").normalize("NFC");
  } catch {
    return lower;
  }
}

const WORD = /[\p{L}\p{N}\p{M}\p{Pc}]/u;
const DIGIT = /\p{Nd}/u;

// A query's words, as Xapian splits text: letters and digits, with an apostrophe or & inside a word, and a point or
// comma between digits, kept ("don't", "AT&T", "8.25"), and up to three + or # after it ("C++")
export function words(text: string): string[] {
  const s = Array.from(plain(text).replace(/[\u2019\u201b]/g, "'"));
  const out: string[] = [];
  let i = 0;
  while (i < s.length) {
    while (i < s.length && !WORD.test(s[i])) i++;
    if (i >= s.length) break;
    let term = "";
    for (;;) {
      while (i < s.length && WORD.test(s[i])) term += s[i++];
      const ch = s[i];
      const after = s[i + 1];
      if (ch === undefined || after === undefined || !WORD.test(after)) break;
      if (/[\u200b-\u200d\u2060\ufeff]/.test(ch)) i++;
      else if (
        DIGIT.test(term[term.length - 1]) && DIGIT.test(after)
          ? ",.;".includes(ch)
          : "'&\u00b7\u05f4\u2027".includes(ch)
      )
        term += s[i++];
      else break;
    }
    let j = i;
    while (j < s.length && j - i < 4 && (s[j] === "+" || s[j] === "#")) j++;
    if (j > i && j - i <= 3 && (j >= s.length || !WORD.test(s[j]))) {
      term += s.slice(i, j).join("");
      i = j;
    }
    out.push(term);
  }
  return out;
}

type Page = { did: number; wdf: number };
type Budget = { chunks: number };
type List = Page & { end: boolean; skipTo(did: number): boolean; nextAtLeast(least: number): boolean };

// Some of a word's pages, in order, picked out
class Picked {
  did = 0;
  wdf = 0;
  end = false;
  private i = -1;

  constructor(private readonly pages: Page[]) {
    this.next();
  }

  private next(): boolean {
    const p = this.pages[++this.i];
    if (!p) return !(this.end = true);
    this.did = p.did;
    this.wdf = p.wdf;
    return true;
  }

  nextAtLeast(least: number): boolean {
    while (this.next()) if (this.wdf >= least) return true;
    return false;
  }

  skipTo(did: number): boolean {
    while (!this.end && this.did < did) this.next();
    return !this.end;
  }
}

const indexes = new WeakMap<Zim, Fulltext | null>();

export class Fulltext {
  private readonly stop: Set<string>;
  private readonly english: boolean;

  private constructor(
    private readonly zim: Zim,
    private readonly db: Glass,
  ) {
    this.stop = new Set(this.metadata("stopwords").split("\n"));
    this.english = /^en(g|$|[-_])/.test(this.metadata("language"));
  }

  // A book's index, when it has one the app can read
  static of(zim: Zim): Fulltext | undefined {
    let index = indexes.get(zim);
    if (index === undefined) {
      index = null;
      try {
        const entry = zim.find("X", "fulltext/xapian");
        const place = entry && zim.locate(entry);
        if (place) index = new Fulltext(zim, new Glass(zim.src, place.offset, place.length));
      } catch {
        // an index in a format the app doesn't know: the book is searched by its titles
      }
      indexes.set(zim, index);
    }
    return index ?? undefined;
  }

  get pages(): number {
    return this.db.docs;
  }

  metadata(name: string): string {
    const c = new Cursor(this.db, this.db.postlist);
    return c.find(concat([Uint8Array.of(0, 0xc0), encoder.encode(name)])) ? utf8(c.tag()) : "";
  }

  private has(term: string): boolean {
    return new Cursor(this.db, this.db.postlist).find(termKey(term));
  }

  // The words of a query as the index has them: stems, without the book's stop words. A word the index has no stem of
  // is looked for as it is, then as the longest start of it the index has, as a stemmer for another language would cut it.
  terms(query: string): string[] {
    const out = new Set<string>();
    for (const w of words(query)) {
      if (this.stop.has(w) || encoder.encode(w).length > 64) continue;
      const stem = this.english ? porter2(w) : w;
      let term = this.has(stem) ? stem : this.has(w) ? w : "";
      for (let n = Array.from(w).length - 1; !term && n >= (this.english ? 4 : 3); n--) {
        const start = Array.from(w).slice(0, n).join("");
        if (this.has(start)) term = start;
      }
      out.add(term || stem);
    }
    return [...out];
  }

  // The best pages with every word of the query, at most `limit`. First the pages the leading word (the one in the
  // fewest pages) is in most often are weighed, to know about how much the best pages weigh; then every page is, passing
  // over those that can't weigh as much. A pass reads at most `chunks` chunks of the index, so a word that's in most of
  // a big book's pages takes a second, not minutes: then the best of the pages that have it most often are found.
  search(query: string, limit = 10, chunks = CHUNKS): Entry[] {
    const terms = this.terms(query);
    if (!terms.length || limit < 1) return [];
    const budget = { chunks };
    const open = () => terms.map((t) => new Postings(this.db, t, budget)).sort((a, b) => a.freq - b.freq);
    const [lead] = open();
    if (lead.end) return [];
    const room = Math.max(limit * 4, 32);
    const most: Page[] = [];
    for (let more = true; more; more = lead.nextAtLeast(most.length < room ? 0 : most[room - 1].wdf + 1)) {
      let i = most.length;
      while (i > 0 && most[i - 1].wdf < lead.wdf) i--;
      most.splice(i, 0, { did: lead.did, wdf: lead.wdf });
      if (most.length > room) most.pop();
    }
    const cut = budget.chunks < 0; // in more pages than a pass can read
    most.sort((a, b) => a.did - b.did);
    budget.chunks = chunks;
    const [, ...others] = open();
    const docs = this.db.docs;
    // BM25, with Xapian's defaults: k1 = 1, b = 0.5, and pages shorter than half the average counted as that long
    const weights = [lead, ...others].map((l) => {
      let tw = (docs - l.freq + 0.5) / (l.freq + 0.5);
      if (tw < 2) tw = tw * 0.5 + 1;
      return Math.log(tw) * 2;
    });
    let best = this.rank(new Picked(most), others, budget, weights, -Infinity, limit);
    if (!cut && lead.freq > room) {
      budget.chunks = chunks;
      const lists = open();
      const bar = best.length === limit ? best[limit - 1].w : -Infinity;
      const more = this.rank(lists[0], lists.slice(1), budget, weights, bar, limit);
      // with the first pages weighed, should the pass have stopped short
      best = [...more, ...best.filter((p) => !more.some((m) => m.did === p.did))]
        .sort((a, b) => b.w - a.w || a.did - b.did)
        .slice(0, limit);
    }
    return best.map(({ did }) => this.page(did)).filter((e): e is Entry => !!e);
  }

  // The best pages, at most `limit`, of those `lead` lists that have every word and weigh at least `bar`. A word's part
  // of a page's weight is at most weights[i] * wdf / (0.75 + wdf), and less than weights[i] whatever its wdf: a page
  // is passed over once what's known of its weight and the most the other words could add can't make the list.
  private rank(lead: List, others: List[], budget: Budget, weights: number[], bar: number, limit: number) {
    const lists = [lead, ...others];
    const n = lists.length;
    const average = this.db.words / this.db.docs || 1;
    const score = (length: number) => {
      const norm = Math.max(length / average, 0.5) * 0.5 + 0.5;
      let w = 0;
      for (let i = 0; i < n; i++) w += (weights[i] * lists[i].wdf) / (norm + lists[i].wdf);
      return w;
    };
    const rest = [0]; // rest[i]: the most the words from i on can add
    for (let i = n - 1; i >= 0; i--) rest.unshift(rest[0] + weights[i]);
    const best: { did: number; w: number }[] = [];
    const could = (w: number) => (best.length === limit ? w > best[limit - 1].w : w >= bar);
    // The times the leading word must be in a page for it to make the list
    let least = 0;
    const raise = (floor: number) => {
      const need = floor - rest[1];
      if (need >= weights[0]) return false; // no page can
      if (need > 0) least = Math.floor((0.75 * need) / (weights[0] - need));
      return true;
    };
    const lengths = new Postings(this.db, "", budget);
    if (!raise(bar)) return best;
    for (let more = lead.wdf >= least || lead.nextAtLeast(least); more;) {
      const did = lead.did;
      let w = (weights[0] * lead.wdf) / (0.75 + lead.wdf);
      let i = 1;
      let after = 0; // the next page that could have every word, when one isn't in this one
      for (; i < n && could(w + rest[i]); i++) {
        const l = lists[i];
        if (!l.skipTo(did)) return best; // no page after has it
        if (l.did !== did) {
          after = l.did;
          break;
        }
        w += (weights[i] * l.wdf) / (0.75 + l.wdf);
      }
      if (after) {
        more = lead.skipTo(after) && (lead.wdf >= least || lead.nextAtLeast(least));
        continue;
      }
      // A page with every word: its length only when it could make the list (it's at least the times they're in it)
      let times = 0;
      for (let j = 0; i === n && j < n; j++) times += lists[j].wdf;
      if (i === n && could(score(times))) {
        if (!lengths.skipTo(did)) break;
        const s = score(lengths.did === did ? lengths.wdf : times);
        if (could(s)) {
          let j = best.length;
          while (j > 0 && best[j - 1].w < s) j--; // after pages that weigh the same, as Xapian has them
          best.splice(j, 0, { did, w: s });
          if (best.length > limit) best.pop();
          if (best.length === limit && !raise(best[limit - 1].w)) break;
        }
      }
      more = lead.nextAtLeast(least);
    }
    return best;
  }

  // A page by its number in the index, which keeps its path in the book: C/Water_purification
  private page(did: number): Entry | undefined {
    const c = new Cursor(this.db, this.db.docdata);
    if (!c.find(sortable(did))) return undefined;
    const path = utf8(c.tag());
    const slash = path.indexOf("/");
    return this.zim.find(path.slice(0, slash), path.slice(slash + 1));
  }
}
