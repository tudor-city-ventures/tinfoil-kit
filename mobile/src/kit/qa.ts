// The testing menu's switches. Every build has the menu, hidden (Travis's pick): App Review's notes say where it is,
// as Apple's rules bar hidden features it isn't told about. Each fake stands in for something a tester can't easily
// make happen on a real phone, and lasts until the app closes.
import { Paths } from "expo-file-system";
import { useSyncExternalStore } from "react";

import type { AIState } from "../../modules/kit-files";

export const COMMIT = process.env.EXPO_PUBLIC_COMMIT ?? "";

export type Fakes = {
  ai?: AIState | "failing"; // the phone's AI, as it says it is; "failing": ready, but every answer fails
  full?: boolean; // the phone has hardly any room left
  failing?: boolean; // every download fails as it starts
};

export const FULL = 2e8; // the room a full phone has left, in bytes
export const FAILED = "Failed on purpose, from the testing menu";

let fakes: Fakes = {};
const listeners = new Set<() => void>();

// None unless the menu pretends
export function faked(): Fakes {
  return fakes;
}

export function fake(more: Fakes) {
  fakes = { ...fakes, ...more };
  listeners.forEach((l) => l());
}

// The room left on the phone, in bytes
export function spaceLeft(): number {
  return fakes.full ? FULL : Paths.availableDiskSpace;
}

export function useFakes(): Fakes {
  return useSyncExternalStore((l) => {
    listeners.add(l);
    return () => listeners.delete(l);
  }, faked);
}

// Seven taps in a row on This phone in Get more open the menu. A slow simulator taps about once a second, so each tap
// may come up to a second and a half after the last.
export function tapper(open: () => void, taps = 7, within = 1500) {
  let count = 0;
  let last = 0;
  return () => {
    const now = Date.now();
    count = now - last <= within ? count + 1 : 1;
    last = now;
    if (count >= taps) {
      count = 0;
      open();
    }
  };
}
