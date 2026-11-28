// One area out of Protomaps' world map, as the kit takes it with `pmtiles extract`: the whole world in little detail and
// the area in street detail. The world map's directories say where each tile is, so only the area's tiles are
// downloaded, and they go into a map file of the area's own. PMTiles v3:
// https://github.com/protomaps/PMTiles/blob/main/spec/v3/spec.md
import { gunzipSync, gzipSync, strFromU8, strToU8 } from "fflate";

export const HEADER = 127; // bytes
const FIRST = 16384; // a reader's first read, which holds the header and the root directory
const NONE = 1;
const GZIP = 2;
const MERCATOR = 85.0511287798; // the latitude where Web Mercator's square world ends

export type Header = {
  rootOffset: number;
  rootLength: number;
  metadataOffset: number;
  metadataLength: number;
  leavesOffset: number;
  leavesLength: number;
  dataOffset: number;
  dataLength: number;
  addressedTiles: number;
  tileEntries: number;
  tileContents: number;
  clustered: boolean;
  internalCompression: number;
  tileCompression: number;
  tileType: number;
  minZoom: number;
  maxZoom: number;
  minLon: number;
  minLat: number;
  maxLon: number;
  maxLat: number;
  centerZoom: number;
  centerLon: number;
  centerLat: number;
};

export function readHeader(b: Uint8Array): Header {
  if (b.length < HEADER || String.fromCharCode(...b.subarray(0, 7)) !== "PMTiles") throw new Error("Not a map file");
  if (b[7] !== 3) throw new Error(`A map file of version ${b[7]}, not 3`);
  const v = new DataView(b.buffer, b.byteOffset, b.byteLength);
  const u64 = (at: number) => v.getUint32(at, true) + v.getUint32(at + 4, true) * 2 ** 32;
  const deg = (at: number) => v.getInt32(at, true) / 1e7;
  return {
    rootOffset: u64(8),
    rootLength: u64(16),
    metadataOffset: u64(24),
    metadataLength: u64(32),
    leavesOffset: u64(40),
    leavesLength: u64(48),
    dataOffset: u64(56),
    dataLength: u64(64),
    addressedTiles: u64(72),
    tileEntries: u64(80),
    tileContents: u64(88),
    clustered: b[96] === 1,
    internalCompression: b[97],
    tileCompression: b[98],
    tileType: b[99],
    minZoom: b[100],
    maxZoom: b[101],
    minLon: deg(102),
    minLat: deg(106),
    maxLon: deg(110),
    maxLat: deg(114),
    centerZoom: b[118],
    centerLon: deg(119),
    centerLat: deg(123),
  };
}

export function writeHeader(h: Header): Uint8Array {
  const b = new Uint8Array(HEADER);
  const v = new DataView(b.buffer);
  b.set([0x50, 0x4d, 0x54, 0x69, 0x6c, 0x65, 0x73, 3]); // "PMTiles", version 3
  const u64 = (at: number, n: number) => {
    v.setUint32(at, n % 2 ** 32, true);
    v.setUint32(at + 4, Math.floor(n / 2 ** 32), true);
  };
  const deg = (at: number, d: number) => v.setInt32(at, Math.round(d * 1e7), true);
  u64(8, h.rootOffset);
  u64(16, h.rootLength);
  u64(24, h.metadataOffset);
  u64(32, h.metadataLength);
  u64(40, h.leavesOffset);
  u64(48, h.leavesLength);
  u64(56, h.dataOffset);
  u64(64, h.dataLength);
  u64(72, h.addressedTiles);
  u64(80, h.tileEntries);
  u64(88, h.tileContents);
  b[96] = h.clustered ? 1 : 0;
  b[97] = h.internalCompression;
  b[98] = h.tileCompression;
  b[99] = h.tileType;
  b[100] = h.minZoom;
  b[101] = h.maxZoom;
  deg(102, h.minLon);
  deg(106, h.minLat);
  deg(110, h.maxLon);
  deg(114, h.maxLat);
  b[118] = h.centerZoom;
  deg(119, h.centerLon);
  deg(123, h.centerLat);
  return b;
}

// A directory's entries, in columns: a big area has a million or more. An entry with a run of 0 points at a leaf
// directory; the rest are tiles, a run of tile ids that share one tile's bytes.
export class Entries {
  n = 0;
  ids = new Float64Array(256);
  offsets = new Float64Array(256);
  lengths = new Float64Array(256);
  runs = new Float64Array(256);

  push(id: number, offset: number, length: number, run: number) {
    if (this.n === this.ids.length) {
      const grow = (a: Float64Array) => {
        const b = new Float64Array(a.length * 2);
        b.set(a);
        return b;
      };
      this.ids = grow(this.ids);
      this.offsets = grow(this.offsets);
      this.lengths = grow(this.lengths);
      this.runs = grow(this.runs);
    }
    this.ids[this.n] = id;
    this.offsets[this.n] = offset;
    this.lengths[this.n] = length;
    this.runs[this.n] = run;
    this.n++;
  }
}

// Whole numbers past 32 bits stay exact: offsets in the world map run past 100 GB.
function varint(b: Uint8Array, at: { i: number }): number {
  let value = 0;
  let scale = 1;
  for (;;) {
    const byte = b[at.i++];
    if (byte === undefined) throw new Error("A map directory ends too soon");
    value += (byte & 0x7f) * scale;
    if (byte < 0x80) return value;
    scale *= 128;
  }
}

class Bytes {
  b = new Uint8Array(4096);
  n = 0;
  varint(v: number) {
    if (this.n + 10 > this.b.length) {
      const b = new Uint8Array(this.b.length * 2);
      b.set(this.b);
      this.b = b;
    }
    while (v >= 0x80) {
      this.b[this.n++] = (v % 0x80) | 0x80;
      v = Math.floor(v / 0x80);
    }
    this.b[this.n++] = v;
  }
  done() {
    return this.b.slice(0, this.n);
  }
}

export function readDirectory(b: Uint8Array): Entries {
  const at = { i: 0 };
  const n = varint(b, at);
  const e = new Entries();
  let id = 0;
  for (let k = 0; k < n; k++) {
    id += varint(b, at);
    e.push(id, 0, 0, 0);
  }
  for (let k = 0; k < n; k++) e.runs[k] = varint(b, at);
  for (let k = 0; k < n; k++) e.lengths[k] = varint(b, at);
  for (let k = 0; k < n; k++) {
    const v = varint(b, at);
    e.offsets[k] = v === 0 && k > 0 ? e.offsets[k - 1] + e.lengths[k - 1] : v - 1;
  }
  return e;
}

export function writeDirectory(e: Entries, from = 0, to = e.n): Uint8Array {
  const out = new Bytes();
  out.varint(to - from);
  for (let k = from, last = 0; k < to; k++) {
    out.varint(e.ids[k] - last);
    last = e.ids[k];
  }
  for (let k = from; k < to; k++) out.varint(e.runs[k]);
  for (let k = from; k < to; k++) out.varint(e.lengths[k]);
  for (let k = from; k < to; k++)
    out.varint(k > from && e.offsets[k] === e.offsets[k - 1] + e.lengths[k - 1] ? 0 : e.offsets[k] + 1);
  return out.done();
}

function inflate(b: Uint8Array, compression: number): Uint8Array {
  if (compression === GZIP) return gunzipSync(b);
  if (compression === NONE) return b;
  throw new Error("A map file compressed in a way this app can't read");
}

// A tile's id: the tiles of every zoom before it, then its place along a Hilbert curve, which keeps tiles that are
// near each other on the map near each other in the file.
export function tileId(z: number, x: number, y: number): number {
  let id = (4 ** z - 1) / 3;
  for (let s = 2 ** (z - 1); s >= 1; s /= 2) {
    const rx = x & s ? 1 : 0;
    const ry = y & s ? 1 : 0;
    id += s * s * ((3 * rx) ^ ry);
    x &= s - 1;
    y &= s - 1;
    if (ry === 0) {
      if (rx === 1) {
        x = s - 1 - x;
        y = s - 1 - y;
      }
      [x, y] = [y, x];
    }
  }
  return id;
}

export type Box = [west: number, south: number, east: number, north: number]; // in degrees
export type Range = [first: number, end: number]; // tile ids, the end not included

// Sorted, with ranges that touch or overlap made one.
export function merge(ranges: Range[]): Range[] {
  const sorted = [...ranges].sort((a, b) => a[0] - b[0]);
  const out: Range[] = [];
  for (const [first, end] of sorted) {
    const last = out[out.length - 1];
    if (last && first <= last[1]) last[1] = Math.max(last[1], end);
    else out.push([first, end]);
  }
  return out;
}

// The tiles of zoom z that cover a box. A tile at a lower zoom has all its tiles of zoom z in one run of ids, so a
// box comes to a few runs along its edges rather than one id per tile.
export function cover(box: Box, z: number): Range[] {
  const [w, s, e, n] = box;
  if (w > e) return merge([...cover([w, s, 180, n], z), ...cover([-180, s, e, n], z)]); // across the date line
  const size = 2 ** z;
  const clamp = (t: number) => Math.min(size - 1, Math.max(0, Math.floor(t)));
  const tx = (lon: number) => clamp(((lon + 180) / 360) * size);
  const ty = (lat: number) => {
    const r = (Math.max(-MERCATOR, Math.min(MERCATOR, lat)) * Math.PI) / 180;
    return clamp(((1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2) * size);
  };
  const [x0, y0, x1, y1] = [tx(w), ty(n), tx(e), ty(s)];
  const out: Range[] = [];
  const base = (4 ** z - 1) / 3;
  const visit = (k: number, x: number, y: number) => {
    const side = 2 ** (z - k); // tiles of zoom z along each side of this one
    const [ax, ay] = [x * side, y * side];
    const [bx, by] = [ax + side - 1, ay + side - 1];
    if (bx < x0 || ax > x1 || by < y0 || ay > y1) return;
    if (ax >= x0 && bx <= x1 && ay >= y0 && by <= y1) {
      const first = base + (tileId(k, x, y) - (4 ** k - 1) / 3) * side * side;
      out.push([first, first + side * side]);
      return;
    }
    for (const [dx, dy] of [
      [0, 0],
      [1, 0],
      [0, 1],
      [1, 1],
    ])
      visit(k + 1, 2 * x + dx, 2 * y + dy);
  };
  visit(0, 0, 0);
  return merge(out);
}

// What an area's map holds: every tile up to zoom `world`, and the tiles in its boxes from there to zoom `detail`.
export type Area = { world: number; detail: number; boxes: Box[] };

export function wanted({ world, detail, boxes }: Area): Range[] {
  const ranges: Range[] = [[0, (4 ** (world + 1) - 1) / 3]];
  for (let z = world + 1; z <= detail; z++) for (const box of boxes) ranges.push(...cover(box, z));
  return merge(ranges);
}

export type Read = (offset: number, length: number) => Promise<Uint8Array>;

export type Part = { offset: number; length: number }; // a span of the world map's tile data

export type Plan = {
  header: Header; // the world map's
  metadata: Record<string, unknown>; // its description: layers, attribution
  tiles: Entries; // the area's tiles, at their offsets in the area's tile data
  contents: number; // how many different tiles they come to
  parts: Part[]; // what to download, in order: one after another, they're the area's tile data
  bytes: number; // the parts' total
};

const LEAVES = 4 << 20; // leaf directories near each other are read together, up to this much
const GAP = 64 << 10; // tiles this close are downloaded together, the bytes between them too
const PART = 8 << 20; // a part's most: a failed part starts over

// Works out which of the world map's bytes the area needs, reading only its directories.
export async function plan(read: Read, area: Area, most = PART): Promise<Plan> {
  const want = wanted(area);
  const first = await read(0, FIRST);
  const header = readHeader(first);
  const ic = header.internalCompression;
  const rootEnd = header.rootOffset + header.rootLength;
  const rootBytes =
    rootEnd <= first.length
      ? first.subarray(header.rootOffset, rootEnd)
      : await read(header.rootOffset, header.rootLength);
  const metadata = JSON.parse(strFromU8(inflate(await read(header.metadataOffset, header.metadataLength), ic)));
  const tiles = new Entries();

  // A directory's tiles in the area, in order: leaves it points at are read first, the near ones together.
  const walk = async (dir: Entries, end: number, depth: number): Promise<void> => {
    const spans = (k: number) => {
      const run = dir.runs[k];
      return [dir.ids[k], run > 0 ? dir.ids[k] + run : k + 1 < dir.n ? dir.ids[k + 1] : end] as const;
    };
    const needed: number[] = [];
    for (let k = 0, j = 0; k < dir.n; k++) {
      if (dir.runs[k] !== 0) continue;
      const [a, b] = spans(k);
      while (j < want.length && want[j][1] <= a) j++;
      if (j < want.length && want[j][0] < b) needed.push(k);
    }
    if (needed.length && depth >= 3) throw new Error("A map file with leaves too deep");
    const leaves = new Map<number, Uint8Array>();
    for (let i = 0; i < needed.length;) {
      const start = dir.offsets[needed[i]];
      let stop = start + dir.lengths[needed[i]];
      let j = i + 1;
      while (j < needed.length) {
        const [o, l] = [dir.offsets[needed[j]], dir.lengths[needed[j]]];
        if (o < stop || o + l - start > LEAVES) break;
        stop = o + l;
        j++;
      }
      const bytes = await read(header.leavesOffset + start, stop - start);
      for (; i < j; i++) {
        const o = dir.offsets[needed[i]] - start;
        leaves.set(needed[i], bytes.subarray(o, o + dir.lengths[needed[i]]));
      }
    }
    for (let k = 0, j = 0; k < dir.n; k++) {
      const [a, b] = spans(k);
      while (j < want.length && want[j][1] <= a) j++;
      if (dir.runs[k] === 0) {
        const leaf = leaves.get(k);
        if (leaf) await walk(readDirectory(inflate(leaf, ic)), b, depth + 1);
        continue;
      }
      for (let i = j; i < want.length && want[i][0] < b; i++) {
        const [from, to] = [Math.max(a, want[i][0]), Math.min(b, want[i][1])];
        tiles.push(from, dir.offsets[k], dir.lengths[k], to - from);
      }
    }
  };
  await walk(readDirectory(inflate(rootBytes, ic)), Infinity, 0);

  // The parts: the tiles' bytes in the order the world map keeps them, each tile once however many ids share it
  const order = new Uint32Array(tiles.n);
  for (let k = 0; k < tiles.n; k++) order[k] = k;
  order.sort((a, b) => tiles.offsets[a] - tiles.offsets[b]);
  const parts: Part[] = [];
  let bytes = 0;
  let contents = 0;
  let last = -1;
  let moved = 0; // where the last tile went in the area's tile data
  for (const k of order) {
    const offset = tiles.offsets[k];
    if (offset !== last) {
      last = offset;
      contents++;
      const part = parts[parts.length - 1];
      const end = offset + tiles.lengths[k];
      if (part && offset - (part.offset + part.length) <= GAP && end - part.offset <= most) {
        moved = bytes - part.length + (offset - part.offset);
        bytes += Math.max(0, end - (part.offset + part.length));
        part.length = Math.max(part.length, end - part.offset);
      } else {
        moved = bytes;
        parts.push({ offset, length: tiles.lengths[k] });
        bytes += tiles.lengths[k];
      }
    }
    tiles.offsets[k] = moved;
  }
  return { header, metadata, tiles, contents, parts, bytes };
}

// The area's map file up to its tile data: its header, directories and description. The parts follow, in order.
export function head(p: Plan, area: Area, home: { lon: number; lat: number; zoom: number }): Uint8Array {
  const { root, leaves } = directories(p.tiles);
  // MapLibre takes zooms, bounds and center from the description before the header: let the header say them
  const described = { ...p.metadata };
  for (const key of ["minzoom", "maxzoom", "bounds", "center"]) delete described[key];
  const metadata = gzipSync(strToU8(JSON.stringify(described)));
  let addressed = 0;
  for (let k = 0; k < p.tiles.n; k++) addressed += p.tiles.runs[k];
  const at = HEADER + root.length + metadata.length + leaves.length;
  const header = writeHeader({
    ...p.header,
    rootOffset: HEADER,
    rootLength: root.length,
    metadataOffset: HEADER + root.length,
    metadataLength: metadata.length,
    leavesOffset: HEADER + root.length + metadata.length,
    leavesLength: leaves.length,
    dataOffset: at,
    dataLength: p.bytes,
    addressedTiles: addressed,
    tileEntries: p.tiles.n,
    tileContents: p.contents,
    clustered: true,
    internalCompression: GZIP,
    minZoom: 0,
    maxZoom: area.detail,
    minLon: -180,
    minLat: -MERCATOR,
    maxLon: 180,
    maxLat: MERCATOR,
    centerZoom: home.zoom,
    centerLon: home.lon,
    centerLat: home.lat,
  });
  const out = new Uint8Array(at);
  out.set(header);
  out.set(root, HEADER);
  out.set(metadata, HEADER + root.length);
  out.set(leaves, HEADER + root.length + metadata.length);
  return out;
}

// All the entries in the root when they fit in a reader's first read, otherwise in leaves of a few thousand each,
// bigger until the root that points at them fits.
export function directories(tiles: Entries): { root: Uint8Array; leaves: Uint8Array } {
  const all = gzipSync(writeDirectory(tiles));
  if (HEADER + all.length <= FIRST) return { root: all, leaves: new Uint8Array(0) };
  for (let size = 4096; ; size *= 2) {
    const root = new Entries();
    const blobs: Uint8Array[] = [];
    let at = 0;
    for (let k = 0; k < tiles.n; k += size) {
      const leaf = gzipSync(writeDirectory(tiles, k, Math.min(tiles.n, k + size)));
      root.push(tiles.ids[k], at, leaf.length, 0);
      blobs.push(leaf);
      at += leaf.length;
    }
    const r = gzipSync(writeDirectory(root));
    if (HEADER + r.length > FIRST) continue;
    const leaves = new Uint8Array(at);
    blobs.reduce((o, leaf) => (leaves.set(leaf, o), o + leaf.length), 0);
    return { root: r, leaves };
  }
}
