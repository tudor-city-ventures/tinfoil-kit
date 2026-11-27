import { expect, test } from "@jest/globals";

import { createStore, type Storage } from "./store";

function memory(text: string | null = null): Storage & { text: string | null } {
  const m = {
    text,
    read: async () => m.text,
    write: async (t: string) => {
      m.text = t;
    },
  };
  return m;
}

test("starts on the first screen, with mobile data off", async () => {
  const s = createStore(memory());
  await s.load();
  expect(s.loaded()).toBe(true);
  expect(s.get()).toEqual({ welcomed: false, cellular: false, items: {} });
});

test("the first screen queues the try-it kit, and every change is saved", async () => {
  const disk = memory();
  const s = createStore(disk);
  await s.load();
  s.welcome(["a", "b"]);
  expect(s.get().welcomed).toBe(true);
  expect(Object.keys(s.get().items)).toEqual(["a", "b"]);
  s.update("a", { status: "ready", received: 10, total: 10 });
  s.remove("b");
  s.setCellular(true);
  const again = createStore(disk);
  await again.load();
  expect(again.get()).toEqual({
    welcomed: true,
    cellular: true,
    items: { a: { status: "ready", received: 10, total: 10 } },
  });
});

test("an unreadable file starts over", async () => {
  const s = createStore(memory("{not json"));
  await s.load();
  expect(s.get().welcomed).toBe(false);
});

test("queueing twice keeps the first", async () => {
  const s = createStore(memory());
  await s.load();
  s.queue("a");
  s.update("a", { status: "downloading", received: 5 });
  s.queue("a");
  expect(s.get().items.a.status).toBe("downloading");
});
