import { beforeEach, expect, jest, test } from "@jest/globals";

import { catalog } from "@/kit/catalog";
import { store } from "@/kit/store";
import { book, type Item } from "@/kit/test-zim";
import { Zim, type Source } from "@/kit/zim";

import { addFile, describe, identify } from "./add";

const mockBooks = new Map<string, Source>(); // what each file the app adds turns out to be
const mockMoved: string[][] = [];
const mockRemoved: string[] = [];
const mockAdd = jest.fn<(from: string, to: string) => Promise<number>>();

jest.mock("../../modules/kit-files", () => ({
  addBook: (from: string, to: string) => mockAdd(from, to),
  adding: () => ({ done: 0, total: 0 }),
  moveBook: (from: string, to: string) => mockMoved.push([from, to]),
}));
jest.mock("@/kit/downloads", () => ({
  libraryPath: () => "/library",
  removeBook: (id: string) => {
    mockRemoved.push(id);
    jest.requireActual<typeof import("@/kit/store")>("@/kit/store").store.remove(id);
  },
}));
jest.mock("@/kit/books", () => {
  const { Zim } = jest.requireActual<typeof import("@/kit/zim")>("@/kit/zim");
  return { openBook: (path: string) => new Zim(mockBooks.get(path)!), closeBook: () => {} };
});

const wikipedia = catalog.find((b) => b.id === "wikipedia_en_all_maxi")!;
const knots = catalog.find((b) => b.id === "zimgit-knots_en")!;

// A book with these names for itself
const named = (meta: Record<string, string>) =>
  book([
    ...Object.entries(meta).map(([path, body]): Item => ({ ns: "M", path, body, mime: "text/plain" })),
    { ns: "C", path: "Knot", body: "<p>A knot</p>" },
  ]);

// The phone's native code takes the file and checks it; this is what it turns out to be
function sends(source: Source, size = 4e8) {
  mockAdd.mockImplementationOnce(async (_from, to) => {
    mockBooks.set(to, source);
    return size;
  });
}

beforeEach(() => {
  jest.spyOn(store, "loaded").mockReturnValue(true);
  for (const id of Object.keys(store.get().items)) store.remove(id);
  mockMoved.length = 0;
  mockRemoved.length = 0;
});

test("a book is known by the name it gives itself, with its edition, else by its file's name", () => {
  // Kiwix's books name themselves without the edition, which they give as their flavour
  const zim = new Zim(named({ Name: "wikipedia_en_all", Flavour: "nopic", Date: "2026-10-01" }));
  expect(identify(zim, "Wikipedia (1).zim")).toEqual({ id: wikipedia.id, file: "wikipedia_en_all_nopic_2026-10.zim" });
  expect(identify(new Zim(named({ Name: "wikipedia_en_all_mini" })), "x.zim")?.id).toBe(wikipedia.id);
  expect(identify(new Zim(named({ Name: "zimgit-knots_en" })), "zimgit-knots_en_2026-03.zim")).toEqual({
    id: knots.id,
    file: "zimgit-knots_en_2026-03.zim",
  });
  expect(identify(new Zim(named({})), "zimgit-knots_en_2026-03.zim")?.id).toBe(knots.id);
  expect(identify(new Zim(named({ Name: "someone_elses_book" })), "someone_elses_book_2026-01.zim")).toBeUndefined();
});

test("a book from a file goes in the library, named as Kiwix names it, and replaces its download", async () => {
  store.queue(knots.id); // waiting for Wi-Fi
  sends(named({ Name: "zimgit-knots_en", Date: "2026-03-05" }), 7e7);
  const got = await addFile("file:///tmp/Inbox/Knots.zim", "Knots.zim");
  expect(got).toEqual({ added: knots.id });
  expect(mockAdd).toHaveBeenLastCalledWith(
    "file:///tmp/Inbox/Knots.zim",
    expect.stringMatching(/^\/library\/adding\//),
  );
  expect(mockRemoved).toEqual([knots.id]); // its download stops
  expect(mockMoved).toEqual([[mockAdd.mock.calls.at(-1)![1], "/library/zimgit-knots_en_2026-03.zim"]]);
  expect(store.get().items[knots.id]).toEqual({
    status: "ready",
    file: "zimgit-knots_en_2026-03.zim",
    received: 7e7,
    total: 7e7,
  });
  expect(describe(got)[0]).toBe(`${knots.title} is on this phone`);

  // The same again, or an older one, leaves the phone's copy be; a newer one takes its place
  sends(named({ Name: "zimgit-knots_en", Date: "2026-01-01" }));
  expect(await addFile("content://downloads/1", "zimgit-knots_en_2026-01.zim")).toEqual({ have: knots.id });
  expect(mockMoved).toHaveLength(1);
  sends(named({ Name: "zimgit-knots_en", Date: "2026-06-01" }), 8e7);
  expect(await addFile("content://downloads/2", "zimgit-knots_en_2026-06.zim")).toEqual({ added: knots.id });
  expect(mockMoved.at(-1)![1]).toBe("/library/zimgit-knots_en_2026-06.zim");
  expect(store.get().items[knots.id]).toMatchObject({
    status: "ready",
    file: "zimgit-knots_en_2026-06.zim",
    total: 8e7,
  });
});

test("a file that isn't one of the app's books, or came through damaged, stays out", async () => {
  sends(named({ Name: "someone_elses_book" }));
  const other = await addFile("content://downloads/3", "someone_elses_book_2026-01.zim");
  expect(other).toEqual({ refused: "not-ours" });
  expect(describe(other)).toEqual(["That book isn't one of Tinfoil Kit's", "Tinfoil Kit takes the books in Get more."]);
  for (const [code, refused] of [
    ["ERR_NOT_A_BOOK", "not-a-book"],
    ["ERR_DAMAGED", "damaged"],
    ["ERR_FILE", "failed"],
  ]) {
    mockAdd.mockRejectedValueOnce(Object.assign(new Error(code), { code }));
    expect(await addFile("content://downloads/4", "x.zim")).toEqual({ refused });
  }
  expect(mockMoved).toHaveLength(0);
  expect(store.get().items).toEqual({});
});
