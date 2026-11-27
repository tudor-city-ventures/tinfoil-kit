import { expect, test } from "@jest/globals";

import { duration, size } from "./format";

test("sizes", () => {
  expect(size(950e6)).toBe("950 MB");
  expect(size(2.14e9)).toBe("2.1 GB");
  expect(size(12.4e9)).toBe("12 GB");
  expect(size(1)).toBe("1 MB");
});

test("durations", () => {
  expect(duration(1.8e9, 10e6)).toBe("about 3 min");
  expect(duration(36e9, 10e6)).toBe("about 1 hour");
  expect(duration(100e9, 10e6)).toBe("about 3 hours");
});
