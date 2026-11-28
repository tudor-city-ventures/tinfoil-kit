// What's on this phone and what the person chose, kept in one JSON file in the app's documents.
import { File, Paths } from "expo-file-system";
import { useSyncExternalStore } from "react";

export type Status = "queued" | "downloading" | "checking" | "ready" | "failed";
export type Item = {
  status: Status;
  received: number;
  total: number;
  file?: string; // Kiwix's file, e.g. wikipedia_en_medicine_mini_2026-10.zim
  sha256?: string; // what Kiwix says it should be
  task?: string; // the phone's download of it
  error?: string;
};
// A map being downloaded: of a new place, or the same place from a newer world map
export type MapDownload = {
  place: string; // an id from places.ts
  status: "queued" | "planning" | "downloading" | "checking" | "failed";
  received: number;
  total: number;
  waiting?: "wifi" | "internet"; // until the phone is on Wi-Fi, or online again
  error?: string;
};
export type State = {
  welcomed: boolean; // past the first screen
  cellular: boolean; // big downloads may use mobile data: off until the person turns it on
  items: Record<string, Item>;
  map?: { place: string; file: string }; // the map on this phone, a file in the maps folder
  mapDownload?: MapDownload;
};

export type Storage = { read(): Promise<string | null>; write(text: string): Promise<void> };

const initial: State = { welcomed: false, cellular: false, items: {} };

export function createStore(storage: Storage) {
  let state: State = initial;
  let loaded = false;
  const listeners = new Set<() => void>();

  function set(next: State) {
    state = next;
    listeners.forEach((l) => l());
    storage.write(JSON.stringify(state)).catch(() => {}); // the next change writes it again
  }

  function update(id: string, item: Partial<Item>) {
    const now = state.items[id];
    if (now) set({ ...state, items: { ...state.items, [id]: { ...now, ...item } } });
  }

  return {
    get: () => state,
    loaded: () => loaded,
    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    async load() {
      try {
        const text = await storage.read();
        if (text) state = { ...initial, ...JSON.parse(text) };
      } catch {} // unreadable: start over rather than not start
      loaded = true;
      listeners.forEach((l) => l());
    },
    welcome(ids: string[]) {
      const items = { ...state.items };
      for (const id of ids) items[id] ??= { status: "queued", received: 0, total: 0 };
      set({ ...state, welcomed: true, items });
    },
    queue(id: string) {
      if (state.items[id]) return;
      set({ ...state, items: { ...state.items, [id]: { status: "queued", received: 0, total: 0 } } });
    },
    update,
    retry(id: string) {
      if (state.items[id]?.status === "failed") update(id, { status: "queued", received: 0, error: undefined });
    },
    remove(id: string) {
      const { [id]: _, ...items } = state.items;
      set({ ...state, items });
    },
    setCellular(cellular: boolean) {
      set({ ...state, cellular });
    },
    getMap(place: string) {
      set({ ...state, mapDownload: { place, status: "queued", received: 0, total: 0 } });
    },
    updateMap(m: Partial<MapDownload>) {
      if (state.mapDownload) set({ ...state, mapDownload: { ...state.mapDownload, ...m } });
    },
    mapReady(place: string, file: string) {
      set({ ...state, map: { place, file }, mapDownload: undefined });
    },
    stopMap() {
      set({ ...state, mapDownload: undefined });
    },
  };
}

export type Store = ReturnType<typeof createStore>;

function fileStorage(): Storage {
  const file = () => new File(Paths.document, "kit.json");
  return {
    read: async () => (file().exists ? file().text() : null),
    write: async (text) => file().write(text),
  };
}

export const store = createStore(fileStorage());

export function useKit(): State {
  return useSyncExternalStore(store.subscribe, store.get);
}

export function useLoaded(): boolean {
  return useSyncExternalStore(store.subscribe, store.loaded);
}
