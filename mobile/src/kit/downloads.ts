// Books download in the background: each goes to the phone's own downloader (iOS's background transfers, Android's
// download jobs), so it carries on with the app closed. It waits for Wi-Fi unless the person allows mobile data, and
// it's checked against Kiwix's SHA-256 before it's ready.
import {
  completeHandler,
  createDownloadTask,
  getExistingDownloadTasks,
  setConfig,
} from "@kesha-antonov/react-native-background-downloader";
import { Directory, File, Paths } from "expo-file-system";
import { addNetworkStateListener } from "expo-network";
import { AppState, Platform } from "react-native";

import { excludeFromBackup, sha256 } from "../../modules/kit-files";

import { catalog } from "@/kit/catalog";
import { size } from "@/kit/format";
import { checksum, findFile, type ZimFile } from "@/kit/kiwix";
import { store as kitStore, type Store } from "@/kit/store";

// The phone's downloader's task, as far as this goes.
export type Task = {
  id: string;
  state: string;
  metadata: Record<string, unknown>;
  bytesDownloaded: number;
  bytesTotal: number;
  progress(handler: (p: { bytesDownloaded: number; bytesTotal: number }) => void): Task;
  done(handler: () => void): Task;
  error(handler: (e: { error: string }) => void): Task;
  start(): void;
  resume(): Promise<void>;
  stop(): Promise<void>;
};

// What this needs from the phone, so the tests can stand in for it.
export type Phone = {
  library: string; // the folder books go in, as a path
  download(o: { id: string; url: string; path: string; book: string; cellular: boolean }): Task;
  existing(): Promise<Task[]>;
  complete(task: string): void;
  find(editions: string[]): Promise<ZimFile | undefined>;
  checksum(url: string): Promise<string | undefined>;
  free(): number;
  exists(path: string): boolean;
  sha256(path: string): Promise<string>;
  move(from: string, to: string): Promise<void>;
  remove(path: string): void;
};

const AGAIN = 60_000; // when Kiwix's catalog couldn't be reached, ask again after this long
const SPARE = 5e8; // room a download leaves free on the phone

const byId = new Map(catalog.map((b) => [b.id, b]));

export function createDownloads(store: Store, phone: Phone) {
  const live = new Map<string, Task>(); // book: its download
  const busy = new Set<string>(); // books being looked up or checked
  const later = new Map<string, number>(); // book: when to look it up again
  let pending = false;

  const incoming = (file: string) => `${phone.library}/incoming/${file}`; // downloaded, not yet checked
  const mine = (id: string, task: Task) => store.get().items[id]?.task === task.id;

  function pump() {
    if (pending) return;
    pending = true;
    queueMicrotask(() => {
      pending = false;
      const { items, cellular } = store.get();
      for (const [id, task] of live) {
        if (items[id]?.task !== task.id) {
          drop(id, task); // the book was removed
        } else if (task.metadata.cellular !== cellular) {
          // iOS and Android fix a download's use of mobile data when it starts, so a change starts it over
          drop(id, task);
          store.update(id, { status: "queued", received: 0, task: undefined });
        }
      }
      for (const [id, it] of Object.entries(store.get().items))
        if (it.status === "queued" && !busy.has(id) && Date.now() >= (later.get(id) ?? 0)) void begin(id);
    });
  }

  function drop(id: string, task: Task) {
    live.delete(id);
    task.stop().catch(() => {});
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
      const task = phone.download({
        id: `${id}@${Date.now()}`,
        url: zim.url,
        path: incoming(zim.file),
        book: id,
        cellular,
      });
      store.update(id, { status: "downloading", file: zim.file, sha256, received: 0, total: zim.bytes, task: task.id });
      watch(id, task);
      task.start();
    } catch {
      later.set(id, Date.now() + AGAIN); // no answer from Kiwix: the book waits, and asks again
      setTimeout(pump, AGAIN);
    } finally {
      busy.delete(id);
    }
  }

  function watch(id: string, task: Task) {
    live.set(id, task);
    const over = () => {
      phone.complete(task.id);
      if (live.get(id) === task) live.delete(id);
      return mine(id, task);
    };
    task
      .progress(({ bytesDownloaded, bytesTotal }) => {
        if (mine(id, task))
          store.update(id, { received: bytesDownloaded, ...(bytesTotal > 0 && { total: bytesTotal }) });
      })
      .done(() => {
        if (over()) void check(id);
      })
      .error(({ error }) => {
        if (over()) store.update(id, { status: "failed", error, task: undefined });
      });
  }

  async function check(id: string) {
    const file = store.get().items[id]?.file;
    if (!file) return;
    busy.add(id);
    store.update(id, { status: "checking", task: undefined });
    const from = incoming(file);
    try {
      if (!phone.exists(from)) throw new Error("The download went missing");
      const want = store.get().items[id]?.sha256;
      if (want && (await phone.sha256(from)) !== want) throw new Error("It came through damaged");
      await phone.move(from, `${phone.library}/${file}`);
      store.update(id, { status: "ready", received: store.get().items[id]?.total ?? 0 });
    } catch (e) {
      phone.remove(from);
      store.update(id, { status: "failed", error: e instanceof Error ? e.message : String(e) });
    } finally {
      busy.delete(id);
    }
  }

  return {
    // Picks up where the last run left off, then keeps the downloads in step with the store.
    async start() {
      for (const task of await phone.existing()) {
        const id = String(task.metadata.book ?? "");
        if (!mine(id, task)) {
          phone.complete(task.id);
          if (task.state !== "DONE") task.stop().catch(() => {});
        } else if (task.state === "DONE") {
          phone.complete(task.id);
          void check(id);
        } else {
          watch(id, task);
          store.update(id, { received: task.bytesDownloaded, ...(task.bytesTotal > 0 && { total: task.bytesTotal }) });
          if (task.state === "PAUSED") task.resume().catch(() => {});
        }
      }
      // Downloads the phone no longer has (iOS cancels them when the app is swiped away) start again
      for (const [id, it] of Object.entries(store.get().items)) {
        if (live.has(id) || busy.has(id)) continue;
        if (it.status === "checking" || (it.status === "downloading" && it.file && phone.exists(incoming(it.file))))
          void check(id);
        else if (it.status === "downloading") store.update(id, { status: "queued", received: 0, task: undefined });
      }
      store.subscribe(pump);
      pump();
    },
    // Back in the app, or on another network: books that couldn't reach Kiwix ask again now.
    wake() {
      later.clear();
      pump();
    },
  };
}

function phone(): Phone {
  const library = new Directory(Paths.document, "library");
  const file = (path: string) => new File(`file://${path}`);
  return {
    library: decodeURI(library.uri.replace(/^file:\/\//, "")).replace(/\/$/, ""),
    download: ({ id, url, path, book, cellular }) =>
      createDownloadTask({
        id,
        url,
        destination: path,
        isAllowedOverMetered: cellular,
        isAllowedOverRoaming: cellular,
        metadata: { book, cellular },
      }),
    existing: getExistingDownloadTasks,
    complete: completeHandler,
    find: findFile,
    checksum,
    free: () => Paths.availableDiskSpace,
    exists: (path) => file(path).exists,
    sha256,
    move: (from, to) => file(from).move(file(to), { overwrite: true }),
    remove: (path) => {
      if (file(path).exists) file(path).delete();
    },
  };
}

let started = false;

// Called once the store has loaded.
export function startDownloads() {
  if (started || Platform.OS === "web") return;
  started = true;
  const p = phone();
  setConfig({ allowsCellularAccess: false }); // each download says for itself; this is the default
  new Directory(`file://${p.library}/incoming`).create({ intermediates: true, idempotent: true });
  excludeFromBackup(p.library);
  const downloads = createDownloads(kitStore, p);
  void downloads.start();
  AppState.addEventListener("change", (s) => s === "active" && downloads.wake());
  addNetworkStateListener(() => downloads.wake());
}
