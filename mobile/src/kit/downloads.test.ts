import { afterEach, beforeEach, expect, jest, test } from "@jest/globals";

import type { BookOptions, BookState } from "../../modules/kit-files";

import { catalog } from "./catalog";
import { createDownloads, type Phone } from "./downloads";
import { createStore } from "./store";

const [a, b, c] = catalog;
const SUM = "ab".repeat(32);
const zim = (id: string) => `${catalog.find((x) => x.id === id)!.editions[0]}_2026-10.zim`;

// The phone's downloader and its records: what it has is what books() lists, until stopped or forgotten.
function fakePhone() {
  const phone = {
    library: "/docs/library",
    online: true,
    published: true,
    space: 100e9,
    failing: undefined as string | undefined, // why start() fails
    started: [] as BookOptions[],
    stopped: [] as string[],
    forgotten: [] as string[],
    has: new Map<string, BookState>(),
    files: new Set<string>(),
    start: async (o: BookOptions) => {
      if (phone.failing) throw new Error(phone.failing);
      phone.started.push(o);
      phone.has.set(o.id, { id: o.id, book: o.book, state: "downloading", cellular: o.cellular, received: 0 });
    },
    stop: (id: string) => {
      phone.stopped.push(id);
      phone.has.delete(id);
    },
    forget: (id: string) => {
      phone.forgotten.push(id);
      phone.has.delete(id);
    },
    books: async () => [...phone.has.values()],
    find: async (editions: string[]) => {
      if (!phone.online) throw new TypeError("Network request failed");
      const name = editions[0];
      return phone.published
        ? { name, date: "2026-10", file: `${name}_2026-10.zim`, url: `https://k/${name}.zim`, bytes: 5e8 }
        : undefined;
    },
    checksum: async () => SUM,
    free: () => phone.space,
    exists: (p: string) => phone.files.has(p),
  };
  return phone;
}

type FakePhone = ReturnType<typeof fakePhone>;

const settle = () => new Promise<void>((r) => setImmediate(() => r()));

// Time passes, long enough for the app to look at the downloads again
async function later(ms = 1000) {
  await jest.advanceTimersByTimeAsync(ms);
  await settle();
}

// The phone's downloader moves one on
function set(phone: FakePhone, id: string, to: Partial<BookState>) {
  phone.has.set(id, { ...phone.has.get(id)!, ...to });
}

async function setup(state = {}) {
  const store = createStore({ read: async () => JSON.stringify(state), write: async () => {} });
  await store.load();
  const phone = fakePhone();
  const downloads = createDownloads(store, phone as Phone);
  return { store, phone, downloads };
}

beforeEach(() => {
  jest.useFakeTimers({ doNotFake: ["queueMicrotask", "nextTick", "setImmediate"] });
});
afterEach(() => {
  jest.useRealTimers();
});

test("a book downloads over Wi-Fi only, then the phone checks it and puts it on the shelf", async () => {
  const { store, phone, downloads } = await setup();
  await downloads.start();
  store.queue(a.id);
  await settle();
  const [o] = phone.started;
  expect(o).toMatchObject({
    book: a.id,
    title: a.title,
    url: `https://k/${a.editions[0]}.zim`,
    incoming: `/docs/library/incoming/${zim(a.id)}`,
    path: `/docs/library/${zim(a.id)}`,
    sha256: SUM,
    cellular: false,
  });
  expect(store.get().items[a.id]).toMatchObject({ status: "downloading", total: 5e8, sha256: SUM, task: o.id });

  set(phone, o.id, { received: 2e8, total: 4.9e8 });
  await later();
  expect(store.get().items[a.id]).toMatchObject({ status: "downloading", received: 2e8, total: 4.9e8 });

  set(phone, o.id, { state: "downloaded" });
  await later();
  expect(store.get().items[a.id]).toMatchObject({ status: "checking", received: 4.9e8 });

  set(phone, o.id, { state: "ready" });
  await later();
  expect(store.get().items[a.id]).toMatchObject({ status: "ready", received: 4.9e8, file: zim(a.id), task: undefined });
  expect(phone.forgotten).toEqual([o.id]);
  await later();
  expect(jest.getTimerCount()).toBe(0); // nothing going: it stops looking
});

test("a download that failed says why, and can be tried again", async () => {
  const { store, phone, downloads } = await setup();
  await downloads.start();
  store.queue(a.id);
  await settle();
  set(phone, phone.started[0].id, { state: "failed", error: "It came through damaged" });
  await later();
  expect(store.get().items[a.id]).toMatchObject({
    status: "failed",
    error: "It came through damaged",
    task: undefined,
  });
  expect(phone.forgotten).toEqual([phone.started[0].id]);

  store.retry(a.id);
  await settle();
  expect(phone.started).toHaveLength(2);
  expect(store.get().items[a.id]).toMatchObject({ status: "downloading", task: phone.started[1].id });
});

test("a book waits while Kiwix can't be reached, and asks again", async () => {
  const { store, phone, downloads } = await setup();
  await downloads.start();
  phone.online = false;
  store.queue(a.id);
  await settle();
  expect(store.get().items[a.id].status).toBe("queued");
  phone.online = true;
  store.queue(b.id); // other changes don't make it ask again straight away
  await settle();
  expect(phone.started.map((o) => o.book)).toEqual([b.id]);
  downloads.wake(); // back in the app, or another network
  await settle();
  expect(phone.started.map((o) => o.book)).toEqual([b.id, a.id]);
});

test("allowing mobile data starts the downloads again with it, and so does taking it away", async () => {
  const { store, phone, downloads } = await setup();
  await downloads.start();
  store.queue(a.id);
  await settle();
  store.setCellular(true);
  await later();
  expect(phone.stopped).toEqual([phone.started[0].id]);
  expect(phone.started[1]).toMatchObject({ book: a.id, cellular: true });
  store.setCellular(false);
  await later();
  expect(phone.stopped).toEqual([phone.started[0].id, phone.started[1].id]);
  expect(phone.started[2]).toMatchObject({ book: a.id, cellular: false });
});

test("a removed book's download stops", async () => {
  const { store, phone, downloads } = await setup();
  await downloads.start();
  store.queue(a.id);
  await settle();
  store.remove(a.id);
  await later();
  expect(phone.stopped).toEqual([phone.started[0].id]);
});

test("what Kiwix doesn't publish, doesn't fit, or the phone can't start, stops with the reason", async () => {
  const { store, phone, downloads } = await setup();
  await downloads.start();
  phone.published = false;
  store.queue(a.id);
  await settle();
  expect(store.get().items[a.id]).toMatchObject({ status: "failed", error: "Kiwix doesn't publish it at the moment" });
  phone.published = true;
  phone.space = 9e8;
  store.queue(b.id);
  await settle();
  expect(store.get().items[b.id]).toMatchObject({ status: "failed", error: "Not enough free space for its 500 MB" });
  phone.space = 100e9;
  phone.failing = "Not a web address";
  store.queue(c.id);
  await settle();
  expect(store.get().items[c.id]).toMatchObject({ status: "failed", error: "Not a web address", task: undefined });
  expect(phone.started).toHaveLength(0);
});

test("on the next start: what finished while the app was closed is taken in, lost downloads start again", async () => {
  const item = { received: 1, total: 5e8, sha256: SUM };
  const { store, phone, downloads } = await setup({
    welcomed: true,
    cellular: false,
    items: {
      [a.id]: { ...item, status: "downloading", file: zim(a.id), task: "a@2" },
      [b.id]: { ...item, status: "downloading", file: zim(b.id), task: "b@1" },
      [c.id]: { ...item, status: "checking", file: zim(c.id), task: "c@1" },
    },
  });
  const done = { book: a.id, cellular: false };
  phone.has.set("a@2", { ...done, id: "a@2", state: "ready" });
  phone.has.set("a@1", { ...done, id: "a@1", state: "failed", error: "Stopped" }); // an earlier try's outcome
  phone.has.set("x@1", { id: "x@1", book: "gone", state: "downloading", cellular: false });
  phone.files.add(`/docs/library/${zim(c.id)}`); // filed just before its record was written

  await downloads.start();
  await settle();
  expect(store.get().items[a.id]).toMatchObject({ status: "ready", received: 5e8 });
  expect(store.get().items[c.id]).toMatchObject({ status: "ready", received: 5e8 });
  expect(phone.forgotten.sort()).toEqual(["a@1", "a@2"]);
  expect(phone.stopped).toEqual(["x@1"]);
  expect(phone.started.map((o) => o.book)).toEqual([b.id]); // b's download was lost: it starts over
  expect(store.get().items[b.id]).toMatchObject({ status: "downloading", task: phone.started[0].id });
});
