// A book from a file, such as one another phone sent with AirDrop or Quick Share, or one saved in Files: checked, named
// and filed in the library like a downloaded one. Only the app's own books: the name a book gives itself says which.
import { Directory, Paths } from "expo-file-system";
import { useEffect, useState, useSyncExternalStore } from "react";
import { Platform } from "react-native";

import { addBook, adding, moveBook } from "../../modules/kit-files";

import { closeBook, openBook } from "@/kit/books";
import { catalog } from "@/kit/catalog";
import { libraryPath, removeBook } from "@/kit/downloads";
import { size } from "@/kit/format";
import { store } from "@/kit/store";
import type { Zim } from "@/kit/zim";

const SPARE = 5e8; // room a copy leaves free on the phone, as a download does
const ZIM = /^(.+)_(\d{4}-\d{2})\.zim$/; // Kiwix's file names: wikipedia_en_medicine_mini_2026-10.zim

const byId = new Map(catalog.map((b) => [b.id, b]));
const dateOf = (file: string) => ZIM.exec(file)?.[2] ?? "";

export type Outcome =
  | { added: string } // the book's id
  | { have: string } // on the phone already, as new or newer
  | { refused: "not-a-book" | "not-ours" | "damaged" | "space" | "failed"; bytes?: number };

// Which of the app's books a file is, by the name the book gives itself (with its edition, for books in several), else
// by its file name, and Kiwix's name for its file
export function identify(zim: Zim, name: string): { id: string; file: string } | undefined {
  const meta = (key: string) => zim.metadata(key)?.trim() || undefined;
  const own = meta("Name");
  const flavour = meta("Flavour");
  const named = ZIM.exec(name);
  for (const edition of [own && flavour && `${own}_${flavour}`, own, named?.[1]]) {
    const book = edition && catalog.find((b) => b.editions.includes(edition));
    if (!book) continue;
    const date = named?.[1] === edition ? named[2] : /^\d{4}-\d{2}/.exec(meta("Date") ?? "")?.[0];
    return { id: book.id, file: date ? `${edition}_${date}.zim` : `${edition}.zim` };
  }
  return undefined;
}

// What to tell the person
export function describe(o: Outcome): [string, string] {
  const title = (id: string) => byId.get(id)?.title ?? "The book";
  if ("added" in o) return [`${title(o.added)} is on this phone`, "It's in your library, ready without the internet."];
  if ("have" in o)
    return [`${title(o.have)} is on this phone already`, "The copy here is as new as that one, or newer."];
  if (o.refused === "not-a-book")
    return ["That file isn't a book", "Tinfoil Kit takes its books as ZIM files, like the ones another phone sends."];
  if (o.refused === "not-ours")
    return ["That book isn't one of Tinfoil Kit's", "Tinfoil Kit takes the books in Get more."];
  if (o.refused === "damaged")
    return ["That book came through damaged", "It was cut short or changed on the way. Ask for it again."];
  if (o.refused === "space")
    return ["Not enough free space", `The book needs ${size(o.bytes ?? 0)}, and room to spare.`];
  return ["That book couldn't be added", "Try again."];
}

let current: string | undefined; // the file being added
const listeners = new Set<() => void>();

function set(name: string | undefined) {
  current = name;
  listeners.forEach((l) => l());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

// The file being added, if one is, and how much of it is checked
export function useAdding(): { name: string; percent: number } | undefined {
  const name = useSyncExternalStore(subscribe, () => current);
  const [seen, setSeen] = useState<{ name: string; percent: number }>();
  useEffect(() => {
    if (!name) return;
    const timer = setInterval(() => {
      const { done, total } = adding();
      setSeen({ name, percent: total ? Math.floor((100 * done) / total) : 0 });
    }, 500);
    return () => clearInterval(timer);
  }, [name]);
  return name ? { name, percent: seen?.name === name ? seen.percent : 0 } : undefined;
}

function clear(folder: string) {
  try {
    const d = new Directory(`file://${folder}`);
    if (d.exists) d.delete();
  } catch {} // tried again next time
}

// What's left of a book the app was closed while adding
export function startAdding() {
  if (!current) clear(`${libraryPath()}/adding`);
}

const loaded = () =>
  new Promise<void>((resolve) => {
    if (store.loaded()) return resolve();
    const stop = store.subscribe(() => {
      if (!store.loaded()) return;
      stop();
      resolve();
    });
  });

// Adds a book from a file: `from` is where the phone has it, a file or, on Android, a document another app hands over
export async function addFile(from: string, name: string, bytes?: number): Promise<Outcome> {
  if (current) return { refused: "failed" }; // one at a time
  set(name);
  try {
    await loaded();
    return await take(from, name, bytes);
  } catch (e) {
    console.error(e);
    return { refused: "failed" };
  } finally {
    set(undefined);
  }
}

async function take(from: string, name: string, bytes?: number): Promise<Outcome> {
  const library = libraryPath();
  // Android copies it, which takes room; iOS moves its own copy
  if (Platform.OS === "android" && bytes && Paths.availableDiskSpace < bytes + SPARE)
    return { refused: "space", bytes };
  const folder = `${library}/adding`;
  clear(folder);
  const incoming = `${folder}/${Date.now()}.zim`;
  let got: number;
  try {
    got = await addBook(from, incoming);
  } catch (e) {
    const code = (e as { code?: string }).code;
    return { refused: code === "ERR_NOT_A_BOOK" ? "not-a-book" : code === "ERR_DAMAGED" ? "damaged" : "failed" };
  }
  let found: ReturnType<typeof identify>;
  try {
    found = identify(openBook(incoming), name);
  } catch {
    found = undefined; // a whole file, but not a book this app can read
  } finally {
    closeBook(incoming);
  }
  if (!found) {
    clear(folder);
    return { refused: "not-ours" };
  }
  const it = store.get().items[found.id];
  if (it?.status === "ready" && it.file && dateOf(found.file) <= dateOf(it.file)) {
    clear(folder);
    return { have: found.id };
  }
  if (it && it.status !== "ready") removeBook(found.id); // its download stops: this takes its place
  try {
    moveBook(incoming, `${library}/${found.file}`);
  } catch {
    clear(folder);
    return { refused: "failed" };
  }
  if (it?.status === "ready") removeBook(found.id); // the older copy, once this one is in
  store.ready(found.id, found.file, got);
  return { added: found.id };
}
