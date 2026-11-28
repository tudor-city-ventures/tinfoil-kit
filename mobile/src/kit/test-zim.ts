/// <reference types="node" />
// Small ZIM books for tests, laid out as openZIM describes and libzim writes them
import { zstdCompressSync } from "node:zlib";

import type { Source } from "./zim";

export type Item = { ns: string; path: string; title?: string; mime?: string; body?: string | Uint8Array; to?: string };
export type Options = { old?: boolean; wide?: boolean; xz?: boolean; main?: string };

const enc = new TextEncoder();
const LISTING = "listing/titleOrdered/v1";

function cmp(a: Uint8Array, b: Uint8Array) {
  for (let i = 0; i < Math.min(a.length, b.length); i++) if (a[i] !== b[i]) return a[i] - b[i];
  return a.length - b.length;
}

function concat(parts: Uint8Array[]) {
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  parts.reduce((at, p) => (out.set(p, at), at + p.length), 0);
  return out;
}

function le(n: number, bytes: number) {
  const b = new Uint8Array(bytes);
  for (let i = 0; i < bytes; i++) b[i] = Math.floor(n / 2 ** (8 * i)) % 256;
  return b;
}

// A book: header, MIME types, an uncompressed cluster for pictures and a compressed one for text, the entries, then
// the lists of where they are
export function book(items: Item[], o: Options = {}): Source {
  const content = o.old ? "A" : "C";
  const all = [...items];
  if (!o.old) all.push({ ns: "X", path: LISTING, mime: "application/octet-stream+zimlisting" });
  if (!o.old && o.main) all.push({ ns: "W", path: "mainPage", to: content + o.main });
  all.sort((a, b) => cmp(enc.encode(a.ns + a.path), enc.encode(b.ns + b.path)));
  const index = new Map(all.map((it, i) => [it.ns + it.path, i]));
  const titleOf = (it: Item) => enc.encode(it.title ?? it.path);
  const pages = all.filter((it) => it.ns === content && !it.to && (it.mime ?? "text/html") === "text/html");
  pages.sort((a, b) => cmp(titleOf(a), titleOf(b)));
  const listing = concat(pages.map((it) => le(index.get(it.ns + it.path)!, 4)));

  const mimes = [...new Set(all.filter((it) => !it.to).map((it) => it.mime ?? "text/html"))];
  const blobs: Uint8Array[][] = [[], []]; // pictures and the listing, then text
  const place = new Map<string, [number, number]>();
  for (const it of all) {
    if (it.to) continue;
    const body =
      it.path === LISTING ? listing : typeof it.body === "string" ? enc.encode(it.body) : (it.body ?? enc.encode(""));
    const c = (it.mime ?? "text/html").startsWith("text/") ? 1 : 0;
    place.set(it.ns + it.path, [c, blobs[c].length]);
    blobs[c].push(body);
  }
  const w = o.wide ? 8 : 4;
  const cluster = (list: Uint8Array[], compress: boolean) => {
    let at = (list.length + 1) * w;
    const offsets = [at, ...list.map((b) => (at += b.length))].map((n) => le(n, w));
    const data = concat([...offsets, ...list]);
    const info = (compress ? (o.xz ? 4 : 5) : 1) | (o.wide ? 0x10 : 0);
    return concat([new Uint8Array([info]), compress ? new Uint8Array(zstdCompressSync(data)) : data]);
  };

  const head = 80;
  const mimeList = concat([...mimes.map((m) => enc.encode(m + "\0")), new Uint8Array([0])]);
  const clusters = [cluster(blobs[0], false), cluster(blobs[1], true)];
  const clusterAt = [head + mimeList.length, head + mimeList.length + clusters[0].length];
  let at = clusterAt[1] + clusters[1].length;
  const dirents = all.map((it) => {
    const fixed = it.to
      ? concat([le(0xffff, 2), new Uint8Array([0, it.ns.charCodeAt(0)]), le(0, 4), le(index.get(it.to)!, 4)])
      : concat([
          le(mimes.indexOf(it.mime ?? "text/html"), 2),
          new Uint8Array([0, it.ns.charCodeAt(0)]),
          le(0, 4),
          le(place.get(it.ns + it.path)![0], 4),
          le(place.get(it.ns + it.path)![1], 4),
        ]);
    const d = concat([fixed, enc.encode(`${it.path}\0${it.title ?? ""}\0`)]);
    const offset = at;
    at += d.length;
    return { d, offset };
  });
  const pathPtr = at;
  const titleOrder = [...all].sort((a, b) =>
    cmp(enc.encode(a.ns + (a.title ?? a.path)), enc.encode(b.ns + (b.title ?? b.path))),
  );
  const titlePtr = o.old ? pathPtr + 8 * all.length : 0;
  const clusterPtr = pathPtr + 8 * all.length + (o.old ? 4 * all.length : 0);
  const checksum = clusterPtr + 16;
  const main = o.old && o.main ? index.get(content + o.main)! : 0xffffffff;
  const header = concat([
    le(72173914, 4),
    le(o.old ? 5 : 6, 2),
    le(o.old ? 0 : 3, 2),
    new Uint8Array(16),
    le(all.length, 4),
    le(2, 4),
    le(pathPtr, 8),
    o.old ? le(titlePtr, 8) : new Uint8Array(8).fill(0xff),
    le(clusterPtr, 8),
    le(head, 8),
    le(main, 4),
    le(0xffffffff, 4),
    le(checksum, 8),
  ]);
  const bytes = concat([
    header,
    mimeList,
    ...clusters,
    ...dirents.map((x) => x.d),
    ...dirents.map((x) => le(x.offset, 8)),
    ...(o.old ? titleOrder.map((it) => le(index.get(it.ns + it.path)!, 4)) : []),
    le(clusterAt[0], 8),
    le(clusterAt[1], 8),
    new Uint8Array(16),
  ]);
  return { size: bytes.length, read: (offset, length) => bytes.subarray(offset, offset + length) };
}

export const png = new Uint8Array(3000).map((_, i) => i % 251);

export function pages(ns: string): Item[] {
  return [
    { ns, path: "Fever", body: "<h1>Fever</h1><p>A body temperature above 38 °C.</p>" },
    { ns, path: "Dehydration", body: "<h1>Dehydration</h1>" },
    { ns, path: "Water_purification", title: "Water purification", body: "<h1>Water</h1>" },
    { ns, path: "Temperature", to: `${ns}Fever` },
    { ns: ns === "C" ? "C" : "I", path: "fever.png", mime: "image/png", body: png },
    { ns: "M", path: "Title", mime: "text/plain", body: "Test Medical Library" },
  ];
}
