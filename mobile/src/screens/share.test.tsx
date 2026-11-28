import { afterEach, expect, jest, test } from "@jest/globals";
import { act, render, screen, userEvent } from "@testing-library/react-native";

import type { ShareOptions, Sharing } from "../../modules/kit-files";
import { catalog } from "@/kit/catalog";
import { store } from "@/kit/store";

import { Share } from "./share";

const mockPhone = {
  started: [] as ShareOptions[],
  stops: 0,
  state: { on: true, port: 8000, addresses: ["192.168.1.31"], sent: 0, copying: 0, stopped: "" } as Sharing,
  codes: ["48217736", "11112222"],
};
jest.mock("expo-router", () => ({ Stack: { Screen: () => null } }));
jest.mock("expo-keep-awake", () => ({ activateKeepAwakeAsync: async () => {}, deactivateKeepAwake: async () => {} }));
jest.mock("../../modules/kit-files", () => ({
  startSharing: async (o: ShareOptions) => {
    mockPhone.started.push(o);
    return 8000;
  },
  stopSharing: () => void mockPhone.stops++,
  sharing: () => mockPhone.state,
  newCode: () => mockPhone.codes.shift(),
}));
jest.mock("@/kit/downloads", () => ({ libraryPath: () => "/docs/library" }));
jest.mock("@/kit/maps", () => ({ mapsPath: () => "/docs/maps" }));
// every file the screen looks for is there, at 70 MB
jest.mock("expo-file-system", () => ({
  ...jest.requireActual<object>("expo-file-system"),
  File: class {
    exists = true;
    size = 7e7;
  },
}));

const book = catalog[0];

afterEach(() => act(() => store.remove(book.id)));

test("while the screen is open, the phone shares its books and map with its code, and stops when it's left", async () => {
  await act(async () => {
    store.welcome([book.id]);
    store.update(book.id, { status: "ready", file: `${book.id}_2026-10.zim`, sha256: "ab".repeat(32) });
    store.mapReady("us/alabama", "us-alabama-20261127.pmtiles");
  });
  const { unmount } = await render(<Share />);
  expect(await screen.findByText("4821 7736")).toBeOnTheScreen();
  expect(store.get().shareCode).toBe("48217736");
  const o = mockPhone.started.at(-1)!;
  expect(o).toMatchObject({ name: "iPhone", code: "48217736", folders: { "maps/style": "/docs/maps/style" } });
  expect(o.files).toEqual({
    [`library/${book.id}_2026-10.zim`]: `/docs/library/${book.id}_2026-10.zim`,
    "maps/us-alabama-20261127.pmtiles": "/docs/maps/us-alabama-20261127.pmtiles",
  });
  expect(JSON.parse(o.listing)).toMatchObject({ name: "iPhone", phone: true, books: [{ id: book.id }] });
  expect(screen.getByText(book.title)).toBeOnTheScreen();
  expect(screen.getByText("Map of Alabama")).toBeOnTheScreen();
  // once it has looked at how it's going: that it's sharing, and where the other phone finds it
  expect(await screen.findByTestId("share-on", {}, { timeout: 3000 })).toBeOnTheScreen();
  expect(screen.getByText("Sharing as iPhone")).toBeOnTheScreen();
  expect(await screen.findByText(/type 192\.168\.1\.31, then type this code/, {}, { timeout: 3000 })).toBeOnTheScreen();

  const stops = mockPhone.stops;
  await act(async () => unmount());
  expect(mockPhone.stops).toBe(stops + 1);
});

test("after 10 wrong codes it stops, and shares again with a new code", async () => {
  const user = userEvent.setup();
  mockPhone.state = { ...mockPhone.state, on: false, stopped: "tries" };
  await render(<Share />);
  await user.press(await screen.findByTestId("share-again", {}, { timeout: 3000 }));
  expect(store.get().shareCode).toBe("11112222");
  expect(await screen.findByText("1111 2222")).toBeOnTheScreen();
  expect(mockPhone.started.at(-1)?.code).toBe("11112222");
});
