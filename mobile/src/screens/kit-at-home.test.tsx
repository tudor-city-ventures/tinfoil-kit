import { afterEach, expect, jest, test } from "@jest/globals";
import { act, render, screen, userEvent } from "@testing-library/react-native";

import { catalog } from "@/kit/catalog";
import { store } from "@/kit/store";

import { KitAtHome } from "./kit-at-home";

const mockKits = [{ name: "Kitchen Mac", host: "192.168.1.20", port: 8000 }];
jest.mock("expo-router", () => ({ Stack: { Screen: () => null } }));
jest.mock("../../modules/kit-files", () => ({ findKits: async () => mockKits }));

const book = catalog[0];
const zim = { path: `downloads/library/${book.id}_2026-10.zim`, bytes: 7e7, sha256: "cd".repeat(32) };
const listing = {
  name: "Kitchen Mac",
  books: [
    { id: book.id, title: book.title, group: book.group, why: book.why, files: [zim] },
    {
      id: "someones_own_book",
      title: "Someone's own",
      group: "",
      why: "",
      files: [{ path: "downloads/library/x.zim", bytes: 1 }],
    },
  ],
  map: null,
};
const asked: { url: string; auth?: string }[] = [];
global.fetch = jest.fn(async (url: string, init?: RequestInit) => {
  const auth = (init?.headers as Record<string, string>)?.Authorization;
  asked.push({ url, auth });
  return auth === "Bearer 48217736"
    ? new Response(JSON.stringify(listing), { status: 200 })
    : new Response(JSON.stringify({ error: "this needs the kit's access code" }), { status: 401 });
}) as unknown as typeof fetch;

afterEach(() => act(() => store.setHome(undefined)));

test("a kit found on the Wi-Fi lets the phone in with its code, then its books copy with a tap", async () => {
  const user = userEvent.setup();
  await render(<KitAtHome />);
  await user.press(await screen.findByTestId("kit-Kitchen Mac"));
  await user.type(screen.getByTestId("kit-code"), "1111 2222");
  await user.press(screen.getByTestId("kit-connect"));
  expect(await screen.findByText(/That code didn't work/)).toBeOnTheScreen();
  expect(store.get().home).toBeUndefined();

  await user.clear(screen.getByTestId("kit-code"));
  await user.type(screen.getByTestId("kit-code"), "4821 7736");
  await user.press(screen.getByTestId("kit-connect"));
  expect(await screen.findByText("Its books")).toBeOnTheScreen();
  expect(store.get().home).toEqual({ name: "Kitchen Mac", address: "192.168.1.20:8000", code: "48217736" });
  expect(asked.at(-1)).toEqual({ url: "http://192.168.1.20:8000/data/files", auth: "Bearer 48217736" });
  expect(screen.queryByText("Someone's own")).toBeNull(); // a book this app can't open

  await user.press(screen.getByTestId(`copy-get-${book.id}`));
  expect(store.get().items[book.id]).toMatchObject({ status: "queued", total: 7e7, from: zim });
});

test("a kit typed in: its address, or the link from Share with family, which has the code", async () => {
  const user = userEvent.setup();
  await render(<KitAtHome />);
  await user.press(await screen.findByTestId("kit-type"));
  await user.type(screen.getByTestId("kit-address"), "http://192.168.1.31:8001/?code=48217736");
  await user.press(screen.getByTestId("kit-connect"));
  expect(await screen.findByText("Its books")).toBeOnTheScreen();
  expect(store.get().home).toEqual({ name: "Kitchen Mac", address: "192.168.1.31:8001", code: "48217736" });
});
