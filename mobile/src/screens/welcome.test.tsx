import { expect, test } from "@jest/globals";
import { render, screen, userEvent } from "@testing-library/react-native";

import { starter } from "@/kit/catalog";
import { store } from "@/kit/store";

import { Welcome } from "./welcome";

test("the first screen offers the try-it kit and queues it", async () => {
  const user = userEvent.setup();
  await render(<Welcome />);
  expect(screen.getByText("Tinfoil Kit")).toBeOnTheScreen();
  for (const b of starter) expect(screen.getByText(b.title)).toBeOnTheScreen();
  await user.press(screen.getByRole("button", { name: "Get the try-it kit" }));
  expect(store.get().welcomed).toBe(true);
  expect(Object.keys(store.get().items).sort()).toEqual(starter.map((b) => b.id).sort());
});
