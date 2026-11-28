/// <reference types="node" />
// The phone map's real sizes for a few places, from Protomaps' newest world map, at the zooms that could be the
// phone's. It reads a few MB of the world map's directories over the internet, so it runs only when asked: the
// phone app workflow's "map sizes" run sets MAP_SIZES.
import { expect, test } from "@jest/globals";
import { appendFileSync } from "node:fs";
import * as http from "node:http";
import * as https from "node:https";

import { BUILD_BASE, BUILDS, latest } from "./maps";
import { place } from "./places";
import { plan, type Area } from "./pmtiles";

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
