import { expect, test } from "@jest/globals";

import { catalog } from "./catalog";
import { kitMapFrom, kitPlaces, phoneBook, zimOf } from "./home";
import { place } from "./places";
import { shared, STYLE } from "./share";
import type { Item } from "./store";

const [first, second, third] = catalog;
const ready = (file: string, sha256?: string): Item => ({
  status: "ready",
  received: 7e7,
  total: 7e7,
  file,
  ...(sha256 && { sha256 }),
});
const items: Record<string, Item> = {
  [first.id]: ready(`${first.id}_2026-10.zim`, "ab".repeat(32)),
  [second.id]: { status: "downloading", received: 1, total: 9e7, file: `${second.id}_2026-10.zim` },
  [third.id]: ready(`${third.id}_2026-09.zim`), // its file is gone
};
const sizes = new Map([
  [`/docs/library/${first.id}_2026-10.zim`, 7e7],
  [`/docs/library/${second.id}_2026-10.zim`, 1],
  ["/docs/maps/us-alabama-20261127.pmtiles", 6e8],
]);
const here = { library: "/docs/library", maps: "/docs/maps", size: (p: string) => sizes.get(p) ?? -1 };

test("a phone shares its books that are ready and its map, and names nothing else", () => {
  const map = { place: "us/alabama", file: "us-alabama-20261127.pmtiles" };
  const { listing, files, folders } = shared("iPhone", { items, map }, here);
  expect(listing.name).toBe("iPhone");
  expect(listing.phone).toBe(true);
  expect(listing.books).toEqual([
    {
      id: first.id,
      title: first.title,
      group: first.group,
      why: first.why,
      files: [{ path: `library/${first.id}_2026-10.zim`, bytes: 7e7, sha256: "ab".repeat(32) }],
    },
  ]);
  expect(listing.map).toMatchObject({
    files: [{ path: "maps/us-alabama-20261127.pmtiles", bytes: 6e8 }],
    areas: [place("us/alabama")!.bbox],
    day: "20261127",
    assets: STYLE,
  });
  expect(files).toEqual({
    [`library/${first.id}_2026-10.zim`]: `/docs/library/${first.id}_2026-10.zim`,
    "maps/us-alabama-20261127.pmtiles": "/docs/maps/us-alabama-20261127.pmtiles",
  });
  expect(folders).toEqual({ [STYLE]: "/docs/maps/style" });

  // without a map, no fonts or icons either
  expect(shared("iPhone", { items }, here)).toMatchObject({ listing: { map: null }, folders: {} });
});

test("the other phone reads it as it reads a kit's: the same book, and the same place's map", () => {
  const map = { place: "us/alabama", file: "us-alabama-20261127.pmtiles" };
  const { listing } = shared("Pixel 9", { items, map }, here);
  const [part] = listing.books;
  expect(phoneBook(part)).toBe(first.id);
  expect(zimOf(part)).toEqual(part.files[0]);
  expect(kitPlaces(listing.map).map((p) => p.id)).toEqual(["us/alabama"]);
  expect(kitMapFrom(listing.map)).toEqual({ path: "maps/us-alabama-20261127.pmtiles", day: "20261127", assets: STYLE });
});
