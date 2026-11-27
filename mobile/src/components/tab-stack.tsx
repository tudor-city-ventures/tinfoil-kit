import { Stack } from "expo-router";

import { useColors } from "@/theme";

// Each tab is a stack with iOS's large title on paper; Android keeps its own top app bar.
export function TabStack({ title }: { title: string }) {
  const c = useColors();
  return (
    <Stack
      screenOptions={{
        headerLargeTitle: true,
        headerLargeTitleShadowVisible: false,
        headerShadowVisible: false,
        headerStyle: { backgroundColor: c.background },
        headerLargeStyle: { backgroundColor: c.background },
        headerTitleStyle: { color: c.ink },
        headerLargeTitleStyle: { color: c.ink, fontWeight: "800" },
        headerTintColor: c.accent,
        contentStyle: { backgroundColor: c.background },
      }}
    >
      <Stack.Screen name="index" options={{ title }} />
    </Stack>
  );
}
