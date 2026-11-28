import { expect, test } from "@jest/globals";
import { gunzipSync, strFromU8 } from "fflate";

import {
  type Area,
  type Box,
  cover,
  directories,
  Entries,
  head,
  HEADER,
  plan,
  readDirectory,
  readHeader,
  tileId,
  wanted,
  writeDirectory,
  writeHeader,
  type Header,
} from "./pmtiles";
import { concat, tile, world } from "./test-map";

const base = (z: number) => (4 ** z - 1) / 3;

// The tiles of zoom z in a box, one by one: what cover() does by runs
function tilesIn([w, s, e, n]: Box, z: number): number[] {
  const size = 2 ** z;
  const x = (lon: number) => Math.min(size - 1, Math.max(0, Math.floor(((lon + 180) / 360) * size)));
  const y = (lat: number) => {
    const r = (lat * Math.PI) / 180;
    return Math.min(size - 1, Math.max(0, Math.floor(((1 - Math.asinh(Math.tan(r)) / Math.PI) / 2) * size)));
  };
  const ids: number[] = [];
  for (let tx = x(w); tx <= x(e); tx++) for (let ty = y(n); ty <= y(s); ty++) ids.push(tileId(z, tx, ty));
  return ids.sort((a, b) => a - b);
}

const ids = (ranges: [number, number][]) => ranges.flatMap(([a, b]) => Array.from({ length: b - a }, (_, i) => a + i));

test("tile ids follow the PMTiles spec's Hilbert curve", () => {
  expect([tileId(0, 0, 0), tileId(1, 0, 0), tileId(1, 0, 1), tileId(1, 1, 1), tileId(1, 1, 0)]).toEqual([
    0, 1, 2, 3, 4,
  ]);
  expect(tileId(2, 0, 0)).toBe(5);
  expect(tileId(15, 32767, 32767)).toBeLessThan(base(16));
  for (let z = 0; z <= 6; z++) {
    const seen = new Set<number>();
    for (let x = 0; x < 2 ** z; x++) for (let y = 0; y < 2 ** z; y++) seen.add(tileId(z, x, y) - base(z));
    expect(seen.size).toBe(4 ** z);
    expect(Math.max(...seen)).toBe(4 ** z - 1);
    // a tile's tiles at the next zoom come right after one another
    if (z > 0)
      for (let x = 0; x < 2 ** z; x++)
        for (let y = 0; y < 2 ** z; y++) {
          const parent = tileId(z - 1, x >> 1, y >> 1) - base(z - 1);
          expect(Math.floor((tileId(z, x, y) - base(z)) / 4)).toBe(parent);
        }
  }
});

test("a box's tiles come as runs: the same tiles as one by one, fewer pieces", () => {
  const boxes: Box[] = [
    [-80.53, 38.74, -66.87, 47.47], // the US Northeast
    [-88.49, 29.95, -84.88, 35.01], // Alabama
    [5.9, 45.8, 10.5, 47.8], // Switzerland
    [-180, 15.92, -129.79, 72.99], // the US Pacific, to the date line
    [-10, -89, 10, 89], // past where the square world ends
  ];
  for (const box of boxes)
    for (let z = 0; z <= 9; z++) {
      const runs = cover(box, z);
      expect(ids(runs)).toEqual(tilesIn(box, z));
      if (z === 9) expect(runs.length).toBeLessThan(tilesIn(box, z).length / 4);
    }
  // across the date line: Fiji's islands either side of it
  expect(ids(cover([177, -21, -178, -12], 6))).toEqual(
    [...tilesIn([177, -21, 180, -12], 6), ...tilesIn([-180, -21, -178, -12], 6)].sort((a, b) => a - b),
  );
});

test("an area: every tile up to the world's zoom, then the box's", () => {
  const area: Area = { world: 2, detail: 5, boxes: [[-88.49, 29.95, -84.88, 35.01]] };
  const expected = [...ids([[0, base(3)]])];
  for (let z = 3; z <= 5; z++) expected.push(...tilesIn(area.boxes[0], z));
  expect(ids(wanted(area))).toEqual([...new Set(expected)].sort((a, b) => a - b));
});

test("headers and directories read back as written, offsets past 32 bits too", () => {
  const h: Header = {
    rootOffset: 127,
    rootLength: 900,
    metadataOffset: 1027,
    metadataLength: 400,
    leavesOffset: 1427,
    leavesLength: 2 ** 33 + 5,
    dataOffset: 2 ** 33 + 1432,
    dataLength: 120e9,
    addressedTiles: 1_431_655_765,
    tileEntries: 300_000_000,
    tileContents: 200_000_000,
    clustered: true,
    internalCompression: 2,
    tileCompression: 2,
    tileType: 1,
    minZoom: 0,
    maxZoom: 15,
    minLon: -180,
    minLat: -85.0511287,
    maxLon: 180,
    maxLat: 85.0511287,
    centerZoom: 10,
    centerLon: -86.5859,
    centerLat: 34.7304,
  };
  expect(readHeader(writeHeader(h))).toEqual(h);
  expect(() => readHeader(new Uint8Array(127))).toThrow("Not a map file");

  const e = new Entries();
  e.push(5, 0, 120, 1);
  e.push(6, 120, 80, 3); // right after the last: written as 0
  e.push(9, 2 ** 40, 7, 1); // far on
  e.push(1_000_000_000, 7, 16000, 0); // a leaf
  const back = readDirectory(writeDirectory(e));
  expect(back.n).toBe(4);
  for (const col of ["ids", "offsets", "lengths", "runs"] as const)
    expect(Array.from(back[col].subarray(0, 4))).toEqual(Array.from(e[col].subarray(0, 4)));
});

const find = (file: Uint8Array, id: number) => {
  const b = tile(file, id);
  return b && strFromU8(b);
};

async function extract(file: Uint8Array, area: Area) {
  const h = readHeader(file);
  const reads: [number, number][] = [];
  const p = await plan(async (offset, length) => {
    reads.push([offset, length]);
    return file.slice(offset, offset + length);
  }, area);
  const top = head(p, area, { lon: -86.59, lat: 34.73, zoom: 9 });
  const parts = p.parts.map((part) =>
    file.subarray(h.dataOffset + part.offset, h.dataOffset + part.offset + part.length),
  );
  return { p, reads, h, out: concat([top, ...parts]) };
}

test("an area's map: its tiles, the same bytes as the world's, and nothing else, from the directories alone", async () => {
  for (const leafSize of [0, 50]) {
    const file = world(7, { leafSize });
    const area: Area = { world: 3, detail: 7, boxes: [[-88.49, 29.95, -84.88, 35.01]] };
    const { p, reads, h, out } = await extract(file, area);
    // after the first read, which a small file's tiles fall into, only directories and the description were read
    for (const [offset, length] of reads.slice(1)) expect(offset + length).toBeLessThanOrEqual(h.dataOffset);
    if (leafSize) expect(reads.length).toBeLessThan(10);

    const want = new Set(ids(wanted(area)));
    for (let id = 0; id < base(8); id++) expect(find(out, id)).toBe(want.has(id) ? find(file, id) : undefined);
    const header = readHeader(out);
    expect(header).toMatchObject({ maxZoom: 7, minZoom: 0, centerZoom: 9, addressedTiles: want.size });
    expect(header.dataLength).toBe(p.bytes);
    expect(header.dataOffset + header.dataLength).toBe(out.length);
    expect(p.bytes).toBe(p.parts.reduce((n, part) => n + part.length, 0));
    // the sea's bytes once, however many tiles share them
    expect(p.contents).toBeLessThan(want.size);
    // the description, without the world's zooms: the header says them
    const m = JSON.parse(
      strFromU8(gunzipSync(out.subarray(header.metadataOffset, header.metadataOffset + header.metadataLength))),
    );
    expect(m).toEqual({ name: "test world", vector_layers: [] });
  }
});

test("a big area: the far side of the world stays out", async () => {
  const file = world(8, { leafSize: 2000 });
  const area: Area = { world: 2, detail: 8, boxes: [[-130, 20, -60, 55]] };
  const { out } = await extract(file, area);
  for (const id of ids(wanted(area)).filter((_, i) => i % 7 === 0)) expect(find(out, id)).toBe(find(file, id));
  expect(find(out, tileId(8, 250, 100))).toBeUndefined(); // Kazakhstan, in street detail
});

test("a directory too big for the first read goes into leaves, the root still in it", () => {
  const tiles = new Entries();
  for (let k = 0, at = 0, seed = 1; k < 100_000; k++) {
    seed = (seed * 1103515245 + 12345) % 2 ** 31; // tiles' sizes vary as real ones do
    const length = 100 + (seed % 50_000);
    tiles.push(k * 2, at, length, 1 + (k % 3));
    at += length;
  }
  const { root, leaves } = directories(tiles);
  expect(HEADER + root.length).toBeLessThanOrEqual(16384);
  const top = readDirectory(gunzipSync(root));
  expect(top.n).toBeGreaterThan(1);
  expect(top.runs.subarray(0, top.n).every((r) => r === 0)).toBe(true);
  const back = new Entries();
  for (let k = 0; k < top.n; k++) {
    const leaf = readDirectory(gunzipSync(leaves.subarray(top.offsets[k], top.offsets[k] + top.lengths[k])));
    expect(leaf.ids[0]).toBe(top.ids[k]);
    for (let i = 0; i < leaf.n; i++) back.push(leaf.ids[i], leaf.offsets[i], leaf.lengths[i], leaf.runs[i]);
  }
  for (const col of ["ids", "offsets", "lengths", "runs"] as const)
    expect(back[col].subarray(0, back.n)).toEqual(tiles[col].subarray(0, tiles.n));
});
