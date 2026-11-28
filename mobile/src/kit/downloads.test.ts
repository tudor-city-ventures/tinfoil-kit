import { afterEach, beforeEach, expect, jest, test } from "@jest/globals";

import { catalog } from "./catalog";
import { createDownloads, type Phone, type Task } from "./downloads";
import { createStore } from "./store";

jest.mock("@kesha-antonov/react-native-background-downloader", () => ({}));

const [a, b] = catalog;
const SUM = "ab".repeat(32);

class FakeTask implements Task {
  state = "PENDING";
  bytesDownloaded = 0;
  bytesTotal = 0;
  stopped = false;
  handlers: Record<string, (p: never) => void> = {};
  constructor(
    public id: string,
    public metadata: Record<string, unknown>,
    public path = "",
  ) {}
  progress(h: (p: { bytesDownloaded: number; bytesTotal: number }) => void) {
    this.handlers.progress = h;
    return this;
  }
  done(h: () => void) {
    this.handlers.done = h;
    return this;
  }
  error(h: (e: { error: string }) => void) {
    this.handlers.error = h;
    return this;
  }
  start() {
    this.state = "DOWNLOADING";
  }
  async resume() {}
  async stop() {
    this.stopped = true;
  }
}

function fakePhone() {
  const files = new Map<string, string>(); // path: its SHA-256
  const tasks: FakeTask[] = [];
  const phone = {
    library: "/docs/library",
    online: true,
    published: true,
    space: 100e9,
    old: [] as FakeTask[],
    tasks,
    files,
    completed: [] as string[],
    download: (o: { id: string; path: string; book: string; cellular: boolean }) => {
      const t = new FakeTask(o.id, { book: o.book, cellular: o.cellular }, o.path);
      tasks.push(t);
      return t;
    },
    existing: async () => phone.old,
    complete: (id: string) => void phone.completed.push(id),
    find: async (editions: string[]) => {
      if (!phone.online) throw new TypeError("Network request failed");
      const name = editions[0];
      return phone.published
        ? { name, date: "2026-10", file: `${name}_2026-10.zim`, url: `https://k/${name}.zim`, bytes: 5e8 }
        : undefined;
    },
    checksum: async () => SUM,
    free: () => phone.space,
    exists: (p: string) => files.has(p),
    sha256: async (p: string) => files.get(p)!,
    move: async (from: string, to: string) => {
      files.set(to, files.get(from)!);
      files.delete(from);
    },
    remove: (p: string) => void files.delete(p),
  };
  return phone;
}

const settle = () => new Promise<void>((r) => setImmediate(() => r()));

async function setup(state = {}) {
  const store = createStore({ read: async () => JSON.stringify(state), write: async () => {} });
  await store.load();
  const phone = fakePhone();
  const downloads = createDownloads(store, phone as Phone);
  return { store, phone, downloads };
}

// The task finishes: its file lands where it was told to go, with this checksum.
function finish(phone: ReturnType<typeof fakePhone>, task: FakeTask, sum = SUM) {
  phone.files.set(task.path, sum);
  task.handlers.done(undefined as never);
}

beforeEach(() => {
  jest.useFakeTimers({ doNotFake: ["queueMicrotask", "nextTick", "setImmediate"] });
});
afterEach(() => {
  jest.useRealTimers();
});

test("a book downloads over Wi-Fi only, then is checked and put on the shelf", async () => {
  const { store, phone, downloads } = await setup();
  await downloads.start();
  store.queue(a.id);
  await settle();
  const [task] = phone.tasks;
  expect(task.metadata).toEqual({ book: a.id, cellular: false });
  expect(task.path).toBe(`/docs/library/incoming/${a.editions[0]}_2026-10.zim`);
  expect(task.state).toBe("DOWNLOADING");
  expect(store.get().items[a.id]).toMatchObject({ status: "downloading", total: 5e8, sha256: SUM, task: task.id });

  task.handlers.progress({ bytesDownloaded: 2e8, bytesTotal: 4.9e8 } as never);
  expect(store.get().items[a.id]).toMatchObject({ received: 2e8, total: 4.9e8 });

  finish(phone, task);
  await settle();
  const file = `${a.editions[0]}_2026-10.zim`;
  expect(store.get().items[a.id]).toMatchObject({ status: "ready", received: 4.9e8, file });
  expect([...phone.files.keys()]).toEqual([`/docs/library/${file}`]);
  expect(phone.completed).toEqual([task.id]);
});

test("a damaged download is thrown away and can be tried again", async () => {
  const { store, phone, downloads } = await setup();
  await downloads.start();
  store.queue(a.id);
  await settle();
  finish(phone, phone.tasks[0], "00".repeat(32));
  await settle();
  expect(store.get().items[a.id]).toMatchObject({ status: "failed", error: "It came through damaged" });
  expect(phone.files.size).toBe(0);

  store.retry(a.id);
  await settle();
  expect(phone.tasks).toHaveLength(2);
  expect(store.get().items[a.id].status).toBe("downloading");
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
  expect(phone.tasks.map((t) => t.metadata.book)).toEqual([b.id]);
  downloads.wake(); // back in the app, or another network
  await settle();
  expect(phone.tasks.map((t) => t.metadata.book)).toEqual([b.id, a.id]);
});

test("allowing mobile data starts the downloads again with it, and so does taking it away", async () => {
  const { store, phone, downloads } = await setup();
  await downloads.start();
  store.queue(a.id);
  await settle();
  store.setCellular(true);
  await settle();
  expect(phone.tasks[0].stopped).toBe(true);
  expect(phone.tasks[1].metadata).toEqual({ book: a.id, cellular: true });
  store.setCellular(false);
  await settle();
  expect(phone.tasks[1].stopped).toBe(true);
  expect(phone.tasks[2].metadata.cellular).toBe(false);
});

test("what Kiwix doesn't publish, or doesn't fit, stops with the reason", async () => {
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
  expect(phone.tasks).toHaveLength(0);
});

test("on the next start: finished downloads are checked, lost ones start again, strays are stopped", async () => {
  const item = { received: 1, total: 5e8, sha256: SUM };
  const { store, phone, downloads } = await setup({
    welcomed: true,
    cellular: false,
    items: {
      [a.id]: { ...item, status: "downloading", file: "a_2026-10.zim", task: "a@1" },
      [b.id]: { ...item, status: "downloading", file: "b_2026-10.zim", task: "b@1" },
    },
  });
  const done = new FakeTask("a@1", { book: a.id, cellular: false });
  done.state = "DONE";
  const stray = new FakeTask("x@1", { book: "gone", cellular: false });
  stray.state = "DOWNLOADING";
  phone.old = [done, stray];
  phone.files.set("/docs/library/incoming/a_2026-10.zim", SUM);

  await downloads.start();
  await settle();
  expect(store.get().items[a.id].status).toBe("ready");
  expect(phone.files.has("/docs/library/a_2026-10.zim")).toBe(true);
  expect(stray.stopped).toBe(true);
  expect(phone.tasks.map((t) => t.metadata.book)).toEqual([b.id]); // b's download was lost: it starts over
  expect(store.get().items[b.id]).toMatchObject({ status: "downloading", task: phone.tasks[0].id });
});
