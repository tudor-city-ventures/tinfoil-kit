import { beforeEach, expect, jest, test } from "@jest/globals";
import { strFromU8, strToU8 } from "fflate";

import {
  ASSETS,
  BUILD_BASE,
  BUILDS,
  createMaps,
  latest,
  mapStyle,
  NOT_ON_WIFI,
  OFFLINE,
  STYLE_FILES,
  type MapPhone,
} from "./maps";
import { fileUrl, FORGOTTEN, NEW_CODE } from "./home";
import { place } from "./places";
import { tileId, wanted, type Area } from "./pmtiles";
import { createStore, type State } from "./store";
import { tile, world } from "./test-map";

const WORLD_MAP = world(7, { leafSize: 300, gzip: true });
const OPTIONS = { world: 3, detail: 7, part: 100, wait: async () => {} };
const BUILD = `${BUILD_BASE}/20261127.pmtiles`;
const KIT = { name: "Kitchen Mac", address: "192.168.1.20:8000", code: "48217736" };
const KIT_MAP = {
  path: "downloads/maps/tiles/basemap.pmtiles",
  day: "20261120",
  assets: "downloads/maps/viewer/basemaps-assets/2026-11-01/basemaps-assets-1a2b3c",
};

const coded = (code: string) => Object.assign(new Error(code), { code });
const settle = () => new Promise((r) => setTimeout(r, 0));

async function until(done: () => boolean) {
  for (let i = 0; i < 200 && !done(); i++) await settle();
  expect(done()).toBe(true);
}

// The phone, with the internet as tests want it: Protomaps' builds and the fonts and icons, all in memory
function fakePhone(files = new Map<string, Uint8Array>()) {
  const sources = new Map<string, Uint8Array>([
    [BUILD, WORLD_MAP],
    ...STYLE_FILES.map((f): [string, Uint8Array] => [`${ASSETS}/${encodeURI(f)}`, strToU8(f)]),
    // the kit at home's map, cut from the same world map, and its fonts and icons
    [fileUrl(KIT, KIT_MAP.path), WORLD_MAP],
    ...STYLE_FILES.map((f): [string, Uint8Array] => [fileUrl(KIT, `${KIT_MAP.assets}/${f}`), strToU8(f)]),
  ]);
  const t = {
    files,
    sources,
    builds: [
      { key: "20261126.pmtiles", version: "4.13.0" },
      { key: "20261127.pmtiles", version: "4.13.1" },
      { key: "20261128.pmtiles", version: "5.0.0" }, // layers the kit page's style isn't for
    ] as unknown,
    wifi: true,
    online: true,
    free: 1e12,
    awake: false,
    stops: 0,
    allow: Infinity, // parts that go through before the rest wait
    damage: (_k: number, _offset: number) => false, // parts that land as zeros, by count from the first or offset
    count: 0,
    held: [] as { go: () => void; stop: (e: unknown) => void }[],
    requests: [] as {
      url: string;
      cellular: boolean;
      headers?: Record<string, string>;
      offset?: number;
      at?: number;
    }[],
    kitCode: KIT.code, // the kit at home's, now
    release() {
      t.allow = Infinity;
      for (const h of t.held.splice(0)) h.go();
    },
    fail(e: unknown) {
      for (const h of t.held.splice(0)) h.stop(e);
    },
  };
  const phone: MapPhone = {
    dir: "/maps",
    async json(url) {
      if (url !== BUILDS) throw coded("ERR_HTTP_404");
      return t.builds;
    },
    async download({ url, path, cellular, headers, offset, length, at }) {
      t.requests.push({ url, cellular, headers, offset, at });
      if (url.startsWith(`http://${KIT.address}/`) && headers?.Authorization !== `Bearer ${t.kitCode}`)
        throw coded("ERR_HTTP_401");
      if (!t.online) throw coded(OFFLINE);
      if (!t.wifi && !cellular) throw coded(NOT_ON_WIFI);
      const src = t.sources.get(url);
      if (!src) throw coded("ERR_HTTP_404");
      let bytes = offset === undefined ? src : src.slice(offset, offset + (length ?? 0));
      if (at === undefined) {
        files.set(path, bytes.slice());
        return bytes.length;
      }
      const k = t.count++;
      if (k >= t.allow) await new Promise<void>((go, stop) => t.held.push({ go, stop }));
      if (t.damage(k, offset ?? 0)) bytes = new Uint8Array(bytes.length);
      const was = files.get(path);
      if (!was) throw coded("ERR_GONE");
      const out = new Uint8Array(Math.max(was.length, at + bytes.length));
      out.set(was);
      out.set(bytes, at);
      files.set(path, out);
      return bytes.length;
    },
    stop() {
      t.stops++;
      t.fail(coded("ERR_STOPPED"));
    },
    list: () => [...files.keys()].filter((p) => /^\/maps\/[^/]+$/.test(p)).map((p) => p.slice(6)),
    read: async (path, at, length) => (files.get(path) ?? new Uint8Array(0)).slice(at, at + length),
    write: async (path, bytes) => void files.set(path, bytes.slice()),
    size: (path) => files.get(path)?.length ?? -1,
    text: (path) => (files.has(path) ? strFromU8(files.get(path)!) : null),
    save: (path, text) => void files.set(path, strToU8(text)),
    move(from, to) {
      const f = files.get(from);
      if (!f) throw new Error(`No ${from}`);
      files.set(to, f);
      files.delete(from);
    },
    remove: (path) => void files.delete(path),
    free: () => t.free,
    awake: (on) => void (t.awake = on),
  };
  return { phone, t };
}

async function newStore(state: Partial<State> = {}) {
  let text = JSON.stringify(state);
  const store = createStore({ read: async () => text, write: async (s) => void (text = s) });
  await store.load();
  return { store, saved: () => text };
}

// The map has the world's tiles for its area and nothing else
function expectMap(file: Uint8Array | undefined, id: string) {
  expect(file).toBeDefined();
  const area: Area = { world: OPTIONS.world, detail: OPTIONS.detail, boxes: [place(id)!.bbox] };
  const want = new Set(wanted(area).flatMap(([a, b]) => Array.from({ length: b - a }, (_, i) => a + i)));
  for (const n of want) expect(tile(file!, n)).toEqual(tile(WORLD_MAP, n));
  expect(want.has(tileId(7, 100, 40))).toBe(false); // the middle of the Atlantic, in street detail
  expect(tile(file!, tileId(7, 100, 40))).toBeUndefined();
}

const leftovers = (files: Map<string, Uint8Array>) =>
  [...files.keys()].filter((p) => /\/(next|read)[-.][^/]*$/.test(p) || p.endsWith(".part"));

let now = 0;
beforeEach(() => {
  jest.spyOn(Date, "now").mockImplementation(() => (now += 1000)); // every part's progress is saved
});

test("a place's map: the world's tiles for the area, the kit page's fonts and icons, the old map kept until then", async () => {
  const { phone, t } = fakePhone();
  t.files.set("/maps/us-rhode-island-20261001.pmtiles", strToU8("the old map"));
  const { store } = await newStore({ map: { place: "us/rhode-island", file: "us-rhode-island-20261001.pmtiles" } });
  const maps = createMaps(store, phone, OPTIONS);
  maps.start();
  t.allow = 3;
  store.getMap("us/alabama");
  await until(() => t.held.length > 0);
  expect(store.get().mapDownload).toMatchObject({ place: "us/alabama", status: "downloading" });
  expect(store.get().mapDownload!.received).toBeLessThan(store.get().mapDownload!.total);
  expect(t.files.has("/maps/us-rhode-island-20261001.pmtiles")).toBe(true);
  expect(t.awake).toBe(true);

  t.release();
  await until(() => !store.get().mapDownload);
  expect(store.get().map).toEqual({ place: "us/alabama", file: "us-alabama-20261127.pmtiles" });
  expectMap(t.files.get("/maps/us-alabama-20261127.pmtiles"), "us/alabama");
  expect(t.files.has("/maps/us-rhode-island-20261001.pmtiles")).toBe(false);
  for (const f of STYLE_FILES) expect(strFromU8(t.files.get(`/maps/style/${f}`)!)).toBe(f);
  expect(leftovers(t.files)).toEqual([]);
  expect(t.awake).toBe(false);
  expect(t.requests.every((r) => !r.cellular)).toBe(true);
  // the newest build of the layers the style is for
  expect(t.requests.filter((r) => r.url.startsWith(BUILD_BASE)).every((r) => r.url === BUILD)).toBe(true);
});

test("mobile data only once the person allows it, and not a byte more once they don't", async () => {
  const { phone, t } = fakePhone();
  t.wifi = false;
  const { store } = await newStore();
  const maps = createMaps(store, phone, OPTIONS);
  maps.start();
  store.getMap("us/alabama");
  await until(() => store.get().mapDownload?.waiting === "wifi");
  expect(t.requests.length).toBeGreaterThan(0);
  expect(t.requests.every((r) => !r.cellular)).toBe(true);

  t.allow = 3;
  store.setCellular(true);
  await until(() => t.held.length > 0);
  expect(store.get().mapDownload).toMatchObject({ status: "downloading", waiting: undefined });
  expect(t.requests.filter((r) => r.cellular).length).toBeGreaterThan(3);

  const before = t.requests.length;
  store.setCellular(false);
  expect(t.stops).toBe(1); // the parts under way stop at once
  await until(() => store.get().mapDownload?.waiting === "wifi");
  expect(t.requests.slice(before).every((r) => !r.cellular)).toBe(true);

  t.release();
  t.wifi = true;
  maps.network();
  await until(() => !store.get().mapDownload);
  expectMap(t.files.get("/maps/us-alabama-20261127.pmtiles"), "us/alabama");
  expect(t.requests.slice(before).every((r) => !r.cellular)).toBe(true);
});

test("offline, it waits for the internet; away from the screen, a failure waits for the app to be back", async () => {
  const { phone, t } = fakePhone();
  t.online = false;
  const { store } = await newStore();
  const maps = createMaps(store, phone, OPTIONS);
  maps.start();
  store.getMap("us/alabama");
  await until(() => store.get().mapDownload?.waiting === "internet");

  t.online = true;
  t.allow = 2;
  maps.network();
  await until(() => t.held.length > 0);
  maps.shown(false);
  t.fail(coded("ERR_HTTP_500"));
  await until(() => store.get().mapDownload?.waiting === "internet");
  expect(store.get().mapDownload?.status).toBe("downloading");
  t.allow = Infinity;
  maps.network(); // nothing while it's away
  await settle();
  expect(store.get().mapDownload?.waiting).toBe("internet");

  maps.shown(true);
  await until(() => !store.get().mapDownload);
  expect(store.get().map?.place).toBe("us/alabama");
});

test("it picks up where it left off when the app is next open", async () => {
  const first = fakePhone();
  first.t.allow = 5;
  const one = await newStore();
  createMaps(one.store, first.phone, OPTIONS).start();
  one.store.getMap("us/alabama");
  await until(() => first.t.held.length === 4);
  // the app closes, with parts under way
  const next = JSON.parse(strFromU8(first.t.files.get("/maps/next.json")!));
  expect(next.done).toHaveLength(5);
  first.t.files.set("/maps/read-old.bin", new Uint8Array(9)); // left from a stopped plan

  const { phone, t } = fakePhone(first.t.files);
  const two = await newStore(JSON.parse(one.saved()));
  createMaps(two.store, phone, OPTIONS).start();
  await until(() => !two.store.get().mapDownload);
  expect(t.requests.filter((r) => r.url === BUILD && r.at === undefined)).toEqual([]); // no planning again
  expect(t.requests.filter((r) => r.at !== undefined)).toHaveLength(next.parts.length - 5);
  expectMap(t.files.get("/maps/us-alabama-20261127.pmtiles"), "us/alabama");
  expect(leftovers(t.files)).toEqual([]);
});

test("another place, or stopping: the parts under way stop, and their files go", async () => {
  const { phone, t } = fakePhone();
  const { store } = await newStore();
  const maps = createMaps(store, phone, OPTIONS);
  maps.start();
  t.allow = 2;
  store.getMap("us/alabama");
  await until(() => t.held.length > 0);
  store.getMap("us/rhode-island");
  expect(t.stops).toBe(1);
  t.release();
  await until(() => !store.get().mapDownload);
  expect(store.get().map?.place).toBe("us/rhode-island");
  expectMap(t.files.get("/maps/us-rhode-island-20261127.pmtiles"), "us/rhode-island");
  expect(leftovers(t.files)).toEqual([]);

  t.allow = t.count + 2;
  store.getMap("italy");
  await until(() => t.held.length > 0);
  store.stopMap();
  await until(() => !t.awake);
  expect(t.stops).toBe(2);
  expect(store.get().map?.place).toBe("us/rhode-island");
  expect(leftovers(t.files)).toEqual([]);
  expect([...t.files.keys()].filter((p) => p.endsWith(".pmtiles"))).toEqual(["/maps/us-rhode-island-20261127.pmtiles"]);
});

test("a world map that's gone by the time it carries on: it starts over from the newest", async () => {
  const first = fakePhone();
  first.t.allow = 3;
  const one = await newStore();
  createMaps(one.store, first.phone, OPTIONS).start();
  one.store.getMap("us/alabama");
  await until(() => first.t.held.length > 0);

  const { phone, t } = fakePhone(first.t.files);
  t.sources.delete(BUILD);
  t.sources.set(`${BUILD_BASE}/20261129.pmtiles`, WORLD_MAP);
  t.builds = [{ key: "20261129.pmtiles", version: "4.13.2" }];
  const two = await newStore(JSON.parse(one.saved()));
  createMaps(two.store, phone, OPTIONS).start();
  await until(() => !two.store.get().mapDownload);
  expect(two.store.get().map?.file).toBe("us-alabama-20261129.pmtiles");
  expectMap(t.files.get("/maps/us-alabama-20261129.pmtiles"), "us/alabama");
  expect(leftovers(t.files)).toEqual([]);
});

test("a part that lands damaged comes again; damaged twice, the map fails and says so", async () => {
  const { phone, t } = fakePhone();
  t.damage = (k) => k === 2;
  const { store } = await newStore();
  const maps = createMaps(store, phone, OPTIONS);
  maps.start();
  store.getMap("us/alabama");
  await until(() => !store.get().mapDownload);
  expectMap(t.files.get("/maps/us-alabama-20261127.pmtiles"), "us/alabama");

  let target: number | undefined;
  t.damage = (_k, offset) => (target ??= offset) === offset; // the first part, every time
  store.getMap("us/rhode-island");
  await until(() => store.get().mapDownload?.status === "failed");
  expect(store.get().mapDownload?.error).toBe("The map came through damaged");
  expect(store.get().map?.place).toBe("us/alabama");

  t.damage = () => false; // trying again checks what's there, and downloads only that part
  const before = t.requests.length;
  store.getMap("us/rhode-island");
  await until(() => !store.get().mapDownload);
  expect(t.requests.slice(before).filter((r) => r.at !== undefined)).toEqual([
    expect.objectContaining({ offset: target }),
  ]);
  expect(t.requests.slice(before).filter((r) => r.url === BUILD && r.at === undefined)).toEqual([]);
  expectMap(t.files.get("/maps/us-rhode-island-20261127.pmtiles"), "us/rhode-island");
});

test("not enough free space: it says how much the map needs, and downloads none of it", async () => {
  const { phone, t } = fakePhone();
  t.free = 1e6;
  const { store } = await newStore();
  createMaps(store, phone, OPTIONS).start();
  store.getMap("us/alabama");
  await until(() => store.get().mapDownload?.status === "failed");
  expect(store.get().mapDownload?.error).toMatch(/^Not enough free space for its \d+ MB$/);
  expect(t.requests.filter((r) => r.at !== undefined)).toEqual([]);
  expect(leftovers(t.files)).toEqual([]);
});

test("fonts and icons: one that fails is tried again, and one that's gone stops the map until it's back", async () => {
  const { phone, t } = fakePhone();
  const font = STYLE_FILES[300];
  const url = `${ASSETS}/${encodeURI(font)}`;
  const download = phone.download;
  let fails = 1;
  phone.download = (o) => (o.url === url && fails-- > 0 ? Promise.reject(coded("ERR_HTTP_500")) : download(o));
  const { store } = await newStore();
  createMaps(store, phone, OPTIONS).start();
  store.getMap("us/rhode-island");
  await until(() => !store.get().mapDownload);
  expect(fails).toBe(-1);
  expect(strFromU8(t.files.get(`/maps/style/${font}`)!)).toBe(font);

  t.files.delete(`/maps/style/${font}`);
  t.sources.delete(url);
  store.getMap("us/alabama");
  await until(() => store.get().mapDownload?.status === "failed");
  expect(store.get().mapDownload?.error).toBe("ERR_HTTP_404");
  t.sources.set(url, strToU8(font));
  store.getMap("us/alabama");
  await until(() => !store.get().mapDownload);
  expectMap(t.files.get("/maps/us-alabama-20261127.pmtiles"), "us/alabama");
  expect(leftovers(t.files)).toEqual([]);
});

test("the newest world map of the layers the kit page's style is for", () => {
  expect(
    latest([
      { key: "20261127.pmtiles", version: "4.13.1" },
      { key: "20261128.pmtiles", version: "5.0.0" },
      { key: "20261126.pmtiles" },
      { key: "20261129.json" },
    ]),
  ).toBe("20261127.pmtiles");
  expect(() => latest({ error: "busy" })).toThrow("Protomaps lists no world map at the moment");
});

test("the map's style: the file on the phone, the fonts and icons beside it, labels in the place's own language", () => {
  const style = mapStyle("/docs/maps", "italy-20261127.pmtiles", ["xx", "it"]);
  expect(style.sources.protomaps).toMatchObject({
    type: "vector",
    url: "pmtiles://file:///docs/maps/italy-20261127.pmtiles",
  });
  expect(style.glyphs).toBe("file:///docs/maps/style/fonts/{fontstack}/{range}.pbf");
  expect(style.sprite).toBe("file:///docs/maps/style/sprites/v4/light");
  expect(STYLE_FILES).toContain("sprites/v4/light@2x.png");
  expect(JSON.stringify(style.layers)).toContain('"name:it"');
  expect(JSON.stringify(mapStyle("/d", "x.pmtiles", ["xx"]).layers)).not.toContain('"name:xx"'); // one Protomaps lacks
});

const fromKit = (r: { url: string; cellular: boolean; headers?: Record<string, string> }) =>
  r.url.startsWith(`http://${KIT.address}/data/files/`) &&
  !r.cellular &&
  r.headers?.Authorization === "Bearer 48217736";

test("a map cut from the kit at home's: its file, fonts and icons, over its Wi-Fi only, with its code", async () => {
  const { phone, t } = fakePhone();
  t.sources.forEach((_, url) => url.startsWith(fileUrl(KIT, "")) || t.sources.delete(url)); // no internet
  const { store } = await newStore({ home: KIT, cellular: true });
  createMaps(store, phone, OPTIONS).start();
  store.getMap("us/alabama", KIT_MAP);
  await until(() => !store.get().mapDownload);
  expect(store.get().map).toEqual({ place: "us/alabama", file: "us-alabama-20261120.pmtiles" });
  expectMap(t.files.get("/maps/us-alabama-20261120.pmtiles"), "us/alabama");
  for (const f of STYLE_FILES) expect(strFromU8(t.files.get(`/maps/style/${f}`)!)).toBe(f);
  expect(t.requests.length).toBeGreaterThan(STYLE_FILES.length);
  expect(t.requests.every(fromKit)).toBe(true); // mobile data allowed, yet the kit's over its Wi-Fi
  expect(leftovers(t.files)).toEqual([]);
});

test("a map from the kit says when its code has changed, or the kit was forgotten", async () => {
  const { phone, t } = fakePhone();
  t.kitCode = "11112222";
  const { store } = await newStore({ home: KIT });
  createMaps(store, phone, OPTIONS).start();
  store.getMap("us/alabama", KIT_MAP);
  await until(() => store.get().mapDownload?.status === "failed");
  expect(store.get().mapDownload?.error).toBe(NEW_CODE);

  store.setHome(undefined);
  store.getMap("us/alabama", KIT_MAP);
  await until(() => store.get().mapDownload?.status === "failed");
  expect(store.get().mapDownload?.error).toBe(FORGOTTEN);
});

test("switching a place's map between Protomaps and the kit starts it again from the other", async () => {
  const { phone, t } = fakePhone();
  const { store } = await newStore({ home: KIT });
  createMaps(store, phone, OPTIONS).start();
  t.allow = 3;
  store.getMap("us/alabama");
  await until(() => t.held.length > 0);
  const before = t.requests.length;
  store.getMap("us/alabama", KIT_MAP);
  t.release();
  await until(() => !store.get().mapDownload);
  expect(store.get().map).toEqual({ place: "us/alabama", file: "us-alabama-20261120.pmtiles" });
  expectMap(t.files.get("/maps/us-alabama-20261120.pmtiles"), "us/alabama");
  // after the switch, only the kit: its map planned afresh, not Protomaps' parts with its code
  expect(
    t.requests
      .slice(before)
      .filter((r) => r.at !== undefined)
      .every(fromKit),
  ).toBe(true);
  expect(leftovers(t.files)).toEqual([]);
});
