// Books download in the background: each goes to the phone's own downloader (iOS's background transfers, Android's
// download manager), so it carries on with the app closed, and the app's native code checks it against Kiwix's
// SHA-256 and files it in the library as it lands, also with the app closed. It waits for Wi-Fi unless the person
// allows mobile data.
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

import { catalog } from "@/kit/catalog";
import { size } from "@/kit/format";
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
};

const AGAIN = 60_000; // when Kiwix's catalog couldn't be reached, ask again after this long
const EVERY = 1000; // how often to look at the downloads while one is going
const SPARE = 5e8; // room a download leaves free on the phone

const byId = new Map(catalog.map((b) => [b.id, b]));

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
      if (b.state === "downloading" && b.cellular !== cellular) {
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

  async function begin(id: string) {
    const book = byId.get(id);
    if (!book) return; // not in this version of the app
    busy.add(id);
    try {
      const zim = await phone.find(book.editions);
      if (!zim) return store.update(id, { status: "failed", error: "Kiwix doesn't publish it at the moment" });
      const sha256 = await phone.checksum(zim.url);
      const { items, cellular } = store.get();
      if (items[id]?.status !== "queued") return; // removed while looking
      const owed = Object.values(items).reduce(
        (n, it) => n + (it.status === "downloading" ? it.total - it.received : 0),
        0,
      );
      if (phone.free() - owed < zim.bytes + SPARE)
        return store.update(id, { status: "failed", error: `Not enough free space for its ${size(zim.bytes)}` });
      const task = `${id}@${Date.now()}`;
      store.update(id, { status: "downloading", file: zim.file, sha256, received: 0, total: zim.bytes, task });
      try {
        await phone.start({
          id: task,
          book: id,
          title: book.title,
          url: zim.url,
          incoming: `${phone.library}/incoming/${zim.file}`,
          path: `${phone.library}/${zim.file}`,
          ...(sha256 && { sha256 }),
          cellular,
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
  };
}

let started = false;

// Called once the store has loaded.
export function startDownloads() {
  if (started || Platform.OS === "web") return;
  started = true;
  const p = phone();
  new Directory(`file://${p.library}/incoming`).create({ intermediates: true, idempotent: true });
  excludeFromBackup(p.library);
  const downloads = createDownloads(kitStore, p);
  void downloads.start();
  AppState.addEventListener("change", (s) => s === "active" && downloads.wake());
  addNetworkStateListener(() => downloads.wake());
}
