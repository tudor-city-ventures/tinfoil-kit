import { expect, jest, test } from "@jest/globals";
import { act, render, screen, userEvent } from "@testing-library/react-native";

import { starter } from "@/kit/catalog";
import { store } from "@/kit/store";
import { book } from "@/kit/test-zim";

import { Ask } from "./ask";

const mockPush = jest.fn();
const mockOpened: string[] = [];
const mockSurvival = book([
  {
    ns: "C",
    path: "Water_purification",
    title: "Water purification",
    body: "<p><b>Water purification</b> makes water safe to drink.</p><p>Bring water to a rolling boil for 1 minute.</p>",
  },
  { ns: "C", path: "Fire", body: "<p>Keep a fire small and out of the wind.</p>" },
]);

let mockAI = "none"; // what the phone's AI can do
const mockAnswer = jest.fn<(instructions: string, prompt: string) => Promise<string>>();

jest.mock("expo-router", () => ({ router: { push: (to: unknown) => mockPush(to) } }));
jest.mock("../../modules/kit-files", () => ({
  aiState: () => mockAI,
  aiAnswer: (instructions: string, prompt: string) => mockAnswer(instructions, prompt),
}));
jest.mock("@/kit/downloads", () => ({ libraryPath: () => "/library" }));
jest.mock("@/kit/books", () => {
  const { Zim } = jest.requireActual<typeof import("@/kit/zim")>("@/kit/zim");
  return {
    ...jest.requireActual<object>("@/kit/books"),
    openBook: (path: string) => (mockOpened.push(path), new Zim(mockSurvival)),
  };
});

test("a question finds the best passages in the books on this phone, and each opens its page", async () => {
  const user = userEvent.setup();
  await render(<Ask />);
  expect(screen.getByText("No books yet")).toBeOnTheScreen();

  const id = starter[0].id;
  await act(async () => {
    store.queue(id);
    store.update(id, { status: "ready", file: "survival.zim" });
  });
  await user.type(screen.getByTestId("ask-question"), "How do I purify water?");
  await user.press(screen.getByRole("button", { name: "Search" }));
  expect(await screen.findByText("Best passages from your library")).toBeOnTheScreen();
  expect(mockOpened).toContain("/library/survival.zim");
  expect(screen.getByText("1. Water purification")).toBeOnTheScreen();
  expect(screen.getByText(starter[0].title)).toBeOnTheScreen();
  expect(screen.getByText(/rolling boil/)).toBeOnTheScreen();
  expect(screen.getByText(/^Done in \d+\.\ds\.$/)).toBeOnTheScreen();

  await user.press(screen.getByTestId("passage-0"));
  expect(mockPush).toHaveBeenCalledWith({ pathname: "/book/[id]", params: { id, page: "/Water_purification" } });

  await user.clear(screen.getByTestId("ask-question"));
  await user.type(screen.getByTestId("ask-question"), "quantum chromodynamics");
  await user.press(screen.getByRole("button", { name: "Search" }));
  expect(await screen.findByText("Nothing found")).toBeOnTheScreen();
  expect(screen.queryByRole("button", { name: "Ask the AI" })).toBeNull();
});

test("on a phone with AI built in, it answers from the passages, citing them", async () => {
  mockAI = "ready";
  mockAnswer.mockResolvedValueOnce("**Boil it** for 1 minute [1].");
  const user = userEvent.setup();
  await render(<Ask />);
  await user.type(screen.getByTestId("ask-question"), "How do I purify water?");
  await user.press(screen.getByRole("button", { name: "Ask the AI" }));
  expect(await screen.findByText("Boil it for 1 minute [1].")).toBeOnTheScreen();
  expect(screen.getByText("Sources from your library")).toBeOnTheScreen();
  expect(screen.getByText("1. Water purification")).toBeOnTheScreen();
  const [instructions, prompt] = mockAnswer.mock.calls[0];
  expect(instructions).toContain("offline emergency kit");
  expect(prompt).toContain('[1] "Water purification"');
  expect(prompt).toContain("Question: How do I purify water?");

  // Search first, then the AI answers from the same passages; when it can't, the passages stay
  mockAnswer.mockRejectedValueOnce(new Error("guardrail"));
  await user.press(screen.getByRole("button", { name: "Search" }));
  expect(await screen.findByText("Best passages from your library")).toBeOnTheScreen();
  await user.press(screen.getByRole("button", { name: "Have the AI answer from these" }));
  expect(await screen.findByText(/didn't answer this one/)).toBeOnTheScreen();
  expect(screen.getByText("1. Water purification")).toBeOnTheScreen();
  expect(mockAnswer).toHaveBeenCalledTimes(2);
});
