import { getDocumentAsync } from "expo-document-picker";
import { Paths } from "expo-file-system";
import { router } from "expo-router";
import { Alert, Platform, Pressable, ScrollView, StyleSheet, Switch, View } from "react-native";

import { Group, Pill, Row } from "@/components/group";
import { Icon } from "@/components/icon";
import { addFile, describe, useAdding } from "@/kit/add";
import { catalog, groups } from "@/kit/catalog";
import { size } from "@/kit/format";
import { store, useKit } from "@/kit/store";
import { useColors } from "@/theme";

function freeSpace(): string {
  try {
    return `${size(Paths.availableDiskSpace)} free of ${size(Paths.totalDiskSpace)}`;
  } catch {
    return "";
  }
}

const NEARBY = Platform.OS === "ios" ? "AirDrop" : "Quick Share";

// A book another phone sent, or one saved on this one, from the phone's own file picker
async function pick() {
  const got = await getDocumentAsync({ type: "*/*", copyToCacheDirectory: false }).catch(() => undefined);
  const file = got && !got.canceled ? got.assets[0] : undefined;
  if (file) Alert.alert(...describe(await addFile(file.uri, file.name, file.size)));
}

export default function GetMore() {
  const { items, cellular, home } = useKit();
  const adding = useAdding();
  const c = useColors();
  return (
    <ScrollView contentInsetAdjustmentBehavior="automatic">
      <Group footer="Big downloads wait for Wi-Fi unless you allow mobile data, which can cost money.">
        <Row icon="phone" title="This phone" detail={freeSpace()} />
        <Row
          icon="cellular"
          title="Use mobile data"
          right={
            <Switch
              testID="cellular"
              value={cellular}
              onValueChange={(on) => store.setCellular(on)}
              trackColor={{ true: c.accent }}
            />
          }
        />
      </Group>
      <Group
        label="Nearby"
        footer={`From a Tinfoil Kit or another phone, over the Wi-Fi or with ${NEARBY}: faster than the internet, and it works without it.`}
      >
        <Row
          testID="kit-at-home"
          icon={home?.phone ? "phone" : "drive"}
          title={home ? home.name : "Copy from a kit or phone"}
          detail={home ? (home.phone ? "Copy its books and map" : "Copy its books and map, or open it") : undefined}
          right={<Icon name="forward" color={c.mute} />}
          onPress={() => router.push("/more/home")}
        />
        <Row
          testID="share-phone"
          icon="wifi"
          title="Share with a phone"
          detail="Let another phone copy this one's books and map"
          right={<Icon name="forward" color={c.mute} />}
          onPress={() => router.push("/more/share")}
        />
        <Row
          testID="add-file"
          icon="file"
          title={adding ? "Adding a book" : "Add a book from a file"}
          detail={
            adding?.name ??
            (Platform.OS === "ios"
              ? "One sent with AirDrop, or saved in Files"
              : "One sent with Quick Share, or saved in Downloads")
          }
          right={adding ? <Pill text={`${adding.percent}%`} /> : <Icon name="forward" color={c.mute} />}
          onPress={adding ? undefined : pick}
        />
      </Group>
      {groups.map((g) => (
        <Group key={g} label={g}>
          {catalog
            .filter((b) => b.group === g)
            .map((b) => {
              const have = items[b.id];
              return (
                <Row
                  key={b.id}
                  testID={`book-${b.id}`}
                  title={b.title}
                  detail={b.bytes ? `${b.why} ${size(b.bytes)}.` : b.why}
                  right={
                    have ? (
                      <Icon name={have.status === "ready" ? "ready" : "download"} color={c.mute} size={22} />
                    ) : (
                      <Pressable
                        testID={`get-${b.id}`}
                        accessibilityRole="button"
                        accessibilityLabel={`Get ${b.title}`}
                        hitSlop={12}
                        onPress={() => store.queue(b.id)}
                        style={styles.add}
                      >
                        <Icon name="add" color={c.accent} size={24} />
                      </Pressable>
                    )
                  }
                />
              );
            })}
        </Group>
      ))}
      <View style={styles.end} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  add: { padding: 2 },
  end: { height: 24 },
});
