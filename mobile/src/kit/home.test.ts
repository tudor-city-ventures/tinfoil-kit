import { expect, jest, test } from "@jest/globals";

import { catalog } from "./catalog";
import {
  cleanCode,
  fileUrl,
  KitError,
  kitMapFrom,
  kitPlaces,
  listKit,
  pageUrl,
  phoneBook,
  readAddress,
  type KitMap,
  type KitPart,
} from "./home";
import { place } from "./places";

const kit = { name: "Kitchen Mac", address: "192.168.1.20:8000", code: "48217736" };
let mockNetwork = "WIFI";
jest.mock("expo-network", () => ({
  NetworkStateType: { CELLULAR: "CELLULAR", WIFI: "WIFI" },
  getNetworkStateAsync: async () => ({ type: mockNetwork }),
}));

test("the kit's address as typed, or the link from Share with family with its code", () => {
  expect(readAddress("192.168.1.20")).toEqual({ address: "192.168.1.20:8000" });
  expect(readAddress(" 192.168.1.20:8001 ")).toEqual({ address: "192.168.1.20:8001" });
  expect(readAddress("kitchen.local")).toEqual({ address: "kitchen.local:8000" });
  expect(readAddress("http://192.168.1.20:8000/?code=4821%207736")).toEqual({
    address: "192.168.1.20:8000",
    code: "48217736",
  });
  expect(readAddress("Join my Wi-Fi")).toBeUndefined();
  expect(readAddress("https://example.com")).toBeUndefined(); // the kit is plain http, on the home network
  expect(readAddress("")).toBeUndefined();
  expect(cleanCode("4821 7736")).toBe("48217736");
});

test("the kit's files and page", () => {
  expect(fileUrl(kit, "downloads/library/a b.zim")).toBe(
    "http://192.168.1.20:8000/data/files/downloads/library/a%20b.zim",
  );
  expect(pageUrl(kit)).toBe("http://192.168.1.20:8000/?code=48217736");
});

const answer = (status: number, body?: unknown) =>
  (async () => new Response(body === undefined ? "" : JSON.stringify(body), { status })) as unknown as typeof fetch;

test("what the kit has, asked with its code, and what to do when that fails", async () => {
  const asked: [string, RequestInit | undefined][] = [];
  const listing = { name: "Kitchen Mac", books: [], map: null };
  const get = (async (url: string, init?: RequestInit) => {
    asked.push([url, init]);
    return new Response(JSON.stringify(listing), { status: 200 });
  }) as unknown as typeof fetch;
  expect(await listKit(kit, get)).toEqual(listing);
  expect(asked[0][0]).toBe("http://192.168.1.20:8000/data/files");
  expect(asked[0][1]?.headers).toEqual({ Authorization: "Bearer 48217736" });

  const problem = (get: typeof fetch) => listKit(kit, get).catch((e: KitError) => e.problem);
  expect(await problem(answer(401, { error: "this needs the kit's access code" }))).toBe("code");
  expect(await problem(answer(429))).toBe("tries");
  expect(await problem(answer(404, { error: "Nothing here." }))).toBe("old"); // a kit from before phones
  const offline = (async () => Promise.reject(new TypeError("Network request failed"))) as typeof fetch;
  expect(await problem(offline)).toBe("unreachable");
  const told = () => listKit(kit, offline).catch((e: KitError) => e.message);
  expect(await told()).not.toMatch(/mobile data/);
  mockNetwork = "CELLULAR"; // on a Wi-Fi without the internet, an Android phone may use mobile data instead
  expect(await told()).toMatch(/turn off mobile data while you copy/);
});

test("a kit's book is the phone's own, in whichever edition the kit has", () => {
  const wiki = catalog.find((b) => /^wikipedia_en_all_/.test(b.id))!;
  const part = (id: string): KitPart => ({ id, title: id, group: "", why: "", files: [] });
  expect(phoneBook(part(wiki.id))).toBe(wiki.id);
  expect(phoneBook(part("wikipedia_en_all_nopic"))).toBe(wiki.id);
  expect(phoneBook(part(catalog[0].id))).toBe(catalog[0].id);
  expect(phoneBook(part("someones_own_book"))).toBeUndefined();
});

test("the places whose map the phone can cut from the kit's: the kit's own, and the phone's own inside them", () => {
  const ny = place("us/new-york")!;
  const map = (areas: KitMap["areas"]): KitMap => ({
    id: "map",
    title: "Map",
    group: "Maps",
    why: "",
    files: [{ path: "downloads/maps/tiles/basemap.pmtiles", bytes: 4e9, sha256: "ab".repeat(32) }],
    areas,
    day: "20261120",
    assets: "downloads/maps/viewer/basemaps-assets/2026-11-01/basemaps-assets-1a2b3c",
  });
  expect(kitPlaces(map([ny.bbox])).map((p) => p.id)).toEqual(["us/new-york"]);
  // Connecticut's box is inside New York's, so the kit's map has all of it
  expect(kitPlaces(map([ny.bbox]), "us/connecticut").map((p) => p.id)).toEqual(["us/connecticut", "us/new-york"]);
  expect(kitPlaces(map([ny.bbox]), "us/alabama").map((p) => p.id)).toEqual(["us/new-york"]);
  expect(kitPlaces(map([]))).toEqual([]); // a kit from before phones could copy maps
  expect(kitPlaces(null)).toEqual([]);
  expect(kitMapFrom(map([ny.bbox]))).toEqual({
    path: "downloads/maps/tiles/basemap.pmtiles",
    day: "20261120",
    assets: "downloads/maps/viewer/basemaps-assets/2026-11-01/basemaps-assets-1a2b3c",
  });
  expect(kitMapFrom({ ...map(undefined), files: [] })).toBeUndefined();
});
