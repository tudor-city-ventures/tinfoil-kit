import { afterEach, expect, jest, test } from "@jest/globals";
import { act, fireEvent, render, screen, userEvent } from "@testing-library/react-native";
import { Alert } from "react-native";

import { catalog } from "@/kit/catalog";
import { fake, faked, tapper } from "@/kit/qa";
import { store } from "@/kit/store";

import { Testing } from "./testing";

const mockRemoved: string[] = [];
const mockEmptied: string[] = [];

jest.mock("expo-router", () => ({ Stack: { Screen: () => null } }));
jest.mock("@/kit/downloads", () => ({
  libraryPath: () => "/docs/library",
  removeBook: (id: string) => {
    mockRemoved.push(id);
    jest.requireActual<typeof import("@/kit/store")>("@/kit/store").store.remove(id);
  },
}));
jest.mock("@/kit/maps", () => ({ mapsPath: () => "/docs/maps" }));
jest.mock("expo-file-system", () => ({
  Paths: { cache: { uri: "file:///caches/" } },
  Directory: class {
    exists = true;
    uri: string;
    constructor(uri: string) {
      this.uri = uri;
    }
    list() {
      return [{ delete: () => void mockEmptied.push(this.uri) }];
    }
  },
}));

const [one, two] = catalog;

afterEach(async () => {
  mockRemoved.length = mockEmptied.length = 0;
  fake({ ai: undefined, full: false, failing: false });
  await act(async () => store.startOver(false));
  jest.restoreAllMocks();
});

test("seven taps in a row open the menu; a pause starts the count again", () => {
  let now = 0;
  jest.spyOn(Date, "now").mockImplementation(() => now);
  const open = jest.fn();
  const tap = tapper(open);
  const taps = (n: number, apart: number) => {
    for (let i = 0; i < n; i++) {
      now += apart;
      tap();
    }
  };
  taps(6, 300);
  taps(1, 2000); // too slow: this one counts as the first
  expect(open).not.toHaveBeenCalled();
  taps(6, 300);
  expect(open).toHaveBeenCalledTimes(1);
});

test("it says what the build is, and pretends what the menu says", async () => {
  await render(<Testing />);
  expect(screen.getByText(/^Tinfoil Kit/)).toBeOnTheScreen();
  expect(screen.getByText("The internet: Kiwix, Protomaps and kits")).toBeOnTheScreen();
  const user = userEvent.setup();
  await user.press(screen.getByText("Ready, but every answer fails"));
  expect(faked().ai).toBe("failing");
  await act(async () => fireEvent(screen.getByTestId("fake-full"), "valueChange", true));
  expect(faked().full).toBe(true);
  await user.press(screen.getByText("As it is"));
  expect(faked().ai).toBeUndefined();
});

test("reset everything, once you say so, leaves the phone as a fresh install has it", async () => {
  await act(async () => {
    store.welcome([one.id, two.id]);
    store.setCellular(true);
    store.mapReady("us/alabama", "us-alabama-20261127.pmtiles");
  });
  const alert = jest.spyOn(Alert, "alert");
  await render(<Testing />);
  await userEvent.setup().press(screen.getByTestId("reset-all"));
  expect(store.get().items[one.id]).toBeDefined(); // not until it's confirmed
  const buttons = alert.mock.calls[0][2]!;
  expect(buttons.map((b) => b.text)).toEqual(["Cancel", "Reset"]);
  await act(async () => buttons[1].onPress!());
  expect(mockRemoved.sort()).toEqual([one.id, two.id].sort());
  expect(mockEmptied).toEqual(expect.arrayContaining(["file:///docs/library", "file:///docs/maps", "file:///caches/"]));
  expect(store.get()).toEqual({ welcomed: false, cellular: false, items: {} });
});

test("the first screen again keeps the books", async () => {
  await act(async () => store.welcome([one.id]));
  const alert = jest.spyOn(Alert, "alert");
  await render(<Testing />);
  await userEvent.setup().press(screen.getByTestId("first-screen"));
  await act(async () => alert.mock.calls[0][2]![1].onPress!());
  expect(store.get().welcomed).toBe(false);
  expect(store.get().items[one.id]).toBeDefined();
});
