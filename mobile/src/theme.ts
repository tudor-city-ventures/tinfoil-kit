import { useColorScheme } from "react-native";

// The kit page's paper, ink and signal orange (tools/portal.html), on iOS's grouped lists: orange is the only accent.
const light = {
  background: "#F3F0E6",
  cell: "#FFFDF7",
  ink: "#1C1F1A",
  mute: "#6B6F63",
  line: "#E2DDCF",
  accent: "#D9531E",
  onAccent: "#FFFFFF",
  icon: "#1C1F1A",
};

const dark: typeof light = {
  background: "#1C1F1A",
  cell: "#262A23",
  ink: "#F3F0E6",
  mute: "#8A8E80",
  line: "#343A30",
  accent: "#E4672F",
  onAccent: "#1C1F1A",
  icon: "#F3F0E6",
};

export type Colors = typeof light;

export function useColors(): Colors {
  return useColorScheme() === "dark" ? dark : light;
}

export const space = { xs: 4, s: 8, m: 12, l: 16, xl: 24 };
export const radius = { cell: 12, pill: 999 };
