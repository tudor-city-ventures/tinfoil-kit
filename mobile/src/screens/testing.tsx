import Constants from "expo-constants";
import { Directory, Paths } from "expo-file-system";
import { Stack } from "expo-router";
import { Alert, Platform, ScrollView, Share, StyleSheet, Switch, Text } from "react-native";

import { Group, Row } from "@/components/group";
import { Icon } from "@/components/icon";
import { libraryPath, removeBook } from "@/kit/downloads";
import { mapsPath } from "@/kit/maps";
import { COMMIT, fake, useFakes, type Fakes } from "@/kit/qa";
import { store, useKit } from "@/kit/store";
import { space, useColors } from "@/theme";

// What each platform's AI can say it is (modules/kit-files), to pretend
const AI: [Fakes["ai"], string][] = [
  [undefined, "As it is"],
  ["ready", "Ready, with pretend answers"],
  ["failing", "Ready, but every answer fails"],
  Platform.OS === "android" ? ["downloadable", "Can download"] : ["off", "Turned off in Settings"],
  ["downloading", "Downloading"],
  ["none", "None on this phone"],
];

const stand = process.env.EXPO_PUBLIC_KIWIX_CATALOG;

// Everything in a folder, gone; the folder stays
function empty(path: string) {
  const dir = new Directory(path.startsWith("file:") ? path : `file://${path}`);
  if (!dir.exists) return;
  for (const entry of dir.list())
    try {
      entry.delete();
    } catch {} // in use: the rest still go
}

function removeBooks() {
  for (const id of Object.keys(store.get().items)) removeBook(id);
}

function removeMap() {
  store.forgetMap();
  empty(mapsPath());
}

function clearCaches() {
  empty(Paths.cache.uri);
}

function resetAll() {
  removeBooks();
  empty(libraryPath());
  removeMap();
  clearCaches();
  store.startOver(false);
}

function sure(title: string, message: string, verb: string, act: () => void) {
  Alert.alert(`${title}?`, message, [
    { text: "Cancel", style: "cancel" },
    { text: verb, style: "destructive", onPress: act },
  ]);
}

// The testing menu, hidden in every build (qa.ts): what this build is, pretend states that are hard to make happen on a
// real phone, ways to start over, and what the app keeps. Seven taps on This phone in Get more open it.
export function Testing() {
  const c = useColors();
  const kit = useKit();
  const fakes = useFakes();
  const record = JSON.stringify(kit, null, 2);
  return (
    <ScrollView contentInsetAdjustmentBehavior="automatic">
      <Stack.Screen options={{ title: "Testing", headerLargeTitle: false }} />
      <Group label="This build">
        <Row
          testID="testing-build"
          title={`Tinfoil Kit ${Constants.expoConfig?.version ?? ""}`}
          detail={`${COMMIT ? `From commit ${COMMIT.slice(0, 7)}` : "Built by hand"}, on ${Platform.OS} ${Platform.Version}`}
        />
        <Row
          title="Downloads from"
          detail={stand ? `Stand-ins at ${new URL(stand).host}` : "The internet: Kiwix, Protomaps and kits"}
        />
      </Group>
      <Group
        label="The phone's AI"
        footer="Pretend answers take two seconds. Everything pretend lasts until the app closes."
      >
        {AI.map(([value, title]) => (
          <Row
            key={title}
            testID={`ai-${value ?? "real"}`}
            title={title}
            right={fakes.ai === value ? <Icon name="ready" color={c.accent} /> : undefined}
            onPress={() => fake({ ai: value })}
          />
        ))}
      </Group>
      <Group label="Pretend">
        <Row
          title="The phone is full"
          detail="Books and maps say there's no room"
          right={
            <Switch
              testID="fake-full"
              value={!!fakes.full}
              onValueChange={(full) => fake({ full })}
              trackColor={{ true: c.accent }}
            />
          }
        />
        <Row
          title="Downloads fail"
          detail="Books and maps fail as they start"
          right={
            <Switch
              testID="fake-failing"
              value={!!fakes.failing}
              onValueChange={(failing) => fake({ failing })}
              trackColor={{ true: c.accent }}
            />
          }
        />
      </Group>
      <Group label="Start over">
        <Row
          testID="first-screen"
          title="Show the first screen"
          detail="Keeps the books and map"
          onPress={() =>
            sure("Show the first screen", "Books and the map stay.", "Show it", () => store.startOver(true))
          }
        />
        <Row
          title="Remove every book"
          detail="And stops their downloads"
          onPress={() => sure("Remove every book", "Their files are deleted from this phone.", "Remove", removeBooks)}
        />
        <Row
          title="Remove the map"
          detail="And stops its download"
          onPress={() => sure("Remove the map", "The map's files are deleted from this phone.", "Remove", removeMap)}
        />
        <Row
          title="Forget the kit or phone"
          detail={kit.home ? kit.home.name : "None found yet"}
          onPress={() =>
            sure("Forget the kit or phone", "Its address and code are forgotten.", "Forget", () =>
              store.setHome(undefined),
            )
          }
        />
        <Row
          title="Clear the caches"
          detail="Files opened from books, and other leftovers"
          onPress={() => sure("Clear the caches", "Books, the map and settings stay.", "Clear", clearCaches)}
        />
        <Row
          testID="reset-all"
          title="Reset everything"
          detail="As a fresh install: every book, the map and every setting gone"
          onPress={() =>
            sure("Reset everything", "Everything on this phone from Tinfoil Kit is deleted.", "Reset", resetAll)
          }
        />
      </Group>
      <Group label="What the app keeps">
        <Row title="Send it" detail="To paste into a bug report" onPress={() => Share.share({ message: record })} />
        <Text selectable style={[styles.record, { color: c.ink }]}>
          {record}
        </Text>
      </Group>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  record: {
    fontFamily: Platform.select({ ios: "Menlo", default: "monospace" }),
    fontSize: 11,
    padding: space.m,
  },
});
