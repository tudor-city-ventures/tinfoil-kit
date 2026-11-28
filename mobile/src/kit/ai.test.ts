import { afterEach, expect, jest, test } from "@jest/globals";

import { PRETEND, aiAnswer, aiDownload, aiState } from "@/kit/ai";
import { FAILED, fake } from "@/kit/qa";

jest.mock("../../modules/kit-files", () => ({
  aiState: async () => "none",
  aiDownload: async () => {
    throw new Error("This phone can't get an AI");
  },
  aiAnswer: async () => "the phone's own answer",
}));

afterEach(() => {
  fake({ ai: undefined });
  jest.useRealTimers();
});

test("with nothing pretend, it's the phone's own AI", async () => {
  expect(await aiState()).toBe("none");
  expect(await aiAnswer("Answer from the passages.", "Question")).toBe("the phone's own answer");
  await expect(aiDownload(false)).rejects.toThrow("can't get an AI");
});

test("the testing menu's pretend AI answers, fails, or downloads, after a moment", async () => {
  jest.useFakeTimers();
  fake({ ai: "ready" });
  expect(await aiState()).toBe("ready");
  const answer = aiAnswer("Answer from the passages.", "Question");
  await jest.advanceTimersByTimeAsync(2000);
  expect(await answer).toBe(PRETEND);

  fake({ ai: "failing" });
  expect(await aiState()).toBe("ready");
  const failed = expect(aiAnswer("Answer from the passages.", "Question")).rejects.toThrow(FAILED);
  await jest.advanceTimersByTimeAsync(2000);
  await failed;

  fake({ ai: "downloadable" });
  expect(await aiState()).toBe("downloadable");
  const got = aiDownload(false);
  await jest.advanceTimersByTimeAsync(3000);
  await got;
  expect(await aiState()).toBe("ready");
});
