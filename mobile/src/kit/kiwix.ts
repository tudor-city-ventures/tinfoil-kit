// Kiwix's catalog: where a book's newest file is and its SHA-256, from the same places the kit looks.
const CATALOG = process.env.EXPO_PUBLIC_KIWIX_CATALOG || "https://library.kiwix.org/catalog/v2/entries";

export type ZimFile = {
  name: string; // wikipedia_en_medicine_mini
  date: string; // 2026-10
  file: string; // wikipedia_en_medicine_mini_2026-10.zim
  url: string;
  bytes: number; // as the catalog lists it, rounded up to a whole KiB
};

type Get = (url: string) => Promise<{ ok: boolean; status: number; text(): Promise<string> }>;

const ZIM = /^(.+)_(\d{4}-\d{2})\.zim$/;

function attr(tag: string, name: string): string {
  return new RegExp(`\\s${name}="([^"]*)"`).exec(tag)?.[1]?.replace(/&amp;/g, "&") ?? "";
}

// The newest file of each book in a catalog feed (OPDS, Atom).
export function parseCatalog(xml: string): Map<string, ZimFile> {
  const newest = new Map<string, ZimFile>();
  for (const entry of xml.split(/<entry[\s>]/).slice(1)) {
    const link = /<link\s[^>]*type="application\/x-zim"[^>]*>/.exec(entry)?.[0];
    if (!link) continue;
    const url = attr(link, "href").split(".meta4")[0];
    const file = decodeURIComponent(url.slice(url.lastIndexOf("/") + 1));
    const m = ZIM.exec(file);
    if (!m) continue;
    const found = { name: m[1], date: m[2], file, url, bytes: Number(attr(link, "length")) || 0 };
    const now = newest.get(found.name);
    if (!now || found.date > now.date) newest.set(found.name, found);
  }
  return newest;
}

// The first of a book's editions that Kiwix publishes, or undefined when it publishes none of them. A book's name in
// the catalog can leave out its edition (wikipedia_en_all, in its maxi, nopic and mini flavours), so the catalog is
// asked for that first, then for each edition. Throws when the catalog can't be reached, so the book waits rather
// than fails.
export async function findFile(editions: string[], get: Get = fetch): Promise<ZimFile | undefined> {
  const base = editions[0].replace(/_(maxi|nopic|mini)$/, "");
  for (const name of base === editions[0] ? editions : [base, ...editions]) {
    const res = await get(`${CATALOG}${CATALOG.includes("?") ? "&" : "?"}name=${encodeURIComponent(name)}`);
    if (!res.ok) throw new Error(`Kiwix's catalog answered ${res.status}`);
    const found = parseCatalog(await res.text());
    const file = editions.map((e) => found.get(e)).find((f) => f);
    if (file) return file;
  }
  return undefined;
}

// The file's SHA-256 from Kiwix: <file>.sha256, else the .meta4. Undefined when Kiwix gives none; throws when it
// couldn't be asked, so a download is never left unchecked because the network blinked.
export async function checksum(url: string, get: Get = fetch): Promise<string | undefined> {
  let failed: unknown;
  for (const [suffix, re] of [
    [".sha256", /\b([0-9a-fA-F]{64})\b/],
    [".meta4", /type="sha-256">\s*([0-9a-fA-F]{64})/],
  ] as const) {
    try {
      const res = await get(url + suffix);
      const m = res.ok ? re.exec(await res.text()) : null;
      if (m) return m[1].toLowerCase();
    } catch (e) {
      failed = e;
    }
  }
  if (failed) throw failed;
  return undefined;
}
