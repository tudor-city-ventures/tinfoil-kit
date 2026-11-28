import { expect, test } from "@jest/globals";

import { checksum, findFile, parseCatalog } from "./kiwix";

const D = "https://download.kiwix.org/zim/wikipedia";

function entry(file: string, kib = 1024) {
  return `<entry>
    <id>urn:uuid:${file}</id>
    <title>${file}</title>
    <link type="text/html" href="/content/${file.slice(0, -4)}" />
    <link rel="http://opds-spec.org/acquisition/open-access" type="application/x-zim" href="${D}/${file}.meta4" length="${kib * 1024}" />
  </entry>`;
}

const feed = (...files: string[]) =>
  `<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom">${files.map((f) => entry(f)).join("")}</feed>`;

function server(pages: Record<string, string | number>) {
  const asked: string[] = [];
  const get = async (url: string) => {
    asked.push(url);
    const page = pages[url] ?? 404;
    if (page === -1) throw new TypeError("Network request failed");
    return { ok: typeof page === "string", status: typeof page === "number" ? page : 200, text: async () => `${page}` };
  };
  return { get, asked };
}

test("the catalog gives each book's newest file", () => {
  const books = parseCatalog(
    feed("wikipedia_en_medicine_mini_2026-03.zim", "wikipedia_en_medicine_mini_2026-10.zim", "notazim.txt"),
  );
  expect([...books.keys()]).toEqual(["wikipedia_en_medicine_mini"]);
  expect(books.get("wikipedia_en_medicine_mini")).toEqual({
    name: "wikipedia_en_medicine_mini",
    date: "2026-10",
    file: "wikipedia_en_medicine_mini_2026-10.zim",
    url: `${D}/wikipedia_en_medicine_mini_2026-10.zim`,
    bytes: 1024 * 1024,
  });
});

test("a book comes in its smallest published edition", async () => {
  const cat = "https://library.kiwix.org/catalog/v2/entries?name=";
  const { get, asked } = server({
    [`${cat}wikipedia_en_medicine_mini`]: feed(),
    [`${cat}wikipedia_en_medicine_nopic`]: feed("wikipedia_en_medicine_nopic_2026-10.zim"),
  });
  const file = await findFile(["wikipedia_en_medicine_mini", "wikipedia_en_medicine_nopic"], get);
  expect(file?.file).toBe("wikipedia_en_medicine_nopic_2026-10.zim");
  expect(asked).toHaveLength(2);
  await expect(findFile(["wikipedia_en_medicine_mini"], get)).resolves.toBeUndefined();
  await expect(findFile(["gone"], get)).rejects.toThrow("Kiwix's catalog answered 404");
});

test("the SHA-256 comes from the .sha256, else the .meta4", async () => {
  const url = `${D}/wikipedia_en_medicine_mini_2026-10.zim`;
  const sum = "AB".repeat(32);
  expect(await checksum(url, server({ [`${url}.sha256`]: `${sum}  file.zim\n` }).get)).toBe(sum.toLowerCase());
  const meta4 = `<metalink><file><hash type="md5">x</hash><hash type="sha-256">${sum}</hash></file></metalink>`;
  expect(await checksum(url, server({ [`${url}.meta4`]: meta4 }).get)).toBe(sum.toLowerCase());
  expect(await checksum(url, server({}).get)).toBeUndefined();
  await expect(checksum(url, server({ [`${url}.sha256`]: -1 }).get)).rejects.toThrow("Network request failed");
});
