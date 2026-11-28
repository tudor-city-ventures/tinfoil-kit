// What the reader's page view gets for each address it asks for. Each book has its own origin, zim://<book>/ on iOS and
// https://<book>.zim.tinfoilkit.invalid/ on Android (where the web view stands in only for https), so its links work as
// they did on its website and one book can't read another's storage.
import { File, FileMode } from "expo-file-system";
import { Platform } from "react-native";

import { unzstd } from "../../modules/kit-files";

import { Zim, type Entry, type Source } from "./zim";

export type Answer =
  | { status: number; mime: string; body: Uint8Array }
  | { status: number; mime: string; file: string; offset: number; length: number }; // read from the file as it is

const ANDROID = ".zim.tinfoilkit.invalid";
const encoder = new TextEncoder();

// A book's name as a host name: letters, digits and hyphens
export function host(id: string): string {
  return id
    .toLowerCase()
    .replace(/[^a-z0-9-]/g, "-")
    .slice(0, 63);
}

export function origin(id: string, os: string = Platform.OS): string {
  return os === "ios" ? `zim://${host(id)}` : `https://${host(id)}${ANDROID}`;
}

// The book and path an address points to, or undefined for one that isn't a book's
export function parse(url: string): { host: string; path: string } | undefined {
  const m = /^(?:zim:\/\/([^/?#]+)|https:\/\/([^/?#]+)\.zim\.tinfoilkit\.invalid)(\/[^?#]*)?/i.exec(url);
  if (!m) return undefined;
  const raw = (m[3] ?? "/").slice(1);
  let path = raw;
  try {
    path = decodeURIComponent(raw);
  } catch {} // a stray % in a link: take it as written
  return { host: (m[1] ?? m[2]).toLowerCase(), path };
}

// An entry's path in its book's origin. Books from before 2021 keep pages and pictures in separate namespaces (A/, I/),
// and their links say so; newer ones keep both in C, and their links leave it out.
export function address(zim: Zim, entry: Entry): string {
  const path = zim.content === "C" ? entry.path : `${entry.namespace}/${entry.path}`;
  return "/" + path.split("/").map(encodeURIComponent).join("/");
}

function find(zim: Zim, path: string): Entry | undefined {
  if (zim.content === "C") return zim.find("C", path);
  return path[1] === "/" ? zim.find(path[0], path.slice(2)) : undefined;
}

const TEXT = /^(text\/|application\/(javascript|json|xml|xhtml\+xml)|image\/svg\+xml)/;

function page(status: number, html: string): Answer {
  return { status, mime: "text/html; charset=utf-8", body: encoder.encode(html) };
}

const missing = `<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Not in this book</title>
<style>body{font:17px/1.5 -apple-system,system-ui,sans-serif;margin:24px;color:#1c1f1a;background:#f3f0e6}
@media (prefers-color-scheme:dark){body{color:#f3f0e6;background:#1c1f1a}}</style>
<h1>Not in this book</h1><p>This link goes to a page the book doesn't have.</p>`;

// `main` says the page view will show this as a page, rather than use it in one
export function answer(zim: Zim, file: string, path: string, main: boolean): Answer {
  let entry = path === "" ? zim.mainPage() : find(zim, path);
  if (!entry) return page(404, missing);
  if (entry.redirect !== undefined || path === "") {
    entry = zim.follow(entry);
    // A page under another name: send the view on to the page's own address, so its links work from there
    if (main)
      return page(200, `<!doctype html><script>location.replace(${JSON.stringify(address(zim, entry))})</script>`);
  }
  const mime = !entry.mime
    ? "application/octet-stream"
    : TEXT.test(entry.mime) && !/charset=/i.test(entry.mime)
      ? `${entry.mime}; charset=utf-8`
      : entry.mime;
  const place = zim.locate(entry);
  if (place) return { status: 200, mime, file, ...place };
  return { status: 200, mime, body: zim.read(entry) };
}

// Copies a file out of the book, for another app to open (a PDF on Android, an e-book): a few megabytes at a time
// when it's stored as it is, so a big one never sits in memory whole.
export function extract(zim: Zim, file: string, path: string, dest: string): Entry | undefined {
  const found = path === "" ? undefined : find(zim, path);
  if (!found) return undefined;
  const entry = zim.follow(found);
  const out = new File(`file://${dest}`);
  out.create({ intermediates: true, overwrite: true });
  const write = out.open(FileMode.Truncate);
  try {
    const place = zim.locate(entry);
    if (!place) {
      write.writeBytesSync(zim.read(entry));
      return entry;
    }
    const read = new File(`file://${file}`).open(FileMode.ReadOnly);
    try {
      read.offset = place.offset;
      for (let left = place.length; left > 0;) {
        const piece = read.readBytesSync(Math.min(left, 4 << 20));
        if (piece.length === 0) throw new Error("The book is damaged");
        write.writeBytesSync(piece);
        left -= piece.length;
      }
    } finally {
      read.close();
    }
    return entry;
  } finally {
    write.close();
  }
}

// Books kept open while they're read, a few at a time
const open = new Map<string, { zim: Zim; close(): void }>();

export function openBook(path: string): Zim {
  const known = open.get(path);
  if (known) {
    open.delete(path); // most recently used last
    open.set(path, known);
    return known.zim;
  }
  const handle = new File(`file://${path}`).open(FileMode.ReadOnly);
  const size = handle.size ?? 0;
  const decoder = unzstd;
  const source: Source = {
    size,
    read(offset, length) {
      handle.offset = offset;
      return handle.readBytesSync(Math.max(0, Math.min(length, size - offset)));
    },
    unzstd: decoder && ((offset, length) => decoder(path, offset, length)),
  };
  let zim: Zim;
  try {
    zim = new Zim(source);
  } catch (e) {
    handle.close();
    throw e;
  }
  open.set(path, { zim, close: () => handle.close() });
  for (const [p, book] of open) {
    if (open.size <= 4) break;
    book.close();
    open.delete(p);
  }
  return zim;
}

export function closeBook(path: string) {
  open.get(path)?.close();
  open.delete(path);
}
