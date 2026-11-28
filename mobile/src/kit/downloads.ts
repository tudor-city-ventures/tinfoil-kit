// Books download in the background: each goes to the phone's own downloader (iOS's background transfers, Android's
// download manager), so it carries on with the app closed, and the app's native code checks it against Kiwix's
// SHA-256 and files it in the library as it lands, also with the app closed. It waits for Wi-Fi unless the person
// allows mobile data. A book copied from the kit at home comes the same way, from the kit, over its Wi-Fi only.
import { Directory, File, Paths } from "expo-file-system";
import { addNetworkStateListener } from "expo-network";
import { AppState, Platform } from "react-native";

import {
  books,
  excludeFromBackup,
  forgetBook,
  libraryPath as nativeLibraryPath,
  startBook,
  stopBook,
  type BookOptions,
  type BookState,
} from "../../modules/kit-files";

import { closeBook } from "@/kit/books";
import { catalog } from "@/kit/catalog";
import { size } from "@/kit/format";
import { FORGOTTEN, fileName, fileUrl, headers } from "@/kit/home";
import { checksum, findFile, type ZimFile } from "@/kit/kiwix";
import { store as kitStore, type Store } from "@/kit/store";

// What this needs from the phone, so the tests can stand in for it.
export type Phone = {
  library: string; // the folder books go in, as a path
  start(o: BookOptions): Promise<void>;
  stop(id: string): void;
  forget(id: string): void;
  books(): Promise<BookState[]>;
  find(editions: string[]): Promise<ZimFile | undefined>;
  checksum(url: string): Promise<string | undefined>;
  free(): number;
  exists(path: string): boolean;
  delete(path: string): void; // a file, if it's there
};

const AGAIN = 60_000; // when Kiwix's catalog couldn't be reached, ask again after this long
const EVERY = 1000; // how often to look at the downloads while one is going
const SPARE = 5e8; // room a download leaves free on the phone

const byId = new Map(catalog.map((b) => [b.id, b]));

// A book's file, where to get it, and what it must add up to
type Source = { url: string; file: string; bytes: number; sha256?: string; headers?: Record<string, string> };

export function createDownloads(store: Store, phone: Phone) {
  const busy = new Set<string>(); // books being looked up and started
  const later = new Map<string, number>(); // book: when to look it up again
  let pending = false;
  let ready = false; // started
  let timer: ReturnType<typeof setTimeout> | undefined;

  const going = () =>
    Object.values(store.get().items).some((it) => it.status === "downloading" || it.status === "checking");

  function pump() {
    if (pending) return;
    pending = true;
    queueMicrotask(() => {
      pending = false;
      for (const [id, it] of Object.entries(store.get().items))
        if (it.status === "queued" && !busy.has(id) && Date.now() >= (later.get(id) ?? 0)) void begin(id);
      soon(); // after any change, such as a book removed or mobile data turned off
    });
  }

  // Looks at the downloads in a moment, and again every so often while any is going
  function soon(wait = EVERY) {
    if (timer) return;
    timer = setTimeout(() => {
      timer = undefined;
      look()
        .catch(() => {})
        .finally(() => going() && soon());
    }, wait);
  }

  // Brings the store up to date with the phone's downloads, and stops the ones it no longer wants: a book that was
  // removed, or one that started before mobile data was allowed or turned off (iOS and Android fix that when a
  // download starts).
  async function look() {
    const seen = new Set<string>();
    for (const b of await phone.books()) {
      const { items, cellular } = store.get();
      const it = items[b.book];
      if (it?.task !== b.id) {
        if (b.state === "downloading" || b.state === "downloaded") phone.stop(b.id);
        else phone.forget(b.id);
        continue;
      }
      seen.add(b.book);
      if (b.state === "downloading" && b.cellular !== (cellular && !it.from)) {
        phone.stop(b.id);
        store.update(b.book, { status: "queued", received: 0, task: undefined });
      } else if (b.state === "downloading") {
        store.update(b.book, { received: b.received ?? 0, ...(b.total ? { total: b.total } : {}) });
      } else if (b.state === "downloaded") {
        store.update(b.book, { status: "checking", received: it.total });
      } else if (b.state === "ready") {
        store.update(b.book, { status: "ready", received: it.total, task: undefined });
        phone.forget(b.id);
      } else {
        store.update(b.book, { status: "failed", error: b.error ?? "The download stopped", task: undefined });
        phone.forget(b.id);
      }
    }
    return seen;
  }

  // Where a book comes from: Kiwix, which may not publish it now, or the kit at home
  async function source(id: string, editions: string[]): Promise<Source | string> {
    const { items, home } = store.get();
    const from = items[id]?.from;
    if (from) {
      if (!home) return FORGOTTEN;
      const file = { url: fileUrl(home, from.path), file: fileName(from.path), bytes: from.bytes };
      return { ...file, ...(from.sha256 && { sha256: from.sha256 }), headers: headers(home) };
    }
    const zim = await phone.find(editions); // throws when Kiwix doesn't answer
    if (!zim) return "Kiwix doesn't publish it at the moment";
    const sha256 = await phone.checksum(zim.url);
    return { url: zim.url, file: zim.file, bytes: zim.bytes, ...(sha256 && { sha256 }) };
  }

  async function begin(id: string) {
    const book = byId.get(id);
    if (!book) return; // not in this version of the app
    busy.add(id);
    try {
      const got = await source(id, book.editions);
      if (typeof got === "string") return store.update(id, { status: "failed", error: got });
      const { items } = store.get();
      if (items[id]?.status !== "queued") return; // removed while looking
      const owed = Object.values(items).reduce(
        (n, it) => n + (it.status === "downloading" ? it.total - it.received : 0),
        0,
      );
      if (phone.free() - owed < got.bytes + SPARE)
        return store.update(id, { status: "failed", error: `Not enough free space for its ${size(got.bytes)}` });
      const task = `${id}@${Date.now()}`;
      const { sha256 } = got;
      store.update(id, { status: "downloading", file: got.file, sha256, received: 0, total: got.bytes, task });
      try {
        await phone.start({
          id: task,
          book: id,
          title: book.title,
          url: got.url,
          incoming: `${phone.library}/incoming/${got.file}`,
          path: `${phone.library}/${got.file}`,
          ...(sha256 && { sha256 }),
          cellular: store.get().cellular && !got.headers, // the kit at home is on the Wi-Fi
          ...(got.headers && { headers: got.headers }),
        });
      } catch (e) {
        store.update(id, { status: "failed", error: e instanceof Error ? e.message : String(e), task: undefined });
      }
    } catch {
      later.set(id, Date.now() + AGAIN); // no answer from Kiwix: the book waits, and asks again
      setTimeout(pump, AGAIN);
    } finally {
      busy.delete(id);
    }
  }

  return {
    // Takes in what happened while the app was closed, then keeps the downloads in step with the store.
    async start() {
      const seen = await look().catch(() => undefined);
      // Downloads the phone has no word of: a book filed just before its record was written is ready, as only checked
      // books go in the library. The rest start again.
      for (const [id, it] of Object.entries(store.get().items)) {
        if (!seen || (it.status !== "downloading" && it.status !== "checking") || seen.has(id)) continue;
        if (it.file && phone.exists(`${phone.library}/${it.file}`))
          store.update(id, { status: "ready", received: it.total, task: undefined });
        else store.update(id, { status: "queued", received: 0, task: undefined });
      }
      store.subscribe(pump);
      ready = true;
      pump();
    },
    // A book off the phone: out of the list, its file deleted, and its download, if it has one, stopped at the next look
    remove(id: string) {
      const it = store.get().items[id];
      if (!it) return;
      store.remove(id);
      if (it.file) phone.delete(`${phone.library}/${it.file}`);
    },
    // Back in the app, or on another network: books that couldn't reach Kiwix ask again now, and the downloads are
    // looked at at once, since the phone may have finished some meanwhile.
    wake() {
      if (!ready) return;
      later.clear();
      pump();
      if (going()) {
        clearTimeout(timer);
        timer = undefined;
        soon(0);
      }
    },
  };
}

// The folder books go in, as a path
export function libraryPath(): string {
  const native = nativeLibraryPath();
  if (native) return native;
  const library = new Directory(Paths.document, "library");
  return decodeURI(library.uri.replace(/^file:\/\//, "")).replace(/\/$/, "");
}

function phone(): Phone {
  return {
    library: libraryPath(),
    start: startBook,
    stop: stopBook,
    forget: forgetBook,
    books,
    find: findFile,
    checksum,
    free: () => Paths.availableDiskSpace,
    exists: (path) => new File(`file://${path}`).exists,
    delete(path) {
      closeBook(path);
      const f = new File(`file://${path}`);
      if (f.exists) f.delete();
    },
  };
}

let running: ReturnType<typeof createDownloads> | undefined;

// Called once the store has loaded.
export function startDownloads() {
  if (running || Platform.OS === "web") return;
  const p = phone(); // its library is there by now: the native code makes it
  excludeFromBackup(p.library);
  const downloads = (running = createDownloads(kitStore, p));
  void downloads.start();
  AppState.addEventListener("change", (s) => s === "active" && downloads.wake());
  addNetworkStateListener(() => downloads.wake());
}

// Takes a book off the phone, or stops its download
export function removeBook(id: string) {
  if (running) running.remove(id);
  else kitStore.remove(id);
}
