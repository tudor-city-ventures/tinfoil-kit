import { expect, jest, test } from "@jest/globals";
import { act, render, screen, userEvent } from "@testing-library/react-native";
import type { ReactElement } from "react";

import { store } from "@/kit/store";

import { MapScreen } from "./map";

type Options = {
  headerShown?: boolean;
  headerSearchBarOptions?: { onChangeText(e: { nativeEvent: { text: string } }): void };
  headerRight?: () => ReactElement<{ onPress(): void }>;
};
let mockOptions: Options = {};

// The stack's header, as the screen sets it, and the map as a plain view that says which file it shows
jest.mock("expo-router", () => ({
  Stack: { Screen: ({ options }: { options: Options }) => ((mockOptions = options), null) },
}));
jest.mock("@maplibre/maplibre-react-native", () => {
  const { createElement } = jest.requireActual<typeof import("react")>("react");
  const { Text } = jest.requireActual<typeof import("react-native")>("react-native");
  return {
    Map: (p: { testID: string; mapStyle: { sources: { protomaps: { url: string } } }; onDidFailLoadingMap(): void }) =>
      createElement(Text, { testID: p.testID, onPress: p.onDidFailLoadingMap }, p.mapStyle.sources.protomaps.url),
    Camera: () => null,
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
  await user.press(screen.getByText("Alabama"));
  expect(store.get().mapDownload).toMatchObject({ place: "us/alabama" });
  expect(screen.getByText("Alabama: Starting")).toBeOnTheScreen(); // over Rhode Island's map, until Alabama's is here
});
