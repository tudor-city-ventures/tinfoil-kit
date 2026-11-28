// The places a map can be of: the kit's "Where do you live?" list (kit/tools/regions.json, copied beside the website's
// kit.json), each with its box and home.
import regionsJson from "../../../site/regions.json";

import type { Box } from "@/kit/pmtiles";

export type Place = {
  id: string; // the kit's name for it, e.g. us/alabama
  name: string;
  group: string; // part of the world
  bbox: Box;
  home: { label: string; lat: number; lon: number };
  also: string[]; // other names people know it by
};

type Region = Omit<Place, "bbox" | "also"> & { bbox: number[]; also?: string[] };

export const places: Place[] = (regionsJson.regions as Region[]).map(
  ({ id, name, group, bbox: [w, s, e, n], home, also }) => ({
    id,
    name,
    group,
    bbox: [w, s, e, n],
    home,
    also: also ?? [],
  }),
);

const byId = new Map(places.map((p) => [p.id, p]));

export function place(id: string): Place | undefined {
  return byId.get(id);
}

// Places whose name, or another name for them, has a word starting with what was typed: "new" finds New York and
// New Zealand, "uk" the United Kingdom.
export function findPlaces(typed: string): Place[] {
  const words = typed.toLowerCase().trim().split(/\s+/).filter(Boolean);
  if (!words.length) return places;
  const starts = (text: string, word: string) =>
    text
      .toLowerCase()
      .split(/[\s,()/-]+/)
      .some((w) => w.startsWith(word));
  return places.filter((p) =>
    words.every((word) => [p.name, ...p.also].some((name) => starts(name, word) || name.toLowerCase() === word)),
  );
}
