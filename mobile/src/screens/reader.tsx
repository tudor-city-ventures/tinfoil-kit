import { File, Paths } from "expo-file-system";
import { Stack } from "expo-router";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  BackHandler,
  Linking,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { bookView, type BookViewHandle, type Page } from "../../modules/kit-files";
import { Group, Row } from "@/components/group";
import { Icon, type icons } from "@/components/icon";
import { address, answer, extract, host, openBook, origin, parse } from "@/kit/books";
import { catalog } from "@/kit/catalog";
import { libraryPath } from "@/kit/downloads";
import { useKit } from "@/kit/store";
import type { Zim } from "@/kit/zim";
import { space, useColors } from "@/theme";

const byId = new Map(catalog.map((b) => [b.id, b]));
const encoder = new TextEncoder();

function escape(text: string) {
  return text.replace(/[&<>"]/g, (ch) => `&#${ch.charCodeAt(0)};`);
}

function problem(error: unknown) {
  const message = error instanceof Error ? error.message : String(error);
  return encoder.encode(
    `<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">` +
      `<style>body{font:17px/1.5 -apple-system,system-ui,sans-serif;margin:24px}</style>` +
      `<h1>This page couldn't be read</h1><p>${escape(message)}</p>`,
  );
}

function open(file: string | undefined): { zim?: Zim; error?: string } {
  if (!file) return { error: "This book isn't on the phone yet." };
  try {
    return { zim: openBook(file) };
  } catch (e) {
    return { error: `This book can't be opened: ${e instanceof Error ? e.message : String(e)}` };
  }
}

// Reading a book, from its home page or the page Ask found. Its pages are in a page view that asks this screen for
// every file it needs; search finds pages by title, and the toolbar goes back and forward in the book and to its home
// page.
export function Reader({ id, page: first }: { id: string; page?: string }) {
  const c = useColors();
  const insets = useSafeAreaInsets();
  const item = useKit().items[id];
  const name = byId.get(id)?.title ?? id;
  const file = item?.status === "ready" && item.file ? `${libraryPath()}/${item.file}` : undefined;
  const book = useMemo(() => open(file), [file]);
  const BookView = bookView();
  const view = useRef<BookViewHandle>(null);
  const [page, setPage] = useState<Page>();
  const [life, setLife] = useState(0); // a new page view when Android ends the old one's process
  const [resume, setResume] = useState<string>(); // and the page it was on
  const last = useRef<string | undefined>(undefined);
  const [searching, setSearching] = useState(false);
  const [query, setQuery] = useState("");

  const zim = book.zim;
  const main = useMemo(() => zim?.mainPage(), [zim]);
  const home = `${origin(id)}${zim && main ? address(zim, main) : "/"}`;
  const found = useMemo(() => (zim && query.trim() ? zim.titles(query.trim(), 30) : []), [zim, query]);

  useEffect(() => {
    if (Platform.OS !== "android") return;
    const sub = BackHandler.addEventListener("hardwareBackPress", () => {
      if (searching) setSearching(false);
      else if (page?.back) void view.current?.back();
      else return false;
      return true;
    });
    return () => sub.remove();
  }, [searching, page?.back]);

  if (!zim || !file || !BookView) {
    return (
      <View style={[styles.empty, { backgroundColor: c.background }]}>
        <Stack.Screen options={{ title: name }} />
        <Text style={[styles.emptyText, { color: c.mute }]}>
          {book.error ?? "Books open in the Tinfoil Kit app on a phone."}
        </Text>
      </View>
    );
  }

  function go(url: string) {
    setSearching(false);
    setQuery("");
    void view.current?.load(url);
  }

  function ask({ id: ask, url, main: asPage }: { id: number; url: string; main: boolean }) {
    const v = view.current;
    if (!v || !zim || !file) return;
    const done = (p: Promise<void>) => p.catch(() => {}); // the page view may have gone
    try {
      const at = parse(url);
      if (!at || at.host !== host(id)) return void done(v.respond(ask, 404, "text/plain", new Uint8Array()));
      const a = answer(zim, file, at.path, asPage);
      if ("file" in a) void done(v.respondFile(ask, a.status, a.mime, a.file, a.offset, a.length));
      else void done(v.respond(ask, a.status, a.mime, a.body));
    } catch (e) {
      void done(v.respond(ask, 500, "text/html; charset=utf-8", problem(e)));
    }
  }

  // A file the page view can't show: copied out of the book for another app, or iOS's Quick Look, to open
  async function show(url: string, mime: string) {
    const at = parse(url);
    if (!at || !zim || !file) return;
    const base =
      at.path
        .split("/")
        .pop()
        ?.replace(/[^\w.-]+/g, "_") || "file";
    const dest = `${decodeURI(Paths.cache.uri.replace(/^file:\/\//, "")).replace(/\/$/, "")}/open/${base}`;
    try {
      const entry = extract(zim, file, at.path, dest);
      if (!entry) return;
      await new File(`file://${dest}`).preview({ title: entry.title, mimeType: mime || entry.mime });
    } catch {
      Alert.alert("This file can't be opened", "No app on this phone opens this kind of file.");
    }
  }

  function leave(url: string) {
    const web = /^https?:\/\/([^/?#]+)/i.exec(url);
    Alert.alert(
      web ? "Open in your browser?" : "Open in another app?",
      web ? `This link goes to ${web[1]}, on the internet.` : "This link leaves the book.",
      [
        { text: "Cancel", style: "cancel" },
        { text: "Open", onPress: () => void Linking.openURL(url).catch(() => {}) },
      ],
    );
  }

  return (
    <View style={[styles.page, { backgroundColor: c.background }]}>
      <Stack.Screen
        options={{
          title: page?.title || name,
          headerRight: () => (
            <Tool icon="search" label={`Search ${name}`} testID="search-book" onPress={() => setSearching(true)} />
          ),
        }}
      />
      <BookView
        key={life}
        ref={view}
        style={styles.page}
        testID="book-pages"
        start={resume ?? (first ? `${origin(id)}${first}` : home)}
        onAsk={(e) => ask(e.nativeEvent)}
        onPage={(e) => {
          if (e.nativeEvent.gone) {
            setResume(last.current);
            return setLife((n) => n + 1);
          }
          if (e.nativeEvent.url) last.current = e.nativeEvent.url;
          setPage(e.nativeEvent);
        }}
        onLeave={(e) => leave(e.nativeEvent.url)}
        onOpen={(e) => void show(e.nativeEvent.url, e.nativeEvent.mime)}
      />
      <View
        style={[
          styles.toolbar,
          { borderTopColor: c.line, backgroundColor: c.background, paddingBottom: Math.max(insets.bottom, space.s) },
        ]}
      >
        <Tool
          icon="back"
          label="Back"
          testID="book-back"
          disabled={!page?.back}
          onPress={() => void view.current?.back()}
        />
        <Tool
          icon="forward"
          label="Forward"
          testID="book-forward"
          disabled={!page?.forward}
          onPress={() => void view.current?.forward()}
        />
        <Tool icon="home" label="The book's home page" testID="book-home" onPress={() => go(home)} />
        {Platform.OS === "ios" ? (
          <Tool icon="find" label="Find on this page" testID="book-find" onPress={() => void view.current?.find()} />
        ) : null}
      </View>
      {searching ? (
        <View style={[StyleSheet.absoluteFill, { backgroundColor: c.background }]}>
          <View style={styles.searchBar}>
            <TextInput
              testID="search-field"
              autoFocus
              value={query}
              onChangeText={setQuery}
              placeholder={`Search ${name}`}
              placeholderTextColor={c.mute}
              returnKeyType="search"
              autoCorrect={false}
              clearButtonMode="while-editing"
              style={[styles.searchField, { backgroundColor: c.cell, color: c.ink }]}
            />
            <Pressable
              accessibilityRole="button"
              hitSlop={8}
              onPress={() => {
                setSearching(false);
                setQuery("");
              }}
            >
              <Text style={[styles.cancel, { color: c.accent }]}>Cancel</Text>
            </Pressable>
          </View>
          <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={{ paddingBottom: insets.bottom }}>
            {found.length > 0 ? (
              <Group label="Pages">
                {found.map((e) => (
                  <Row
                    key={e.index}
                    testID={`found-${e.title}`}
                    title={e.title}
                    onPress={() => go(`${origin(id)}${address(zim, e)}`)}
                  />
                ))}
              </Group>
            ) : query.trim() ? (
              <Text style={[styles.none, { color: c.mute }]}>
                No page in this book has a title that starts that way.
              </Text>
            ) : (
              <Text style={[styles.none, { color: c.mute }]}>{"Type the start of a page's title."}</Text>
            )}
          </ScrollView>
        </View>
      ) : null}
    </View>
  );
}

function Tool({
  icon,
  label,
  onPress,
  disabled,
  testID,
}: {
  icon: keyof typeof icons;
  label: string;
  onPress: () => void;
  disabled?: boolean;
  testID?: string;
}) {
  const c = useColors();
  return (
    <Pressable
      testID={testID}
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityState={{ disabled: !!disabled }}
      disabled={disabled}
      onPress={onPress}
      hitSlop={8}
      style={({ pressed }) => [styles.tool, pressed && { opacity: 0.5 }]}
    >
      <Icon name={icon} color={disabled ? c.line : c.accent} size={22} />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  page: { flex: 1 },
  empty: { flex: 1, justifyContent: "center", padding: space.xl },
  emptyText: { fontSize: 17, lineHeight: 24, textAlign: "center" },
  toolbar: {
    flexDirection: "row",
    justifyContent: "space-around",
    paddingTop: space.s,
    borderTopWidth: StyleSheet.hairlineWidth,
  },
  tool: { padding: space.s, minWidth: 44, minHeight: 44, alignItems: "center", justifyContent: "center" },
  searchBar: { flexDirection: "row", alignItems: "center", gap: space.m, padding: space.l },
  searchField: { flex: 1, fontSize: 17, borderRadius: 10, paddingHorizontal: space.m, paddingVertical: space.s },
  cancel: { fontSize: 17 },
  none: { fontSize: 15, marginHorizontal: space.xl, marginTop: space.l },
});
