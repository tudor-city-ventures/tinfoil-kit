import { useLocalSearchParams } from "expo-router";

import { Reader } from "@/screens/reader";

export default function Book() {
  const { id, page, from } = useLocalSearchParams<{ id: string; page?: string; from?: string }>();
  return <Reader id={id} page={page} back={from === "ask" ? "Ask" : "Library"} />;
}
