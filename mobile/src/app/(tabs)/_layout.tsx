import { NativeTabs } from "expo-router/native-tabs";

import { useColors } from "@/theme";

export default function TabsLayout() {
  const c = useColors();
  return (
    <NativeTabs tintColor={c.accent}>
      <NativeTabs.Trigger name="(library)">
        <NativeTabs.Trigger.Icon
          sf={{ default: "books.vertical", selected: "books.vertical.fill" }}
          md="library_books"
        />
        <NativeTabs.Trigger.Label>Library</NativeTabs.Trigger.Label>
      </NativeTabs.Trigger>
      <NativeTabs.Trigger name="ask">
        <NativeTabs.Trigger.Icon
          sf={{ default: "bubble.left.and.text.bubble.right", selected: "bubble.left.and.text.bubble.right.fill" }}
          md="question_answer"
        />
        <NativeTabs.Trigger.Label>Ask</NativeTabs.Trigger.Label>
      </NativeTabs.Trigger>
      <NativeTabs.Trigger name="map">
        <NativeTabs.Trigger.Icon sf={{ default: "map", selected: "map.fill" }} md="map" />
        <NativeTabs.Trigger.Label>Map</NativeTabs.Trigger.Label>
      </NativeTabs.Trigger>
      <NativeTabs.Trigger name="more">
        <NativeTabs.Trigger.Icon
          sf={{ default: "arrow.down.circle", selected: "arrow.down.circle.fill" }}
          md="download"
        />
        <NativeTabs.Trigger.Label>Get more</NativeTabs.Trigger.Label>
      </NativeTabs.Trigger>
    </NativeTabs>
  );
}
