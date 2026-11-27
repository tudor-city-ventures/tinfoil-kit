import { Paths } from "expo-file-system";
import { Pressable, ScrollView, StyleSheet, Switch, View } from "react-native";

import { Group, Row } from "@/components/group";
import { Icon } from "@/components/icon";
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

export default function GetMore() {
  const { items, cellular } = useKit();
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
