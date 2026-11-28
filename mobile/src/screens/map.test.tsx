import { expect, jest, test } from "@jest/globals";
import { act, render, screen, userEvent } from "@testing-library/react-native";
import type { ReactElement, ReactNode, Ref } from "react";
import { Linking } from "react-native";

import { place } from "@/kit/places";
import { store } from "@/kit/store";

import { MapScreen } from "./map";

type Options = {
  headerShown?: boolean;
  headerSearchBarOptions?: { onChangeText(e: { nativeEvent: { text: string } }): void };
  headerRight?: () => ReactElement<{ onPress(): void }>;
};
let mockOptions: Options = {};
type MockFix = { coords: { longitude: number; latitude: number } };
type MockMapProps = {
  testID: string;
  mapStyle: { sources: { protomaps: { url: string } } };
  onDidFailLoadingMap(): void;
  children?: ReactNode;
};
let mockGranted = true; // what the person answers when asked for their location
let mockListener: ((at: MockFix) => void) | undefined; // waiting for the phone's next fix
const mockFly = jest.fn();

// The stack's header, as the screen sets it; the map as a plain view that says which file it shows, the camera as
// where it was sent, and the person's dot as a word
jest.mock("expo-router", () => ({
  Stack: { Screen: ({ options }: { options: Options }) => ((mockOptions = options), null) },
}));
jest.mock("@maplibre/maplibre-react-native", () => {
  const { createElement, Fragment, useImperativeHandle } = jest.requireActual<typeof import("react")>("react");
  const { Text } = jest.requireActual<typeof import("react-native")>("react-native");
  return {
    Map: (p: MockMapProps) =>
      createElement(
        Fragment,
        null,
        createElement(Text, { testID: p.testID, onPress: p.onDidFailLoadingMap }, p.mapStyle.sources.protomaps.url),
        p.children,
      ),
    Camera: ({ ref }: { ref: Ref<unknown> }) => (useImperativeHandle(ref, () => ({ flyTo: mockFly })), null),
    NativeUserLocation: () => createElement(Text, null, "(you)"),
    LocationManager: {
      requestPermissions: async () => mockGranted,
      addListener: (f: (at: MockFix) => void) => void (mockListener = f),
      removeListener: () => void (mockListener = undefined),
    },
  };
});
jest.mock(
  "react-native-safe-area-context",
  () => jest.requireActual<{ default: object }>("react-native-safe-area-context/jest/mock").default,
);

test("pick where you live, watch its map come, then see it, and pick another", async () => {
  const user = userEvent.setup();
  await render(<MapScreen />);
  expect(screen.getByText(/^Where do you live\?/)).toBeOnTheScreen();
  expect(screen.getByText("Alabama")).toBeOnTheScreen();

  await act(() => mockOptions.headerSearchBarOptions!.onChangeText({ nativeEvent: { text: "rhode" } }));
  expect(screen.queryByText("Alabama")).toBeNull();
  await user.press(screen.getByText("Rhode Island"));
  expect(store.get().mapDownload).toMatchObject({ place: "us/rhode-island", status: "queued" });
  expect(screen.getByText("Starting")).toBeOnTheScreen();

  await act(() => store.updateMap({ status: "downloading", received: 1e8, total: 2.72e8 }));
  expect(screen.getByText("100 MB of 272 MB")).toBeOnTheScreen();
  expect(screen.getByText("36%")).toBeOnTheScreen();
  await act(() => store.updateMap({ waiting: "wifi" }));
  expect(screen.getByText("Waiting for Wi-Fi · 100 MB of 272 MB")).toBeOnTheScreen();
  await act(() => store.updateMap({ status: "failed", waiting: undefined, error: "The map came through damaged." }));
  await user.press(screen.getByText("Stopped: The map came through damaged. Tap to try again."));
  expect(store.get().mapDownload).toEqual({ place: "us/rhode-island", status: "queued", received: 0, total: 0 });

  await act(() => store.mapReady("us/rhode-island", "us-rhode-island-20261127.pmtiles"));
  expect(mockOptions.headerShown).toBe(false);
  expect(screen.getByTestId("map")).toHaveTextContent(/^pmtiles:\/\/file:\/\/.*\/us-rhode-island-20261127\.pmtiles$/);

  await user.press(screen.getByTestId("map")); // the stand-in map fails to draw
  await user.press(screen.getByText("This map can't be shown. Tap to get it again."));
  expect(store.get().mapDownload).toMatchObject({ place: "us/rhode-island", status: "queued" });
  await act(() => store.stopMap());

  await user.press(screen.getByRole("button", { name: "Rhode Island" }));
  expect(screen.getByText("On your phone")).toBeOnTheScreen();
  await act(() => mockOptions.headerRight!().props.onPress()); // Cancel
  expect(screen.getByTestId("map")).toBeOnTheScreen();

  await user.press(screen.getByRole("button", { name: "Rhode Island" }));
  expect(screen.getByText("Yours is from November 27, 2026.")).toBeOnTheScreen();
  await user.press(screen.getByText("Rhode Island")); // its own place: back to its map, and nothing downloads
  expect(store.get().mapDownload).toBeUndefined();
  expect(screen.getByTestId("map")).toBeOnTheScreen();
  await user.press(screen.getByRole("button", { name: "Rhode Island" }));
  await user.press(screen.getByText("Get the newest map of Rhode Island"));
  expect(store.get().mapDownload).toMatchObject({ place: "us/rhode-island", status: "queued" });
  await act(() => store.stopMap());

  await user.press(screen.getByRole("button", { name: "Rhode Island" }));
  await user.press(screen.getByText("Alabama"));
  expect(store.get().mapDownload).toMatchObject({ place: "us/alabama" });
  expect(screen.getByText("Alabama: Starting")).toBeOnTheScreen(); // over Rhode Island's map, until Alabama's is here
}, 20_000); // the whole of it, step by step: longer than a test's usual 5 seconds on a busy runner

test("where you are: asked for once, then the map goes there, or says you're outside its place", async () => {
  const user = userEvent.setup();
  await act(() => store.stopMap());
  await render(<MapScreen />);
  const locate = () => user.press(screen.getByRole("button", { name: "Show where I am" }));

  mockGranted = false;
  const settings = jest.spyOn(Linking, "openSettings").mockResolvedValue();
  await locate();
  expect(screen.queryByText("(you)")).toBeNull();
  await user.press(screen.getByText("Location is off for Tinfoil Kit. Tap to turn it on in Settings."));
  expect(settings).toHaveBeenCalled();

  mockGranted = true;
  await locate();
  expect(screen.getByText("Finding where you are")).toBeOnTheScreen();
  expect(screen.getByText("(you)")).toBeOnTheScreen();
  const { home } = place("us/rhode-island")!;
  await act(() => mockListener!({ coords: { longitude: home.lon, latitude: home.lat } }));
  expect(mockFly).toHaveBeenLastCalledWith({ center: [home.lon, home.lat], zoom: 15 });
  expect(screen.queryByText("Finding where you are")).toBeNull();
  expect(mockListener).toBeUndefined(); // one fix is enough: the dot follows on its own

  await locate();
  expect(screen.queryByText("Finding where you are")).toBeNull();
  await act(() => mockListener!({ coords: { longitude: -0.12, latitude: 51.5 } })); // London
  expect(mockFly).toHaveBeenLastCalledWith({ center: [-0.12, 51.5], zoom: 7 });
  await user.press(screen.getByText("You're outside Rhode Island's map. Tap to pick another place."));
  expect(screen.getByText(/^Where do you live\?/)).toBeOnTheScreen();
});
