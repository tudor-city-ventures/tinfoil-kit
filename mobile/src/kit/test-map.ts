// Small world maps for tests, laid out as the PMTiles spec describes and Protomaps' builds are
import { gunzipSync, gzipSync, strToU8 } from "fflate";

import { Entries, HEADER, readDirectory, readHeader, writeDirectory, writeHeader } from "./pmtiles";

const base = (z: number) => (4 ** z - 1) / 3;

export function concat(parts: Uint8Array[]): Uint8Array {
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  parts.reduce((at, p) => (out.set(p, at), at + p.length), 0);
  return out;
}

// A world map of every tile up to a zoom: most tiles have bytes of their own; the sea's tiles share one tile's bytes,
// in long runs (the last quarter of each zoom, east of 0° and north of the equator) and one by one (every seventh).
// With leafSize, the directory goes in leaves of that many tiles; with gzip, every tile is compressed, as Protomaps'
// are.
export function world(maxZoom: number, { leafSize = 0, gzip = false } = {}): Uint8Array {
  const tiles = new Entries();
  const chunks: Uint8Array[] = [];
  let size = 0;
  const add = (text: string) => {
    const b = gzip ? gzipSync(strToU8(text), { mtime: 0 }) : strToU8(text);
    chunks.push(b);
    size += b.length;
    return [size - b.length, b.length];
  };
  let sea: number[] = [];
  for (let z = 0; z <= maxZoom; z++)
    for (let i = 0; i < 4 ** z; i++) {
      const id = base(z) + i;
      if (z >= 2 && (i >= (3 * 4 ** z) / 4 || id % 7 === 0)) {
        if (!sea.length) sea = add("sea");
        const k = tiles.n - 1;
        if (tiles.offsets[k] === sea[0] && tiles.ids[k] + tiles.runs[k] === id) tiles.runs[k]++;
        else tiles.push(id, sea[0], sea[1], 1);
      } else {
        const [offset, length] = add(`tile ${id}`);
        tiles.push(id, offset, length, 1);
      }
    }
  let root = tiles;
  const leafBlobs: Uint8Array[] = [];
  if (leafSize) {
    root = new Entries();
    let at = 0;
    for (let k = 0; k < tiles.n; k += leafSize) {
      const leaf = gzipSync(writeDirectory(tiles, k, Math.min(tiles.n, k + leafSize)));
      root.push(tiles.ids[k], at, leaf.length, 0);
      leafBlobs.push(leaf);
      at += leaf.length;
    }
  }
  const r = gzipSync(writeDirectory(root));
  const meta = gzipSync(strToU8(JSON.stringify({ name: "test world", maxzoom: maxZoom, vector_layers: [] })));
  const leaves = concat(leafBlobs);
  const data = concat(chunks);
  const header = writeHeader({
    rootOffset: HEADER,
    rootLength: r.length,
    metadataOffset: HEADER + r.length,
    metadataLength: meta.length,
    leavesOffset: HEADER + r.length + meta.length,
    leavesLength: leaves.length,
    dataOffset: HEADER + r.length + meta.length + leaves.length,
    dataLength: data.length,
    addressedTiles: base(maxZoom + 1),
    tileEntries: tiles.n,
    tileContents: chunks.length,
    clustered: true,
    internalCompression: 2,
    tileCompression: gzip ? 2 : 1,
    tileType: 1,
    minZoom: 0,
    maxZoom,
    minLon: -180,
    minLat: -85,
    maxLon: 180,
    maxLat: 85,
    centerZoom: 0,
    centerLon: 0,
    centerLat: 0,
  });
  return concat([header, r, meta, leaves, data]);
}

// A tile's bytes, found the way MapLibre finds them: the root, then a leaf
export function tile(file: Uint8Array, id: number): Uint8Array | undefined {
  const h = readHeader(file);
  let dir = readDirectory(gunzipSync(file.subarray(h.rootOffset, h.rootOffset + h.rootLength)));
  for (let depth = 0; depth < 4; depth++) {
    let k = -1;
    for (let i = 0; i < dir.n && dir.ids[i] <= id; i++) k = i;
    if (k < 0) return undefined;
    if (dir.runs[k] > 0) {
      if (id >= dir.ids[k] + dir.runs[k]) return undefined;
      const at = h.dataOffset + dir.offsets[k];
      return file.subarray(at, at + dir.lengths[k]);
    }
    const at = h.leavesOffset + dir.offsets[k];
    dir = readDirectory(gunzipSync(file.subarray(at, at + dir.lengths[k])));
  }
  return undefined;
}
