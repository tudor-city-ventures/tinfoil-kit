import { Pressable, StyleSheet, Text } from "react-native";

import { space, useColors } from "@/theme";

export function Button({
  title,
  onPress,
  plain,
  testID,
}: {
  title: string;
  onPress: () => void;
  plain?: boolean; // a text button, for the quieter choice
  testID?: string;
}) {
  const c = useColors();
  return (
    <Pressable
      testID={testID}
      accessibilityRole="button"
      onPress={onPress}
      style={({ pressed }) => [styles.button, !plain && { backgroundColor: c.accent }, pressed && { opacity: 0.7 }]}
    >
      <Text style={[styles.text, { color: plain ? c.accent : c.onAccent }]}>{title}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  button: { borderRadius: 12, paddingVertical: 14, paddingHorizontal: space.l, alignItems: "center" },
  text: { fontSize: 17, fontWeight: "600" },
});
