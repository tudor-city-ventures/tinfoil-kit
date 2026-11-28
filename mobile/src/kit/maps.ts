// The map of where the person lives: their area of Protomaps' world map, cut out on the phone as the kit does it
// (pmtiles.ts), with the kit page's fonts and icons.
//
// A map downloads only while the app is open. It's parts of one 120 GB file, and after a dropped connection the
// phones' background downloaders ask for the rest of the file from where they stopped: here, the rest of the world.
// So the app asks for each part itself, a few at a time, over Wi-Fi unless the person allows mobile data, and picks
// up where it left off when it's next open.
import type { StyleSpecification } from "@maplibre/maplibre-react-native";
import { language_script_pairs, layers, namedFlavor } from "@protomaps/basemaps";
import { Directory, File, FileMode, Paths } from "expo-file-system";
import { activateKeepAwakeAsync, deactivateKeepAwake } from "expo-keep-awake";
import { addNetworkStateListener } from "expo-network";
import { AppState, Platform } from "react-native";

import { download, excludeFromBackup, stopDownloads } from "../../modules/kit-files";

import { size } from "@/kit/format";
import { place } from "@/kit/places";
import { head, plan } from "@/kit/pmtiles";
import { store as kitStore, type Store } from "@/kit/store";

export const WORLD = 7; // every place on earth up to this zoom: countries, towns, main roads
export const DETAIL = 15; // the area up to this zoom: every street, path and building, as the kit has it

export const BUILDS = process.env.EXPO_PUBLIC_PROTOMAPS_BUILDS || "https://build-metadata.protomaps.dev/builds.json";
export const BUILD_BASE = process.env.EXPO_PUBLIC_PROTOMAPS_BUILD_BASE || "https://build.protomaps.com";
export const ASSETS = process.env.EXPO_PUBLIC_BASEMAPS_ASSETS || "https://protomaps.github.io/basemaps-assets";

// The kit page's: fonts for its labels and its icons. Every range of each font, as the kit has, since a place's
// labels can be in any script: most ranges are empty, and all of them come to about 11 MB.
export const FONTS = ["Noto Sans Regular", "Noto Sans Medium", "Noto Sans Italic"];
export const STYLE_FILES = [
  ...FONTS.flatMap((f) => Array.from({ length: 256 }, (_, i) => `fonts/${f}/${i * 256}-${i * 256 + 255}.pbf`)),
  ...["light.json", "light.png", "light@2x.json", "light@2x.png"].map((s) => `sprites/v4/${s}`),
];

// The kit page's style for the map on this phone, with its labels in the place's own language where Protomaps has it
export function mapStyle(dir: string, file: string, langs: string[]): StyleSpecification {
  const known = new Set(language_script_pairs.map((p) => p.lang));
  return {
    version: 8,
    glyphs: `file://${dir}/style/fonts/{fontstack}/{range}.pbf`,
    sprite: `file://${dir}/style/sprites/v4/light`,
    sources: {
      protomaps: {
        type: "vector",
        url: `pmtiles://file://${dir}/${file}`,
        attribution: "© OpenStreetMap contributors, Protomaps",
      },
    },
    layers: layers("protomaps", namedFlavor("light"), { lang: langs.find((l) => known.has(l)) ?? "en" }),
  };
}

// The phone's errors
export const NOT_ON_WIFI = "ERR_NOT_ON_WIFI"; // only mobile data is there, and it isn't allowed
export const OFFLINE = "ERR_OFFLINE"; // no connection, or it dropped
const GONE = /^ERR_HTTP_(404|410|416)$/; // that day's world map is no longer there

// What this needs from the phone, so the tests can stand in for it.
export type MapPhone = {
  dir: string; // the folder maps go in, as a path
  json(url: string): Promise<unknown>;
  // A file on the internet, or `length` bytes of it from `offset`, into a new file on the phone, or at `at` into one
  // that's there already (it fails if it's gone). Resolves with how many bytes came.
  download(o: {
    url: string;
    path: string;
    cellular: boolean;
    offset?: number;
    length?: number;
    at?: number;
  }): Promise<number>;
  stop(): void; // every download under way
  list(): string[]; // the files in the maps folder, by name
  read(path: string, at: number, length: number): Promise<Uint8Array>;
  write(path: string, bytes: Uint8Array): Promise<void>; // a new file of these bytes
  size(path: string): number; // -1 when there's no such file
  text(path: string): string | null;
  save(path: string, text: string): void;
  move(from: string, to: string): void;
  remove(path: string): void;
  free(): number;
  awake(on: boolean): void; // keeps the screen on while a map downloads
};

// A map under way, saved beside it so it carries on when the app is next open
type Next = {
  place: string;
  file: string; // its name once it's done
  partial: string; // its name until then
  url: string; // the world map it's from, one day's
  head: number; // its bytes before the tiles
  parts: [offset: number, length: number][]; // the world map's bytes it needs: one after another, they're its tiles
  done: number[]; // parts on the phone
  gzip: boolean; // every tile starts with gzip's two bytes, which the check looks for
};

const AT_ONCE = 4; // parts downloading at the same time
const TRIES = 3; // a part that fails this many times running stops the map
const SPARE = 5e8; // room a map leaves free on the phone
const EVERY = 1000; // ms between saves of how far it got

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

export function createMaps(
  store: Store,
  phone: MapPhone,
  // tests' zooms, parts and waits: smaller, and none
  {
    world = WORLD,
    detail = DETAIL,
    part,
    wait = sleep,
  }: { world?: number; detail?: number; part?: number; wait?: typeof sleep } = {},
) {
  const nextFile = `${phone.dir}/next.json`;
  const path = (name: string) => `${phone.dir}/${name}`;
  let busy: string | undefined; // the place downloading
  let run = 0; // goes up when what's downloading must stop
  let active = true; // the app is on screen
  let seen = { d: store.get().mapDownload, cellular: store.get().cellular };

  const current = () => store.get().mapDownload;
  const total = (next: Next) => next.parts.reduce((n, [, length]) => n + length, next.head);

  function saved(): Next | undefined {
    try {
      return JSON.parse(phone.text(nextFile) ?? "null") ?? undefined;
    } catch {
      return undefined; // unreadable: start over
    }
  }

  function forget() {
    const next = saved();
    if (next?.partial) phone.remove(path(next.partial));
    phone.remove(nextFile);
  }

  // How far this place's map got, if it's the one under way
  function load(id: string): Next | undefined {
    const next = saved();
    if (next?.place === id && phone.size(path(next.partial)) >= next.head) return next;
    forget();
    return undefined;
  }

  // Where each part goes in the map file
  function positions(next: Next): number[] {
    let at = next.head;
    return next.parts.map(([, length]) => ((at += length), at - length));
  }

  // Each plan writes files of its own, so a download stopped too late to cancel can only land in its own plan's
  async function prepare(id: string, cellular: boolean): Promise<Next> {
    const p = place(id);
    if (!p) throw new Error("This version of the app doesn't know that place");
    const build = latest(await phone.json(BUILDS));
    const url = `${BUILD_BASE}/${build}`;
    const stamp = Date.now().toString(36);
    const scratch = path(`read-${stamp}.bin`);
    const area = { world, detail, boxes: [p.bbox] };
    const read = async (offset: number, length: number) => {
      const n = await phone.download({ url, path: scratch, cellular, offset, length });
      return phone.read(scratch, 0, n);
    };
    const pl = await plan(read, area, part).finally(() => phone.remove(scratch));
    const top = head(pl, area, { lon: p.home.lon, lat: p.home.lat, zoom: 12 });
    if (phone.free() < top.length + pl.bytes + SPARE)
      throw new Error(`Not enough free space for its ${size(top.length + pl.bytes)}`);
    const next: Next = {
      place: id,
      file: `${id.replace(/[^a-z0-9]+/gi, "-")}-${build.replace(/\.pmtiles$/, "")}.pmtiles`,
      partial: `next-${stamp}.pmtiles`,
      url,
      head: top.length,
      parts: pl.parts.map((q) => [pl.header.dataOffset + q.offset, q.length]),
      done: [],
      gzip: pl.header.tileCompression === 2,
    };
    await phone.write(path(next.partial), top);
    phone.save(nextFile, JSON.stringify(next));
    return next;
  }

  // Each job, a few at a time, each tried again a little later unless that can't help. The first that still fails
  // stops the rest, and is thrown once they have.
  async function each<T>(jobs: T[], live: () => boolean, job: (j: T) => Promise<void>) {
    let failure: unknown;
    const worker = async () => {
      for (let j = jobs.shift(); j !== undefined; j = jobs.shift())
        for (let tries = 1; ; tries++) {
          if (failure !== undefined || !live()) return;
          try {
            await job(j);
            break;
          } catch (e) {
            if (failure !== undefined || !live()) return;
            const c = code(e);
            if (tries >= TRIES || !active || c === NOT_ON_WIFI || GONE.test(c)) return void (failure = e);
            await wait(1000 * 2 ** tries);
          }
        }
    };
    await Promise.all(Array.from({ length: AT_ONCE }, worker));
    if (failure !== undefined) throw failure;
  }

  // The kit page's fonts and icons, once
  async function style(cellular: boolean, live: () => boolean) {
    const todo = STYLE_FILES.map((f) => path(`style/${f}`)).filter((to) => phone.size(to) <= 0);
    await each(todo, live, async (to) => {
      const f = to.slice(path("style/").length);
      await phone.download({ url: `${ASSETS}/${encodeURI(f)}`, path: `${to}.part`, cellular });
      if (live()) phone.move(`${to}.part`, to);
    });
  }

  async function parts(next: Next, cellular: boolean, live: () => boolean) {
    const at = positions(next);
    const done = new Set(next.done);
    let received = next.done.reduce((n, i) => n + next.parts[i][1], next.head);
    let saved = Date.now();
    const todo = next.parts.map((_, i) => i).filter((i) => !done.has(i));
    try {
      await each(todo, live, async (i) => {
        const [offset, length] = next.parts[i];
        const n = await phone.download({
          url: next.url,
          path: path(next.partial),
          cellular,
          offset,
          length,
          at: at[i],
        });
        if (n !== length) throw new Error("Part of the map came through short");
        if (!live()) return;
        next.done.push(i);
        received += length;
        if (Date.now() - saved >= EVERY) {
          saved = Date.now();
          phone.save(nextFile, JSON.stringify(next));
          store.updateMap({ received });
        }
      });
    } finally {
      if (current()?.place === next.place) phone.save(nextFile, JSON.stringify(next));
      if (live()) store.updateMap({ received });
    }
  }

  // Parts that didn't land whole: each part starts with a tile, and each tile with gzip's two bytes
  async function damaged(next: Next): Promise<number[]> {
    const end = phone.size(path(next.partial));
    const at = positions(next);
    const bad: number[] = [];
    for (let i = 0; i < at.length; i++) {
      if (at[i] + next.parts[i][1] > end) bad.push(i);
      else if (next.gzip) {
        const b = await phone.read(path(next.partial), at[i], 2);
        if (b[0] !== 0x1f || b[1] !== 0x8b) bad.push(i);
      }
    }
    return bad;
  }

  function finish(next: Next) {
    const old = store.get().map?.file;
    phone.move(path(next.partial), path(next.file));
    phone.remove(nextFile);
    busy = undefined; // so the store's change isn't taken for a stop
    store.mapReady(next.place, next.file);
    if (old && old !== next.file) phone.remove(path(old)); // only now the new one is in place
  }

  async function go() {
    const d = current();
    if (busy || !d || d.status === "failed") return;
    busy = d.place;
    const me = ++run;
    const live = () => run === me && current()?.place === d.place;
    const { cellular } = store.get();
    const fresh = async () => {
      store.updateMap({ status: "planning", waiting: undefined, error: undefined, received: 0, total: 0 });
      return prepare(d.place, cellular);
    };
    phone.awake(true);
    try {
      let next = load(d.place);
      let newest = !next; // planned from the newest world map in this go
      let rechecked = false;
      next ??= await fresh();
      for (;;) {
        if (!live()) return;
        store.updateMap({ status: "downloading", waiting: undefined, error: undefined, total: total(next) });
        await style(cellular, live); // outside: a missing font isn't the world map gone
        try {
          await parts(next, cellular, live);
        } catch (e) {
          if (newest || !GONE.test(code(e))) throw e;
          newest = true; // that day's world map is no longer there: start over from the newest
          forget();
          next = await fresh();
          continue;
        }
        if (!live()) return;
        store.updateMap({ status: "checking" });
        const bad = await damaged(next);
        if (!live()) return;
        if (!bad.length && phone.size(path(next.partial)) === total(next)) break;
        if (rechecked || !bad.length) throw new Error("The map came through damaged");
        rechecked = true; // once more, those parts only
        next.done = next.done.filter((i) => !bad.includes(i));
      }
      finish(next);
    } catch (e) {
      if (live()) {
        const c = code(e);
        if (c === NOT_ON_WIFI) store.updateMap({ waiting: "wifi" });
        else if (c === OFFLINE || !active) store.updateMap({ waiting: "internet" });
        else store.updateMap({ status: "failed", error: e instanceof Error ? e.message : String(e) });
      }
    } finally {
      busy = undefined;
      phone.awake(false);
      const now = current();
      if (!now)
        forget(); // stopped
      else if (run !== me && now.status !== "failed" && !now.waiting) void go(); // another place, or mobile data switched
    }
  }

  function halt() {
    run++;
    phone.stop();
  }

  function changed() {
    const d = current();
    const { cellular } = store.get();
    const was = seen;
    seen = { d, cellular };
    if (d === was.d && cellular === was.cellular) return;
    if (busy) {
      // stopped, another place, or mobile data switched, which the phone fixes as each part starts: stop, then go on
      if (!d || d.place !== busy || cellular !== was.cellular) halt();
    } else if (!d) {
      if (was.d) forget();
    } else if (d.status === "queued" || (d.waiting && cellular !== was.cellular)) void go();
  }

  const resume = () => {
    if (active && !busy && current()?.waiting) void go();
  };

  return {
    // Clears away what an earlier run left half done, then carries on with the map under way
    start() {
      const keep = [store.get().map?.file, current() && saved()?.partial];
      for (const name of phone.list())
        if (/\.(pmtiles|bin)$/.test(name) && !keep.includes(name)) phone.remove(path(name));
      if (!current()) forget();
      seen = { d: current(), cellular: store.get().cellular };
      store.subscribe(changed);
      void go();
    },
    // The app came on screen, or left it
    shown(on: boolean) {
      active = on;
      resume();
    },
    // The phone joined or left a network
    network: resume,
  };
}

// The newest world map in the version of Protomaps' layers the kit page's style is for
export function latest(builds: unknown): string {
  const keys = (Array.isArray(builds) ? builds : [])
    .filter((b): b is { key: string; version?: string } => typeof b?.key === "string" && b.key.endsWith(".pmtiles"))
    .filter((b) => (b.version ?? "4.").startsWith("4."))
    .map((b) => b.key)
    .sort();
  if (!keys.length) throw new Error("Protomaps lists no world map at the moment");
  return keys[keys.length - 1];
}

function code(e: unknown): string {
  return typeof e === "object" && e !== null && "code" in e ? String((e as { code: unknown }).code) : "";
}

// The day of the world map a map on the phone was cut from, as people write it
export function mapDay(file: string): string | undefined {
  const m = /-(\d{4})(\d{2})(\d{2})\.pmtiles$/.exec(file);
  if (!m) return undefined;
  const day = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
  return day.toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric", timeZone: "UTC" });
}

// The folder maps go in, as a path
export function mapsPath(): string {
  const maps = new Directory(Paths.document, "maps");
  return decodeURI(maps.uri.replace(/^file:\/\//, "")).replace(/\/$/, "");
}

function phone(): MapPhone {
  const dir = mapsPath();
  const file = (path: string) => new File(`file://${path}`);
  return {
    dir,
    async json(url) {
      const res = await fetch(url);
      if (!res.ok) throw new Error(`Protomaps said ${res.status}`);
      return res.json();
    },
    download,
    stop: stopDownloads,
    list: () =>
      new Directory(`file://${dir}`)
        .list()
        .filter((f) => f instanceof File)
        .map((f) => f.name),
    async read(path, at, length) {
      const handle = file(path).open(FileMode.ReadOnly);
      try {
        handle.offset = at;
        return handle.readBytesSync(length);
      } finally {
        handle.close();
      }
    },
    async write(path, bytes) {
      const f = file(path);
      f.create({ intermediates: true, overwrite: true });
      f.writeSync(bytes);
    },
    size: (path) => (file(path).exists ? file(path).size : -1),
    text: (path) => (file(path).exists ? file(path).textSync() : null),
    save: (path, text) => file(path).writeSync(text),
    move: (from, to) => file(from).moveSync(file(to), { overwrite: true }),
    remove(path) {
      if (file(path).exists) file(path).delete();
    },
    free: () => Paths.availableDiskSpace,
    awake: (on) => void (on ? activateKeepAwakeAsync("map") : deactivateKeepAwake("map")).catch(() => {}),
  };
}

let started = false;

// Called once the store has loaded.
export function startMaps() {
  if (started || Platform.OS === "web") return;
  started = true;
  const p = phone();
  new Directory(`file://${p.dir}`).create({ intermediates: true, idempotent: true });
  excludeFromBackup(p.dir);
  const maps = createMaps(kitStore, p);
  maps.start();
  AppState.addEventListener("change", (s) => maps.shown(s === "active"));
  addNetworkStateListener(() => maps.network());
}
