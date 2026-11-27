import { ScrollView, StyleSheet, Text, View } from "react-native";

import { Button } from "@/components/button";
import { Group, Row } from "@/components/group";
import { bytesOf, starter } from "@/kit/catalog";
import { size } from "@/kit/format";
import { store } from "@/kit/store";
import { space, useColors } from "@/theme";

// The first screen: what the app is, and a small kit to try before choosing the rest.
export function Welcome() {
  const c = useColors();
  return (
    <ScrollView contentInsetAdjustmentBehavior="automatic" contentContainerStyle={styles.page}>
      <View style={styles.top}>
        <Text style={[styles.title, { color: c.ink }]}>Tinfoil Kit</Text>
        <Text style={[styles.lede, { color: c.mute }]}>
          Books, maps and answers on your phone, for when the internet goes down.
        </Text>
      </View>
      <Group
        label={`Try-it kit · ${size(bytesOf(starter))}`}
        footer="It downloads over Wi-Fi. Choose more in Get more whenever you like."
      >
        {starter.map((b) => (
          <Row key={b.id} icon="book" title={b.title} detail={b.why} />
        ))}
      </Group>
      <View style={styles.actions}>
        <Button
          testID="get-try-it"
          title="Get the try-it kit"
          onPress={() => store.welcome(starter.map((b) => b.id))}
        />
        <Button testID="not-now" plain title="Not now" onPress={() => store.welcome([])} />
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  page: { paddingVertical: space.xl },
  top: { paddingHorizontal: space.xl, paddingTop: space.xl, paddingBottom: space.xl },
  title: { fontSize: 40, fontWeight: "800", letterSpacing: -0.5 },
  lede: { fontSize: 17, lineHeight: 24, marginTop: space.s },
  actions: { paddingHorizontal: space.l, gap: space.s },
});
