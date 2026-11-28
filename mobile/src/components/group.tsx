import { Children, Fragment, type ReactNode } from "react";
import { Platform, Pressable, StyleSheet, Text, View } from "react-native";

import { Icon, type icons } from "@/components/icon";
import { radius, space, useColors } from "@/theme";

// A grouped list in the iOS Settings manner: a small label above rounded rows on paper.
export function Group({ label, footer, children }: { label?: string; footer?: string; children: ReactNode }) {
  const c = useColors();
  const rows = Children.toArray(children).filter(Boolean);
  return (
    <View style={styles.group}>
      {label ? <Text style={[styles.label, { color: c.mute }]}>{label}</Text> : null}
      <View style={[styles.card, { backgroundColor: c.cell }]}>
        {rows.map((row, i) => (
          <Fragment key={i}>
            {i > 0 ? <View style={[styles.line, { backgroundColor: c.line }]} /> : null}
            {row}
          </Fragment>
        ))}
      </View>
      {footer ? <Text style={[styles.footer, { color: c.mute }]}>{footer}</Text> : null}
    </View>
  );
}

type RowProps = {
  title: string;
  detail?: string;
  icon?: keyof typeof icons;
  accent?: boolean; // an orange tile, for what's happening now
  right?: ReactNode;
  onPress?: () => void;
  onLongPress?: () => void;
  testID?: string;
};

export function Row({ title, detail, icon, accent, right, onPress, onLongPress, testID }: RowProps) {
  const c = useColors();
  const body = (
    <View style={styles.row}>
      {icon ? (
        <View style={[styles.tile, { backgroundColor: accent ? c.accent : c.icon }]}>
          <Icon name={icon} color={accent ? c.onAccent : c.background} size={16} />
        </View>
      ) : null}
      <View style={styles.text}>
        <Text style={[styles.title, { color: c.ink }]}>{title}</Text>
        {detail ? <Text style={[styles.detail, { color: c.mute }]}>{detail}</Text> : null}
      </View>
      {right}
    </View>
  );
  if (!onPress && !onLongPress) return <View testID={testID}>{body}</View>;
  return (
    <Pressable
      testID={testID}
      accessibilityRole="button"
      onPress={onPress}
      onLongPress={onLongPress}
      android_ripple={{ color: c.line }}
      style={({ pressed }) => (pressed && Platform.OS === "ios" ? { backgroundColor: c.line } : null)}
    >
      {body}
    </Pressable>
  );
}

export function Pill({ text }: { text: string }) {
  const c = useColors();
  return (
    <View style={[styles.pill, { backgroundColor: c.accent }]}>
      <Text style={[styles.pillText, { color: c.onAccent }]}>{text}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  group: { marginHorizontal: space.l, marginBottom: space.xl },
  label: { fontSize: 13, fontWeight: "600", marginHorizontal: space.xs, marginBottom: space.s },
  footer: { fontSize: 13, marginHorizontal: space.xs, marginTop: space.s, lineHeight: 18 },
  card: { borderRadius: radius.cell, overflow: "hidden" },
  line: { height: StyleSheet.hairlineWidth, marginLeft: space.l },
  row: { flexDirection: "row", alignItems: "center", gap: space.m, paddingHorizontal: space.l, paddingVertical: 11 },
  tile: { width: 28, height: 28, borderRadius: 7, alignItems: "center", justifyContent: "center" },
  text: { flex: 1 },
  title: { fontSize: 16 },
  detail: { fontSize: 13, marginTop: 2 },
  pill: { borderRadius: radius.pill, paddingHorizontal: 10, paddingVertical: 3 },
  pillText: { fontSize: 12, fontWeight: "600", fontVariant: ["tabular-nums"] },
});
