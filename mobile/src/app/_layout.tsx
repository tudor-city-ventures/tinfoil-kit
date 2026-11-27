import { Stack } from "expo-router";
import * as SplashScreen from "expo-splash-screen";
import { StatusBar } from "expo-status-bar";
import { useEffect } from "react";

import { store, useKit, useLoaded } from "@/kit/store";
import { useColors } from "@/theme";

SplashScreen.preventAutoHideAsync();
store.load();

export default function RootLayout() {
  const loaded = useLoaded();
  const { welcomed } = useKit();
  const c = useColors();

  useEffect(() => {
    if (loaded) SplashScreen.hideAsync();
  }, [loaded]);

  if (!loaded) return null;
  return (
    <>
      <StatusBar style="auto" />
      <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: c.background } }}>
        <Stack.Protected guard={welcomed}>
          <Stack.Screen name="(tabs)" />
        </Stack.Protected>
        <Stack.Protected guard={!welcomed}>
          <Stack.Screen name="welcome" />
        </Stack.Protected>
      </Stack>
    </>
  );
}
