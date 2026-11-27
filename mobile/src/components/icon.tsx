import { SymbolView } from "expo-symbols";
import type { ComponentProps } from "react";

type Names = ComponentProps<typeof SymbolView>["name"];

// SF Symbols on iOS, Material Symbols on Android: the same idea in each platform's own drawing.
export const icons = {
  book: { ios: "book.closed.fill", android: "menu_book", web: "menu_book" },
  download: { ios: "arrow.down.circle.fill", android: "downloading", web: "downloading" },
  ready: { ios: "checkmark.circle.fill", android: "check_circle", web: "check_circle" },
  failed: { ios: "exclamationmark.circle.fill", android: "error", web: "error" },
  add: { ios: "plus.circle.fill", android: "add_circle", web: "add_circle" },
  drive: { ios: "externaldrive.fill", android: "storage", web: "storage" },
  wifi: { ios: "wifi", android: "wifi", web: "wifi" },
  cellular: { ios: "antenna.radiowaves.left.and.right", android: "cell_tower", web: "cell_tower" },
  phone: { ios: "iphone", android: "smartphone", web: "smartphone" },
} satisfies Record<string, Names>;

export function Icon({ name, color, size = 18 }: { name: keyof typeof icons; color: string; size?: number }) {
  return <SymbolView name={icons[name]} tintColor={color} size={size} />;
}
