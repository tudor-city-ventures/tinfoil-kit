// Search: the passages in this phone's books that best answer a question, picked as the kit page's Search picks them
// (keywords, the pages they find, the paragraphs with the most of them). The kit finds pages with Kiwix's full-text
// search; the phone finds them by their titles, which every book lists in order.
import { address } from "./books";
import { utf8, type Entry, type Zim } from "./zim";

// A book is opened when it's needed: the phone keeps only a few open at a time
export type Book = { id: string; title: string; zim(): Zim };
export type Passage = { book: string; bookTitle: string; title: string; page: string; text: string };

// The kit page's, so both ask a book the same words
const STOP = new Set(
  (
    "a about above after again against all am an and any are aren't as at be because been before being below between both but by can can't cannot could " +
    "did do does doing don't down during each few for from further get got had has have having he her here hers herself him himself his how i if in into is isn't it " +
    "it's its itself just let's like me more most my myself need no nor not now of off on once only or other ought our ours ourselves out over own please same she " +
    "should so some such than that the their theirs them themselves then there these they this those through to too under until up use using very want was we were " +
    "what when where which while who whom why will with without would you your yours yourself what's how's i'm i've my best way tell know thing things make made " +
    "someone something one ones much many also really"
  ).split(" "),
);

export function stem(w: string): string {
  if (w.length > 5 && w.endsWith("ing")) return w.slice(0, -3);
  if (w.length > 4 && w.endsWith("ies")) return w.slice(0, -3) + "y";
  if (w.length > 4 && /(ed|es)$/.test(w)) return w.slice(0, -2);
  if (w.length > 3 && w.endsWith("s") && !w.endsWith("ss")) return w.slice(0, -1);
  return w;
}

// What two forms of a word share: "purify" and "purification" both give "purif", "children" and "child" "child"
const root = (w: string) => stem(w).slice(0, 5);

function words(text: string): string[] {
  return text.toLowerCase().match(/[\p{L}\p{N}][\p{L}\p{N}'-]*/gu) ?? [];
}

export function keywords(text: string): string[] {
  const out = new Set<string>();
  for (let w of words(text)) {
    w = w.replace(/'s$/, "");
    // nor contractions (we're, won't, I'd): they find nothing worth reading
    if (w.length < 3 || STOP.has(w) || /'(re|ve|ll|d|m)$|n't$/.test(w)) continue;
    out.add(w);
  }
  return [...out];
}

const NAMED: Record<string, string> = {
  amp: "&",
  lt: "<",
  gt: ">",
  quot: '"',
  apos: "'",
  nbsp: " ",
  ndash: "-",
  mdash: "-",
  hellip: "...",
  deg: "°",
  times: "x",
  rsquo: "'",
  lsquo: "'",
  rdquo: '"',
  ldquo: '"',
};

function decode(s: string): string {
  return s.replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (m, e: string) => {
    if (e[0] === "#") {
      const n = e[1] === "x" || e[1] === "X" ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10);
      try {
        return String.fromCodePoint(n);
      } catch {
        return m;
      }
    }
    return NAMED[e.toLowerCase()] ?? m;
  });
}

// A page's words, a paragraph to a line, without its menus, notes and scripts
export function text(html: string): string {
  let s = /<body[^>]*>([\s\S]*)<\/body>/i.exec(html)?.[1] ?? html;
  s = s
    .replace(/<(script|style|noscript|svg|nav|footer|header|figure|sup)\b[\s\S]*?<\/\1>/gi, " ")
    .replace(/<!--[\s\S]*?-->/g, " ")
    .replace(/<(br|\/p|\/div|\/li|\/h[1-6]|\/tr|\/table|\/ul|\/ol|\/dd|\/dt|\/blockquote|\/section)\b[^>]*>/gi, "\n")
    .replace(/<li\b[^>]*>/gi, "\n- ")
    .replace(/<(td|th)\b[^>]*>/gi, " | ")
    .replace(/<[^>]+>/g, " ");
  return decode(s)
    .replace(/\[(\d+|edit|citation needed)\]/gi, "")
    .split("\n")
    .map((l) => l.replace(/[ \t ]+/g, " ").trim())
    .filter((l) => l && l !== "-" && l !== "|")
    .join("\n");
}

// Paragraphs gathered into pieces of about `size` characters
export function chunks(text: string, size = 900): string[] {
  const out: string[] = [];
  let cur = "";
  for (const p of text.split("\n")) {
    if (cur && cur.length + p.length > size) {
      out.push(cur);
      cur = "";
    }
    if (p.length > size * 1.6) for (let i = 0; i < p.length; i += size) out.push(p.slice(i, i + size));
    else cur += (cur ? "\n" : "") + p;
  }
  if (cur) out.push(cur);
  return out;
}

function overlap(text: string, roots: Set<string>) {
  let hits = 0;
  const found = new Set<string>();
  for (const w of words(text)) {
    const r = root(w);
    if (roots.has(r)) {
      hits++;
      found.add(r);
    }
  }
  return { found: found.size, hits };
}

// Pages whose titles start with the question's words: each word alone, and each pair with the second word cut to
// its root, so "purify water" finds "Water purification". A redirect counts by its own title: "Temperature" finds
// the page it leads to.
function candidates(zim: Zim, kw: string[]): { entry: Entry; matched: string }[] {
  const prefixes = new Set<string>();
  for (const a of kw) {
    prefixes.add(a);
    for (const b of kw) if (a !== b) prefixes.add(`${a} ${root(b)}`);
  }
  const seen = new Map<number, { entry: Entry; matched: string }>();
  for (const p of prefixes)
    for (const e of zim.titles(p, p.includes(" ") ? 10 : 5)) {
      const entry = zim.follow(e);
      if (entry.mime.startsWith("text/html") && !seen.has(entry.index))
        seen.set(entry.index, { entry, matched: e.title });
    }
  return [...seen.values()];
}

// The best passages for a question, at most `limit`, the best first
export function search(question: string, books: Book[], limit = 5): Passage[] {
  const kw = keywords(question).slice(0, 6);
  if (!kw.length) return [];
  const roots = new Set(kw.map(root));
  const longest = [...kw].sort((a, b) => b.length - a.length).slice(0, 4); // the likeliest to be in a title
  // The pages whose titles share the most words with the question, the shortest (the most general) first
  const pages = books
    .flatMap((book) => {
      try {
        return candidates(book.zim(), longest).map((c) => ({ book, entry: c.entry, title: overlap(c.matched, roots) }));
      } catch {
        return []; // a book this phone can't open: the others still can be
      }
    })
    .sort((a, b) => b.title.found - a.title.found || a.entry.title.length - b.entry.title.length)
    .slice(0, 8);
  const found: (Passage & { score: number })[] = [];
  for (const { book, entry, title } of pages) {
    let html: string;
    let zim: Zim;
    try {
      zim = book.zim();
      html = utf8(zim.read(entry));
    } catch {
      continue; // a page this phone can't read: the others still can be
    }
    const best = chunks(text(html))
      .map((piece, position) => {
        const o = overlap(piece, roots);
        return { piece, score: title.found * 2 + o.found * 3 + Math.min(o.hits, 12) * 0.5 - position * 0.15 };
      })
      .sort((a, b) => b.score - a.score)[0];
    if (!best) continue;
    found.push({
      book: book.id,
      bookTitle: book.title,
      title: entry.title,
      page: address(zim, entry),
      text: best.piece,
      score: best.score,
    });
  }
  return found
    .sort((a, b) => b.score - a.score)
    .slice(0, limit)
    .map(({ score: _, ...p }) => p);
}
