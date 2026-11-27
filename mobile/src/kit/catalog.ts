// What a phone can get: the kit's books (kit.json's library, with the website's titles and sizes in sources.json), each
// in its smallest edition. A copy of both files goes into the app when it's built; the website serves newer ones.
import kitJson from "../../../site/kit.json";
import sourcesJson from "../../../site/sources.json";

export type Book = {
  id: string; // the kit's name for it, e.g. wikipedia_en_all_maxi
  title: string;
  why: string;
  group: string;
  starter: boolean; // in the try-it kit
  editions: string[]; // Kiwix names to look for, smallest first: the phone takes the first one published
  bytes?: number; // the size of the kit's edition, when that's the one the phone gets
};

type Source = { id: string; group: string; title: string; why: string; bytes?: number };
type LibraryEntry = { zim: string; enabled?: boolean; starter?: boolean };

// Kiwix publishes some books in several editions: maxi (with pictures), nopic and mini (the opening of each article).
const FLAVORS = ["mini", "nopic", "maxi"];

export function editions(id: string): string[] {
  const m = /^(.*)_(maxi|nopic|mini)$/.exec(id);
  if (!m) return [id];
  return FLAVORS.slice(0, FLAVORS.indexOf(m[2]) + 1).map((f) => `${m[1]}_${f}`);
}

export function buildCatalog(library: LibraryEntry[], sources: Source[]): Book[] {
  const byId = new Map(sources.map((s) => [s.id, s]));
  return library
    .filter((e) => e.enabled !== false && byId.has(e.zim))
    .map((e) => {
      const s = byId.get(e.zim)!;
      const ed = editions(e.zim);
      return {
        id: e.zim,
        title: s.title,
        why: s.why,
        group: s.group,
        starter: e.starter === true,
        editions: ed,
        bytes: ed.length === 1 ? s.bytes : undefined,
      };
    });
}

export const catalog: Book[] = buildCatalog(kitJson.library as LibraryEntry[], sourcesJson.sources as Source[]);

export const groups: string[] = [...new Set(catalog.map((b) => b.group))];

export const starter: Book[] = catalog.filter((b) => b.starter);

export function bytesOf(books: Book[]): number {
  return books.reduce((sum, b) => sum + (b.bytes ?? 0), 0);
}
