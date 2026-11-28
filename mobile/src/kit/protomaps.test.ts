/// <reference types="node" />
// Protomaps' newest world map, read over the internet, so these run only when asked:
// - MAP_SIZES: the phone map's real sizes for a few places, at the zooms that could be the phone's. The phone app
//   workflow's "map sizes" run sets it.
// - E2E_MAP=folder: a small piece of the world map around Alabama's home, with the kit page's fonts and icons, for
//   e2e/internet.py to serve in the end-to-end test, so the simulators show a real map.
import { expect, test } from "@jest/globals";
import { appendFileSync, mkdirSync, writeFileSync } from "node:fs";
import * as http from "node:http";
import * as https from "node:https";
import { dirname } from "node:path";

import { ASSETS, BUILD_BASE, BUILDS, latest, STYLE_FILES } from "./maps";
import { place } from "./places";
import { head, plan, type Area } from "./pmtiles";
import { concat } from "./test-map";

const PLACES = ["us/rhode-island", "us/new-jersey", "us/alabama", "us/new-york", "us/texas", "us/california", "italy"];
const WORLDS = [5, 6, 7];
const DETAILS = [14, 15];

function get(url: string, headers: Record<string, string> = {}): Promise<Buffer> {
  return new Promise((resolve, reject) => {
    (url.startsWith("https:") ? https : http)
      .request(url, { headers }, (res) => {
        if (res.statusCode && res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
          res.resume();
          return resolve(get(new URL(res.headers.location, url).toString(), headers));
        }
        if (res.statusCode !== 200 && res.statusCode !== 206) return reject(new Error(`${url}: ${res.statusCode}`));
        const chunks: Buffer[] = [];
        res.on("data", (c: Buffer) => chunks.push(c));
        res.on("end", () => resolve(Buffer.concat(chunks)));
        res.on("error", reject);
      })
      .on("error", reject)
      .end();
  });
}

const zoom = (id: number) => {
  let z = 0;
  while ((4 ** (z + 1) - 1) / 3 <= id) z++;
  return z;
};

(process.env.MAP_SIZES ? test : test.skip)(
  "the phone map's sizes",
  async () => {
    const build = latest(JSON.parse((await get(BUILDS)).toString()));
    const url = `${BUILD_BASE}/${build}`;
    let read = 0;
    const range = async (offset: number, length: number) => {
      read += length;
      return new Uint8Array(await get(url, { Range: `bytes=${offset}-${offset + length - 1}` }));
    };
    // Each zoom's bytes, the same tile's once
    const byZoom = async (area: Area) => {
      const p = await plan(range, area);
      const bytes = new Array(DETAILS[DETAILS.length - 1] + 1).fill(0);
      const seen = new Set<number>();
      for (let k = 0; k < p.tiles.n; k++) {
        if (seen.has(p.tiles.offsets[k])) continue;
        seen.add(p.tiles.offsets[k]);
        bytes[zoom(p.tiles.ids[k])] += p.tiles.lengths[k];
      }
      return { bytes, download: p.bytes };
    };
    const sum = (b: number[], from: number, to: number) => b.slice(from, to + 1).reduce((n, x) => n + x, 0);
    const mb = (n: number) => String(Math.round(n / 1e6));

    const world = (await byZoom({ world: 7, detail: 7, boxes: [[0, 0, 0.01, 0.01]] })).bytes;
    const lines = [
      `Protomaps ${build}. MB to download: the world to the first zoom, the place to the second.`,
      "",
      `| Place | ${WORLDS.flatMap((w) => DETAILS.map((d) => `${w}+${d}`)).join(" | ")} | 7+15 as planned |`,
      `| --- | ${WORLDS.flatMap(() => DETAILS.map(() => "---")).join(" | ")} | --- |`,
      `| The world alone | ${WORLDS.flatMap((w) => DETAILS.map(() => mb(sum(world, 0, w)))).join(" | ")} | |`,
    ];
    for (const id of PLACES) {
      const p = place(id)!;
      const area = (await byZoom({ world: 0, detail: DETAILS[DETAILS.length - 1], boxes: [p.bbox] })).bytes;
      const planned = await byZoom({ world: 7, detail: 15, boxes: [p.bbox] });
      const cells = WORLDS.flatMap((w) => DETAILS.map((d) => mb(sum(world, 0, w) + sum(area, w + 1, d))));
      lines.push(`| ${p.name} | ${cells.join(" | ")} | ${mb(planned.download)} |`);
    }
    lines.push("", `Read ${mb(read)} MB of directories.`);
    const table = lines.join("\n");
    console.log(table);
    if (process.env.GITHUB_STEP_SUMMARY) appendFileSync(process.env.GITHUB_STEP_SUMMARY, table + "\n");
    expect(world[0]).toBeGreaterThan(0);
  },
  15 * 60_000,
);

(process.env.E2E_MAP ? test : test.skip)(
  "a piece of the world map for the end-to-end test",
  async () => {
    const dir = process.env.E2E_MAP!;
    const build = latest(JSON.parse((await get(BUILDS)).toString()));
    const url = `${BUILD_BASE}/${build}`;
    const range = async (offset: number, length: number) =>
      new Uint8Array(await get(url, { Range: `bytes=${offset}-${offset + length - 1}` }));
    // Wider than a phone's screen at the zoom the map opens at, around where it opens
    const { home } = place("us/alabama")!;
    const area: Area = {
      world: 0,
      detail: 13,
      boxes: [[home.lon - 0.05, home.lat - 0.07, home.lon + 0.05, home.lat + 0.07]],
    };
    const p = await plan(range, area);
    const parts: Uint8Array[] = [head(p, area, { ...home, zoom: 12 })];
    for (const q of p.parts) parts.push(await range(p.header.dataOffset + q.offset, q.length));
    const map = concat(parts);
    mkdirSync(dir, { recursive: true });
    writeFileSync(`${dir}/${build}`, map);
    writeFileSync(`${dir}/builds.json`, JSON.stringify([{ key: build }]));
    const files = [...STYLE_FILES]; // hundreds of small ones, so several at a time
    const worker = async () => {
      for (let f = files.shift(); f; f = files.shift()) {
        mkdirSync(dirname(`${dir}/assets/${f}`), { recursive: true });
        writeFileSync(`${dir}/assets/${f}`, await get(`${ASSETS}/${encodeURI(f)}`));
      }
    };
    await Promise.all(Array.from({ length: 16 }, worker));
    console.log(`${build}: ${p.tiles.n} tiles, ${Math.round(map.length / 1e3)} KB`);
    expect(p.tiles.n).toBeGreaterThan(20);
  },
  5 * 60_000,
);
