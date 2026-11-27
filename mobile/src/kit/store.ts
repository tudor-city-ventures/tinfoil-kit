// What's on this phone and what the person chose, kept in one JSON file in the app's documents.
import { File, Paths } from "expo-file-system";
import { useSyncExternalStore } from "react";

export type Status = "queued" | "downloading" | "ready" | "failed";
export type Item = { status: Status; received: number; total: number; edition?: string; error?: string };
export type State = {
  welcomed: boolean; // past the first screen
  cellular: boolean; // big downloads may use mobile data: off until the person turns it on
  items: Record<string, Item>;
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
    update(id: string, item: Partial<Item>) {
      const now = state.items[id];
      if (now) set({ ...state, items: { ...state.items, [id]: { ...now, ...item } } });
    },
    remove(id: string) {
      const { [id]: _, ...items } = state.items;
      set({ ...state, items });
    },
    setCellular(cellular: boolean) {
      set({ ...state, cellular });
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
