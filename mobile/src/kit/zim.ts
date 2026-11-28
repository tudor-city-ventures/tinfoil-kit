// Kiwix's books are ZIM files. This reads them on the phone, from openZIM's description of the format
// (wiki.openzim.org/wiki/ZIM_file_format): a header, entries sorted by path, and clusters of content, most of them
// compressed with Zstandard. Kiwix's own reader, libzim, is GPL, so the app has its own.
import { decompress } from "fzstd";

// Where the bytes come from: the file on the phone, or a test's.
export type Source = { size: number; read(offset: number, length: number): Uint8Array };

export type Entry = {
  index: number;
  namespace: string; // C for content (A, I and - in books from before 2021), M metadata, W and X the book's own
  path: string;
  title: string; // the path, when the book gives no title
  mime: string; // "" for a redirect
  redirect?: number; // the entry it stands for
  cluster: number;
  blob: number;
};

const NONE = 0xffffffff;
const CACHE = 16e6; // bytes of decompressed clusters kept for the next page

const encoder = new TextEncoder();
const decoder = typeof TextDecoder === "undefined" ? undefined : new TextDecoder();

export function utf8(bytes: Uint8Array): string {
  if (decoder) return decoder.decode(bytes);
  const points: number[] = [];
  for (let i = 0; i < bytes.length;) {
    const b = bytes[i++];
    const n = b < 0x80 ? 0 : b < 0xe0 ? 1 : b < 0xf0 ? 2 : 3;
    let c = n ? b & (0x3f >> n) : b;
    for (let k = 0; k < n; k++) c = (c << 6) | (bytes[i++] & 0x3f);
    points.push(c > 0x10ffff ? 0xfffd : c);
  }
  let out = "";
  for (let i = 0; i < points.length; i += 4096) out += String.fromCodePoint(...points.slice(i, i + 4096));
  return out;
}

function compare(a: Uint8Array, b: Uint8Array): number {
  const n = Math.min(a.length, b.length);
  for (let i = 0; i < n; i++) if (a[i] !== b[i]) return a[i] - b[i];
  return a.length - b.length;
}

function startsWith(a: Uint8Array, prefix: Uint8Array): boolean {
  return a.length >= prefix.length && compare(a.subarray(0, prefix.length), prefix) === 0;
}

// Where a Zstandard frame ends, from its header and block headers, without decompressing it.
function frameEnd(src: Source, at: number): number {
  const h = src.read(at, 6);
  if (h[0] !== 0x28 || h[1] !== 0xb5 || h[2] !== 0x2f || h[3] !== 0xfd) throw new Error("The book is damaged");
  const single = (h[4] >> 5) & 1;
  let p = at + 5 + (single ? 0 : 1) + [0, 1, 2, 4][h[4] & 3] + [single, 2, 4, 8][h[4] >> 6];
  for (let last = 0; !last;) {
    const b = src.read(p, 3);
    const v = b[0] | (b[1] << 8) | (b[2] << 16);
    last = v & 1;
    p += 3 + (((v >> 1) & 3) === 1 ? 1 : v >>> 3);
  }
  return p + ((h[4] >> 2) & 1 ? 4 : 0);
}

export class Zim {
  readonly count: number;
  readonly content: string; // the namespace of the book's pages
  private readonly clusters: number;
  private readonly pathPtr: number;
  private readonly titlePtr: number;
  private readonly clusterPtr: number;
  private readonly mainIndex: number;
  private readonly mimes: string[] = [];
  private readonly cache = new Map<number, Uint8Array>(); // cluster: its data, most recently used last
  private cached = 0;

  constructor(private readonly src: Source) {
    const v = this.view(0, 80);
    if (v.getUint32(0, true) !== 72173914) throw new Error("This isn't a ZIM book");
    const minor = v.getUint16(6, true);
    const u64 = (at: number) => v.getUint32(at, true) + v.getUint32(at + 4, true) * 2 ** 32;
    this.count = v.getUint32(24, true);
    this.clusters = v.getUint32(28, true);
    this.pathPtr = u64(32);
    this.titlePtr = u64(40) < src.size ? u64(40) : 0;
    this.clusterPtr = u64(48);
    this.mainIndex = v.getUint32(64, true);
    this.content = v.getUint16(4, true) >= 6 && minor >= 1 ? "C" : "A";
    const list = src.read(u64(56), Math.min(65536, src.size - u64(56)));
    for (let i = 0, start = 0; i < list.length; i++) {
      if (list[i] !== 0) continue;
      if (i === start) break;
      this.mimes.push(utf8(list.subarray(start, i)));
      start = i + 1;
    }
  }

  private view(offset: number, length: number): DataView {
    const b = this.src.read(offset, length);
    return new DataView(b.buffer, b.byteOffset, b.byteLength);
  }

  private u64(offset: number): number {
    const v = this.view(offset, 8);
    return v.getUint32(0, true) + v.getUint32(4, true) * 2 ** 32;
  }

  // An entry's fixed part, and its path and title as bytes.
  private raw(index: number) {
    if (index < 0 || index >= this.count) throw new Error("No such entry");
    const at = this.u64(this.pathPtr + 8 * index);
    for (let length = 512; ; length *= 8) {
      const b = this.src.read(at, Math.min(length, this.src.size - at));
      const v = new DataView(b.buffer, b.byteOffset, b.byteLength);
      const mime = v.getUint16(0, true);
      const start = mime === 0xffff ? 12 : 16;
      const end = b.indexOf(0, start);
      const titleEnd = end < 0 ? -1 : b.indexOf(0, end + 1);
      if (titleEnd < 0) {
        if (at + length >= this.src.size) throw new Error("The book is damaged");
        continue;
      }
      const key = new Uint8Array(end - start + 1);
      key[0] = b[3];
      key.set(b.subarray(start, end), 1);
      return {
        mime,
        key, // namespace and path, the order entries are sorted in
        title: titleEnd > end + 1 ? b.subarray(end + 1, titleEnd) : key.subarray(1),
        a: v.getUint32(8, true),
        b: mime === 0xffff ? 0 : v.getUint32(12, true),
      };
    }
  }

  entry(index: number): Entry {
    const r = this.raw(index);
    const redirect = r.mime === 0xffff;
    return {
      index,
      namespace: String.fromCharCode(r.key[0]),
      path: utf8(r.key.subarray(1)),
      title: utf8(r.title),
      mime: redirect ? "" : (this.mimes[r.mime] ?? "application/octet-stream"),
      ...(redirect && { redirect: r.a }),
      cluster: redirect ? 0 : r.a,
      blob: r.b,
    };
  }

  // The entry at a path, by binary search: entries are sorted by namespace, then path.
  find(namespace: string, path: string): Entry | undefined {
    const want = encoder.encode(namespace + path);
    let lo = 0;
    let hi = this.count - 1;
    while (lo <= hi) {
      const mid = (lo + hi) >>> 1;
      const c = compare(this.raw(mid).key, want);
      if (c === 0) return this.entry(mid);
      if (c < 0) lo = mid + 1;
      else hi = mid - 1;
    }
    return undefined;
  }

  // A redirect's target, through any chain of them.
  follow(entry: Entry): Entry {
    for (let hops = 0; entry.redirect !== undefined; hops++) {
      if (hops > 50) throw new Error("The book is damaged");
      entry = this.entry(entry.redirect);
    }
    return entry;
  }

  mainPage(): Entry | undefined {
    const main = this.mainIndex !== NONE ? this.entry(this.mainIndex) : this.find("W", "mainPage");
    return main && this.follow(main);
  }

  metadata(name: string): string | undefined {
    const e = this.find("M", name);
    return e && utf8(this.read(e));
  }

  private clusterAt(cluster: number): number {
    if (cluster >= this.clusters) throw new Error("The book is damaged");
    return this.u64(this.clusterPtr + 8 * cluster);
  }

  // A cluster's start, whether it's compressed and how wide its offsets are, and where a blob in it starts and ends
  private cluster(index: number) {
    const at = this.clusterAt(index);
    const info = this.src.read(at, 1)[0];
    const wide = info & 0x10 ? 8 : 4;
    const offsets = (bytes: Uint8Array, blob: number) => {
      const v = new DataView(bytes.buffer, bytes.byteOffset + blob * wide, 2 * wide);
      const get = (i: number) =>
        wide === 8 ? v.getUint32(i, true) + v.getUint32(i + 4, true) * 2 ** 32 : v.getUint32(i, true);
      return [get(0), get(wide)];
    };
    return { at, kind: info & 0x0f, wide, offsets };
  }

  // Where an entry's content lies in the file, when it's stored as it is (pictures, PDFs and videos usually are), so
  // it can be read straight from the file.
  locate(entry: Entry): { offset: number; length: number } | undefined {
    if (entry.redirect !== undefined) return undefined;
    const c = this.cluster(entry.cluster);
    if (c.kind > 1) return undefined;
    const [start, end] = c.offsets(this.src.read(c.at + 1 + entry.blob * c.wide, 2 * c.wide), 0);
    return { offset: c.at + 1 + start, length: end - start };
  }

  // An entry's content. Compressed clusters are decompressed whole and kept for a while, since a page's neighbours
  // are usually in the same cluster.
  read(entry: Entry): Uint8Array {
    if (entry.redirect !== undefined) return this.read(this.follow(entry));
    const place = this.locate(entry);
    if (place) return this.src.read(place.offset, place.length);
    const { at, kind, offsets } = this.cluster(entry.cluster);
    if (kind !== 5) throw new Error("This book is in an older format the app can't read yet");
    let data = this.cache.get(entry.cluster);
    if (data) {
      this.cache.delete(entry.cluster);
    } else {
      data = decompress(this.src.read(at + 1, frameEnd(this.src, at + 1) - at - 1));
      this.cached += data.length;
    }
    this.cache.set(entry.cluster, data);
    for (const [k, d] of this.cache) {
      if (this.cached <= CACHE || k === entry.cluster) break;
      this.cache.delete(k);
      this.cached -= d.length;
    }
    const [start, end] = offsets(data, entry.blob);
    return data.subarray(start, end);
  }

  // Pages whose titles start with these words, in title order. Books list their pages by title in
  // X/listing/titleOrdered/v1; older ones have a title list for every entry.
  titles(prefix: string, limit = 20): Entry[] {
    const listing = this.find("X", "listing/titleOrdered/v1");
    let size: number;
    let at: (i: number) => number;
    if (listing) {
      const list = this.read(listing);
      const v = new DataView(list.buffer, list.byteOffset, list.byteLength);
      size = list.length / 4;
      at = (i) => v.getUint32(4 * i, true);
    } else if (this.titlePtr) {
      size = this.count;
      at = (i) => this.view(this.titlePtr + 4 * i, 4).getUint32(0, true);
    } else {
      return [];
    }
    const out: Entry[] = [];
    const seen = new Set<number>();
    // Titles are sorted as bytes, so capitals come first: look for the words as typed and with a capital
    for (const words of new Set([prefix, prefix.charAt(0).toUpperCase() + prefix.slice(1)])) {
      const ns = listing ? "" : this.content;
      const want = encoder.encode(ns + words);
      const key = (i: number) => {
        const r = this.raw(at(i));
        if (listing) return r.title;
        const k = new Uint8Array(r.title.length + 1);
        k[0] = r.key[0];
        k.set(r.title, 1);
        return k;
      };
      let lo = 0;
      let hi = size;
      while (lo < hi) {
        const mid = (lo + hi) >>> 1;
        if (compare(key(mid), want) < 0) lo = mid + 1;
        else hi = mid;
      }
      for (let i = lo; i < size && out.length < limit && startsWith(key(i), want); i++) {
        const index = at(i);
        if (seen.has(index)) continue;
        seen.add(index);
        const e = this.entry(index);
        if (listing || e.mime.startsWith("text/html")) out.push(e);
      }
    }
    return out.sort((a, b) => compare(encoder.encode(a.title), encoder.encode(b.title))).slice(0, limit);
  }
}
