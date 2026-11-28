import { router } from "expo-router";
import { useState } from "react";
import { Keyboard, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";

import { aiAnswer, aiState } from "../../modules/kit-files";
import { Button } from "@/components/button";
import { Group, Row } from "@/components/group";
import { plain, prompt } from "@/kit/answer";
import { openBook } from "@/kit/books";
import { catalog } from "@/kit/catalog";
import { libraryPath } from "@/kit/downloads";
import { search, type Passage } from "@/kit/search";
import { useKit } from "@/kit/store";
import { space, useColors } from "@/theme";

const byId = new Map(catalog.map((b) => [b.id, b]));

type Found = {
  question: string;
  passages: Passage[];
  started: number;
  seconds?: string; // once it's done
  answer?: string;
  failed?: boolean; // the AI didn't answer
};

const since = (started: number) => ((Date.now() - started) / 1000).toFixed(1);

// Ask, as on the kit page: a question, then the best passages from the books on this phone, each opening its page,
// and on a phone with AI built in, its answer from them.
export function Ask() {
  const c = useColors();
  const { items } = useKit();
  const [ai] = useState(aiState);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState<"searching" | "answering">();
  const [found, setFound] = useState<Found>();
  const books = Object.entries(items).filter(([id, it]) => it.status === "ready" && it.file && byId.has(id));

  function answer(f: Found) {
    setBusy("answering");
    setFound(f);
    const p = prompt(f.question, f.passages);
    aiAnswer(p.instructions, p.prompt)
      .then((text) => setFound({ ...f, answer: plain(text), seconds: since(f.started) }))
      .catch(() => setFound({ ...f, failed: true, seconds: since(f.started) }))
      .finally(() => setBusy(undefined));
  }

  function run(withAI: boolean) {
    const q = question.trim();
    if (!q || busy) return;
    const started = Date.now();
    Keyboard.dismiss(); // out of the way of what's found
    setBusy("searching");
    // After "Searching" shows: the search itself holds up the screen while it reads
    setTimeout(() => {
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
      const f = { question: q, passages, started };
      if (withAI) answer(f);
      else {
        setFound({ ...f, seconds: since(started) });
        setBusy(undefined);
      }
    }, 50);
  }

  const done = found && !busy;
  return (
    <ScrollView contentInsetAdjustmentBehavior="automatic" keyboardShouldPersistTaps="handled">
      <Group label="Your question">
        <TextInput
          testID="ask-question"
          value={question}
          onChangeText={setQuestion}
          onSubmitEditing={() => run(ai === "ready")}
          placeholder="Ask anything. e.g. How do I make water safe to drink without a filter?"
          placeholderTextColor={c.mute}
          multiline
          submitBehavior="blurAndSubmit"
          returnKeyType="search"
          style={[styles.question, { color: c.ink }]}
        />
      </Group>
      <View style={styles.buttons}>
        {ai === "ready" ? <Button title="Ask the AI" onPress={() => run(true)} testID="ask-ai" /> : null}
        <Button title="Search" plain={ai === "ready"} onPress={() => run(false)} testID="ask-search" />
        <Text style={[styles.hint, { color: c.mute }]}>
          {ai === "ready"
            ? "Search: the best passages from your books in seconds, without the AI. It uses very little power.\n" +
              "Ask the AI: it reads your books and writes an answer, with sources. Slower, and it uses more power than Search."
            : "The best passages from your books in seconds, without the internet. It uses very little power." +
              (ai === "off" ? " Turn on Apple Intelligence in Settings and the AI can answer from them too." : "") +
              (ai === "downloading" ? " The phone's AI can answer from them once it has downloaded." : "")}
        </Text>
      </View>
      {busy ? (
        <Group>
          <Row title={busy === "searching" ? "Searching your books" : "The AI is reading your books"} />
        </Group>
      ) : null}
      {books.length === 0 ? (
        <Group>
          <Row icon="book" title="No books yet" detail="Search reads the books on this phone. Get some in Get more." />
        </Group>
      ) : null}
      {found && (found.answer || found.failed) ? (
        <Group
          label="Answer"
          footer={
            "Answers come from the AI built into this phone reading your books. They can be wrong. Check the sources, " +
            "and follow trained medical help whenever you can reach it."
          }
        >
          <Text style={[styles.answer, { color: c.ink }]} testID="ask-answer">
            {found.answer ?? "The phone's AI didn't answer this one. The passages below are from your books."}
          </Text>
        </Group>
      ) : null}
      {found && (done || busy === "answering") && found.passages.length > 0 ? (
        <Group
          label={found.answer ? "Sources from your library" : "Best passages from your library"}
          footer={done ? `Done in ${found.seconds}s.` : undefined}
        >
          {found.passages.map((p, i) => (
            <Pressable
              key={`${p.book}${p.page}`}
              testID={`passage-${i}`}
              accessibilityRole="button"
              onPress={() => router.push({ pathname: "/book/[id]", params: { id: p.book, page: p.page } })}
              android_ripple={{ color: c.line }}
              style={({ pressed }) => [styles.passage, pressed && Platform.OS === "ios" && { backgroundColor: c.line }]}
            >
              <Text style={[styles.title, { color: c.ink }]}>
                {i + 1}. {p.title}
              </Text>
              <Text style={[styles.book, { color: c.mute }]}>{p.bookTitle}</Text>
              <Text style={[styles.text, { color: c.ink }]}>{p.text}</Text>
            </Pressable>
          ))}
        </Group>
      ) : null}
      {done && found.passages.length > 0 && ai === "ready" && !found.answer && !found.failed ? (
        <View style={styles.buttons}>
          <Button
            title="Have the AI answer from these"
            plain
            onPress={() => answer({ ...found, started: Date.now() })}
            testID="ask-answer-these"
          />
        </View>
      ) : null}
      {done && found.passages.length === 0 && !found.answer && !found.failed ? (
        <Group footer={`Done in ${found.seconds}s.`}>
          <Row title="Nothing found" detail="Try other words, or get more books in Get more." />
        </Group>
      ) : null}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  question: { minHeight: 88, fontSize: 17, padding: space.l, paddingTop: space.m, textAlignVertical: "top" },
  buttons: { marginHorizontal: space.l, marginTop: -space.m, marginBottom: space.xl, gap: space.s },
  hint: { fontSize: 13, lineHeight: 18, marginHorizontal: space.xs },
  answer: { fontSize: 16, lineHeight: 23, padding: space.l },
  passage: { paddingHorizontal: space.l, paddingVertical: space.m },
  title: { fontSize: 16, fontWeight: "600" },
  book: { fontSize: 13, marginTop: 2 },
  text: { fontSize: 15, lineHeight: 21, marginTop: space.s },
});
