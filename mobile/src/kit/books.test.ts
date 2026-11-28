/// <reference types="node" />
import { expect, test } from "@jest/globals";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { address, answer, host, origin, parse } from "./books";
import { book, pages, png } from "./test-zim";
import { utf8, Zim } from "./zim";

const FILE = "/books/testmed.zim";
const text = (a: ReturnType<typeof answer>) => ("body" in a ? utf8(a.body) : "");

test("each book has its own origin, and its addresses come back to it", () => {
  expect(host("irp.fas.org_en_military-medicine")).toBe("irp-fas-org-en-military-medicine");
  expect(origin("zimgit-water_en", "ios")).toBe("zim://zimgit-water-en");
  expect(origin("zimgit-water_en", "android")).toBe("https://zimgit-water-en.zim.tinfoilkit.invalid");
  expect(parse("zim://zimgit-water-en/Water_purification#Boiling")).toEqual({
    host: "zimgit-water-en",
    path: "Water_purification",
  });
  expect(parse("https://zimgit-water-en.zim.tinfoilkit.invalid/I/caf%C3%A9.png?x=1")).toEqual({
    host: "zimgit-water-en",
    path: "I/café.png",
  });
  expect(parse("zim://book")).toEqual({ host: "book", path: "" });
  expect(parse("zim://book/100%")?.path).toBe("100%");
  expect(parse("https://example.com/Fever")).toBeUndefined();
  expect(parse("https://zim.tinfoilkit.invalid.example.com/Fever")).toBeUndefined();
});

test("pages, pictures as they lie in the file, and a page under another name", () => {
  const zim = new Zim(book(pages("C"), { main: "Fever" }));
  const fever = answer(zim, FILE, "Fever", true);
  expect(fever).toMatchObject({ status: 200, mime: "text/html; charset=utf-8" });
  expect(text(fever)).toContain("38 °C");

  const picture = answer(zim, FILE, "fever.png", false);
  expect(picture).toMatchObject({ status: 200, mime: "image/png", file: FILE, length: png.length });

  // shown as a page, the view is sent on so the page's links work; used in a page, it's simply the page
  expect(text(answer(zim, FILE, "Temperature", true))).toContain('location.replace("/Fever")');
  expect(text(answer(zim, FILE, "Temperature", false))).toContain("38 °C");
  expect(text(answer(zim, FILE, "", true))).toContain('location.replace("/Fever")');
  expect(text(answer(zim, FILE, "Water_purification", true))).toContain("<h1>Water</h1>");

  const lost = answer(zim, FILE, "Nowhere", true);
  expect(lost.status).toBe(404);
  expect(text(lost)).toContain("Not in this book");
  // metadata and the book's own lists aren't pages
  expect(answer(zim, FILE, "M/Title", false).status).toBe(404);
});

test("an older book's addresses name the namespace", () => {
  const zim = new Zim(book(pages("A"), { old: true, main: "Dehydration" }));
  expect(address(zim, zim.mainPage()!)).toBe("/A/Dehydration");
  expect(text(answer(zim, FILE, "A/Fever", true))).toContain("<h1>Fever</h1>");
  expect(answer(zim, FILE, "I/fever.png", false)).toMatchObject({ mime: "image/png", length: png.length });
  expect(text(answer(zim, FILE, "A/Temperature", true))).toContain('location.replace("/A/Fever")');
  expect(answer(zim, FILE, "Fever", true).status).toBe(404);
});

test("addresses are written so the page view reads them back as they were", () => {
  const zim = new Zim(book([{ ns: "C", path: "Café au lait/Notes #1", body: "<p>ok</p>" }], {}));
  const entry = zim.find("C", "Café au lait/Notes #1")!;
  expect(address(zim, entry)).toBe("/Caf%C3%A9%20au%20lait/Notes%20%231");
  expect(parse(`zim://b${address(zim, entry)}`)?.path).toBe("Café au lait/Notes #1");
});

// A book libzim made (tests/make_zims.py), when CI or a developer has built them
const real = process.env.ZIM_FIXTURES && join(process.env.ZIM_FIXTURES, "testmed_en_all_maxi_2026-01.zim");
(real && existsSync(real) ? test : test.skip)("a book libzim made reads as the reader asks for it", () => {
  const bytes = new Uint8Array(readFileSync(real!));
  const zim = new Zim({ size: bytes.length, read: (o, n) => bytes.subarray(o, o + n) });
  expect(text(answer(zim, real!, "", true))).toContain('location.replace("/Fever")');
  expect(text(answer(zim, real!, "Fever", true))).toContain("When to seek urgent help");
  expect(zim.titles("dehy").map((e) => address(zim, e))).toEqual(["/Dehydration"]);
  expect(text(answer(zim, real!, "Dehydration", true))).toContain("Oral rehydration solution");
});
