import { router } from "expo-router";
import { useState } from "react";
import { Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";

import { Button } from "@/components/button";
import { Group, Row } from "@/components/group";
import { openBook } from "@/kit/books";
import { catalog } from "@/kit/catalog";
import { libraryPath } from "@/kit/downloads";
import { search, type Passage } from "@/kit/search";
import { useKit } from "@/kit/store";
import { space, useColors } from "@/theme";

const byId = new Map(catalog.map((b) => [b.id, b]));

type Found = { question: string; passages: Passage[]; seconds: string };

// Ask, as on the kit page: a question, then the best passages from the books on this phone, each opening its page.
export function Ask() {
  const c = useColors();
  const { items } = useKit();
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [found, setFound] = useState<Found>();
  const books = Object.entries(items).filter(([id, it]) => it.status === "ready" && it.file && byId.has(id));

  function run() {
    const q = question.trim();
    if (!q || busy) return;
    setBusy(true);
    // After "Searching" shows: the search itself holds up the screen while it reads
    setTimeout(() => {
      const started = Date.now();
      let passages: Passage[] = [];
      try {
        const library = libraryPath();
        passages = search(
          q,
          books.map(([id, it]) => ({ id, title: byId.get(id)!.title, zim: () => openBook(`${library}/${it.file}`) })),
        );
      } catch (e) {
        console.error(e); // and it says it found nothing
      }
      setFound({ question: q, passages, seconds: ((Date.now() - started) / 1000).toFixed(1) });
      setBusy(false);
    }, 50);
  }

  return (
    <ScrollView contentInsetAdjustmentBehavior="automatic" keyboardShouldPersistTaps="handled">
      <Group label="Your question">
        <TextInput
          testID="ask-question"
          value={question}
          onChangeText={setQuestion}
          onSubmitEditing={run}
          placeholder="Ask anything. e.g. How do I make water safe to drink without a filter?"
          placeholderTextColor={c.mute}
          multiline
          submitBehavior="blurAndSubmit"
          returnKeyType="search"
          style={[styles.question, { color: c.ink }]}
        />
      </Group>
      <View style={styles.buttons}>
        <Button title={busy ? "Searching your books" : "Search"} onPress={run} testID="ask-search" />
        <Text style={[styles.hint, { color: c.mute }]}>
          The best passages from your books in seconds, without the internet. It uses very little power.
        </Text>
      </View>
      {books.length === 0 ? (
        <Group>
          <Row icon="book" title="No books yet" detail="Search reads the books on this phone. Get some in Get more." />
        </Group>
      ) : found && !busy ? (
        found.passages.length > 0 ? (
          <Group label="Best passages from your library" footer={`Done in ${found.seconds}s.`}>
            {found.passages.map((p, i) => (
              <Pressable
                key={`${p.book}${p.page}`}
                testID={`passage-${i}`}
                accessibilityRole="button"
                onPress={() => router.push({ pathname: "/book/[id]", params: { id: p.book, page: p.page } })}
                android_ripple={{ color: c.line }}
                style={({ pressed }) => [
                  styles.passage,
                  pressed && Platform.OS === "ios" && { backgroundColor: c.line },
                ]}
              >
                <Text style={[styles.title, { color: c.ink }]}>{p.title}</Text>
                <Text style={[styles.book, { color: c.mute }]}>{p.bookTitle}</Text>
                <Text style={[styles.text, { color: c.ink }]}>{p.text}</Text>
              </Pressable>
            ))}
          </Group>
        ) : (
          <Group footer={`Done in ${found.seconds}s.`}>
            <Row title="Nothing found" detail="Try other words, or get more books in Get more." />
          </Group>
        )
      ) : null}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  question: { minHeight: 88, fontSize: 17, padding: space.l, paddingTop: space.m, textAlignVertical: "top" },
  buttons: { marginHorizontal: space.l, marginTop: -space.m, marginBottom: space.xl, gap: space.s },
  hint: { fontSize: 13, lineHeight: 18, marginHorizontal: space.xs },
  passage: { paddingHorizontal: space.l, paddingVertical: space.m },
  title: { fontSize: 16, fontWeight: "600" },
  book: { fontSize: 13, marginTop: 2 },
  text: { fontSize: 15, lineHeight: 21, marginTop: space.s },
});
