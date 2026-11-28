// This phone shared like a kit at home, for another phone on the Wi-Fi to copy its books and map: the listing a kit
// gives (home.ts), with the books under library/, the map under maps/, and the fonts and icons it's drawn with beside
// it. The phone answers only with its code, and serves only the files the listing names (modules/kit-files).
import { catalog } from "./catalog";
import type { KitListing, KitMap, KitPart } from "./home";
import { place } from "./places";
import type { State } from "./store";

export const STYLE = "maps/style"; // the map's fonts and icons, in the listing

export type Shared = { listing: KitListing; files: Record<string, string>; folders: Record<string, string> };

// Where this phone keeps its books and maps, and a file's size there (-1 when it's gone)
export type Here = { library: string; maps: string; size(path: string): number };

// What this phone shares: its books that are ready, and its map
export function shared(name: string, state: Pick<State, "items" | "map">, here: Here): Shared {
  const files: Record<string, string> = {};
  const books: KitPart[] = [];
  for (const b of catalog) {
    const it = state.items[b.id];
    if (it?.status !== "ready" || !it.file) continue;
    const local = `${here.library}/${it.file}`;
    const bytes = here.size(local);
    if (bytes < 0) continue;
    const path = `library/${it.file}`;
    files[path] = local;
    const file = { path, bytes, ...(it.sha256 && { sha256: it.sha256 }) };
    books.push({ id: b.id, title: b.title, group: b.group, why: b.why, files: [file] });
  }
  let map: KitMap | null = null;
  const p = state.map && place(state.map.place);
  const local = state.map && `${here.maps}/${state.map.file}`;
  if (state.map && p && local && here.size(local) >= 0) {
    const path = `maps/${state.map.file}`;
    files[path] = local;
    const day = /-(\d{8})\.pmtiles$/.exec(state.map.file)?.[1];
    map = {
      id: "map",
      title: `Map of ${p.name}`,
      group: "Maps",
      why: "",
      files: [{ path, bytes: here.size(local) }],
      areas: [p.bbox], // the place it has in street detail
      ...(day && { day }),
      assets: STYLE,
    };
  }
  const folders: Record<string, string> = map ? { [STYLE]: `${here.maps}/style` } : {};
  return { listing: { name, phone: true, books, map }, files, folders };
}
