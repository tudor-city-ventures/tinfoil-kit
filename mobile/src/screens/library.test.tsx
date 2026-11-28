import { expect, jest, test } from "@jest/globals";
import { act, render, screen, userEvent } from "@testing-library/react-native";
import { Alert, type AlertButton } from "react-native";

import { starter } from "@/kit/catalog";
import { store } from "@/kit/store";

import { Library } from "./library";

const mockRemove = jest.fn<(id: string) => void>();
jest.mock("expo-router", () => ({ router: { push: jest.fn() } }));
jest.mock("@/kit/downloads", () => ({ removeBook: (id: string) => mockRemove(id) }));
jest.mock("expo-network", () => ({
  NetworkStateType: { WIFI: "WIFI", ETHERNET: "ETHERNET" },
  useNetworkState: () => ({ type: "WIFI" }),
}));

test("touch and hold a book to take it off the phone, or to stop its download", async () => {
  const [a, b] = starter;
  await act(async () => {
    store.queue(a.id);
    store.update(a.id, { status: "ready", file: "a.zim", received: 5e8, total: 5e8 });
    store.queue(b.id);
    store.update(b.id, { status: "downloading", received: 1e8, total: 4e8 });
  });
  const alert = jest.spyOn(Alert, "alert").mockImplementation(() => {});
  const press = (text: string) => {
    const buttons = alert.mock.calls.at(-1)![2] as AlertButton[];
    buttons.find((x) => x.text === text)!.onPress?.(); // Cancel has none
  };
  const user = userEvent.setup();
  await render(<Library />);
  expect(screen.getByText("Touch and hold a book to remove it.")).toBeOnTheScreen();

  await user.longPress(screen.getByTestId(`ready-${a.id}`));
  expect(alert.mock.calls.at(-1)!.slice(0, 2)).toEqual([
    `Remove ${a.title}?`,
    "It comes off this phone, freeing 500 MB. You can get it again in Get more.",
  ]);
  press("Cancel");
  expect(mockRemove).not.toHaveBeenCalled();
  press("Remove");
  expect(mockRemove).toHaveBeenLastCalledWith(a.id);

  await user.longPress(screen.getByTestId(`getting-${b.id}`));
  expect(alert.mock.calls.at(-1)![0]).toBe(`Stop downloading ${b.title}?`);
  press("Stop");
  expect(mockRemove).toHaveBeenLastCalledWith(b.id);
});
