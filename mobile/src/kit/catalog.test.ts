import { expect, test } from "@jest/globals";

import { buildCatalog, bytesOf, catalog, editions, starter } from "./catalog";

test("a phone looks for the smallest edition first", () => {
  expect(editions("wikipedia_en_all_maxi")).toEqual([
    "wikipedia_en_all_mini",
    "wikipedia_en_all_nopic",
    "wikipedia_en_all_maxi",
  ]);
  expect(editions("energypedia_en_all_nopic")).toEqual(["energypedia_en_all_mini", "energypedia_en_all_nopic"]);
  expect(editions("zimgit-water_en")).toEqual(["zimgit-water_en"]);
});

test("the catalog is the kit's library, switched-off books left out", () => {
  const books = buildCatalog(
    [{ zim: "a_en_all_maxi", starter: true }, { zim: "b_en" }, { zim: "c_en", enabled: false }, { zim: "unknown" }],
    [
      { id: "a_en_all_maxi", group: "Medical", title: "A", why: "Why A", bytes: 5e9 },
      { id: "b_en", group: "Reference", title: "B", why: "Why B", bytes: 2e8 },
      { id: "c_en", group: "Reference", title: "C", why: "Why C", bytes: 1e9 },
    ],
  );
  expect(books.map((b) => b.id)).toEqual(["a_en_all_maxi", "b_en"]);
  expect(books[0]).toMatchObject({ starter: true, bytes: undefined }); // a smaller edition may exist: sized later
  expect(books[1]).toMatchObject({ starter: false, bytes: 2e8 });
});

test("the real catalog has the try-it books and no AI models", () => {
  expect(catalog.length).toBeGreaterThan(20);
  expect(catalog.some((b) => b.group === "AI models")).toBe(false);
  expect(starter.map((b) => b.id)).toContain("zimgit-water_en");
  expect(bytesOf(starter)).toBeGreaterThan(1e8);
  expect(bytesOf(starter)).toBeLessThan(3e9);
});
