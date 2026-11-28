/// <reference types="node" />
import { expect, test } from "@jest/globals";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { zstdDecompressSync } from "node:zlib";

import { book, pages, png } from "./test-zim";
import { utf8, Zim, type Source } from "./zim";

const read = (zim: Zim, ns: string, path: string) => utf8(zim.read(zim.find(ns, path)!));

// A book's bytes, unpacked by a decoder of the phone's own, as the app's native code does: given exactly a cluster's
// frame, since zstd refuses one cut short or followed by more
function native(source: Source, frames: number[][] = []): Source {
  return {
    ...source,
    unzstd(offset, length) {
      frames.push([offset, length]);
      return new Uint8Array(zstdDecompressSync(source.read(offset, length)));
    },
  };
}

test("a book from 2021 on: pages in C, a main page, redirects, pictures, metadata and titles", () => {
  for (const wide of [false, true]) {
    const zim = new Zim(book(pages("C"), { main: "Fever", wide }));
    expect(zim.content).toBe("C");
    expect(zim.mainPage()).toMatchObject({ namespace: "C", path: "Fever", title: "Fever", mime: "text/html" });
    expect(read(zim, "C", "Fever")).toContain("38 °C");
    expect(zim.follow(zim.find("C", "Temperature")!).path).toBe("Fever");
    expect(zim.read(zim.find("C", "fever.png")!)).toEqual(png);
    expect(zim.find("C", "Fevers")).toBeUndefined();
    expect(zim.metadata("Title")).toBe("Test Medical Library");
    expect(zim.titles("water").map((e) => e.title)).toEqual(["Water purification"]);
    expect(zim.titles("D").map((e) => e.path)).toEqual(["Dehydration"]);
    expect(zim.titles("x")).toEqual([]);
  }
});

test("an older book: pages in A, pictures in I, the header's title list", () => {
  const zim = new Zim(book(pages("A"), { old: true, main: "Dehydration" }));
  expect(zim.content).toBe("A");
  expect(zim.mainPage()?.path).toBe("Dehydration");
  expect(read(zim, "A", "Fever")).toContain("<h1>Fever</h1>");
  expect(zim.read(zim.find("I", "fever.png")!)).toEqual(png);
  expect(zim.titles("fev").map((e) => e.title)).toEqual(["Fever"]);
});

test("the phone's own decoder unpacks the clusters, where it has one", () => {
  const frames: number[][] = [];
  const zim = new Zim(native(book(pages("C"), { main: "Fever" }), frames));
  expect(read(zim, "C", "Fever")).toContain("38 °C");
  expect(read(zim, "C", "Dehydration")).toContain("<h1>Dehydration</h1>"); // the same cluster, kept
  expect(zim.read(zim.find("C", "fever.png")!)).toEqual(png); // stored as it is: read straight from the file
  expect(frames).toHaveLength(1);
});

test("what it can't read, it says so", () => {
  expect(() =>
    new Zim(book(pages("C"), { xz: true })).read(new Zim(book(pages("C"), { xz: true })).find("C", "Fever")!),
  ).toThrow("older format");
  const junk = new Uint8Array(100);
  expect(() => new Zim({ size: 100, read: (o, n) => junk.subarray(o, o + n) })).toThrow("This isn't a ZIM book");
});

// Real books made by libzim (tests/make_zims.py), when CI or a developer has built them
const real = process.env.ZIM_FIXTURES;
(real && existsSync(real) ? test : test.skip)("books libzim made", () => {
  for (const name of readdirSync(real!).filter((n) => n.endsWith(".zim"))) {
    const bytes = new Uint8Array(readFileSync(join(real!, name)));
    const source: Source = { size: bytes.length, read: (o, n) => bytes.subarray(o, o + n) };
    const zim = new Zim(source);
    const main = zim.mainPage()!;
    expect(utf8(zim.read(main))).toContain(`<h1>${main.title}</h1>`);
    expect(new Zim(native(source)).read(main)).toEqual(zim.read(main));
    expect(zim.metadata("Language")).toBe("eng");
    expect(zim.titles(main.title.slice(0, 3).toLowerCase())[0].path).toBe(main.path);
  }
});
