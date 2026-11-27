import { expect, test } from "@jest/globals";

import { percent, statusLine } from "./status";

test("a queued book waits for Wi-Fi unless mobile data is allowed", () => {
  const item = { status: "queued" as const, received: 0, total: 0 };
  expect(statusLine(item, false, false)).toBe("Waiting for Wi-Fi");
  expect(statusLine(item, false, true)).toBe("Waiting to download");
  expect(statusLine(item, true, false)).toBe("Waiting to download");
});

test("downloading, ready and stopped", () => {
  expect(statusLine({ status: "downloading", received: 1.2e9, total: 1.8e9 }, true, false)).toBe("1.2 GB of 1.8 GB");
  expect(percent({ status: "downloading", received: 1.2e9, total: 1.8e9 })).toBe(66);
  expect(statusLine({ status: "ready", received: 2e8, total: 2e8 }, true, false)).toBe("Ready · 200 MB");
  expect(statusLine({ status: "failed", received: 0, total: 0, error: "the phone is full" }, true, false)).toBe(
    "Stopped: the phone is full",
  );
});
