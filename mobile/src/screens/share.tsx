import { File } from "expo-file-system";
import { activateKeepAwakeAsync, deactivateKeepAwake } from "expo-keep-awake";
import { Stack } from "expo-router";
import { useEffect, useMemo, useState } from "react";
import { ActivityIndicator, AppState, Platform, ScrollView, StyleSheet, Text } from "react-native";

import { newCode, sharing, startSharing, stopSharing, type Sharing } from "../../modules/kit-files";
import { Group, Row } from "@/components/group";
import { libraryPath } from "@/kit/downloads";
import { size } from "@/kit/format";
import { mapsPath } from "@/kit/maps";
import { shared, type Here, type Shared } from "@/kit/share";
import { store, useKit } from "@/kit/store";
import { space, useColors } from "@/theme";

const LOOK = 1000; // ms between looks at how the sharing is going

// What other phones see this one as: an iPhone gives apps no other name
function phoneName(): string {
  if (Platform.OS === "android") return Platform.constants.Model;
  return Platform.OS === "ios" && Platform.isPad ? "iPad" : "iPhone";
}

function fileSize(path: string): number {
  try {
    const f = new File(`file://${path}`);
    return f.exists ? f.size : -1;
  } catch {
    return -1;
  }
}

const here = (): Here => ({ library: libraryPath(), maps: mapsPath(), size: fileSize });

// The code in two groups, as the kit shows its own: 4821 7736
const pretty = (code: string) => code.replace(/^(\d{4})(\d{4})$/, "$1 $2");

// This phone's books and map, for another phone on the Wi-Fi to copy: shared while this screen is open, with a code
export function Share() {
  const c = useColors();
  const { items, map, shareCode } = useKit();
  const [state, setState] = useState<Sharing>();
  const [problem, setProblem] = useState<string>();
  const name = phoneName();

  const what = useMemo(() => shared(name, { items, map }, here()), [name, items, map]);
  // as text, so sharing starts again when what's shared changes, not with each download's progress
  const options = JSON.stringify(what);

  useEffect(() => {
    if (!shareCode) store.setShareCode(newCode());
  }, [shareCode]);

  useEffect(() => {
    if (!shareCode) return;
    let gone = false;
    const { listing, files, folders } = JSON.parse(options) as Shared;
    const start = () => {
      setProblem(undefined);
      startSharing({ name, code: shareCode, listing: JSON.stringify(listing), files, folders }).catch(
        () => gone || setProblem("This phone can't share on this network. Check its Wi-Fi, then come back here."),
      );
    };
    start();
    void activateKeepAwakeAsync("share").catch(() => {});
    const look = setInterval(() => gone || setState(sharing()), LOOK);
    // iOS stops a server in the background: it stops here too, and starts again with the app
    const app = AppState.addEventListener("change", (s) => (s === "active" ? start() : stopSharing()));
    return () => {
      gone = true;
      clearInterval(look);
      app.remove();
      stopSharing();
      void deactivateKeepAwake("share").catch(() => {});
    };
  }, [shareCode, options, name]);

  const port = state?.port || 8000;
  const addresses = (state?.addresses ?? []).map((a) => (port === 8000 ? a : `${a}:${port}`));
  const { books, map: kitMap } = what.listing;
  const nothing = books.length === 0 && !kitMap;

  return (
    <ScrollView contentInsetAdjustmentBehavior="automatic">
      <Stack.Screen options={{ title: "Share with a phone", headerLargeTitle: false }} />
      {state?.stopped === "tries" ? (
        <Group footer="Someone typed a wrong code 10 times, so this phone stopped sharing.">
          <Row
            title="Share again, with a new code"
            testID="share-again"
            onPress={() => store.setShareCode(newCode())}
          />
        </Group>
      ) : null}
      <Group
        label="Code"
        footer={
          problem ??
          `On the other phone, in Get more, tap Copy from a kit or phone. Pick ${name}` +
            (addresses.length ? ` or type ${addresses[0]}` : "") +
            ", then type this code."
        }
      >
        <Text testID="share-code" selectable style={[styles.code, { color: c.ink }]}>
          {shareCode ? pretty(shareCode) : ""}
        </Text>
      </Group>
      <Group
        footer={state && !addresses.length ? "Join a Wi-Fi: the other phone copies over the same one." : undefined}
      >
        <Row
          testID={state?.on ? "share-on" : undefined}
          icon="wifi"
          accent={!!state?.copying}
          title={state?.on ? `Sharing as ${name}` : "Starting…"}
          detail={
            state?.copying
              ? `Copying now: ${size(state.sent)} so far`
              : state?.sent
                ? `Copied ${size(state.sent)}`
                : addresses.join(", ") || undefined
          }
          right={!state?.on || state.copying ? <ActivityIndicator color={c.mute} /> : undefined}
        />
      </Group>
      <Group
        label="What it can copy"
        footer={
          nothing
            ? "Nothing yet: books and the map show here once they're on this phone."
            : "Keep this screen open while the other phone copies. Nothing else on this phone is shared."
        }
      >
        {books.map((b) => (
          <Row key={b.id} icon="book" title={b.title} detail={size(b.files[0].bytes)} />
        ))}
        {kitMap ? <Row icon="locate" title={kitMap.title} detail={size(kitMap.files[0].bytes)} /> : null}
      </Group>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  code: {
    fontSize: 34,
    fontWeight: "600",
    letterSpacing: 4,
    fontVariant: ["tabular-nums"],
    textAlign: "center",
    padding: space.l,
  },
});
