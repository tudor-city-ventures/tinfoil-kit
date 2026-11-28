import { Stack } from "expo-router";
import * as SplashScreen from "expo-splash-screen";
import { StatusBar } from "expo-status-bar";
import { useEffect } from "react";

import { startDownloads } from "@/kit/downloads";
import { startMaps } from "@/kit/maps";
import { store, useKit, useLoaded } from "@/kit/store";
import { useColors } from "@/theme";

SplashScreen.preventAutoHideAsync();
store.load().then(() => {
  for (const start of [startDownloads, startMaps])
    try {
      start();
    } catch (e) {
      console.error(e); // in the phone's log, and the other still starts
    }
});

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
          <Stack.Screen
            name="book/[id]"
            options={{
              headerShown: true,
              headerBackTitle: "Library",
              headerShadowVisible: false,
              headerStyle: { backgroundColor: c.background },
              headerTitleStyle: { color: c.ink },
              headerTintColor: c.accent,
            }}
          />
        </Stack.Protected>
        <Stack.Protected guard={!welcomed}>
          <Stack.Screen name="welcome" />
        </Stack.Protected>
      </Stack>
    </>
  );
}
