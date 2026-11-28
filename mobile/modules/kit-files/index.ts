// The bits of native code Expo lacks: keeping books out of iOS backups, a SHA-256 that reads a megabyte at a time, and
// the view that shows a book's pages, asking the app for each file they need and reaching nothing else.
import { requireNativeView, requireOptionalNativeModule } from "expo";
import { File } from "expo-file-system";
import type { ComponentType, Ref } from "react";
import type { ViewProps } from "react-native";

const native = requireOptionalNativeModule<{
  excludeFromBackup?(path: string): void; // iOS only: app.json turns Android's backups off
  sha256(path: string): Promise<string>;
}>("KitFiles");

export function excludeFromBackup(path: string) {
  native?.excludeFromBackup?.(path);
}

export function sha256(path: string): Promise<string> {
  return native ? native.sha256(path) : new File(`file://${path}`).digest("SHA-256");
}

export type Page = { url: string; title: string; back: boolean; forward: boolean; loading: boolean; gone?: boolean };
type Event<T> = { nativeEvent: T };

export type BookViewHandle = {
  load(url: string): Promise<void>;
  back(): Promise<void>;
  forward(): Promise<void>;
  find(): Promise<void>; // iOS's find on page
  respond(id: number, status: number, mime: string, body: Uint8Array): Promise<void>;
  respondFile(id: number, status: number, mime: string, path: string, offset: number, length: number): Promise<void>;
};

export type BookViewProps = ViewProps & {
  ref?: Ref<BookViewHandle>;
  start: string; // the first page's address
  onAsk(e: Event<{ id: number; url: string; main: boolean }>): void; // answer with respond or respondFile
  onPage?(e: Event<Page>): void;
  onLeave?(e: Event<{ url: string }>): void; // a link out of the book was tapped
  onOpen?(e: Event<{ url: string; mime: string }>): void; // a file the view can't show itself
};

let view: ComponentType<BookViewProps> | undefined;

export function bookView(): ComponentType<BookViewProps> | undefined {
  if (!native) return undefined;
  view ??= requireNativeView<BookViewProps>("KitFiles");
  return view;
}
